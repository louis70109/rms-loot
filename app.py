"""RMS 分贓表系統。

- 分贓紀錄（runs）：每場一筆。A捲 / B捲 / C捲 / tape 各記得主（NJ 或同行者），
  「陪打」記一次性同行者（只打過一次，下次再組隊就換他撿）。
- 掉落物（drops）：每件一筆，記持有人、市價、賣出價、賣出日、是否已付。
- 持有人應付金額 = 同名（不分大小寫）且未付的賣出價合計 × 分潤比例。
"""

from __future__ import annotations

import csv
import hmac
import io
import math
import os
import re
import secrets
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
import json
import urllib.parse
import urllib.request

BASE_DIR = Path(__file__).resolve().parent
ME = "NJ"  # 分贓紀錄裡代表自己的名字
SLOTS = (("a_pick", "A捲"), ("b_pick", "B捲"), ("c_pick", "C捲"), ("tape_pick", "tape"))
RUN_COLS = ("run_date", "partner", "is_guest", "a_pick", "b_pick", "c_pick", "tape_pick", "note")
DROP_COLS = ("item", "member", "market_price", "sale_price", "sold_date", "paid", "paid_date")
TRUE_VALUES = {"v", "✓", "✔", "y", "yes", "true", "1", "已付"}

# CSV 表頭（小寫比對）→ 內部欄位
RUN_HEADERS = {"a捲": "a_pick", "b捲": "b_pick", "c捲": "c_pick", "tape": "tape_pick",
               "陪打": "guest", "日期": "run_date", "備註": "note"}
RUN_REQUIRED = {"a_pick": "A捲", "b_pick": "B捲", "c_pick": "C捲", "tape_pick": "tape"}
DROP_HEADERS = {"v": "item", "item": "item", "member": "member", "price": "market_price",
                "sale price": "sale_price", "sold": "sold_date", "paid": "paid"}
DROP_REQUIRED = {"item": "v（掉落物）", "member": "member（持有人）"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL DEFAULT '',
    partner TEXT NOT NULL DEFAULT '',
    is_guest INTEGER NOT NULL DEFAULT 0,
    a_pick TEXT NOT NULL DEFAULT '',
    b_pick TEXT NOT NULL DEFAULT '',
    c_pick TEXT NOT NULL DEFAULT '',
    tape_pick TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS drops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT NOT NULL,
    member TEXT NOT NULL,
    market_price REAL,
    sale_price REAL,
    sold_date TEXT NOT NULL DEFAULT '',
    paid INTEGER NOT NULL DEFAULT 0,
    paid_date TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member TEXT NOT NULL,
    paid_date TEXT NOT NULL,
    amount REAL NOT NULL,
    unpaid_sum REAL NOT NULL,
    item_count INTEGER NOT NULL,
    item_names TEXT NOT NULL,
    formula TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bindings (
    discord_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class ImportFailed(Exception):
    def __init__(self, errors):
        super().__init__("；".join(errors))
        self.errors = errors


# ---------- 共用小工具 ----------

def clean(value):
    return (value or "").strip()


def parse_money(raw, label):
    text = clean(raw).replace(",", "")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{label}「{text}」不是數字")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label}必須是 0 以上的數字")
    return value


def known_names(db):
    """資料庫裡出現過的名字（同行者 + 持有人），不含 NJ，供自動完成用。"""
    rows = db.execute("SELECT partner AS n FROM runs UNION SELECT member AS n FROM drops").fetchall()
    names = {r["n"] for r in rows if r["n"] and r["n"].lower() != ME.lower()}
    return sorted(names, key=str.lower)


def canon_name(db, raw):
    """名字不分大小寫：若已有相同名字（忽略大小寫），沿用既有寫法（ERIC / Eric / eric 視為同一人）。"""
    name = clean(raw)
    if not name:
        return ""
    if name.lower() == ME.lower():
        return ME
    for existing in known_names(db):
        if existing.lower() == name.lower():
            return existing
    return name


# ---------- 表單 / 資料驗證 ----------

def default_run():
    return {"run_date": "", "partner": "", "is_guest": 0, "note": "",
            **{f: "" for f, _ in SLOTS}}


def read_run_form(db, form):
    """把表單或 CSV 列整理成 runs 的資料，回傳 (data, errors)。"""
    errors = []
    partner = canon_name(db, form.get("partner"))
    is_guest = 1 if form.get("is_guest") else 0
    data = {
        "run_date": clean(form.get("run_date")),
        "note": clean(form.get("note")),
        "partner": partner,
        "is_guest": is_guest,
    }
    if partner.lower() == ME.lower():
        errors.append("同行者不能填 NJ（NJ 是你自己）")
    if is_guest and not partner:
        errors.append("勾選陪打時，要填同行者名字")
    for field, label in SLOTS:
        pick = canon_name(db, form.get(field))
        if partner and pick.lower() == partner.lower():
            pick = partner  # 得主與同行者同一人：統一用同行者的寫法（新名字還沒存進資料庫時也適用）
        data[field] = pick
        if pick and pick.lower() != ME.lower() and (not partner or pick.lower() != partner.lower()):
            errors.append(f"{label} 的得主「{pick}」不是 NJ，也不是本場的同行者")
    if not partner and not any(data[f] for f, _ in SLOTS):
        errors.append("至少要填同行者，或任一捲的得主")
    return data, errors


def read_drop_form(db, form):
    errors = []
    item = clean(form.get("item"))
    member = canon_name(db, form.get("member"))
    if not item:
        errors.append("掉落物名稱不能空白")
    if not member:
        errors.append("持有人（付款對象）不能空白")
    market = sale = None
    try:
        market = parse_money(form.get("market_price"), "市價")
        sale = parse_money(form.get("sale_price"), "賣出價")
    except ValueError as exc:
        errors.append(str(exc))
    data = {
        "item": item,
        "member": member,
        "market_price": market,
        "sale_price": sale,
        "sold_date": clean(form.get("sold_date")),
        "paid": 1 if form.get("paid") else 0,
        "paid_date": clean(form.get("paid_date")),
    }
    return data, errors


def save_run(db, data, run_id=None):
    values = [data[c] for c in RUN_COLS]
    if run_id is None:
        sql = f"INSERT INTO runs ({', '.join(RUN_COLS)}) VALUES ({', '.join('?' * len(RUN_COLS))})"
        db.execute(sql, values)
    else:
        sets = ", ".join(f"{c} = ?" for c in RUN_COLS)
        db.execute(f"UPDATE runs SET {sets} WHERE id = ?", [*values, run_id])


def save_drop(db, data, drop_id=None):
    values = [data[c] for c in DROP_COLS]
    if drop_id is None:
        sql = f"INSERT INTO drops ({', '.join(DROP_COLS)}) VALUES ({', '.join('?' * len(DROP_COLS))})"
        db.execute(sql, values)
    else:
        sets = ", ".join(f"{c} = ?" for c in DROP_COLS)
        db.execute(f"UPDATE drops SET {sets} WHERE id = ?", [*values, drop_id])


# ---------- 統計 ----------

def build_people(db):
    """每位成員：同行次數、各捲拿到幾次、陪打次數，以及是否「下次換他撿」。"""
    people = {}

    def person(name):
        key = name.lower()
        if key not in people:
            people[key] = {"name": name, "runs": 0, "guest_runs": 0,
                           "picks": {f: 0 for f, _ in SLOTS}, "total_picks": 0,
                           "next_turn": False}
        return people[key]

    person(ME)
    for r in db.execute("SELECT * FROM runs ORDER BY id").fetchall():
        if r["partner"]:
            p = person(r["partner"])
            p["runs"] += 1
            p["guest_runs"] += r["is_guest"]
        for field, _ in SLOTS:
            if r[field]:
                p = person(r[field])
                p["picks"][field] += 1
                p["total_picks"] += 1

    result = sorted(people.values(), key=lambda p: (p["name"] != ME, p["name"].lower()))
    for p in result:
        # 陪打只打過一次 → 下次再跟他組隊，換他撿
        p["next_turn"] = p["name"] != ME and p["guest_runs"] > 0 and p["runs"] == 1
    return result


def build_partner_breakdown(db):
    """每位同行者底下：這些場次中 NJ 拿到的各捲次數（沒有同行者的場次另列）。"""
    groups = {}
    for r in db.execute("SELECT * FROM runs ORDER BY id").fetchall():
        name = r["partner"] or "（沒有同行者）"
        key = name.lower()
        g_ = groups.setdefault(key, {"name": name, "runs": 0, "guest_runs": 0,
                                     "picks": {f: 0 for f, _ in SLOTS}, "total": 0})
        g_["runs"] += 1
        g_["guest_runs"] += r["is_guest"] if r["partner"] else 0
        for field, _ in SLOTS:
            if r[field].lower() == ME.lower():
                g_["picks"][field] += 1
                g_["total"] += 1
    return sorted(groups.values(), key=lambda x: (x["name"].startswith("（"), x["name"].lower()))


def build_payouts(db, fee_percent, share_percent):
    """每位持有人（不分大小寫合併）的應付金額，對應原表 G 欄。

    只要未付且有賣出價就計入；缺賣出價的列為未完成，不計金額。
    應付 = 未付賣出價合計 × (1 - 手續費%) × 分配比例%。
    例：154 × 0.97 ÷ 2 = 74.69。
    """
    groups = {}
    for d in db.execute("SELECT * FROM drops ORDER BY id").fetchall():
        g_ = groups.setdefault(d["member"].lower(), {
            "name": d["member"], "paid_items": 0, "unpaid_items": 0,
            "unpaid_sum": 0.0, "incomplete": 0, "sold_items": [], "incomplete_items": []})
        if d["paid"]:
            g_["paid_items"] += 1
        elif d["sale_price"] is None:
            g_["incomplete"] += 1  # 還沒填賣出價，無法算金額
            g_["incomplete_items"].append(d["item"])
        else:
            g_["unpaid_items"] += 1
            g_["unpaid_sum"] += d["sale_price"]
            g_["sold_items"].append({"id": d["id"], "item": d["item"], "sale_price": d["sale_price"],
                                     "sold_date": d["sold_date"]})

    factor = (100 - fee_percent) / 100 * share_percent / 100
    result = sorted(groups.values(), key=lambda x: x["name"].lower())
    for g_ in result:
        g_["unpaid_sum"] = round(g_["unpaid_sum"], 2)
        g_["payout"] = round(g_["unpaid_sum"] * factor, 2)
        g_["formula"] = (f"{g_['unpaid_sum']:g} × {100 - fee_percent:g}% × {share_percent:g}% "
                         f"= {g_['payout']:.2f}")
    return result


def get_setting(db, key, default):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return float(row["value"]) if row else default


def set_setting(db, key, value):
    db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))


# ---------- CSV 匯入 ----------

def read_upload(upload):
    if upload is None or not upload.filename:
        raise ValueError("請選擇 CSV 檔案")
    raw = upload.read()
    for encoding in ("utf-8-sig", "cp950"):  # Google 試算表匯出是 UTF-8；Excel 存檔常見 Big5
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("無法辨識檔案編碼，請用 UTF-8 或 Big5 存成 CSV")


def map_columns(header, mapping, required):
    idx = {}
    for i, title in enumerate(header):
        key = mapping.get(clean(title).lower())
        if key and key not in idx:
            idx[key] = i
    missing = [label for key, label in required.items() if key not in idx]
    if missing:
        raise ValueError("CSV 缺少欄位：" + "、".join(missing))
    return idx


def cell(row, idx, key):
    i = idx.get(key)
    return clean(row[i]) if i is not None and i < len(row) else ""


def import_runs(db, text, replace=False):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("CSV 是空的")
    idx = map_columns(rows[0], RUN_HEADERS, RUN_REQUIRED)
    if replace:
        db.execute("DELETE FROM runs")

    errors, count = [], 0
    for line_no, row in enumerate(rows[1:], start=2):
        if not any(clean(c) for c in row):
            continue
        picks = {f: cell(row, idx, f) for f, _ in SLOTS}
        guest = cell(row, idx, "guest")
        if guest:  # 陪打欄有名字 → 那就是本場的同行者（陪打）
            partner, is_guest = guest, "1"
        else:      # 否則從得主欄推出同行者（非 NJ 的名字）
            others = {}
            for v in picks.values():
                if v and v.lower() != ME.lower():
                    others.setdefault(v.lower(), v)
            if len(others) > 1:
                errors.append(f"第 {line_no} 列同時出現多位同行者：{'、'.join(others.values())}")
                continue
            partner = next(iter(others.values())) if others else ""
            is_guest = ""
        form = {"run_date": cell(row, idx, "run_date"), "note": cell(row, idx, "note"),
                "partner": partner, "is_guest": is_guest, **picks}
        data, row_errors = read_run_form(db, form)
        if row_errors:
            errors += [f"第 {line_no} 列：{e}" for e in row_errors]
            continue
        save_run(db, data)
        count += 1

    if errors:
        db.rollback()  # 有任何錯誤就整批不寫入
        raise ImportFailed(errors)
    return count


def import_drops(db, text, replace=False):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("CSV 是空的")
    idx = map_columns(rows[0], DROP_HEADERS, DROP_REQUIRED)
    if replace:
        db.execute("DELETE FROM drops")

    errors, count = [], 0
    for line_no, row in enumerate(rows[1:], start=2):
        if not any(clean(c) for c in row):
            continue
        form = {
            "item": cell(row, idx, "item"),
            "member": cell(row, idx, "member"),
            "market_price": cell(row, idx, "market_price"),
            "sale_price": cell(row, idx, "sale_price"),
            "sold_date": cell(row, idx, "sold_date"),
            "paid": "1" if cell(row, idx, "paid").lower() in TRUE_VALUES else "",
        }
        data, row_errors = read_drop_form(db, form)
        if row_errors:
            errors += [f"第 {line_no} 列：{e}" for e in row_errors]
            continue
        save_drop(db, data)
        count += 1

    if errors:
        db.rollback()
        raise ImportFailed(errors)
    return count


# ---------- Flask ----------

DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_ME_URL = "https://discord.com/api/users/@me"
# Discord/Cloudflare 會擋 Python 預設的 User-Agent（回 403 且沒有內容），所以要自己帶一個
DISCORD_USER_AGENT = "RMS-Loot (https://rms-loot-nj.fly.dev, 1.0)"


def discord_exchange_code(code, config):
    """用授權碼換 access token（伺服器對伺服器，不經過瀏覽器）。"""
    body = urllib.parse.urlencode({
        "client_id": config["DISCORD_CLIENT_ID"],
        "client_secret": config["DISCORD_CLIENT_SECRET"],
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config["DISCORD_REDIRECT_URI"],
    }).encode()
    req = urllib.request.Request(DISCORD_TOKEN_URL, data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "User-Agent": DISCORD_USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)["access_token"]


def discord_error_detail(exc):
    """Discord 的錯誤代碼與說明（不含任何 token 或 secret）。"""
    try:
        data = json.loads(exc.read().decode("utf-8", "replace"))
        text = f"{data.get('error', '')} {data.get('error_description', '')}".strip()
    except Exception:
        text = ""
    return (text or "無回應內容")[:200]


def discord_fetch_user_id(access_token):
    req = urllib.request.Request(DISCORD_ME_URL, headers={"Authorization": f"Bearer {access_token}",
                                                          "User-Agent": DISCORD_USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return str(json.load(resp)["id"])


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["DB_PATH"] = str(db_path or os.environ.get("RMS_DB") or BASE_DIR / "rms_loot.db")
    # 只用來簽署存提示訊息的 cookie，沒有登入功能，所以每次啟動自動產生即可
    # Discord 登入：三個設定都有才啟用（OWNER_DISCORD_IDS 是擁有者，逗號分隔；其他人登入後綁定名字）
    app.config["DISCORD_CLIENT_ID"] = os.environ.get("DISCORD_CLIENT_ID", "")
    app.config["DISCORD_CLIENT_SECRET"] = os.environ.get("DISCORD_CLIENT_SECRET", "")
    app.config["DISCORD_REDIRECT_URI"] = os.environ.get("DISCORD_REDIRECT_URI", "")
    app.config["OWNER_DISCORD_IDS"] = {x.strip() for x in os.environ.get("OWNER_DISCORD_IDS", "").split(",")
                                       if x.strip()}
    app.config["DISCORD_ON"] = bool(app.config["DISCORD_CLIENT_ID"] and app.config["DISCORD_CLIENT_SECRET"]
                                    and app.config["DISCORD_REDIRECT_URI"] and app.config["OWNER_DISCORD_IDS"])
    if app.config["DISCORD_ON"] and not os.environ.get("RMS_SECRET_KEY"):
        # 沒有固定金鑰的話，機器每次醒來都會換金鑰，登入會全部失效，所以直接拒絕啟動
        raise RuntimeError("啟用 Discord 登入時必須設定 RMS_SECRET_KEY")
    app.config["SECRET_KEY"] = os.environ.get("RMS_SECRET_KEY") or secrets.token_hex(32)
    if app.config["DISCORD_ON"]:
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.jinja_env.globals["SLOTS"] = SLOTS

    @app.context_processor
    def inject_auth():
        """導覽列用：目前登入的身分（沒有 Discord 登入時為空）。"""
        return {"auth_name": session.get("name", ""), "auth_role": session.get("role", "")}
    app.jinja_env.filters["money"] = lambda v: "" if v is None else f"{v:g}"

    # 密碼閘門：設了 APP_PASSWORD 就要 HTTP Basic 登入（帳號隨意，只驗密碼）。
    # RMS_REQUIRE_AUTH=1 且沒設密碼時，除了 /healthz 之外一律 503，避免公開裸奔。
    app.config["APP_PASSWORD"] = os.environ.get("APP_PASSWORD", "")
    app.config["REQUIRE_AUTH"] = os.environ.get("RMS_REQUIRE_AUTH") == "1"
    # 給桌面版等程式用的 API token（Bearer）。沒設就關閉 /api/*。
    app.config["API_TOKEN"] = os.environ.get("RMS_API_TOKEN", "")

    @app.before_request
    def password_gate():
        if request.path == "/healthz" or (request.path.startswith("/auth/") and app.config["DISCORD_ON"]):
            return None
        if request.path.startswith("/api/"):
            # /api/* 只用 token 驗證，不走 Discord / 密碼閘門
            expected = app.config["API_TOKEN"]
            if not expected:
                abort(404)
            scheme, _, token = (request.headers.get("Authorization") or "").partition(" ")
            if scheme != "Bearer" or not hmac.compare_digest(token.strip(), expected):
                return jsonify(ok=False, error="unauthorized"), 401
            return None
        if app.config["DISCORD_ON"]:
            if request.path.startswith("/static/"):
                return None
            role = session.get("role")
            if role == "owner":
                return None
            if role == "member":
                if request.method == "GET" and request.path in ("/", "/drops"):
                    return None
                if request.method == "POST" and re.fullmatch(r"/drops/\d+/edit", request.path):
                    return None  # 權限在 drop_edit 裡逐筆檢查
                return Response("沒有權限", 403)
            if role == "unbound" and request.path == "/auth/bind":
                return None
            if request.method == "GET":
                if role == "unbound":
                    return redirect(url_for("discord_bind"))
                return redirect(url_for("discord_login"))
            return Response("請先登入", 401)
        expected = app.config["APP_PASSWORD"]
        if not expected:
            if app.config["REQUIRE_AUTH"]:
                return Response("尚未設定 APP_PASSWORD，服務暫停中。", 503)
            return None
        auth = request.authorization
        if auth and hmac.compare_digest(auth.password or "", expected):
            return None
        return Response("需要密碼", 401, {"WWW-Authenticate": 'Basic realm="RMS 分贓表"'})

    @app.get("/auth/discord/login")
    def discord_login():
        if not app.config["DISCORD_ON"]:
            abort(404)
        state = secrets.token_urlsafe(24)
        session["oauth_state"] = state
        query = urllib.parse.urlencode({
            "client_id": app.config["DISCORD_CLIENT_ID"],
            "redirect_uri": app.config["DISCORD_REDIRECT_URI"],
            "response_type": "code",
            "scope": "identify",
            "state": state,
        })
        return redirect(f"{DISCORD_AUTHORIZE_URL}?{query}")

    @app.get("/auth/discord/callback")
    def discord_callback():
        if not app.config["DISCORD_ON"]:
            abort(404)
        if request.args.get("error"):
            return Response("Discord 登入已取消", 400)
        expected = session.pop("oauth_state", None)
        if not expected or not hmac.compare_digest(request.args.get("state", ""), expected):
            return Response("登入驗證失敗（state 不符），請重新登入", 400)
        try:
            token = discord_exchange_code(request.args.get("code", ""), app.config)
            discord_id = discord_fetch_user_id(token)
        except urllib.error.HTTPError as exc:  # Discord 回了錯誤（例如 invalid_client）
            detail = discord_error_detail(exc)
            app.logger.error("Discord HTTP %s: %s", exc.code, detail)
            return Response(f"無法向 Discord 取得資料（HTTP {exc.code}：{detail}）", 502)
        except Exception as exc:  # 網路等其他錯誤
            app.logger.error("Discord login failed: %s", type(exc).__name__)
            return Response(f"無法向 Discord 取得資料（{type(exc).__name__}），請稍後再試", 502)
        session.clear()
        session["discord_id"] = discord_id
        if discord_id in app.config["OWNER_DISCORD_IDS"]:
            session["role"], session["name"] = "owner", ME
            return redirect(url_for("index"))
        bound = get_db().execute("SELECT name FROM bindings WHERE discord_id = ?", (discord_id,)).fetchone()
        if bound:
            session["role"], session["name"] = "member", bound["name"]
            return redirect(url_for("index"))
        session["role"] = "unbound"
        return redirect(url_for("discord_bind"))

    @app.route("/auth/bind", methods=["GET", "POST"])
    def discord_bind():
        if not app.config["DISCORD_ON"]:
            abort(404)
        if session.get("role") not in ("unbound", "owner", "member") or not session.get("discord_id"):
            return redirect(url_for("discord_login"))
        if session.get("role") != "unbound":
            return redirect(url_for("index"))
        db = get_db()
        if request.method == "POST":
            name = clean(request.form.get("name"))
            if not name or name.lower() == ME.lower():
                flash("請選一個名字", "error")
            else:
                try:
                    db.execute("INSERT INTO bindings (discord_id, name) VALUES (?, ?)",
                               (session["discord_id"], name))
                    db.commit()
                except sqlite3.IntegrityError:
                    flash(f"「{name}」已經被綁定了，請選別的名字", "error")
                else:
                    session["role"], session["name"] = "member", name
                    flash(f"已綁定為 {name}", "ok")
                    return redirect(url_for("index"))
        taken = {r["name"].lower() for r in db.execute("SELECT name FROM bindings")}
        choices = [n for n in known_names(db) if n.lower() not in taken]
        return render_template("auth_bind.html", choices=choices)

    @app.get("/auth/logout")
    def discord_logout():
        session.clear()
        return redirect(url_for("index"))

    @app.get("/healthz")
    def healthz():
        return "ok"

    # ---- 唯讀 JSON API（Bearer token，見 password_gate）----
    @app.get("/api/settings")
    def api_settings():
        db = get_db()
        return jsonify(fee_percent=get_setting(db, "payout_fee_percent", 3.0),
                       share_percent=get_setting(db, "payout_share_percent", 50.0))

    @app.get("/api/runs")
    def api_runs():
        rows = get_db().execute(
            "SELECT id, run_date, partner, is_guest, a_pick, b_pick, c_pick, tape_pick, note "
            "FROM runs ORDER BY id").fetchall()
        return jsonify([{**dict(r), "is_guest": bool(r["is_guest"])} for r in rows])

    @app.get("/api/drops")
    def api_drops():
        rows = get_db().execute(
            "SELECT id, item, member, market_price, sale_price, sold_date, paid, paid_date "
            "FROM drops ORDER BY id").fetchall()
        return jsonify([{**dict(r), "paid": bool(r["paid"])} for r in rows])

    @app.post("/api/drops/<int:drop_id>/toggle-paid")
    def api_drop_toggle_paid(drop_id):
        # 與網站 drop_toggle 相同：只翻轉 paid，不動付款日
        db = get_db()
        cur = db.execute("UPDATE drops SET paid = 1 - paid WHERE id = ?", (drop_id,))
        if cur.rowcount == 0:
            db.rollback()
            return jsonify(ok=False, error="not found"), 404
        db.commit()
        row = db.execute("SELECT paid FROM drops WHERE id = ?", (drop_id,)).fetchone()
        return jsonify(ok=True, paid=bool(row["paid"]))

    conn = sqlite3.connect(app.config["DB_PATH"])
    conn.executescript(SCHEMA)
    # 舊資料庫補上 paid_date 欄位（CREATE TABLE IF NOT EXISTS 不會改既有的表）
    if "paid_date" not in {r[1] for r in conn.execute("PRAGMA table_info(drops)")}:
        conn.execute("ALTER TABLE drops ADD COLUMN paid_date TEXT NOT NULL DEFAULT ''")
    conn.commit()
    conn.close()

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DB_PATH"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def run_import(importer, label):
        db = get_db()
        try:
            text = read_upload(request.files.get("file"))
            count = importer(db, text, replace=bool(request.form.get("replace")))
            db.commit()
            flash(f"已匯入 {count} {label}", "ok")
        except ImportFailed as exc:
            db.rollback()
            for message in exc.errors[:20]:
                flash(message, "error")
            if len(exc.errors) > 20:
                flash(f"另有 {len(exc.errors) - 20} 個錯誤未列出，請修正後再匯入", "error")
        except ValueError as exc:
            db.rollback()
            flash(str(exc), "error")
        return redirect(url_for("settings"))

    # 總覽
    @app.get("/")
    def index():
        db = get_db()
        fee, share = get_setting(db, "payout_fee_percent", 3.0), get_setting(db, "payout_share_percent", 50.0)
        return render_template("index.html", people=build_people(db), partners=build_partner_breakdown(db),
                               payouts=build_payouts(db, fee, share), fee=fee, share=share,
                               payments=db.execute("SELECT * FROM payments ORDER BY id DESC").fetchall(),
                               today=date.today().isoformat())

    @app.post("/payouts/pay")
    def payout_pay():
        """一鍵付款：標記這位持有人所有可付項目為已付、寫入付款日，並存下當下的金額與計算式。"""
        db = get_db()
        member = clean(request.form.get("member"))
        paid_date = clean(request.form.get("paid_date")) or date.today().isoformat()
        fee, share = get_setting(db, "payout_fee_percent", 3.0), get_setting(db, "payout_share_percent", 50.0)
        group = next((p for p in build_payouts(db, fee, share)
                      if member and p["name"].lower() == member.lower()), None)
        if group is None or not group["sold_items"]:
            flash(f"{member or '這位持有人'} 沒有可付款的項目", "error")
            return redirect(url_for("index"))
        ids = [it["id"] for it in group["sold_items"]]
        db.execute(f"UPDATE drops SET paid = 1, paid_date = ? WHERE id IN ({','.join('?' * len(ids))})",
                   [paid_date, *ids])
        db.execute("INSERT INTO payments (member, paid_date, amount, unpaid_sum, item_count, item_names, formula) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (group["name"], paid_date, group["payout"], group["unpaid_sum"], len(ids),
                    "、".join(it["item"] for it in group["sold_items"]), group["formula"]))
        db.commit()
        flash(f"已付給 {group['name']} {group['payout']:.2f}（{len(ids)} 件），付款日 {paid_date}", "ok")
        return redirect(url_for("index"))

    # 分贓紀錄
    @app.get("/runs")
    def runs():
        db = get_db()
        rows = db.execute("SELECT * FROM runs ORDER BY id").fetchall()
        return render_template("runs.html", runs=rows, names=known_names(db))

    @app.route("/runs/new", methods=["GET", "POST"])
    def run_new():
        db = get_db()
        data, errors = default_run(), []
        if request.method == "POST":
            data, errors = read_run_form(db, request.form)
            if not errors:
                save_run(db, data)
                db.commit()
                flash("已新增分贓紀錄", "ok")
                return redirect(url_for("runs"))
        return render_template("run_form.html", title="新增分贓紀錄", data=data, errors=errors,
                               names=known_names(db), action=url_for("run_new"))

    @app.route("/runs/<int:run_id>/edit", methods=["GET", "POST"])
    def run_edit(run_id):
        db = get_db()
        row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            abort(404)
        data, errors = dict(row), []
        if request.method == "POST":
            data, errors = read_run_form(db, request.form)
            if request.form.get("inline"):  # 表格背景儲存：回 JSON，不跳頁
                if errors:
                    return jsonify(ok=False, errors=errors), 422
                save_run(db, data, run_id)
                db.commit()
                return jsonify(ok=True)
            if not errors:
                save_run(db, data, run_id)
                db.commit()
                flash("已更新分贓紀錄", "ok")
                return redirect(url_for("runs"))
        return render_template("run_form.html", title=f"編輯第 {run_id} 場", data=data, errors=errors,
                               names=known_names(db), action=url_for("run_edit", run_id=run_id))

    @app.post("/runs/copy-last")
    def run_copy_last():
        db = get_db()
        last = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        if last is None:  # 還沒有任何紀錄，改用空白表單
            return redirect(url_for("run_new"))
        data = {c: last[c] for c in RUN_COLS}
        save_run(db, data)
        db.commit()
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        flash(f"已沿用第 {last['id']} 場新增第 {new_id} 場，可直接在表格上修改", "ok")
        return redirect(url_for("runs"))

    @app.post("/runs/<int:run_id>/delete")
    def run_delete(run_id):
        db = get_db()
        db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        db.commit()
        flash("已刪除分贓紀錄", "ok")
        return redirect(url_for("runs"))

    # 掉落物
    @app.get("/drops")
    def drops():
        db = get_db()
        rows = db.execute("SELECT * FROM drops ORDER BY id").fetchall()
        return render_template("drops.html", drops=rows, names=known_names(db))

    @app.route("/drops/new", methods=["GET", "POST"])
    def drop_new():
        db = get_db()
        data, errors = {"item": "", "member": "", "market_price": None, "sale_price": None,
                        "sold_date": "", "paid": 0}, []
        if request.method == "POST":
            data, errors = read_drop_form(db, request.form)
            if not errors:
                save_drop(db, data)
                db.commit()
                flash("已新增掉落物", "ok")
                return redirect(url_for("drops"))
        return render_template("drop_form.html", title="新增掉落物", data=data, errors=errors,
                               names=known_names(db), action=url_for("drop_new"))

    @app.route("/drops/<int:drop_id>/edit", methods=["GET", "POST"])
    def drop_edit(drop_id):
        db = get_db()
        row = db.execute("SELECT * FROM drops WHERE id = ?", (drop_id,)).fetchone()
        if row is None:
            abort(404)
        data, errors = dict(row), []
        if session.get("role") == "member":
            # 成員只能用表格改「持有人是自己」的掉落物；持有人與付款狀態不能改
            if request.method != "POST" or not request.form.get("inline") or \
                    row["member"].lower() != session.get("name", "").lower():
                return Response("沒有權限", 403)
        if request.method == "POST":
            data, errors = read_drop_form(db, request.form)
            if session.get("role") == "member":
                data["member"], data["paid"], data["paid_date"] = row["member"], row["paid"], row["paid_date"]
            if request.form.get("inline"):  # 表格背景儲存：回 JSON，不跳頁
                if errors:
                    return jsonify(ok=False, errors=errors), 422
                save_drop(db, data, drop_id)
                db.commit()
                return jsonify(ok=True)
            if not errors:
                save_drop(db, data, drop_id)
                db.commit()
                flash("已更新掉落物", "ok")
                return redirect(url_for("drops"))
        return render_template("drop_form.html", title=f"編輯掉落物 #{drop_id}", data=data,
                               errors=errors, names=known_names(db),
                               action=url_for("drop_edit", drop_id=drop_id))

    @app.post("/drops/<int:drop_id>/toggle-paid")
    def drop_toggle(drop_id):
        db = get_db()
        db.execute("UPDATE drops SET paid = 1 - paid WHERE id = ?", (drop_id,))
        db.commit()
        return redirect(url_for("drops"))

    @app.post("/drops/<int:drop_id>/delete")
    def drop_delete(drop_id):
        db = get_db()
        db.execute("DELETE FROM drops WHERE id = ?", (drop_id,))
        db.commit()
        flash("已刪除掉落物", "ok")
        return redirect(url_for("drops"))

    # 設定 / 匯入
    @app.get("/backup")
    def backup():
        """下載完整的 SQLite 備份（用 SQLite 的 backup API，寫入中也是一致的快照）。"""
        src = get_db()
        with tempfile.TemporaryDirectory() as tmp:
            dst_path = Path(tmp) / "backup.db"
            dst = sqlite3.connect(dst_path)
            src.backup(dst)
            dst.close()
            data = dst_path.read_bytes()
        name = f"rms-loot-{date.today().isoformat()}.db"
        return Response(data, mimetype="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/settings")
    def settings():
        db = get_db()
        return render_template("settings.html", fee=get_setting(db, "payout_fee_percent", 3.0),
                               share=get_setting(db, "payout_share_percent", 50.0))

    @app.post("/settings/payout")
    def settings_payout():
        db = get_db()
        try:
            fee = float(clean(request.form.get("fee_percent")))
            share = float(clean(request.form.get("share_percent")))
            if not (math.isfinite(fee) and math.isfinite(share)):
                raise ValueError
            if not (0 <= fee < 100 and 0 <= share <= 100):
                raise ValueError
        except ValueError:
            flash("手續費請填 0 到 100 之間（不含 100），分配比例請填 0 到 100 之間", "error")
            return redirect(url_for("settings"))
        set_setting(db, "payout_fee_percent", fee)
        set_setting(db, "payout_share_percent", share)
        db.commit()
        flash(f"已設定：扣手續費 {fee:g}%，分配 {share:g}%", "ok")
        return redirect(url_for("settings"))

    @app.post("/import/runs")
    def import_runs_view():
        return run_import(import_runs, "場分贓紀錄")

    @app.post("/import/drops")
    def import_drops_view():
        return run_import(import_drops, "件掉落物")

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=True)

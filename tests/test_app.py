import sqlite3
import urllib.parse
from pathlib import Path

import pytest

from app import (ImportFailed, build_payouts, build_people, create_app, import_drops,
                 import_runs, read_run_form)

SAMPLE = Path(__file__).resolve().parent.parent / "sample"


def connect(app):
    db = sqlite3.connect(app.config["DB_PATH"])
    db.row_factory = sqlite3.Row
    return db


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "test.db")


@pytest.fixture
def loaded(app):
    db = connect(app)
    import_runs(db, (SAMPLE / "runs.csv").read_text(encoding="utf-8"))
    import_drops(db, (SAMPLE / "drops.csv").read_text(encoding="utf-8"))
    db.commit()
    yield db
    db.close()


def count(db, table):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_sample_import_counts(loaded):
    assert count(loaded, "runs") == 11      # 原表 12 列，其中第 7 列是空白
    assert count(loaded, "drops") == 19     # 原表 2~20 列
    guests = loaded.execute("SELECT partner FROM runs WHERE is_guest = 1 ORDER BY id").fetchall()
    assert [g["partner"] for g in guests] == ["hangi", "XL"]


def test_people_stats_match_sheet(loaded):
    people = {p["name"]: p for p in build_people(loaded)}
    assert people["NJ"]["total_picks"] == 18
    assert people["KIA"]["total_picks"] == 7
    assert people["KIA"]["runs"] == 4
    assert people["ERIC"]["picks"]["a_pick"] == 1
    assert people["hangi"]["next_turn"] is True
    assert people["XL"]["next_turn"] is True
    assert people["ERIC"]["next_turn"] is False
    assert people["KIA"]["next_turn"] is False


def test_payouts_merge_case_and_sum_unpaid(loaded):
    payouts = {p["name"].lower(): p for p in build_payouts(loaded, 0, 100)}
    assert len(payouts) == 2                           # eric / Eric / ERIC 合併
    assert payouts["kia"]["unpaid_items"] == 5         # 所有未付且有賣出價：13、17~20
    assert payouts["kia"]["unpaid_sum"] == 224         # 70+35+19+65+35
    assert payouts["kia"]["incomplete"] == 1           # EP 11211 沒有賣出價，不計金額
    assert payouts["eric"]["unpaid_sum"] == 0
    assert payouts["eric"]["paid_items"] == 11


def test_payout_formula_all_unpaid(loaded):
    # 所有未付（有賣出價）都算：224 × 0.97 ÷ 2 = 108.64
    payouts = {p["name"].lower(): p for p in build_payouts(loaded, 3, 50)}
    assert payouts["kia"]["payout"] == 108.64
    assert payouts["eric"]["payout"] == 0


def test_import_is_all_or_nothing(app):
    db = connect(app)
    bad = "A捲,B捲,C捲,tape,陪打\nNJ,,,,\nKIA,ERIC,,,\n"  # 第二列同時有兩位同行者
    with pytest.raises(ImportFailed):
        import_runs(db, bad)
    assert count(db, "runs") == 0


def test_replace_mode_does_not_duplicate(app):
    db = connect(app)
    text = (SAMPLE / "runs.csv").read_text(encoding="utf-8")
    import_runs(db, text)
    import_runs(db, text, replace=True)
    db.commit()
    assert count(db, "runs") == 11


def test_run_rejects_picker_outside_party():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("CREATE TABLE runs (partner TEXT, is_guest INT, run_date TEXT, note TEXT,"
                     " a_pick TEXT, b_pick TEXT, c_pick TEXT, tape_pick TEXT);"
                     "CREATE TABLE drops (member TEXT);")
    data, errors = read_run_form(db, {"partner": "ERIC", "a_pick": "KIA"})
    assert any("KIA" in e for e in errors)
    data, errors = read_run_form(db, {"partner": "ERIC", "a_pick": "eric", "b_pick": "nj"})
    assert errors == []
    assert data["a_pick"] == "ERIC"  # 得主與同行者是同一人，統一用同行者的寫法
    data, errors = read_run_form(db, {"is_guest": "1"})
    assert any("陪打" in e for e in errors)
    data, errors = read_run_form(db, {})
    assert any("至少" in e for e in errors)


def test_pages_render(app, loaded):
    client = app.test_client()
    for path in ["/", "/runs", "/drops", "/settings", "/runs/new", "/drops/new", "/runs/1/edit", "/drops/1/edit"]:
        resp = client.get(path)
        assert resp.status_code == 200, path
    assert "下次換他撿" in client.get("/").get_data(as_text=True)


def test_create_and_toggle_drop_via_http(app):
    client = app.test_client()
    resp = client.post("/drops/new", data={"item": "Eye for DEX 60%", "member": "KIA",
                                           "market_price": "80", "sale_price": "70",
                                           "sold_date": "9/13"})
    assert resp.status_code == 302
    client.post("/drops/1/toggle-paid")
    db = connect(app)
    assert db.execute("SELECT paid FROM drops WHERE id = 1").fetchone()["paid"] == 1


def test_bad_run_form_does_not_save(app):
    client = app.test_client()
    resp = client.post("/runs/new", data={"partner": "ERIC", "a_pick": "KIA"})
    assert resp.status_code == 200
    assert "不是 NJ" in resp.get_data(as_text=True)
    db = connect(app)
    assert count(db, "runs") == 0


def test_password_gate(tmp_path, monkeypatch):
    import base64

    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    app = create_app(tmp_path / "gate.db")
    client = app.test_client()
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 401
    bad = base64.b64encode(b"nj:wrong").decode()
    assert client.get("/", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    good = base64.b64encode(b"nj:s3cret").decode()
    assert client.get("/", headers={"Authorization": f"Basic {good}"}).status_code == 200


def test_fail_closed_without_password(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.setenv("RMS_REQUIRE_AUTH", "1")
    client = create_app(tmp_path / "closed.db").test_client()
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 503


def test_local_dev_open_without_password(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("RMS_REQUIRE_AUTH", raising=False)
    client = create_app(tmp_path / "open.db").test_client()
    assert client.get("/").status_code == 200


def test_names_case_insensitive_across_run_and_drops(app):
    client = app.test_client()
    client.post("/runs/new", data={"partner": "eric", "a_pick": "ERIC", "b_pick": "nj"})
    client.post("/runs/new", data={"partner": "Eric", "a_pick": "eric", "c_pick": "Nj"})
    client.post("/runs/new", data={"partner": "KIA", "a_pick": "kia", "tape_pick": "NJ", "is_guest": "1"})
    client.post("/drops/new", data={"item": "x1", "member": "KIA", "sale_price": "10", "sold_date": "1/1"})
    client.post("/drops/new", data={"item": "x2", "member": "kia", "sale_price": "5", "sold_date": "1/2"})
    db = connect(app)
    rows = db.execute("SELECT partner, a_pick, b_pick, c_pick, tape_pick FROM runs ORDER BY id").fetchall()
    assert [r["partner"] for r in rows] == ["eric", "eric", "KIA"]
    assert rows[0]["a_pick"] == "eric" and rows[1]["a_pick"] == "eric" and rows[2]["a_pick"] == "KIA"
    assert {p["name"].lower(): p["total_picks"] for p in build_people(db)} == {"nj": 3, "eric": 2, "kia": 1}
    payouts = {p["name"].lower(): p["unpaid_sum"] for p in build_payouts(db, 0, 100)}
    assert payouts == {"kia": 15.0}


def test_inline_drop_edit_saves_and_returns_json(app):
    client = app.test_client()
    client.post("/drops/new", data={"item": "Eye", "member": "KIA", "sale_price": "10"})
    resp = client.post("/drops/1/edit", data={"inline": "1", "item": "Eye", "member": "KIA",
                                              "sale_price": "12", "sold_date": "6/14", "paid": "1"})
    assert resp.status_code == 200 and resp.get_json() == {"ok": True}
    db = connect(app)
    row = db.execute("SELECT sale_price, sold_date, paid FROM drops WHERE id = 1").fetchone()
    assert (row["sale_price"], row["sold_date"], row["paid"]) == (12.0, "6/14", 1)


def test_inline_edit_error_does_not_save_and_returns_422(app):
    client = app.test_client()
    client.post("/runs/new", data={"partner": "ERIC", "a_pick": "NJ"})
    resp = client.post("/runs/1/edit", data={"inline": "1", "partner": "ERIC", "a_pick": "KIA"})
    assert resp.status_code == 422
    assert any("不是 NJ" in e for e in resp.get_json()["errors"])
    db = connect(app)
    assert db.execute("SELECT a_pick FROM runs WHERE id = 1").fetchone()["a_pick"] == "NJ"


def test_copy_last_run_inherits_all_fields(app):
    client = app.test_client()
    client.post("/runs/new", data={"run_date": "7/19", "partner": "KIA", "is_guest": "1",
                                   "a_pick": "KIA", "b_pick": "NJ", "tape_pick": "NJ", "note": "x"})
    resp = client.post("/runs/copy-last")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/runs")
    db = connect(app)
    rows = db.execute("SELECT run_date, partner, is_guest, a_pick, b_pick, c_pick, tape_pick, note "
                      "FROM runs ORDER BY id").fetchall()
    assert len(rows) == 2
    assert dict(rows[0]) == dict(rows[1])


def test_copy_last_run_with_no_runs_opens_blank_form(app):
    client = app.test_client()
    resp = client.post("/runs/copy-last")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/runs/new")


def test_payout_details_list_items_and_formula(loaded, app):
    payouts = {p["name"].lower(): p for p in build_payouts(loaded, 3, 50)}
    kia = payouts["kia"]
    assert kia["formula"] == "224 × 97% × 50% = 108.64"
    assert [i["item"] for i in kia["sold_items"]] == ["Eye for DEX 60%", "shield MA 60%",
                                                 "face for DEX 60%", "face for INT 60%",
                                                 "Eye for LKUK 60%"]
    assert kia["incomplete_items"] == ["EP 11211"]
    page = app.test_client().get("/").get_data(as_text=True)
    assert "計算式：KIA" not in page
    assert "224 × 97% × 50% = 108.64" in page
    assert "shield MA 60%" in page and "未計入（缺賣出價）" in page

def test_partner_breakdown_matches_sheet(loaded):
    from app import build_partner_breakdown
    rows = {p["name"]: p for p in build_partner_breakdown(loaded)}
    assert rows["hangi"]["picks"]["tape_pick"] == 1       # 跟 hangi 打到 tape
    assert rows["XL"]["picks"]["c_pick"] == 1             # 跟 XL 打到 C
    assert rows["ERIC"]["total"] == 2                     # B、C
    assert rows["KIA"]["total"] == 6 and rows["KIA"]["runs"] == 4
    assert rows["（沒有同行者）"]["total"] == 8
    assert sum(p["total"] for p in rows.values()) == 18   # 與 NJ 總數一致


def test_drops_page_shows_payment_status_icons(app):
    client = app.test_client()
    client.post("/drops/new", data={"item": "A", "member": "KIA", "sale_price": "10", "sold_date": "1/1"})
    client.post("/drops/new", data={"item": "B", "member": "KIA", "sale_price": "10", "sold_date": "1/1", "paid": "1"})
    client.post("/drops/new", data={"item": "C", "member": "KIA"})  # 沒有賣出價 → 未完成
    page = client.get("/drops").get_data(as_text=True)
    assert "⏳ 未付" in page and "✅ 已付" in page and "⚠️ 未完成" in page


def test_one_click_pay_marks_paid_and_records_amount(loaded, app):
    db = connect(app)
    unpaid_ids = [r["id"] for r in db.execute(
        "SELECT id FROM drops WHERE lower(member) = 'kia' AND paid = 0 AND sale_price IS NOT NULL")]
    assert len(unpaid_ids) == 5
    client = app.test_client()
    resp = client.post("/payouts/pay", data={"member": "KIA", "paid_date": "2026-11-02"})
    assert resp.status_code == 302
    rows = db.execute(f"SELECT id, paid, paid_date FROM drops WHERE id IN ({','.join('?' * len(unpaid_ids))})",
                      unpaid_ids).fetchall()
    assert all(r["paid"] == 1 and r["paid_date"] == "2026-11-02" for r in rows)
    # 沒有賣出價的 EP 11211 不會被付款
    assert db.execute("SELECT paid FROM drops WHERE item = 'EP 11211'").fetchone()["paid"] == 0
    pay = db.execute("SELECT * FROM payments").fetchone()
    assert (pay["member"], pay["paid_date"], pay["amount"], pay["item_count"]) == ("KIA", "2026-11-02", 108.64, 5)
    assert pay["formula"] == "224 × 97% × 50% = 108.64"
    kia_after = {p["name"].lower(): p for p in build_payouts(db, 3, 50)}["kia"]
    assert kia_after["unpaid_sum"] == 0 and kia_after["payout"] == 0


def test_pay_with_nothing_to_pay_records_nothing(loaded, app):
    client = app.test_client()
    client.post("/payouts/pay", data={"member": "ERIC", "paid_date": "2026-11-02"})
    db = connect(app)
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_migration_adds_paid_date_to_old_database(tmp_path):
    import sqlite3 as sq
    path = tmp_path / "old.db"
    old = sq.connect(path)
    old.executescript("""CREATE TABLE drops (id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT NOT NULL,
        member TEXT NOT NULL, market_price REAL, sale_price REAL, sold_date TEXT NOT NULL DEFAULT '',
        paid INTEGER NOT NULL DEFAULT 0);
        INSERT INTO drops (item, member, sale_price) VALUES ('old', 'KIA', 10);""")
    old.commit(); old.close()
    app = create_app(path)
    db = connect(app)
    cols = {r[1] for r in db.execute("PRAGMA table_info(drops)")}
    assert "paid_date" in cols
    assert db.execute("SELECT item, paid_date FROM drops").fetchone()["paid_date"] == ""


def test_backup_download_is_a_valid_sqlite_snapshot(loaded, app, tmp_path):
    client = app.test_client()
    resp = client.get("/backup")
    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"].startswith('attachment; filename="rms-loot-')
    assert resp.data.startswith(b"SQLite format 3\x00")
    snap_path = tmp_path / "snap.db"
    snap_path.write_bytes(resp.data)
    snap = sqlite3.connect(snap_path)
    assert snap.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 11
    assert snap.execute("SELECT COUNT(*) FROM drops").fetchone()[0] == 19
    snap.close()


DISCORD_ENV = {
    "DISCORD_CLIENT_ID": "123",
    "DISCORD_CLIENT_SECRET": "shh",
    "DISCORD_REDIRECT_URI": "https://example.test/auth/discord/callback",
    "OWNER_DISCORD_IDS": "1566669526534324304",
    "RMS_SECRET_KEY": "fixed-test-key",
}
OWNER = "1566669526534324304"


@pytest.fixture
def discord_app(tmp_path, monkeypatch):
    for k in ("APP_PASSWORD", "RMS_REQUIRE_AUTH"):
        monkeypatch.delenv(k, raising=False)
    for k, v in DISCORD_ENV.items():
        monkeypatch.setenv(k, v)
    return create_app(tmp_path / "discord.db")


def _login_state(client):
    loc = client.get("/auth/discord/login").headers["Location"]
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))["state"], loc


def _log_in_as(app, monkeypatch, discord_id):
    import app as app_module
    monkeypatch.setattr(app_module, "discord_exchange_code", lambda code, cfg: "tok")
    monkeypatch.setattr(app_module, "discord_fetch_user_id", lambda tok: discord_id)
    client = app.test_client()
    state, _ = _login_state(client)
    client.get(f"/auth/discord/callback?code=abc&state={state}")
    return client


def test_discord_gate_redirects_anonymous_to_login(discord_app):
    client = discord_app.test_client()
    resp = client.get("/")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/auth/discord/login")
    assert client.get("/healthz").status_code == 200
    assert client.post("/runs/new", data={}).status_code == 401


def test_discord_login_points_to_discord_with_identify_scope(discord_app):
    client = discord_app.test_client()
    _, loc = _login_state(client)
    assert loc.startswith("https://discord.com/oauth2/authorize?")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))
    assert q["client_id"] == "123" and q["scope"] == "identify" and q["response_type"] == "code"


def test_discord_callback_rejects_bad_state(discord_app):
    client = discord_app.test_client()
    _login_state(client)
    assert client.get("/auth/discord/callback?code=x&state=wrong").status_code == 400


def test_owner_has_full_access(discord_app, monkeypatch):
    client = _log_in_as(discord_app, monkeypatch, OWNER)
    assert client.get("/").status_code == 200
    assert client.get("/settings").status_code == 200
    assert client.get("/runs").status_code == 200


def test_unbound_user_is_sent_to_bind_page(discord_app, monkeypatch):
    client = _log_in_as(discord_app, monkeypatch, "999")
    resp = client.get("/")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/auth/bind")
    assert client.get("/auth/bind").status_code == 200


def test_bind_then_member_sees_only_overview_and_own_drops(discord_app, monkeypatch):
    owner = _log_in_as(discord_app, monkeypatch, OWNER)
    owner.post("/drops/new", data={"item": "mine", "member": "KIA", "sale_price": "10", "sold_date": "1/1"})
    owner.post("/drops/new", data={"item": "theirs", "member": "ERIC", "sale_price": "10", "sold_date": "1/1"})
    member = _log_in_as(discord_app, monkeypatch, "555")
    resp = member.post("/auth/bind", data={"name": "KIA"})
    assert resp.status_code == 302
    assert member.get("/").status_code == 200
    assert member.get("/drops").status_code == 200
    assert member.get("/runs").status_code == 403
    assert member.get("/settings").status_code == 403
    assert member.post("/payouts/pay", data={"member": "KIA"}).status_code == 403
    rows = {r["item"]: r["id"] for r in connect(discord_app).execute("SELECT id, item FROM drops")}
    own = member.post(f"/drops/{rows['mine']}/edit", data={"inline": "1", "item": "mine", "member": "KIA",
                                                            "sale_price": "20", "sold_date": "2/2", "paid": "1"})
    assert own.status_code == 200
    db = connect(discord_app)
    row = db.execute("SELECT sale_price, paid FROM drops WHERE id = ?", (rows["mine"],)).fetchone()
    assert row["sale_price"] == 20 and row["paid"] == 0  # 成員不能改已付狀態
    other = member.post(f"/drops/{rows['theirs']}/edit", data={"inline": "1", "item": "theirs", "member": "ERIC",
                                                               "sale_price": "1", "sold_date": "2/2"})
    assert other.status_code == 403


def test_name_can_only_be_bound_once(discord_app, monkeypatch):
    first = _log_in_as(discord_app, monkeypatch, "111")
    assert first.post("/auth/bind", data={"name": "XL"}).status_code == 302
    second = _log_in_as(discord_app, monkeypatch, "222")
    resp = second.post("/auth/bind", data={"name": "XL"})
    assert resp.status_code == 200  # 重新顯示表單，不綁定
    assert 'value="XL"' not in resp.get_data(as_text=True)  # 已綁定的名字不能再選


def test_static_files_are_open_before_login(discord_app):
    client = discord_app.test_client()
    assert client.get("/static/style.css").status_code == 200


def test_discord_requires_fixed_secret_key(tmp_path, monkeypatch):
    for k, v in DISCORD_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("RMS_SECRET_KEY")
    with pytest.raises(RuntimeError):
        create_app(tmp_path / "nokey.db")


def test_discord_http_error_shows_discord_reason(discord_app, monkeypatch):
    import app as app_module
    import io
    import urllib.error

    def fail(code, cfg):
        raise urllib.error.HTTPError("https://discord.com/api/oauth2/token", 401, "Unauthorized", {},
                                     io.BytesIO(b'{"error": "invalid_client", "error_description": "invalid client"}'))
    monkeypatch.setattr(app_module, "discord_exchange_code", fail)
    client = discord_app.test_client()
    state, _ = _login_state(client)
    resp = client.get(f"/auth/discord/callback?code=abc&state={state}")
    assert resp.status_code == 502
    body = resp.get_data(as_text=True)
    assert "invalid_client" in body and "HTTP 401" in body
    assert "fixed-test-key" not in body and "shh" not in body


def test_discord_requests_send_a_user_agent(monkeypatch):
    import app as app_module
    seen = []

    class FakeResp:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(req, timeout=None):
        seen.append(req.get_header("User-agent"))
        if req.full_url == app_module.DISCORD_TOKEN_URL:
            return FakeResp(b'{"access_token": "tok"}')
        return FakeResp(b'{"id": "42"}')

    monkeypatch.setattr(app_module.urllib.request, "urlopen", fake_urlopen)
    cfg = {"DISCORD_CLIENT_ID": "1", "DISCORD_CLIENT_SECRET": "s", "DISCORD_REDIRECT_URI": "https://x/cb"}
    token = app_module.discord_exchange_code("code", cfg)
    assert app_module.discord_fetch_user_id(token) == "42"
    assert seen == [app_module.DISCORD_USER_AGENT, app_module.DISCORD_USER_AGENT]
    assert not app_module.DISCORD_USER_AGENT.startswith("Python-urllib")


def test_logout_button_shows_when_logged_in(discord_app, monkeypatch):
    client = _log_in_as(discord_app, monkeypatch, OWNER)
    page = client.get("/").get_data(as_text=True)
    assert "/auth/logout" in page and "登出" in page
    anon = discord_app.test_client().get("/auth/discord/login")
    assert anon.status_code == 302  # 未登入時不會顯示登出（登入頁本身不渲染導覽列）

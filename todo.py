"""TODO 清單：每位使用者的待辦存在資料庫，依 Discord ID 分開（見 docs/adr/0010-todo-in-database.md）。

- 沒有啟用 Discord 登入時，所有人共用同一份清單（owner = "local"）。
- 寫入一律需要 JSON 請求（會觸發 CORS 預檢，擋掉一般的跨站表單），並且只能改自己的項目。
- 權限閘門在 app.py 的 password_gate 放行 owner 與 member；其他身分回 401。
"""

import re

from flask import abort, jsonify, request, session

GROUPS = ("level", "quest")
MAX_TEXT = 120
MAX_NOTE = 2000
MAX_IMPORT = 500
SLUG_RE = re.compile(r"^[A-Za-z0-9._~-]{0,120}$")
LINK_RE = re.compile(r"^(https?://\S{1,500})?$", re.IGNORECASE)

TODO_SCHEMA = """
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    grp TEXT NOT NULL CHECK (grp IN ('level', 'quest')),
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    slug TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS todos_owner ON todos (owner, grp, id);
"""


def register_todo(app, get_db):
    def owner_key():
        if not app.config["DISCORD_ON"]:
            return "local"
        return session.get("discord_id") or None

    def require_owner():
        key = owner_key()
        if key is None:
            abort(401)
        return key

    def require_json():
        if not request.is_json:
            abort(415)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            abort(400)
        return body

    def check_fields(body, partial=False):
        """驗證並整理欄位。partial=True 時只檢查有傳入的欄位。"""
        out = {}
        if "text" in body or not partial:
            text = str(body.get("text", "")).strip()
            if not text or len(text) > MAX_TEXT:
                abort(400, description=f"項目文字需要 1 到 {MAX_TEXT} 個字")
            out["text"] = text
        if "done" in body or not partial:
            out["done"] = 1 if body.get("done") else 0
        if "note" in body or not partial:
            note = str(body.get("note", ""))
            if len(note) > MAX_NOTE:
                abort(400, description=f"備註最多 {MAX_NOTE} 字")
            out["note"] = note
        if "link" in body or not partial:
            link = str(body.get("link", "")).strip()
            if not LINK_RE.match(link):
                abort(400, description="連結需要以 http:// 或 https:// 開頭")
            out["link"] = link
        if "slug" in body or not partial:
            slug = str(body.get("slug", "")).strip()
            if not SLUG_RE.match(slug):
                abort(400, description="攻略頁的 slug 格式不正確")
            out["slug"] = slug
        return out

    def group_of(body):
        grp = body.get("group")
        if grp not in GROUPS:
            abort(400, description="group 只能是 level 或 quest")
        return grp

    def serialize(row):
        return {
            "id": row["id"],
            "group": row["grp"],
            "text": row["text"],
            "done": bool(row["done"]),
            "note": row["note"],
            "link": row["link"],
            "slug": row["slug"],
        }

    def fetch_owned(db, owner, todo_id):
        row = db.execute("SELECT * FROM todos WHERE id = ? AND owner = ?", (todo_id, owner)).fetchone()
        if row is None:
            abort(404)
        return row

    @app.get("/api/todos")
    def todos_list():
        owner = require_owner()
        rows = get_db().execute(
            "SELECT * FROM todos WHERE owner = ? ORDER BY id", (owner,)).fetchall()
        result = {g: [] for g in GROUPS}
        for r in rows:
            result[r["grp"]].append(serialize(r))
        return jsonify(result)

    @app.post("/api/todos")
    def todos_create():
        owner = require_owner()
        body = require_json()
        grp = group_of(body)
        fields = check_fields({"text": body.get("text")}, partial=True)
        db = get_db()
        cur = db.execute("INSERT INTO todos (owner, grp, text) VALUES (?, ?, ?)",
                         (owner, grp, fields["text"]))
        db.commit()
        row = db.execute("SELECT * FROM todos WHERE id = ?", (cur.lastrowid,)).fetchone()
        return jsonify(serialize(row)), 201

    @app.route("/api/todos/<int:todo_id>", methods=["PATCH", "DELETE"])
    def todos_item(todo_id):
        owner = require_owner()
        db = get_db()
        row = fetch_owned(db, owner, todo_id)
        if request.method == "DELETE":
            db.execute("DELETE FROM todos WHERE id = ? AND owner = ?", (todo_id, owner))
            db.commit()
            return jsonify(ok=True)
        body = require_json()
        fields = check_fields(body, partial=True)
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            db.execute(f"UPDATE todos SET {sets} WHERE id = ? AND owner = ?",
                       (*fields.values(), todo_id, owner))
            db.commit()
            row = fetch_owned(db, owner, todo_id)
        return jsonify(serialize(row))

    @app.post("/api/todos/clear-done")
    def todos_clear_done():
        owner = require_owner()
        grp = group_of(require_json())
        db = get_db()
        cur = db.execute("DELETE FROM todos WHERE owner = ? AND grp = ? AND done = 1", (owner, grp))
        db.commit()
        return jsonify(ok=True, removed=cur.rowcount)

    @app.post("/api/todos/import")
    def todos_import():
        """把瀏覽器裡舊的清單搬進資料庫。只有在這個使用者還沒有任何項目時才會執行。"""
        owner = require_owner()
        body = require_json()
        db = get_db()
        if db.execute("SELECT 1 FROM todos WHERE owner = ? LIMIT 1", (owner,)).fetchone():
            return jsonify(ok=False, error="已經有資料，沒有匯入"), 409
        items = []
        for grp in GROUPS:
            for item in (body.get(grp) or []):
                if not isinstance(item, dict):
                    abort(400)
                items.append((grp, item))
        if len(items) > MAX_IMPORT:
            abort(400, description=f"一次最多匯入 {MAX_IMPORT} 筆")
        for grp, item in items:
            fields = check_fields({
                "text": item.get("text"), "done": item.get("done"), "note": item.get("note", ""),
                "link": item.get("link", ""), "slug": item.get("slug", ""),
            })
            db.execute(
                "INSERT INTO todos (owner, grp, text, done, note, link, slug) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (owner, grp, fields["text"], fields["done"], fields["note"], fields["link"], fields["slug"]))
        db.commit()
        return jsonify(ok=True, imported=len(items))

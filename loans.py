"""借還紀錄：借出或借入的裝備，附文字與圖片。

- 文字存在 loans 表，圖片存在 loan_images 表，實體檔案放在資料庫旁邊的 uploads/ 目錄。
- 圖片上傳前先用 images.compress_image 壓縮（約 400 KB 以下）。
- 空間到嚴重警告（95%）時拒絕上傳（見 docs/adr/0001-storage-space-warning.md）。
- 權限：有開 Discord 登入時只有 owner 能新增、修改、刪除、上傳；成員只能看（由 password_gate 擋 POST）。
"""

import uuid
from datetime import date
from pathlib import Path

from flask import abort, flash, redirect, render_template, request, send_from_directory, session, url_for

from images import ImageRejected, compress_image
from storage import storage_status

MAX_FILES_PER_UPLOAD = 10
MAX_REQUEST_BYTES = 12 * 1024 * 1024  # 單次請求上限（多張圖一起）
DIRECTIONS = {"lent": "我借出", "borrowed": "我借入"}

LOAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL CHECK (direction IN ('lent', 'borrowed')),
    counterpart TEXT NOT NULL DEFAULT '',
    item TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    loan_date TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    returned INTEGER NOT NULL DEFAULT 0,
    returned_date TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS loan_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id INTEGER NOT NULL,
    filename TEXT NOT NULL UNIQUE
);
"""


def register_loans(app, get_db, known_names):
    """把借還相關的路由掛到 app 上。get_db / known_names 由 app.py 提供。"""
    upload_dir = Path(app.config["DB_PATH"]).resolve().parent / "uploads"
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES

    def can_edit():
        return not app.config["DISCORD_ON"] or session.get("role") == "owner"

    def read_form(form):
        """回傳 (資料, 錯誤清單)。"""
        errors = []
        direction = form.get("direction", "")
        if direction not in DIRECTIONS:
            errors.append("請選擇我借出或我借入")
        item = (form.get("item") or "").strip()
        if not item:
            errors.append("請填寫裝備名稱")
        try:
            quantity = int(form.get("quantity") or 1)
            if quantity < 1:
                raise ValueError
        except ValueError:
            quantity = 1
            errors.append("數量必須是 1 以上的整數")
        returned = 1 if form.get("returned") else 0
        returned_date = (form.get("returned_date") or "").strip() if returned else ""
        data = {
            "direction": direction,
            "counterpart": (form.get("counterpart") or "").strip(),
            "item": item,
            "quantity": quantity,
            "loan_date": (form.get("loan_date") or "").strip(),
            "note": (form.get("note") or "").strip(),
            "returned": returned,
            "returned_date": returned_date,
        }
        return data, errors

    def images_for(db, loan_ids):
        if not loan_ids:
            return {}
        marks = ",".join("?" * len(loan_ids))
        rows = db.execute(
            f"SELECT id, loan_id, filename FROM loan_images WHERE loan_id IN ({marks}) ORDER BY id",
            loan_ids).fetchall()
        grouped = {}
        for r in rows:
            grouped.setdefault(r["loan_id"], []).append(r)
        return grouped

    def save_images(db, loan_id, files):
        """壓縮並存下上傳的圖片，回傳成功張數。"""
        files = [f for f in files if f and f.filename]
        if not files:
            return 0
        if len(files) > MAX_FILES_PER_UPLOAD:
            flash(f"一次最多 {MAX_FILES_PER_UPLOAD} 張喵，貪心的人類。", "error")
            return 0
        status = storage_status(str(upload_dir.parent))
        if status and status["level"] == "critical":
            flash("倉庫快塞爆了（超過 95%），圖片本喵不收喵，先刪一些或擴充 volume。", "error")
            return 0
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved = 0
        for f in files:
            try:
                data = compress_image(f.read())
            except ImageRejected:
                flash(f"「{f.filename}」不是圖片喵，本喵跳過了。", "error")
                continue
            name = f"{uuid.uuid4().hex}.jpg"
            (upload_dir / name).write_bytes(data)
            db.execute("INSERT INTO loan_images (loan_id, filename) VALUES (?, ?)", (loan_id, name))
            saved += 1
        db.commit()
        return saved

    def remove_files(names):
        for name in names:
            (upload_dir / name).unlink(missing_ok=True)

    @app.get("/loans")
    def loans_list():
        db = get_db()
        direction = request.args.get("direction", "all")
        view = "archived" if request.args.get("view") == "archived" else "active"
        archived = 1 if view == "archived" else 0
        if direction in DIRECTIONS:
            rows = db.execute("SELECT * FROM loans WHERE archived = ? AND direction = ? ORDER BY id DESC",
                              (archived, direction)).fetchall()
        else:
            direction = "all"
            rows = db.execute("SELECT * FROM loans WHERE archived = ? ORDER BY id DESC",
                              (archived,)).fetchall()
        counts = {
            "active": db.execute("SELECT COUNT(*) FROM loans WHERE archived = 0").fetchone()[0],
            "archived": db.execute("SELECT COUNT(*) FROM loans WHERE archived = 1").fetchone()[0],
            "returned_active": db.execute(
                "SELECT COUNT(*) FROM loans WHERE archived = 0 AND returned = 1").fetchone()[0],
        }
        # 封存的紀錄只在「已封存」檢視才會列出，所以圖片也只在那時才查詢與載入
        images = images_for(db, [r["id"] for r in rows])
        return render_template("loans.html", loans=rows, images=images, direction=direction,
                               directions=DIRECTIONS, can_edit=can_edit(), view=view, counts=counts)

    def set_archived(loan_id, value):
        if not can_edit():
            abort(403)
        db = get_db()
        if db.execute("SELECT 1 FROM loans WHERE id = ?", (loan_id,)).fetchone() is None:
            abort(404)
        db.execute("UPDATE loans SET archived = ? WHERE id = ?", (value, loan_id))
        db.commit()

    @app.post("/loans/<int:loan_id>/archive")
    def loan_archive(loan_id):
        set_archived(loan_id, 1)
        flash("已封進冷凍櫃喵，平常不拿出來。", "ok")
        return redirect(request.form.get("next") or url_for("loans_list"))

    @app.post("/loans/<int:loan_id>/unarchive")
    def loan_unarchive(loan_id):
        set_archived(loan_id, 0)
        flash("拿出來了喵。", "ok")
        return redirect(request.form.get("next") or url_for("loans_list", view="archived"))

    @app.post("/loans/archive-returned")
    def loans_archive_returned():
        if not can_edit():
            abort(403)
        db = get_db()
        cur = db.execute("UPDATE loans SET archived = 1 WHERE archived = 0 AND returned = 1")
        db.commit()
        flash(f"已封進冷凍櫃 {cur.rowcount} 筆喵（都是還完的）。", "ok")
        return redirect(url_for("loans_list"))

    @app.route("/loans/new", methods=["GET", "POST"])
    def loan_new():
        if not can_edit():
            abort(403)
        db = get_db()
        data = {"direction": "lent", "counterpart": "", "item": "", "quantity": 1,
                "loan_date": date.today().isoformat(), "note": "", "returned": 0, "returned_date": ""}
        errors = []
        if request.method == "POST":
            data, errors = read_form(request.form)
            if not errors:
                cur = db.execute(
                    "INSERT INTO loans (direction, counterpart, item, quantity, loan_date, note, "
                    "returned, returned_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (data["direction"], data["counterpart"], data["item"], data["quantity"],
                     data["loan_date"], data["note"], data["returned"], data["returned_date"]))
                db.commit()
                loan_id = cur.lastrowid
                saved = save_images(db, loan_id, request.files.getlist("files"))
                flash(f"借還紀錄記下了喵" + (f"，還加進 {saved} 張圖片" if saved else "") + "。", "ok")
                return redirect(url_for("loan_edit", loan_id=loan_id))
        return render_template("loan_form.html", title="新增借還紀錄", action=url_for("loan_new"),
                               data=data, errors=errors, names=known_names(db), images=[],
                               loan_id=None, directions=DIRECTIONS)

    @app.route("/loans/<int:loan_id>/edit", methods=["GET", "POST"])
    def loan_edit(loan_id):
        if not can_edit():
            abort(403)
        db = get_db()
        row = db.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
        if row is None:
            abort(404)
        data, errors = dict(row), []
        if request.method == "POST":
            data, errors = read_form(request.form)
            if not errors:
                db.execute(
                    "UPDATE loans SET direction=?, counterpart=?, item=?, quantity=?, loan_date=?, "
                    "note=?, returned=?, returned_date=? WHERE id=?",
                    (data["direction"], data["counterpart"], data["item"], data["quantity"],
                     data["loan_date"], data["note"], data["returned"], data["returned_date"], loan_id))
                db.commit()
                flash("存好了喵。", "ok")
                return redirect(url_for("loan_edit", loan_id=loan_id))
        images = images_for(db, [loan_id]).get(loan_id, [])
        return render_template("loan_form.html", title="編輯借還紀錄", action=url_for("loan_edit", loan_id=loan_id),
                               data=data, errors=errors, names=known_names(db), images=images,
                               loan_id=loan_id, directions=DIRECTIONS)

    @app.post("/loans/<int:loan_id>/images")
    def loan_images_add(loan_id):
        if not can_edit():
            abort(403)
        db = get_db()
        if db.execute("SELECT 1 FROM loans WHERE id = ?", (loan_id,)).fetchone() is None:
            abort(404)
        saved = save_images(db, loan_id, request.files.getlist("files"))
        if saved:
            flash(f"加進 {saved} 張圖片了喵。", "ok")
        return redirect(url_for("loan_edit", loan_id=loan_id))

    @app.post("/loan-images/<int:image_id>/delete")
    def loan_image_delete(image_id):
        if not can_edit():
            abort(403)
        db = get_db()
        row = db.execute("SELECT loan_id, filename FROM loan_images WHERE id = ?", (image_id,)).fetchone()
        if row is None:
            abort(404)
        db.execute("DELETE FROM loan_images WHERE id = ?", (image_id,))
        db.commit()
        remove_files([row["filename"]])
        flash("圖片刪掉了喵，後悔別來找本喵。", "ok")
        return redirect(url_for("loan_edit", loan_id=row["loan_id"]))

    @app.post("/loans/<int:loan_id>/delete")
    def loan_delete(loan_id):
        if not can_edit():
            abort(403)
        db = get_db()
        names = [r["filename"] for r in db.execute(
            "SELECT filename FROM loan_images WHERE loan_id = ?", (loan_id,)).fetchall()]
        db.execute("DELETE FROM loan_images WHERE loan_id = ?", (loan_id,))
        db.execute("DELETE FROM loans WHERE id = ?", (loan_id,))
        db.commit()
        remove_files(names)
        flash("整筆刪光光了喵，別哭喵。", "ok")
        return redirect(url_for("loans_list"))

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename):
        if "/" in filename or "\\" in filename or not filename.endswith(".jpg"):
            abort(404)
        return send_from_directory(upload_dir, filename, mimetype="image/jpeg")

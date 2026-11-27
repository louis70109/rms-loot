import sqlite3
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import storage
from app import create_app

DISCORD_ENV = {
    "DISCORD_CLIENT_ID": "123",
    "DISCORD_CLIENT_SECRET": "shh",
    "DISCORD_REDIRECT_URI": "https://example.test/auth/discord/callback",
    "OWNER_DISCORD_IDS": "1566669526534324304",
    "RMS_SECRET_KEY": "fixed-test-key",
}


def _png(color=(200, 60, 60), size=(640, 480)):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _db(app):
    db = sqlite3.connect(app.config["DB_PATH"])
    db.row_factory = sqlite3.Row
    return db


def _upload_dir(app):
    return Path(app.config["DB_PATH"]).resolve().parent / "uploads"


def _create_loan(client, **overrides):
    form = {"direction": "lent", "counterpart": "ERIC", "item": "Eye for DEX 60%",
            "quantity": "1", "loan_date": "2026-11-16", "note": "", "returned_date": ""}
    form.update(overrides)
    return client.post("/loans/new", data=form)


@pytest.fixture
def app(tmp_path, monkeypatch):
    for k in ("APP_PASSWORD", "RMS_REQUIRE_AUTH", "RMS_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    return create_app(tmp_path / "loans.db")


@pytest.fixture
def client(app):
    return app.test_client()


def test_create_loan_with_text(client, app):
    resp = _create_loan(client)
    assert resp.status_code == 302
    db = _db(app)
    row = db.execute("SELECT * FROM loans").fetchone()
    assert row["direction"] == "lent"
    assert row["counterpart"] == "ERIC"
    assert row["item"] == "Eye for DEX 60%"
    assert row["returned"] == 0


def test_invalid_form_shows_errors_and_saves_nothing(client, app):
    resp = _create_loan(client, direction="???", item="", quantity="0")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "請選擇我借出或我借入" in html
    assert "請填寫裝備名稱" in html
    assert _db(app).execute("SELECT COUNT(*) FROM loans").fetchone()[0] == 0


def test_upload_multiple_images_are_compressed_and_saved(client, app):
    data = {"direction": "borrowed", "item": "Shield", "quantity": "1",
            "files": [(BytesIO(_png((200, 0, 0))), "a.png"), (BytesIO(_png((0, 200, 0))), "b.png")]}
    resp = client.post("/loans/new", data=data, content_type="multipart/form-data")
    assert resp.status_code == 302
    db = _db(app)
    images = db.execute("SELECT * FROM loan_images ORDER BY id").fetchall()
    assert len(images) == 2
    for img in images:
        path = _upload_dir(app) / img["filename"]
        assert path.exists()
        assert path.read_bytes()[:3] == b"\xff\xd8\xff"  # JPEG
        assert path.stat().st_size < 400_000


def test_non_image_upload_is_rejected(client, app):
    resp = client.post(
        "/loans/new",
        data={"direction": "lent", "item": "Thing", "quantity": "1",
              "files": [(BytesIO(b"not an image"), "fake.png")]},
        content_type="multipart/form-data", follow_redirects=True)
    assert "不是可以讀取的圖片" in resp.get_data(as_text=True)
    assert _db(app).execute("SELECT COUNT(*) FROM loan_images").fetchone()[0] == 0


def test_delete_one_image_keeps_loan_and_removes_file(client, app):
    _create_loan(client)
    client.post("/loans/1/images", data={"files": [(BytesIO(_png()), "a.png")]},
                content_type="multipart/form-data")
    img = _db(app).execute("SELECT * FROM loan_images").fetchone()
    path = _upload_dir(app) / img["filename"]
    assert path.exists()

    client.post(f"/loan-images/{img['id']}/delete")
    db = _db(app)
    assert db.execute("SELECT COUNT(*) FROM loan_images").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM loans").fetchone()[0] == 1
    assert not path.exists()


def test_delete_loan_removes_all_its_images(client, app):
    _create_loan(client)
    client.post("/loans/1/images", data={"files": [(BytesIO(_png((1, 2, 3))), "a.png"),
                                                    (BytesIO(_png((4, 5, 6))), "b.png")]},
                content_type="multipart/form-data")
    names = [r["filename"] for r in _db(app).execute("SELECT filename FROM loan_images").fetchall()]
    assert len(names) == 2

    client.post("/loans/1/delete")
    db = _db(app)
    assert db.execute("SELECT COUNT(*) FROM loans").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM loan_images").fetchone()[0] == 0
    assert all(not (_upload_dir(app) / n).exists() for n in names)


def test_return_fields_are_saved(client, app):
    _create_loan(client)
    client.post("/loans/1/edit", data={"direction": "lent", "item": "Eye for DEX 60%", "quantity": "1",
                                       "returned": "1", "returned_date": "2026-11-20"})
    row = _db(app).execute("SELECT returned, returned_date FROM loans WHERE id = 1").fetchone()
    assert row["returned"] == 1
    assert row["returned_date"] == "2026-11-20"


def test_uploaded_image_is_served_and_traversal_is_blocked(client, app):
    _create_loan(client)
    client.post("/loans/1/images", data={"files": [(BytesIO(_png()), "a.png")]},
                content_type="multipart/form-data")
    name = _db(app).execute("SELECT filename FROM loan_images").fetchone()["filename"]
    resp = client.get(f"/uploads/{name}")
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    assert client.get("/uploads/..%2Fapp.py").status_code == 404
    assert client.get("/uploads/nope.jpg").status_code == 404


def test_upload_refused_when_storage_is_critical(client, app, monkeypatch):
    _create_loan(client)
    monkeypatch.setattr(storage, "_usage", lambda p: (0.97, 1_000_000, 970_000))
    resp = client.post("/loans/1/images", data={"files": [(BytesIO(_png()), "a.png")]},
                       content_type="multipart/form-data", follow_redirects=True)
    assert "無法上傳圖片" in resp.get_data(as_text=True)
    assert _db(app).execute("SELECT COUNT(*) FROM loan_images").fetchone()[0] == 0


def test_loan_list_filters_by_direction(client):
    _create_loan(client, direction="lent", item="Lent item")
    _create_loan(client, direction="borrowed", item="Borrowed item")
    html = client.get("/loans?direction=borrowed").get_data(as_text=True)
    assert "Borrowed item" in html
    assert "Lent item" not in html


# ---- Discord 登入時的權限：成員只能看，owner 才能改 ------------------------

@pytest.fixture
def discord_client(tmp_path, monkeypatch):
    for k in ("APP_PASSWORD", "RMS_REQUIRE_AUTH", "RMS_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in DISCORD_ENV.items():
        monkeypatch.setenv(k, v)
    app = create_app(tmp_path / "discord-loans.db")
    return app, app.test_client()


def test_member_can_view_but_not_edit(discord_client):
    app, client = discord_client
    with client.session_transaction() as s:
        s["role"] = "member"
        s["name"] = "ERIC"
    assert client.get("/loans").status_code == 200
    assert "＋ 新增借還" not in client.get("/loans").get_data(as_text=True)
    assert client.get("/loans/new").status_code == 403
    assert client.post("/loans/new", data={"item": "x"}).status_code == 403
    assert client.post("/loans/1/delete").status_code == 403


def test_owner_can_create(discord_client):
    app, client = discord_client
    with client.session_transaction() as s:
        s["role"] = "owner"
        s["name"] = "NJ"
    resp = _create_loan(client)
    assert resp.status_code == 302
    assert _db(app).execute("SELECT COUNT(*) FROM loans").fetchone()[0] == 1


def test_anonymous_cannot_read_uploads(discord_client):
    app, client = discord_client
    resp = client.get("/uploads/anything.jpg")
    assert resp.status_code == 401  # 未登入：顯示擋板頁面


# ---- 封存（冷資料）-------------------------------------------------------

def test_archived_loans_are_hidden_until_requested(client, app):
    _create_loan(client, item="進行中的裝備")
    _create_loan(client, item="封存的裝備")
    client.post("/loans/2/archive")
    default = client.get("/loans").get_data(as_text=True)
    assert "進行中的裝備" in default
    assert "封存的裝備" not in default
    archived = client.get("/loans?view=archived").get_data(as_text=True)
    assert "封存的裝備" in archived
    assert "進行中的裝備" not in archived


def test_unarchive_brings_it_back(client, app):
    _create_loan(client, item="來回的裝備")
    client.post("/loans/1/archive")
    assert "來回的裝備" not in client.get("/loans").get_data(as_text=True)
    client.post("/loans/1/unarchive")
    assert "來回的裝備" in client.get("/loans").get_data(as_text=True)


def test_archive_returned_only_touches_returned_items(client, app):
    _create_loan(client, item="已歸還")
    _create_loan(client, item="還沒還")
    client.post("/loans/1/edit", data={"direction": "lent", "item": "已歸還", "quantity": "1",
                                       "returned": "1", "returned_date": "2026-11-20"})
    resp = client.post("/loans/archive-returned", follow_redirects=True)
    assert "已封存 1 筆" in resp.get_data(as_text=True)
    db = _db(app)
    rows = {r["item"]: r["archived"] for r in db.execute("SELECT item, archived FROM loans")}
    assert rows == {"已歸還": 1, "還沒還": 0}


def test_archive_button_on_edit_page(client, app):
    _create_loan(client, item="表單封存")
    page = client.get("/loans/1/edit").get_data(as_text=True)
    assert "封存這筆紀錄" in page
    client.post("/loans/1/archive")
    page = client.get("/loans/1/edit").get_data(as_text=True)
    assert "取消封存" in page


def test_archived_counts_show_in_tabs(client, app):
    _create_loan(client, item="a")
    _create_loan(client, item="b")
    client.post("/loans/1/archive")
    html = client.get("/loans").get_data(as_text=True)
    assert "進行中（1）" in html
    assert "已封存（1）" in html


def test_member_cannot_archive(discord_client):
    app, client = discord_client
    with client.session_transaction() as s:
        s["role"] = "member"
        s["name"] = "ERIC"
    assert client.post("/loans/1/archive").status_code == 403
    assert client.post("/loans/archive-returned").status_code == 403


def test_old_database_gets_archived_column(tmp_path, monkeypatch):
    for k in ("APP_PASSWORD", "RMS_REQUIRE_AUTH"):
        monkeypatch.delenv(k, raising=False)
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT NOT NULL CHECK (direction IN ('lent', 'borrowed')),
            counterpart TEXT NOT NULL DEFAULT '',
            item TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            loan_date TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            returned INTEGER NOT NULL DEFAULT 0,
            returned_date TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO loans (direction, item) VALUES ('lent', '舊資料');
    """)
    old.commit()
    old.close()
    app = create_app(path)
    db = sqlite3.connect(app.config["DB_PATH"])
    cols = {r[1] for r in db.execute("PRAGMA table_info(loans)")}
    assert "archived" in cols
    assert db.execute("SELECT archived FROM loans WHERE item = '舊資料'").fetchone()[0] == 0

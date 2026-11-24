import json
from pathlib import Path

from app import create_app

DISCORD_ENV = {
    "DISCORD_CLIENT_ID": "123",
    "DISCORD_CLIENT_SECRET": "shh",
    "DISCORD_REDIRECT_URI": "https://example.test/auth/discord/callback",
    "OWNER_DISCORD_IDS": "1566669526534324304",
    "RMS_SECRET_KEY": "fixed-test-key",
}
SNAPSHOT = Path(__file__).resolve().parent.parent / "static" / "guide-index-snapshot.json"


def test_todo_page_renders_with_snapshot_url(tmp_path, monkeypatch):
    for k in ("APP_PASSWORD", "RMS_REQUIRE_AUTH"):
        monkeypatch.delenv(k, raising=False)
    client = create_app(tmp_path / "todo.db").test_client()
    resp = client.get("/todo")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "data-todo-root" in html
    assert 'data-group="level"' in html and 'data-group="quest"' in html
    assert "guide-index-snapshot.json" in html
    assert "todo.js" in html
    # 導覽列有 TODO 連結
    assert 'href="/todo"' in html


def test_todo_is_listed_in_nav_for_everyone(tmp_path, monkeypatch):
    for k in ("APP_PASSWORD", "RMS_REQUIRE_AUTH"):
        monkeypatch.delenv(k, raising=False)
    html = create_app(tmp_path / "nav.db").test_client().get("/").get_data(as_text=True)
    assert ">TODO<" in html


def test_snapshot_file_is_a_valid_index():
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    entries = data["entries"]
    assert data["date"]
    assert len(entries) > 0
    for x in entries:
        assert set(x) == {"slug", "title", "cat"}
        assert all(isinstance(x[k], str) and x[k] for k in ("slug", "title", "cat"))
    assert len({x["slug"] for x in entries}) == len(entries)  # slug 不重複


def test_todo_page_is_public_without_login_when_auth_is_off(tmp_path, monkeypatch):
    for k in ("APP_PASSWORD", "RMS_REQUIRE_AUTH"):
        monkeypatch.delenv(k, raising=False)
    assert create_app(tmp_path / "open.db").test_client().get("/todo").status_code == 200


def test_member_can_view_todo_but_anonymous_is_redirected(tmp_path, monkeypatch):
    for k in ("APP_PASSWORD", "RMS_REQUIRE_AUTH"):
        monkeypatch.delenv(k, raising=False)
    for k, v in DISCORD_ENV.items():
        monkeypatch.setenv(k, v)
    app = create_app(tmp_path / "discord-todo.db")
    client = app.test_client()
    assert client.get("/todo").status_code == 302  # 未登入導向 Discord 登入
    with client.session_transaction() as s:
        s["role"] = "member"
        s["name"] = "ERIC"
    assert client.get("/todo").status_code == 200

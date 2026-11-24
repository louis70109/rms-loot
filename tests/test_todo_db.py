import pytest

from app import create_app

DISCORD_ENV = {
    "DISCORD_CLIENT_ID": "123",
    "DISCORD_CLIENT_SECRET": "shh",
    "DISCORD_REDIRECT_URI": "https://example.test/auth/discord/callback",
    "OWNER_DISCORD_IDS": "1566669526534324304",
    "RMS_SECRET_KEY": "fixed-test-key",
}


@pytest.fixture
def open_client(tmp_path, monkeypatch):
    for k in ("APP_PASSWORD", "RMS_REQUIRE_AUTH"):
        monkeypatch.delenv(k, raising=False)
    return create_app(tmp_path / "open.db").test_client()


@pytest.fixture
def discord_app(tmp_path, monkeypatch):
    for k in ("APP_PASSWORD", "RMS_REQUIRE_AUTH"):
        monkeypatch.delenv(k, raising=False)
    for k, v in DISCORD_ENV.items():
        monkeypatch.setenv(k, v)
    return create_app(tmp_path / "discord.db")


def as_user(app, discord_id, role, name):
    client = app.test_client()
    with client.session_transaction() as s:
        s["discord_id"] = discord_id
        s["role"] = role
        s["name"] = name
    return client


def add(client, group, text):
    resp = client.post("/api/todos", json={"group": group, "text": text})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def test_create_list_update_delete_without_discord(open_client):
    item = add(open_client, "quest", "第一階段")
    assert item["text"] == "第一階段" and item["done"] is False
    data = open_client.get("/api/todos").get_json()
    assert [i["text"] for i in data["quest"]] == ["第一階段"]
    assert data["level"] == []

    upd = open_client.patch(f"/api/todos/{item['id']}", json={
        "done": True, "note": "缺道具", "slug": "babywell",
        "link": "https://example.test/x",
    }).get_json()
    assert upd["done"] is True and upd["slug"] == "babywell" and upd["note"] == "缺道具"

    assert open_client.delete(f"/api/todos/{item['id']}").status_code == 200
    assert open_client.get("/api/todos").get_json()["quest"] == []


def test_each_discord_user_only_sees_their_own_items(discord_app):
    alice = as_user(discord_app, "111", "member", "ERIC")
    bob = as_user(discord_app, "222", "member", "KIA")
    item = add(alice, "level", "A 角練到 Lv.10")

    assert bob.get("/api/todos").get_json()["level"] == []
    assert bob.patch(f"/api/todos/{item['id']}", json={"done": True}).status_code == 404
    assert bob.delete(f"/api/todos/{item['id']}").status_code == 404
    # 擁有者仍然看得到自己的項目
    assert [i["text"] for i in alice.get("/api/todos").get_json()["level"]] == ["A 角練到 Lv.10"]


def test_anonymous_and_unbound_get_401(discord_app):
    anon = discord_app.test_client()
    assert anon.get("/api/todos").status_code == 401
    unbound = as_user(discord_app, "333", "unbound", None)
    assert unbound.get("/api/todos").status_code == 401
    assert unbound.post("/api/todos", json={"group": "level", "text": "x"}).status_code == 401


def test_members_and_owner_can_use_their_list(discord_app):
    member = as_user(discord_app, "444", "member", "ERIC")
    owner = as_user(discord_app, "1566669526534324304", "owner", "NJ")
    assert member.post("/api/todos", json={"group": "quest", "text": "m"}).status_code == 201
    assert owner.post("/api/todos", json={"group": "quest", "text": "o"}).status_code == 201


def test_writes_need_json(open_client):
    resp = open_client.post("/api/todos", data="group=level&text=x",
                            content_type="application/x-www-form-urlencoded")
    assert resp.status_code == 415


def test_invalid_input_is_rejected(open_client):
    assert open_client.post("/api/todos", json={"group": "boss", "text": "x"}).status_code == 400
    assert open_client.post("/api/todos", json={"group": "level", "text": "  "}).status_code == 400
    assert open_client.post("/api/todos", json={"group": "level", "text": "x" * 121}).status_code == 400
    item = add(open_client, "level", "x")
    bad_link = open_client.patch(f"/api/todos/{item['id']}", json={"link": "javascript:alert(1)"})
    assert bad_link.status_code == 400
    bad_slug = open_client.patch(f"/api/todos/{item['id']}", json={"slug": "../etc"})
    assert bad_slug.status_code == 400


def test_clear_done_only_removes_finished_items_in_that_group(open_client):
    a = add(open_client, "level", "done-level")
    add(open_client, "level", "todo-level")
    add(open_client, "quest", "done-quest")
    open_client.patch(f"/api/todos/{a['id']}", json={"done": True})
    open_client.patch(f"/api/todos/{open_client.get('/api/todos').get_json()['quest'][0]['id']}",
                      json={"done": True})
    resp = open_client.post("/api/todos/clear-done", json={"group": "level"})
    assert resp.get_json()["removed"] == 1
    data = open_client.get("/api/todos").get_json()
    assert [i["text"] for i in data["level"]] == ["todo-level"]
    assert [i["text"] for i in data["quest"]] == ["done-quest"]


def test_import_only_when_list_is_empty(open_client):
    payload = {
        "level": [{"text": "A", "done": True, "note": "n", "slug": "babywell"}],
        "quest": [{"text": "B", "done": False, "link": "https://example.test/"}],
    }
    resp = open_client.post("/api/todos/import", json=payload)
    assert resp.status_code == 200 and resp.get_json()["imported"] == 2
    data = open_client.get("/api/todos").get_json()
    assert data["level"][0]["done"] is True and data["level"][0]["slug"] == "babywell"
    assert data["quest"][0]["link"] == "https://example.test/"
    # 已經有資料就不再匯入
    assert open_client.post("/api/todos/import", json=payload).status_code == 409
    assert len(open_client.get("/api/todos").get_json()["level"]) == 1


def test_import_rejects_bad_items(open_client):
    resp = open_client.post("/api/todos/import", json={"level": [{"text": ""}]})
    assert resp.status_code == 400
    assert open_client.get("/api/todos").get_json()["level"] == []

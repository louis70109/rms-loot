import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import app as app_module
from app import create_app

DISCORD_ENV = {
    "DISCORD_CLIENT_ID": "123",
    "DISCORD_CLIENT_SECRET": "shh",
    "DISCORD_REDIRECT_URI": "https://example.test/auth/discord/callback",
    "OWNER_DISCORD_IDS": "1566669526534324304",
    "RMS_SECRET_KEY": "fixed-test-key",
}


def _expires_in(set_cookie):
    """從 Set-Cookie 取出 Expires，回傳它距離現在多久。"""
    m = re.search(r"Expires=([^;]+)", set_cookie or "")
    assert m, set_cookie
    return parsedate_to_datetime(m.group(1)) - datetime.now(timezone.utc)


def _login(app, monkeypatch, discord_id):
    monkeypatch.setattr(app_module, "discord_exchange_code", lambda code, cfg: "tok")
    monkeypatch.setattr(app_module, "discord_fetch_user_id", lambda tok: discord_id)
    client = app.test_client()
    loc = client.get("/auth/discord/login").headers["Location"]
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))["state"]
    return client, client.get(f"/auth/discord/callback?code=abc&state={state}")


def test_login_cookie_lasts_one_day(tmp_path, monkeypatch):
    for k, v in DISCORD_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    app = create_app(tmp_path / "ttl.db")
    _, resp = _login(app, monkeypatch, "1566669526534324304")
    left = _expires_in(resp.headers["Set-Cookie"])
    assert timedelta(hours=23, minutes=55) < left <= timedelta(days=1)


def test_session_is_refreshed_on_each_request(tmp_path, monkeypatch):
    for k, v in DISCORD_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    app = create_app(tmp_path / "refresh.db")
    client, _ = _login(app, monkeypatch, "1566669526534324304")
    resp = client.get("/todo")
    assert resp.status_code == 200
    # 每次請求都會重新設定 cookie 的有效期（閒置才會過期）
    left = _expires_in(resp.headers.get("Set-Cookie"))
    assert timedelta(hours=23, minutes=55) < left <= timedelta(days=1)


def test_session_config_has_one_day_lifetime(tmp_path, monkeypatch):
    for k, v in DISCORD_ENV.items():
        monkeypatch.setenv(k, v)
    app = create_app(tmp_path / "cfg.db")
    assert app.config["PERMANENT_SESSION_LIFETIME"].total_seconds() == 86400

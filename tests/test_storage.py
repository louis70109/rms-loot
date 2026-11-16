import storage
from app import create_app


def _fake_usage(monkeypatch, ratio, total=1_073_741_824):
    used = int(total * ratio)
    monkeypatch.setattr(storage, "_usage", lambda path: (ratio, total, used))


def test_below_warning_threshold_shows_nothing(monkeypatch, tmp_path):
    _fake_usage(monkeypatch, 0.79)
    assert storage.storage_status(str(tmp_path)) is None


def test_warning_level_between_80_and_95_percent(monkeypatch, tmp_path):
    _fake_usage(monkeypatch, 0.85)
    status = storage.storage_status(str(tmp_path))
    assert status["level"] == "warning"
    assert status["percent"] == 85
    assert status["total_mb"] == 1024


def test_critical_level_at_95_percent_or_more(monkeypatch, tmp_path):
    _fake_usage(monkeypatch, 0.96)
    assert storage.storage_status(str(tmp_path))["level"] == "critical"


def test_unreadable_path_returns_none(tmp_path):
    # 不存在的路徑，statvfs 會失敗，應該靜默略過而不是讓頁面出錯
    assert storage.storage_status(str(tmp_path / "missing")) is None


def test_warning_dialog_is_rendered_on_pages(monkeypatch, tmp_path):
    _fake_usage(monkeypatch, 0.85)
    app = create_app(tmp_path / "s.db")
    html = app.test_client().get("/").get_data(as_text=True)
    assert 'id="storage-warning"' in html
    assert "儲存空間快滿" in html
    assert "85%" in html
    assert 'data-level="warning"' in html


def test_critical_dialog_uses_critical_text(monkeypatch, tmp_path):
    _fake_usage(monkeypatch, 0.97)
    app = create_app(tmp_path / "s.db")
    html = app.test_client().get("/runs").get_data(as_text=True)
    assert "空間即將用完" in html
    assert 'data-level="critical"' in html


def test_no_dialog_when_space_is_fine(monkeypatch, tmp_path):
    _fake_usage(monkeypatch, 0.30)
    app = create_app(tmp_path / "s.db")
    html = app.test_client().get("/").get_data(as_text=True)
    assert "storage-warning" not in html


def test_page_still_renders_when_usage_cannot_be_read(monkeypatch, tmp_path):
    def broken(path):
        raise OSError("statvfs failed")

    monkeypatch.setattr(storage, "_usage", broken)
    app = create_app(tmp_path / "s.db")
    resp = app.test_client().get("/")
    assert resp.status_code == 200
    assert "storage-warning" not in resp.get_data(as_text=True)

import sqlite3
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
    payouts = {p["name"].lower(): p for p in build_payouts(loaded, 100)}
    assert len(payouts) == 2                           # eric / Eric / ERIC 合併
    assert payouts["kia"]["unpaid_items"] == 5
    assert payouts["kia"]["unpaid_sum"] == 224         # 70+35+19+65+35
    assert payouts["kia"]["unpriced"] == 1             # EP 11211 沒填賣出價
    assert payouts["eric"]["unpaid_sum"] == 0
    assert payouts["eric"]["paid_items"] == 11


def test_payout_percent_applied(loaded):
    payouts = {p["name"].lower(): p for p in build_payouts(loaded, 50)}
    assert payouts["kia"]["payout"] == 112


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
    assert data["a_pick"] == "eric"  # 資料庫裡還沒有這個名字，保留輸入寫法
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

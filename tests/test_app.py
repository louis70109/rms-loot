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
    payouts = {p["name"].lower(): p for p in build_payouts(loaded, 0, 100)}
    assert len(payouts) == 2                           # eric / Eric / ERIC 合併
    assert payouts["kia"]["unpaid_items"] == 4         # 只計已賣出且未付：17~20
    assert payouts["kia"]["unpaid_sum"] == 154         # 35+19+65+35
    assert payouts["kia"]["incomplete"] == 2           # D13 缺賣出日、EP 11211 缺賣出價
    assert payouts["eric"]["unpaid_sum"] == 0
    assert payouts["eric"]["paid_items"] == 11


def test_payout_formula_matches_sheet_g20(loaded):
    # 原表 G20 = 74.69 = 154 × 0.97 ÷ 2（扣 3% 手續費，再對半分）
    payouts = {p["name"].lower(): p for p in build_payouts(loaded, 3, 50)}
    assert payouts["kia"]["payout"] == 74.69
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
    assert kia["formula"] == "154 × 97% × 50% = 74.69"
    assert [i["item"] for i in kia["sold_items"]] == ["shield MA 60%", "face for DEX 60%",
                                                 "face for INT 60%", "Eye for LKUK 60%"]
    assert kia["incomplete_items"] == ["Eye for DEX 60%", "EP 11211"]
    page = app.test_client().get("/").get_data(as_text=True)
    assert "計算式：KIA" not in page
    assert "154 × 97% × 50% = 74.69" in page
    assert "shield MA 60%" in page and "未計入（缺賣出價或賣出日）" in page

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
    client.post("/drops/new", data={"item": "C", "member": "KIA", "sale_price": "10"})
    page = client.get("/drops").get_data(as_text=True)
    assert "⏳ 未付" in page and "✅ 已付" in page and "⚠️ 未完成" in page

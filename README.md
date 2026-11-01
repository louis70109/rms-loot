Flask 3 + SQLite 的 RMS 分贓表系統。

## 啟動

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

打開 http://127.0.0.1:5000

## 功能對應原表

| 原表 | 系統 |
|---|---|
| RMS 分贓紀錄（A捲/B捲/C捲/tape/陪打） | 「分貝紀錄」每場一筆；得主填 NJ 或同行者 |
| 陪打 | 勾選「陪打」；只打過一次的同行者，總覽會標 **下次換他撿** |
| 掉落物 v / member / price / sale price / sold / paid | 「掉落物」頁，paid 點按鈕切換 |
| G 欄（未付金額 + 同名合併） | 總覽的「持有人應付金額」，同名不分大小寫合併 |

## 匯入原本的表

在 Google 試算表每一頁分別：**檔案 → 下載 → 逗號分隔值 (.csv，目前工作表)**，然後到「匯入 / 設定」上傳。
範例檔在 `sample/`（就是你截圖裡的資料）。

匯入有錯誤時整批不會寫入；要重新匯入請勾「先清空」，否則會重複。

## 設定（環境變數，選填）

- `RMS_DB`：資料庫檔路徑，預設 `rms_loot.db`

## 測試

```bash
.venv/bin/python -m pytest -q
```

## 注意

- 預設沒有登入：知道網址的人都能看、改、刪資料。若要加上密碼，設定環境變數 `APP_PASSWORD` 即可（HTTP Basic，帳號隨意）。
- 名字不分大小寫：ERIC / Eric / eric 會被視為同一人，沿用第一次輸入的寫法。

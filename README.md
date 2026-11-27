Flask 3 + SQLite 的 RMS 分貝 / 分贓表系統，部署在 fly.io。

線上網址：https://rms-loot-nj.fly.dev/（PWA：可以用瀏覽器「加入主畫面」安裝）

## 功能

| 頁面 | 內容 |
|---|---|
| 總覽 | 本次應付合計（楓幣）、持有人應付金額（點一下展開明細、一鍵付款）、人員統計、付款紀錄 |
| 分贓紀錄 | 每場一筆；A捲 / B捲 / C捲 / tape 的得主填 NJ 或同行者；勾選「陪打」 |
| 掉落物 | 掉落物、持有人、市價、賣出價、賣出日、付款狀態（點按鈕切換） |
| 借還 | 借出或借入的裝備，文字加多張圖片（選填，自動壓縮），可刪除單張圖片或整筆紀錄；已歸還的可以封存，封存後預設不顯示，到「已封存」才看得到 |
| TODO | 「練腳色」與「解任務」清單，可加備註，並連到攻略庫的頁面；存在資料庫，依 Discord 帳號分開（見 ADR 0010） |
| 匯入 / 設定 | 匯入 CSV、設定手續費與分配比例、下載備份 |

表格可以像試算表一樣操作：Enter / ↓ 往下、Shift+Enter / ↑ 往上、Ctrl+D 把這一列換成上一列的內容、離開格子即自動儲存。

### 分紅計算

應付 = 未付且有賣出價的合計 × (1 − 手續費) × 分配比例，預設手續費 3%、分配 50%，結果四捨五入到小數 2 位。缺賣出價的項目不計金額，列在「未完成」。

## 原表對應

| 原表 | 系統 |
|---|---|
| RMS 分貝紀錄（A捲/B捲/C捲/tape/陪打） | 分贓紀錄 |
| 陪打 | 只打過一次的同行者，總覽會標 **下次換他撿** |
| 掉落物 v / member / price / sale price / sold / paid | 掉落物 |
| G 欄（未付金額 + 同名合併） | 總覽的持有人應付金額，同名不分大小寫合併 |

## 本機執行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python app.py
```

打開 http://127.0.0.1:5000

匯入原本的表：在 Google 試算表每一頁分別「檔案 → 下載 → 逗號分隔值 (.csv，目前工作表)」，然後到「匯入 / 設定」上傳。範例檔在 `sample/`。匯入有錯誤時整批不會寫入；要重新匯入請勾「先清空」，否則會重複。

## 環境變數

| 變數 | 用途 | 必要性 |
|---|---|---|
| `RMS_DB` | 資料庫檔路徑，預設 `rms_loot.db`；圖片放在它旁邊的 `uploads/` | 選填（fly 上為 `/data/rms_loot.db`） |
| `APP_PASSWORD` | 設定後用 HTTP Basic 登入（帳號隨意，只驗密碼） | 選填 |
| `RMS_REQUIRE_AUTH` | 設為 `1` 時，沒有設定 `APP_PASSWORD` 就回 503，避免裸奔 | 選填（fly 上為 `1`） |
| `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` / `DISCORD_REDIRECT_URI` | Discord 登入 | 三者都要有才會啟用 |
| `OWNER_DISCORD_IDS` | owner 的 Discord 使用者 ID，逗號分隔 | 啟用 Discord 登入時必填 |
| `RMS_SECRET_KEY` | 簽署 session cookie 的金鑰 | 啟用 Discord 登入時必填，沒有會拒絕啟動 |

## 權限（啟用 Discord 登入時）

- **owner**：所有功能。
- **member**（綁定名字的成員）：可以看總覽、掉落物、借還；只能編輯持有人是自己名字的掉落物；其他寫入操作會回 403。
- **unbound**（已登入但還沒綁定名字）：只能到綁定頁面。

沒有設定 Discord 時，所有人都是 owner，請只在內網或設定 `APP_PASSWORD` 後使用。

## 部署

- 映像檔：`Dockerfile`（python 3.13 slim，gunicorn 1 個 worker、4 個 thread；SQLite 只能單一寫入者）。
- fly 設定：`fly.toml`，app 名稱 `rms-loot-nj`，region `nrt`，volume `rms_data` 掛在 `/data`，機器閒置會自動休眠。
- GitHub Actions（`.github/workflows/deploy.yml`）：
  - push 到 `main` 或開 PR 時跑 `pytest`。
  - push 到 `main` 才部署：確認 app 與 volume 存在、設定 secrets、`flyctl deploy --remote-only`。
  - 同一時間只會有一個部署（concurrency group `fly-deploy`）。
- 需要的 GitHub secrets：`FLY_API_TOKEN`、`DISCORD_CLIENT_ID`、`DISCORD_CLIENT_SECRET`、`RMS_SECRET_KEY`。選填：`FLY_ORG`（variable）。

## 偵測

`.github/workflows/uptime.yml` 每 12 小時（UTC 00:17、12:17）檢查 `/healthz`，失敗時這次執行會變紅，GitHub 會通知 repo 的 watcher。第一次請求可能遇到機器休眠，腳本會重試 4 次。

## 備份

`/backup` 下載完整的 SQLite 檔（用 SQLite 的 backup API，寫入中也是一致的快照）。**借還的圖片不在這個檔案裡**，目前沒有圖片的備份方式。

## 測試

```bash
.venv/bin/python -m pytest -q
```

## 文件

設計決定記在 `docs/adr/`，索引見 `docs/adr/README.md`。

## 注意

- 名字不分大小寫：ERIC / Eric / eric 會被視為同一人，沿用第一次輸入的寫法。
- 儲存空間到 80% 會跳警告視窗，到 95% 會跳嚴重警告，並拒絕上傳圖片（見 ADR 0001）。

# ADR 0003：使用單一 SQLite 檔作為資料庫，並且只跑一個 worker

- 狀態：已接受
- 日期：2026-10（專案初期）

## 背景

資料量很小（一個人與少數同行者的分贓紀錄，約數百筆），同時使用的人只有幾個。部署在 fly.io 上，機器會自動休眠。

## 決定

1. 資料全部放在一個 SQLite 檔，位置由 `RMS_DB` 指定；fly 上是 `/data/rms_loot.db`，放在 volume 上。
2. gunicorn 只開 **1 個 worker**，用多個 thread（`-w 1 --threads 4`）處理同時的請求。SQLite 只能有一個寫入者，多個 worker 會互相搶寫入鎖。
3. 備份用 SQLite 的 backup API 產生一致的快照（`/backup`），不直接複製檔案。

## 考慮過的替代方案

- **PostgreSQL（fly 的 managed 服務）**：可以多 worker，但要多管一個服務與費用，對這個規模不划算。
- **多個 worker 加 SQLite WAL 模式**：可以讀取並行，但寫入仍然只有一個，而且 gunicorn 多 worker 時還要處理 schema 遷移的競爭。

## 後果

- 正面：部署與備份都很簡單，只有一個檔案。
- 負面：寫入量變大時會成為瓶頸。若將來需要多人同時大量寫入，要重新考慮。
- 注意：schema 遷移寫在 `create_app` 裡（例如補上 `paid_date` 欄位），每次啟動都會執行，所以新增欄位時要保持相容。

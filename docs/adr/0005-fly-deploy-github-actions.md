# ADR 0005：部署到 fly.io，由 GitHub Actions 在 main 上自動部署

- 狀態：已接受
- 日期：2026-10（部署流程建立時）

## 背景

使用者想要 push 到 `main` 就自動上線，也不想一直開著機器（閒置要能休眠以省錢）。

## 決定

1. 部署平台是 fly.io，app `rms-loot-nj`，region `nrt`，1 個 shared-cpu-1x 機器（256 MB），`auto_stop_machines = "stop"`、`min_machines_running = 0`。
2. `.github/workflows/deploy.yml`：
   - `test` job：push 到 `main` 與所有 PR 都跑 `pytest`。
   - `deploy` job：`needs: test`，只在 push 到 `main` 時跑（PR 不部署）。
   - 步驟：確認 app 與 volume 存在（沒有就建立）→ 把 secrets 設到 fly（`--stage`）→ `flyctl deploy --remote-only`。
   - `concurrency: fly-deploy`，`cancel-in-progress: false`：同時只會有一個部署，後來的排隊。
   - 可以用 `workflow_dispatch` 手動重跑。
3. 資料放在 volume `rms_data`（掛在 `/data`，1 GB）。部署不會動 volume 的內容。
4. `RMS_API_TOKEN` 之類的選用 secret 只在 GitHub 上有設定時才會寫入 fly，避免把手動設定的值清掉。

## 踩過的坑

- **Dockerfile 只複製 `app.py`**：新增模組（`images.py`、`storage.py`、`loans.py`）後，映像檔裡缺檔案，程式啟動就 import 失敗，fly 回 502。之後改成 `COPY *.py ./`（PR #31）。**新增 Python 模組時，要確認映像檔會包含它。**
- **volume 所在主機不可達**：部署時 fly 回報機器需要人工介入，無法自動替換。之後主機恢復，重新觸發 `workflow_dispatch` 就成功了。這時 volume 的資料沒有受影響。
- 合併 PR 之前，要確認 `test` 通過；部署失敗時，線上會停留在舊版或無法啟動。

## 考慮過的替代方案

- **手動執行 `flyctl deploy`**：每次都要人工操作，容易忘記。
- **Fly 的 GitHub 整合**：可以用，但 secrets 與測試門檻不好控制。

## 後果

- 正面：合併到 `main` 就會上線，測試失敗時不會部署。
- 負面：fly 只檢查機器的 `/healthz`（`fly.toml`），deploy 流程本身沒有端到端的檢查。`flyctl deploy` 成功不代表網站的頁面都正常。這個缺口由每 12 小時的偵測補上（ADR 0007）。
- 相關文件：README 的「部署」一節列出需要的 secrets。

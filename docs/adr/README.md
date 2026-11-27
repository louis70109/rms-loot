# 架構決策紀錄（ADR）

每一份 ADR 記錄一個決定、它的背景、考慮過的替代方案，以及後果。新增時使用下一個編號，檔名格式是 `NNNN-簡短英文標題.md`。

| 編號 | 標題 | 狀態 |
|---|---|---|
| [0001](0001-storage-space-warning.md) | 儲存空間快滿時在網頁上跳出警告 | 已接受 |
| [0002](0002-maple-royals-todo-guide-links.md) | Maple Royals TODO 如何連到攻略庫 | 已接受 |
| [0003](0003-sqlite-single-file.md) | 使用單一 SQLite 檔，並且只跑一個 worker | 已接受 |
| [0004](0004-discord-login-roles.md) | 用 Discord 登入決定權限（owner / member / unbound） | 已接受 |
| [0005](0005-fly-deploy-github-actions.md) | 部署到 fly.io，由 GitHub Actions 在 main 上自動部署 | 已接受 |
| [0006](0006-loan-images-on-volume.md) | 借還圖片壓縮後存在 volume，資料庫只存檔名 | 已接受 |
| [0007](0007-uptime-check-github-actions.md) | 用 GitHub Actions 排程做網站偵測 | 已接受 |
| [0008](0008-gpui-desktop-and-api-removed.md) | 移除 GPUI 桌面版與唯讀 API | 已接受（已移除） |
| [0009](0009-todo-in-site.md) | TODO 放進網站，資料只存在瀏覽器 | 已被 0010 取代 |
| [0010](0010-todo-in-database.md) | TODO 存進資料庫，依 Discord 帳號分開 | 已接受 |
| [0011](0011-loan-archive-cold-data.md) | 借還紀錄封存為冷資料，預設不顯示 | 已接受 |
| [0012](0012-cat-voice.md) | 全站文字改用貓的口吻 | 已接受 |

## 約定

- 文件變更（ADR、README）可以直接 commit 到 `main`，不需要開 PR。
- 程式變更仍然走分支與 PR，CI 通過後才合併。
- 其他細節（實作過程、測試結果）請看 commit 紀錄，ADR 只寫決定與原因。

# ADR 0008：移除 GPUI 桌面版與唯讀 API

- 狀態：已接受（已移除）
- 日期：2026-11-16

## 背景

為了在電腦上快速查看分貝與分贓，做過一個 GPUI（Zed 的 UI 框架）寫的桌面版（`desktop/`）。它可以讀本機的 SQLite 檔，也可以透過一組唯讀 API（`/api/*`，Bearer token）讀取線上網站的資料。

## 決定

使用者決定不再需要桌面版，API 也一併移除。

- 關閉 PR #27（未合併）。
- 本機的 `feat/gpui-desktop` 分支已刪除，`desktop/target/`（約 7.2 GB 的編譯快取）也已刪除。
- 遠端的 `feat/gpui-desktop` 分支**沒有刪除成功**：這個工作環境的 GitHub 代理拒絕刪除分支（403）。需要時請在 GitHub 的 Branches 頁面手動刪除。
- 最後的 commit 是 `5d70b43`（API 與桌面版都在這裡），若需要還原可以用它。

## 當時做過的決定（之後如果要重做，可以參考）

- GPUI 0.2 的可點擊元素需要先 `.id(...)` 才能用 `on_click` 與 `overflow_y_scroll`。
- 桌面版的資料來源是 `Source` 抽象：預設讀本機 SQLite，設定 `RMS_API_URL` 與 `RMS_API_TOKEN` 時改讀 API。token 只從環境變數讀，不接受命令列參數，避免留在 shell 歷史裡。
- Windows 上沒有實際編譯測試過。

## 後果

- 正面：少一個要維護的程式與依賴（GPUI、rusqlite、ureq），網站的 API 攻擊面也不存在了。
- 負面：沒有離線的桌面工具。如果之後需要，要重新評估。
- 注意：目前線上網站沒有任何 `/api/*` 路由。

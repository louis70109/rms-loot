# ADR 0010：TODO 存進資料庫，依 Discord 帳號分開

- 狀態：已接受（取代 ADR 0009 的「只存在瀏覽器」）
- 日期：2026-11-24

## 背景

ADR 0009 把 TODO 放進網站，資料只存在瀏覽器的 localStorage。使用者在網頁上輸入的清單，在 PWA（加到主畫面的 App）或其他瀏覽器裡看不到，因為那是另一個儲存空間。使用者要的是「同一個帳號，在哪裡打開都一樣」。

## 決定

1. **資料存進 SQLite**，表 `todos`（`todo.py` 的 `TODO_SCHEMA`），每筆有 `owner`，owner 是登入者的 Discord ID。沒有啟用 Discord 登入時，owner 固定為 `local`，所有人共用。
2. **用 session 的 `discord_id` 決定身分**，不接受使用者從請求裡自己指定 owner。所有查詢與修改都加上 `owner = ?`，別人的項目回 404。
3. **API 只給登入者用**：`GET/POST /api/todos`、`PATCH/DELETE /api/todos/<id>`、`POST /api/todos/clear-done`、`POST /api/todos/import`。owner 與 member 可以使用；未登入或未綁定回 401（不導向登入頁，因為呼叫的是 API）。
4. **寫入一律要求 JSON**（`Content-Type: application/json`），跨站的一般表單送不出 JSON，等於擋掉 CSRF。搭配 `SameSite=Lax` 的 session cookie，跨站請求不會帶 cookie。
5. **輸入驗證**：分組只能是 `level` 或 `quest`；文字 1 到 120 字；備註最多 2000 字；連結只接受 http / https；slug 只接受英數與 `._~-`。
6. **舊資料搬移**：第一次開頁時，如果資料庫是空的、而瀏覽器裡還有舊版的 localStorage 清單，會呼叫 `/api/todos/import` 搬進資料庫，成功後才刪除本機的舊資料。`/import` 只在使用者還沒有任何項目時才執行，不會重複匯入。
7. **前端的寫入**：先更新畫面，再送出；失敗時還原並顯示原因。備註在離開欄位時才儲存，不是每打一個字就送一次。

## 考慮過的替代方案

- **繼續用 localStorage 並加上同步**：要解決衝突，複雜度高，而且 PWA 與網頁的儲存仍然是分開的。
- **把 TODO 放在 Discord 或其他服務**：多一個外部依賴，使用者的資料不在自己的資料庫裡。
- **用 Discord ID 以外的使用者名稱（例如 `session["name"]`）**：名字可以改、也可能重複；Discord ID 是穩定的，所以用 ID。

## 後果

- 正面：所有裝置與瀏覽器看到的都是同一份清單；資料在自己的 SQLite 裡，可以備份。
- 正面：權限集中在 `owner = ?` 的查詢，測試涵蓋了跨使用者的存取。
- 負面：TODO 現在需要網路，離線時無法新增或勾選，只有已經載入的畫面能看。
- 負面：`/backup` 會包含 `todos` 表，備份內容變多，但仍然是同一個檔案。
- 注意：沒有啟用 Discord 登入時所有人共用同一份清單。正式站一定要啟用 Discord（見 ADR 0004）。
- 注意：攻略目錄的讀取順序與 ADR 0009 相同（即時 → 快取 → 內建快照），這部分沒有改。

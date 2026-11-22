# ADR 0004：用 Discord 登入決定權限（owner / member / unbound）

- 狀態：已接受
- 日期：2026-10（Discord 登入功能上線時）

## 背景

網站有分贓金額與付款紀錄，需要限制誰能改資料。使用者不想自己管帳號密碼，同行的人已經都在 Discord 上。

## 決定

1. 使用 Discord OAuth2（`identify` scope）登入，只取得使用者 ID，不存其他個人資料。
2. 三種角色，存在 Flask session 裡：
   - **owner**：`OWNER_DISCORD_IDS` 裡的 ID，所有功能。
   - **member**：登入後綁定到一個名字（`bindings` 表，名字唯一），可以看總覽、掉落物、借還；只能編輯持有人是自己名字的掉落物。
   - **unbound**：已登入但還沒綁定，只能進綁定頁面。
3. 權限在 `password_gate`（`before_request`）統一檢查，不在各個路由裡分散判斷。其他寫入操作對 member 回 403。
4. 啟用條件：`DISCORD_CLIENT_ID`、`DISCORD_CLIENT_SECRET`、`DISCORD_REDIRECT_URI`、`OWNER_DISCORD_IDS` 都有才啟用；啟用時 `RMS_SECRET_KEY` 必須設定，沒有就拒絕啟動。原因是沒有固定金鑰時，每次機器重啟都會換金鑰，所有登入會失效。
5. Session cookie 在啟用 Discord 時設為 `Secure` 與 `SameSite=Lax`。

## 踩過的坑（之後要記得）

- Discord 的 token 交換請求如果沒有 `User-Agent`，會被 Cloudflare 擋成 403，所以程式送出明確的 User-Agent。
- `OWNER_DISCORD_IDS` 要填的是**使用者 ID**，不是應用程式的 Client ID。兩者很容易弄混。
- Redirect URI 要和 Discord 開發者後台的設定完全一致。

## 考慮過的替代方案

- **帳號密碼**：要管理密碼重設與註冊，使用者不想要。
- **只用 APP_PASSWORD（共用密碼）**：所有人都是同一個權限，無法區分 owner 與成員。保留作為沒有 Discord 時的簡單方案。
- **外部的身分服務（Auth0 等）**：多一個服務與費用，對這個規模不需要。

## 後果

- 正面：不用管密碼，成員用既有的 Discord 帳號登入，權限邏輯集中在一處。
- 負面：沒有 Discord 帳號的人無法使用。沒有設定 Discord 也沒有設定 `APP_PASSWORD` 時，所有頁面（包括 `/backup` 的資料庫下載）都是公開的，所以正式站一定要啟用 Discord 登入。
- 相關測試：`tests/test_app.py` 中 Discord 角色與權限的案例。

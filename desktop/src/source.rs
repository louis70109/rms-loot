//! 資料來源：本機 SQLite 檔（預設），或線上網站的唯讀 API（設定 RMS_API_URL 與 RMS_API_TOKEN 時）。
//!
//! - 本機：`rms-loot-desktop [資料庫路徑]` 或環境變數 `RMS_DB`。
//! - 線上：`RMS_API_URL=https://rms-loot-nj.fly.dev` + `RMS_API_TOKEN=...`。
//!   token 只從環境變數讀，不接受命令列參數，避免留在 shell 歷史紀錄裡。

use crate::db::{self, Drop, Run};
use serde::de::DeserializeOwned;
use serde::Deserialize;
use std::path::PathBuf;
use std::time::Duration;

pub enum Source {
    Local(PathBuf),
    Api { base: String, token: String },
}

/// 一次讀取的完整資料（總覽需要的全部內容）。
pub struct Snapshot {
    pub runs: Vec<Run>,
    pub drops: Vec<Drop>,
    pub fee: f64,
    pub share: f64,
}

#[derive(Deserialize)]
struct ApiRun {
    id: i64,
    run_date: String,
    partner: String,
    is_guest: bool,
    a_pick: String,
    b_pick: String,
    c_pick: String,
    tape_pick: String,
    note: String,
}

#[derive(Deserialize)]
struct ApiDrop {
    id: i64,
    item: String,
    member: String,
    market_price: Option<f64>,
    sale_price: Option<f64>,
    sold_date: String,
    paid: bool,
    paid_date: String,
}

#[derive(Deserialize)]
struct ApiSettings {
    fee_percent: f64,
    share_percent: f64,
}

impl Source {
    /// 依環境變數與命令列參數決定來源。線上設定齊全時優先使用 API。
    pub fn from_env(arg_path: Option<String>) -> Source {
        let url = std::env::var("RMS_API_URL").ok().filter(|s| !s.trim().is_empty());
        let token = std::env::var("RMS_API_TOKEN").ok().filter(|s| !s.trim().is_empty());
        if let (Some(base), Some(token)) = (url, token) {
            return Source::Api {
                base: base.trim().trim_end_matches('/').to_string(),
                token: token.trim().to_string(),
            };
        }
        let path = arg_path
            .or_else(|| std::env::var("RMS_DB").ok())
            .unwrap_or_else(|| "rms_loot.db".to_string());
        Source::Local(PathBuf::from(path))
    }

    /// 顯示在錯誤訊息裡的來源說明。
    pub fn describe(&self) -> String {
        match self {
            Source::Local(path) => path.display().to_string(),
            Source::Api { base, .. } => base.clone(),
        }
    }

    pub fn load(&self) -> Result<Snapshot, String> {
        match self {
            Source::Local(path) => {
                let conn = db::open(path).map_err(|e| e.to_string())?;
                Ok(Snapshot {
                    runs: db::runs(&conn).map_err(|e| e.to_string())?,
                    drops: db::drops(&conn).map_err(|e| e.to_string())?,
                    fee: db::percent(&conn, "payout_fee_percent", 3.0),
                    share: db::percent(&conn, "payout_share_percent", 50.0),
                })
            }
            Source::Api { base, token } => {
                let settings: ApiSettings = get_json(base, token, "/api/settings")?;
                let runs: Vec<ApiRun> = get_json(base, token, "/api/runs")?;
                let drops: Vec<ApiDrop> = get_json(base, token, "/api/drops")?;
                Ok(Snapshot {
                    runs: runs
                        .into_iter()
                        .map(|r| Run {
                            id: r.id,
                            run_date: r.run_date,
                            partner: r.partner,
                            is_guest: r.is_guest,
                            picks: [r.a_pick, r.b_pick, r.c_pick, r.tape_pick],
                            note: r.note,
                        })
                        .collect(),
                    drops: drops
                        .into_iter()
                        .map(|d| Drop {
                            id: d.id,
                            item: d.item,
                            member: d.member,
                            market_price: d.market_price,
                            sale_price: d.sale_price,
                            sold_date: d.sold_date,
                            paid: d.paid,
                            paid_date: d.paid_date,
                        })
                        .collect(),
                    fee: settings.fee_percent,
                    share: settings.share_percent,
                })
            }
        }
    }

    /// 切換已付狀態（與網站相同：只翻轉 paid，不動付款日）。
    pub fn toggle_paid(&self, id: i64) -> Result<(), String> {
        match self {
            Source::Local(path) => {
                let conn = db::open(path).map_err(|e| e.to_string())?;
                db::toggle_paid(&conn, id).map(|_| ()).map_err(|e| e.to_string())
            }
            Source::Api { base, token } => {
                let url = format!("{base}/api/drops/{id}/toggle-paid");
                let resp = agent()
                    .post(&url)
                    .set("Authorization", &format!("Bearer {token}"))
                    .call()
                    .map_err(http_error)?;
                resp.into_json::<serde_json::Value>()
                    .map(|_| ())
                    .map_err(|e| e.to_string())
            }
        }
    }
}

fn agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(10))
        .user_agent("rms-loot-desktop")
        .build()
}

fn get_json<T: DeserializeOwned>(base: &str, token: &str, path: &str) -> Result<T, String> {
    agent()
        .get(&format!("{base}{path}"))
        .set("Authorization", &format!("Bearer {token}"))
        .call()
        .map_err(http_error)?
        .into_json::<T>()
        .map_err(|e| format!("回應格式不符：{e}"))
}

fn http_error(e: ureq::Error) -> String {
    match e {
        ureq::Error::Status(401, _) => "API token 不正確（401）".to_string(),
        ureq::Error::Status(404, _) => "伺服器未啟用 API（404），請確認 RMS_API_TOKEN".to_string(),
        ureq::Error::Status(code, _) => format!("伺服器回應錯誤（{code}）"),
        other => format!("連線失敗：{other}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 與 app.py 的 /api/drops 回傳格式相同。
    #[test]
    fn parses_api_drop_json() {
        let json = r#"[{"id":1,"item":"Eye for DEX 60%","member":"KIA","market_price":null,
            "sale_price":null,"sold_date":"","paid":false,"paid_date":""}]"#;
        let drops: Vec<ApiDrop> = serde_json::from_str(json).unwrap();
        assert_eq!(drops[0].member, "KIA");
        assert!(drops[0].sale_price.is_none());
        assert!(!drops[0].paid);
    }

    #[test]
    fn parses_api_run_and_settings_json() {
        let run = r#"{"id":2,"run_date":"","partner":"ERIC","is_guest":true,"a_pick":"ERIC",
            "b_pick":"NJ","c_pick":"NJ","tape_pick":"","note":""}"#;
        let r: ApiRun = serde_json::from_str(run).unwrap();
        assert!(r.is_guest);
        let s: ApiSettings = serde_json::from_str(r#"{"fee_percent":3.0,"share_percent":50.0}"#).unwrap();
        assert_eq!(s.share_percent, 50.0);
    }

    #[test]
    fn env_without_token_falls_back_to_local_file() {
        // 只有 URL、沒有 token 時不應該走 API
        std::env::set_var("RMS_API_URL", "https://example.test");
        std::env::remove_var("RMS_API_TOKEN");
        let src = Source::from_env(Some("x.db".into()));
        std::env::remove_var("RMS_API_URL");
        assert!(matches!(src, Source::Local(_)));
    }

    /// 需要一個跑著的網站：RMS_API_URL=http://127.0.0.1:5055 RMS_API_TOKEN=... cargo test -- --ignored
    #[test]
    #[ignore]
    fn live_api_loads_sample_counts() {
        let src = Source::from_env(None);
        let snap = src.load().expect("API should load");
        assert_eq!(snap.runs.len(), 11);
        assert_eq!(snap.drops.len(), 19);
        assert_eq!(snap.share, 50.0);
    }
}

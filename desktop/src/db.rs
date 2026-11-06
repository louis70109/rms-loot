//! 讀寫與網站相同的 SQLite 檔（欄位與 app.py 的 SCHEMA 一致）。

use rusqlite::{params, Connection, OpenFlags};
use std::path::Path;

#[derive(Clone)]
pub struct Run {
    pub id: i64,
    pub run_date: String,
    pub partner: String,
    pub is_guest: bool,
    /// A捲、B捲、C捲、tape 的得主（空字串 = 沒掉）
    pub picks: [String; 4],
    pub note: String,
}

#[derive(Clone)]
pub struct Drop {
    pub id: i64,
    pub item: String,
    pub member: String,
    pub market_price: Option<f64>,
    pub sale_price: Option<f64>,
    pub sold_date: String,
    pub paid: bool,
    pub paid_date: String,
}

/// 只開既有的檔案，不會因為路徑打錯而悄悄建立空資料庫。
pub fn open(path: &Path) -> rusqlite::Result<Connection> {
    Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_WRITE)
}

pub fn runs(conn: &Connection) -> rusqlite::Result<Vec<Run>> {
    let mut stmt = conn.prepare(
        "SELECT id, run_date, partner, is_guest, a_pick, b_pick, c_pick, tape_pick, note \
         FROM runs ORDER BY id",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok(Run {
            id: r.get(0)?,
            run_date: r.get(1)?,
            partner: r.get(2)?,
            is_guest: r.get::<_, i64>(3)? != 0,
            picks: [r.get(4)?, r.get(5)?, r.get(6)?, r.get(7)?],
            note: r.get(8)?,
        })
    })?;
    rows.collect()
}

pub fn drops(conn: &Connection) -> rusqlite::Result<Vec<Drop>> {
    let mut stmt = conn.prepare(
        "SELECT id, item, member, market_price, sale_price, sold_date, paid, paid_date \
         FROM drops ORDER BY id",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok(Drop {
            id: r.get(0)?,
            item: r.get(1)?,
            member: r.get(2)?,
            market_price: r.get(3)?,
            sale_price: r.get(4)?,
            sold_date: r.get(5)?,
            paid: r.get::<_, i64>(6)? != 0,
            paid_date: r.get(7)?,
        })
    })?;
    rows.collect()
}

/// 讀取設定值；設定表或該欄不存在時用預設值（與網站相同）。
pub fn percent(conn: &Connection, key: &str, default: f64) -> f64 {
    conn.query_row(
        "SELECT value FROM settings WHERE key = ?1",
        params![key],
        |r| r.get::<_, String>(0),
    )
    .ok()
    .and_then(|v| v.parse::<f64>().ok())
    .unwrap_or(default)
}

/// 與網站「一鍵切換已付」相同：只翻轉 paid，不動付款日。
pub fn toggle_paid(conn: &Connection, id: i64) -> rusqlite::Result<usize> {
    conn.execute("UPDATE drops SET paid = 1 - paid WHERE id = ?1", params![id])
}

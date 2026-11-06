//! 計算邏輯，對應 app.py 的 build_payouts 與 build_people，結果要跟網站一致。

use crate::db::{Drop, Run};
use std::collections::BTreeMap;

const ME: &str = "NJ";

pub struct Sold {
    pub item: String,
    pub sale: f64,
    pub sold_date: String,
}

pub struct Holder {
    pub key: String,
    pub name: String,
    pub unpaid_count: usize,
    pub unpaid_sum: f64,
    pub payout: f64,
    pub paid_count: usize,
    pub sold: Vec<Sold>,
    pub incomplete: Vec<String>,
    pub formula: String,
}

pub struct Person {
    pub name: String,
    pub runs: usize,
    pub guest_runs: usize,
    pub picks: [usize; 4],
    pub total: usize,
    pub next_turn: bool,
}

/// 應付 = 未付賣出價合計 ×（1 − 手續費%）× 分配%。只計入未付且有賣出價的項目。
pub fn holders(drops: &[Drop], fee: f64, share: f64) -> Vec<Holder> {
    let factor = (100.0 - fee) / 100.0 * share / 100.0;
    let mut map: BTreeMap<String, Holder> = BTreeMap::new();
    for d in drops {
        let key = d.member.to_lowercase();
        let h = map.entry(key.clone()).or_insert_with(|| Holder {
            key,
            name: d.member.clone(),
            unpaid_count: 0,
            unpaid_sum: 0.0,
            payout: 0.0,
            paid_count: 0,
            sold: Vec::new(),
            incomplete: Vec::new(),
            formula: String::new(),
        });
        if d.paid {
            h.paid_count += 1;
        } else if let Some(sale) = d.sale_price {
            h.unpaid_count += 1;
            h.unpaid_sum += sale;
            h.sold.push(Sold {
                item: d.item.clone(),
                sale,
                sold_date: d.sold_date.clone(),
            });
        } else {
            h.incomplete.push(d.item.clone());
        }
    }
    let mut out: Vec<Holder> = map.into_values().collect();
    for h in &mut out {
        h.unpaid_sum = round2(h.unpaid_sum);
        h.payout = round2(h.unpaid_sum * factor);
        h.formula = format!(
            "{} × {}% × {}% = {:.2}",
            fmt_g(h.unpaid_sum),
            fmt_g(100.0 - fee),
            fmt_g(share),
            h.payout
        );
    }
    out
}

/// 人員統計：同行次數、各捲拿到幾次、陪打與「下次換他撿」。NJ 排第一。
pub fn people(runs: &[Run]) -> Vec<Person> {
    let mut map: BTreeMap<String, Person> = BTreeMap::new();
    let mut get = |name: &str| -> String {
        let key = name.to_lowercase();
        map.entry(key.clone()).or_insert_with(|| Person {
            name: name.to_string(),
            runs: 0,
            guest_runs: 0,
            picks: [0; 4],
            total: 0,
            next_turn: false,
        });
        key
    };
    get(ME);
    for r in runs {
        if !r.partner.is_empty() {
            let key = get(&r.partner);
            let p = map.get_mut(&key).expect("just inserted");
            p.runs += 1;
            if r.is_guest {
                p.guest_runs += 1;
            }
        }
        for (i, pick) in r.picks.iter().enumerate() {
            if !pick.is_empty() {
                let key = get(pick);
                let p = map.get_mut(&key).expect("just inserted");
                p.picks[i] += 1;
                p.total += 1;
            }
        }
    }
    let mut out: Vec<Person> = map.into_values().collect();
    for p in &mut out {
        p.next_turn = p.name != ME && p.guest_runs > 0 && p.runs == 1;
    }
    out.sort_by(|a, b| {
        (a.name != ME, a.name.to_lowercase()).cmp(&(b.name != ME, b.name.to_lowercase()))
    });
    out
}

fn round2(x: f64) -> f64 {
    format!("{x:.2}").parse().unwrap_or(x)
}

/// 與 Python 的 `{:g}` 類似：整數不補 .00，小數去掉多餘的 0。
fn fmt_g(x: f64) -> String {
    if x.fract() == 0.0 {
        format!("{}", x as i64)
    } else {
        format!("{x:.2}").trim_end_matches('0').trim_end_matches('.').to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn drop(id: i64, item: &str, member: &str, sale: Option<f64>, paid: bool) -> Drop {
        Drop {
            id,
            item: item.into(),
            member: member.into(),
            market_price: None,
            sale_price: sale,
            sold_date: String::new(),
            paid,
            paid_date: String::new(),
        }
    }

    #[test]
    fn sample_kia_matches_web_formula() {
        // 範例資料：KIA 未付且有賣出價 = 224，手續費 3%、分配 50% → 108.64
        let drops = vec![
            drop(1, "Eye for DEX", "KIA", Some(70.0), false),
            drop(2, "shield MA", "KIA", Some(35.0), false),
            drop(3, "face for DEX", "kia", Some(19.0), false),
            drop(4, "face for INT", "KIA", Some(65.0), false),
            drop(5, "Eye for LKUK", "KIA", Some(35.0), false),
            drop(6, "EP 11211", "KIA", None, false),
            drop(7, "done", "KIA", Some(10.0), true),
        ];
        let h = holders(&drops, 3.0, 50.0);
        assert_eq!(h.len(), 1);
        assert_eq!(h[0].unpaid_count, 5);
        assert_eq!(h[0].unpaid_sum, 224.0);
        assert_eq!(h[0].payout, 108.64);
        assert_eq!(h[0].formula, "224 × 97% × 50% = 108.64");
        assert_eq!(h[0].incomplete, vec!["EP 11211".to_string()]);
        assert_eq!(h[0].paid_count, 1);
    }

    #[test]
    fn fmt_g_drops_trailing_zeros() {
        assert_eq!(fmt_g(154.0), "154");
        assert_eq!(fmt_g(154.5), "154.5");
        assert_eq!(fmt_g(97.0), "97");
    }
}

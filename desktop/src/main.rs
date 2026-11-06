//! RMS 分贓表桌面版（GPUI）。讀寫與網站相同的 SQLite 檔，畫面採極簡工業風，與網站一致。
//!
//! 用法：`rms-loot-desktop [資料庫路徑]`，或設定環境變數 `RMS_DB`。預設 `rms_loot.db`。

mod calc;
mod db;
mod source;

use source::Source;

use calc::{Holder, Person};
use db::{Drop, Run};
use gpui::{
    div, prelude::*, px, rgb, size, App, Application, Bounds, ClickEvent, Context, Div,
    FontWeight, SharedString, Stateful, Window, WindowBounds, WindowOptions,
};
use std::collections::HashSet;

const BG: u32 = 0xe4e4e1;
const PANEL: u32 = 0xf5f5f2;
const FG: u32 = 0x111111;
const MUTED: u32 = 0x6a6a64;
const LINE: u32 = 0x111111;
const SOFT: u32 = 0xc9c9c4;
const ACCENT: u32 = 0xff5a00;
const OK: u32 = 0x1d6f36;
const WARN: u32 = 0x9a5b00;
const DANGER: u32 = 0xb3261e;

#[derive(Clone, Copy, PartialEq)]
enum Tab {
    Overview,
    Runs,
    Drops,
}

struct Desktop {
    source: Source,
    tab: Tab,
    runs: Vec<Run>,
    drops: Vec<Drop>,
    fee: f64,
    share: f64,
    expanded: HashSet<String>,
    notice: Option<(String, bool)>,
}

impl Desktop {
    fn new(source: Source) -> Self {
        let mut app = Desktop {
            source,
            tab: Tab::Overview,
            runs: Vec::new(),
            drops: Vec::new(),
            fee: 3.0,
            share: 50.0,
            expanded: HashSet::new(),
            notice: None,
        };
        app.reload();
        app
    }

    fn reload(&mut self) {
        match self.source.load() {
            Ok(snap) => {
                self.runs = snap.runs;
                self.drops = snap.drops;
                self.fee = snap.fee;
                self.share = snap.share;
            }
            Err(e) => {
                self.notice = Some((format!("無法讀取資料（{}）：{e}", self.source.describe()), true))
            }
        }
    }

    fn toggle_paid(&mut self, id: i64) {
        match self.source.toggle_paid(id) {
            Ok(()) => {
                self.reload();
                self.notice = Some(("付款狀態已更新".into(), false));
            }
            Err(e) => self.notice = Some((format!("更新失敗：{e}"), true)),
        }
    }

    fn toggle_expanded(&mut self, key: &str) {
        if !self.expanded.remove(key) {
            self.expanded.insert(key.to_string());
        }
    }

    // ---- 版面元件 ------------------------------------------------------

    fn topbar(&self, cx: &mut Context<Self>) -> Div {
        div()
            .flex()
            .items_center()
            .bg(rgb(PANEL))
            .border_b_2()
            .border_color(rgb(LINE))
            .child(
                div()
                    .px_4()
                    .py_3()
                    .border_r_2()
                    .border_color(rgb(LINE))
                    .font_weight(FontWeight::BOLD)
                    .child("RMS 分贓表"),
            )
            .child(self.tab_button("總覽", Tab::Overview, cx))
            .child(self.tab_button("分貝紀錄", Tab::Runs, cx))
            .child(self.tab_button("掉落物", Tab::Drops, cx))
            .child(div().flex_1())
            .child(
                div()
                    .id("reload")
                    .px_4()
                    .py_3()
                    .border_l_1()
                    .border_color(rgb(LINE))
                    .text_color(rgb(MUTED))
                    .hover(|s| s.bg(rgb(FG)).text_color(rgb(BG)))
                    .child("重新讀取")
                    .on_click(cx.listener(|this, _: &ClickEvent, _, cx| {
                        this.reload();
                        cx.notify();
                    })),
            )
    }

    fn tab_button(&self, label: &'static str, tab: Tab, cx: &mut Context<Self>) -> Stateful<Div> {
        let active = self.tab == tab;
        let base = div()
            .px_4()
            .py_3()
            .border_r_1()
            .border_color(rgb(LINE))
            .font_weight(FontWeight::SEMIBOLD);
        let styled = if active {
            base.bg(rgb(FG)).text_color(rgb(BG))
        } else {
            base.hover(|s| s.bg(rgb(FG)).text_color(rgb(BG)))
        };
        styled.id(label).child(label).on_click(cx.listener(move |this, _: &ClickEvent, _, cx| {
            this.tab = tab;
            cx.notify();
        }))
    }

    fn section_title(&self, text: &'static str) -> Div {
        div()
            .mb_2()
            .text_xs()
            .font_weight(FontWeight::BOLD)
            .text_color(rgb(MUTED))
            .child(text)
    }

    fn header_row(&self, cols: &[(&'static str, Option<f32>)]) -> Div {
        let mut row = div()
            .flex()
            .items_center()
            .px_3()
            .py_2()
            .border_b_1()
            .border_color(rgb(LINE))
            .bg(rgb(BG))
            .text_xs()
            .text_color(rgb(MUTED))
            .font_weight(FontWeight::BOLD);
        for (label, width) in cols {
            row = row.child(cell(*width, label));
        }
        row
    }

    // ---- 各頁 ----------------------------------------------------------

    fn overview(&self, cx: &mut Context<Self>) -> Div {
        let holders = calc::holders(&self.drops, self.fee, self.share);
        let people = calc::people(&self.runs);
        let total: f64 = holders.iter().map(|h| h.payout).sum();
        let owing = holders.iter().filter(|h| h.payout > 0.0).count();

        let total_card = div()
            .flex()
            .flex_col()
            .gap_2()
            .p_5()
            .mb_6()
            .bg(rgb(FG))
            .text_color(rgb(BG))
            .child(
                div()
                    .text_xs()
                    .font_weight(FontWeight::BOLD)
                    .child("本次應付合計"),
            )
            .child(
                div()
                    .flex()
                    .items_baseline()
                    .gap_3()
                    .child(
                        div()
                            .text_3xl()
                            .font_weight(FontWeight::BOLD)
                            .text_color(rgb(ACCENT))
                            .child(format!("{total:.2}")),
                    )
                    .child(div().text_sm().child("楓幣")),
            )
            .child(
                div()
                    .text_xs()
                    .opacity(0.7)
                    .child(format!("{owing} 位持有人要付")),
            );

        let mut holder_list = div()
            .flex()
            .flex_col()
            .bg(rgb(PANEL))
            .border_1()
            .border_color(rgb(LINE))
            .child(self.header_row(&[
                ("持有人", None),
                ("未付", Some(72.0)),
                ("未付合計", Some(120.0)),
                ("應付", Some(150.0)),
            ]));
        for h in &holders {
            holder_list = holder_list.child(self.holder_row(h, cx));
            if self.expanded.contains(&h.key) {
                holder_list = holder_list.child(holder_detail(h));
            }
        }
        if holders.is_empty() {
            holder_list = holder_list.child(empty_line("還沒有掉落物"));
        }

        let mut people_list = div()
            .flex()
            .flex_col()
            .bg(rgb(PANEL))
            .border_1()
            .border_color(rgb(LINE))
            .child(self.header_row(&[
                ("名字", None),
                ("同行", Some(64.0)),
                ("A捲", Some(56.0)),
                ("B捲", Some(56.0)),
                ("C捲", Some(56.0)),
                ("tape", Some(56.0)),
                ("合計", Some(64.0)),
                ("提醒", Some(150.0)),
            ]));
        for p in &people {
            people_list = people_list.child(people_row(p));
        }

        div()
            .flex()
            .flex_col()
            .child(total_card)
            .child(self.section_title("持有人應付金額（點一下展開明細）"))
            .child(holder_list)
            .child(div().h_6())
            .child(self.section_title("人員統計"))
            .child(people_list)
    }

    fn holder_row(&self, h: &Holder, cx: &mut Context<Self>) -> Stateful<Div> {
        let key = h.key.clone();
        let expanded = self.expanded.contains(&h.key);
        let caret = if expanded { "▾" } else { "▸" };
        let amount_color = if h.payout > 0.0 { ACCENT } else { MUTED };
        div()
            .id(SharedString::from(format!("holder-{}", h.key)))
            .flex()
            .items_center()
            .px_3()
            .py_3()
            .border_b_1()
            .border_color(rgb(SOFT))
            .hover(|s| s.bg(rgb(BG)))
            .child(
                div()
                    .flex_1()
                    .font_weight(FontWeight::BOLD)
                    .child(format!("{} {caret}", h.name)),
            )
            .child(cell(Some(72.0), &h.unpaid_count.to_string()))
            .child(cell(Some(120.0), &format!("{:.2}", h.unpaid_sum)))
            .child(
                div()
                    .w(px(150.0))
                    .font_weight(FontWeight::BOLD)
                    .text_color(rgb(amount_color))
                    .child(format!("{:.2} 楓幣", h.payout)),
            )
            .on_click(cx.listener(move |this, _: &ClickEvent, _, cx| {
                this.toggle_expanded(&key);
                cx.notify();
            }))
    }

    fn runs_page(&self) -> Div {
        let mut list = div()
            .flex()
            .flex_col()
            .bg(rgb(PANEL))
            .border_1()
            .border_color(rgb(LINE))
            .child(self.header_row(&[
                ("#", Some(48.0)),
                ("日期", Some(80.0)),
                ("同行者", Some(110.0)),
                ("陪打", Some(56.0)),
                ("A捲", Some(90.0)),
                ("B捲", Some(90.0)),
                ("C捲", Some(90.0)),
                ("tape", Some(90.0)),
                ("備註", None),
            ]));
        for r in &self.runs {
            list = list.child(run_row(r));
        }
        if self.runs.is_empty() {
            list = list.child(empty_line("還沒有分貝紀錄"));
        }
        div().flex().flex_col().child(self.section_title("分貝紀錄（唯讀）")).child(list)
    }

    fn drops_page(&self, cx: &mut Context<Self>) -> Div {
        let mut list = div()
            .flex()
            .flex_col()
            .bg(rgb(PANEL))
            .border_1()
            .border_color(rgb(LINE))
            .child(self.header_row(&[
                ("#", Some(48.0)),
                ("掉落物", None),
                ("持有人", Some(110.0)),
                ("賣出價", Some(96.0)),
                ("賣出日", Some(96.0)),
                ("付款狀態（點一下切換）", Some(190.0)),
            ]));
        for d in &self.drops {
            list = list.child(self.drop_row(d, cx));
        }
        if self.drops.is_empty() {
            list = list.child(empty_line("還沒有掉落物"));
        }
        div().flex().flex_col().child(self.section_title("掉落物")).child(list)
    }

    fn drop_row(&self, d: &Drop, cx: &mut Context<Self>) -> Div {
        let id = d.id;
        let (label, color) = if d.paid {
            ("✅ 已付", OK)
        } else if d.sale_price.is_none() {
            ("⚠️ 未完成", WARN)
        } else {
            ("⏳ 未付", FG)
        };
        let status = div()
            .id(SharedString::from(format!("paid-{id}")))
            .w(px(190.0))
            .child(
                div()
                    .px_2()
                    .py_1()
                    .border_1()
                    .border_color(rgb(color))
                    .text_color(rgb(color))
                    .font_weight(FontWeight::BOLD)
                    .child(label),
            )
            .on_click(cx.listener(move |this, _: &ClickEvent, _, cx| {
                this.toggle_paid(id);
                cx.notify();
            }));
        let row = div()
            .flex()
            .items_center()
            .px_3()
            .py_2()
            .border_b_1()
            .border_color(rgb(SOFT))
            .hover(|s| s.bg(rgb(BG)))
            .child(cell(Some(48.0), &d.id.to_string()))
            .child(div().flex_1().overflow_hidden().text_ellipsis().child(d.item.clone()))
            .child(cell(Some(110.0), &d.member))
            .child(cell(Some(96.0), &money_or_dash(d.sale_price)))
            .child(cell(Some(96.0), &d.sold_date))
            .child(status);
        if d.paid {
            row.bg(rgb(BG)).text_color(rgb(MUTED))
        } else {
            row
        }
    }
}

// ---- 小元件（不依賴 self） ---------------------------------------------

fn cell(width: Option<f32>, text: &str) -> Div {
    let base = div().overflow_hidden().text_ellipsis();
    match width {
        Some(w) => base.w(px(w)).child(text.to_string()),
        None => base.flex_1().child(text.to_string()),
    }
}

fn money_or_dash(v: Option<f64>) -> String {
    v.map(|x| format!("{x:.0}")).unwrap_or_else(|| "—".into())
}

fn empty_line(text: &str) -> Div {
    div().px_3().py_4().text_color(rgb(MUTED)).child(text.to_string())
}

fn holder_detail(h: &Holder) -> Div {
    let mut body = div()
        .flex()
        .flex_col()
        .gap_1()
        .px_4()
        .py_3()
        .bg(rgb(BG))
        .border_b_2()
        .border_color(rgb(LINE));
    for s in &h.sold {
        body = body.child(
            div()
                .flex()
                .items_center()
                .py_1()
                .child(div().flex_1().child(s.item.clone()))
                .child(cell(Some(96.0), &format!("{:.0}", s.sale)))
                .child(cell(Some(96.0), &s.sold_date)),
        );
    }
    body = body.child(
        div()
            .mt_2()
            .font_weight(FontWeight::BOLD)
            .child(format!("計算式：{}", h.formula)),
    );
    if !h.incomplete.is_empty() {
        body = body.child(
            div()
                .text_xs()
                .text_color(rgb(WARN))
                .child(format!("未計入（缺賣出價）：{}", h.incomplete.join("、"))),
        );
    }
    if h.paid_count > 0 {
        body = body.child(
            div()
                .text_xs()
                .text_color(rgb(MUTED))
                .child(format!("已付 {} 件", h.paid_count)),
        );
    }
    body
}

fn people_row(p: &Person) -> Div {
    let mut reminder = div().w(px(150.0)).flex().gap_2();
    if p.next_turn {
        reminder = reminder.child(
            div()
                .px_1()
                .border_1()
                .border_color(rgb(WARN))
                .text_color(rgb(WARN))
                .text_xs()
                .child("下次換他撿"),
        );
    }
    if p.guest_runs > 0 {
        reminder = reminder.child(
            div()
                .px_1()
                .border_1()
                .border_color(rgb(FG))
                .text_xs()
                .child(format!("陪打 {} 次", p.guest_runs)),
        );
    }
    div()
        .flex()
        .items_center()
        .px_3()
        .py_2()
        .border_b_1()
        .border_color(rgb(SOFT))
        .child(div().flex_1().font_weight(FontWeight::BOLD).child(p.name.clone()))
        .child(cell(Some(64.0), &p.runs.to_string()))
        .child(cell(Some(56.0), &p.picks[0].to_string()))
        .child(cell(Some(56.0), &p.picks[1].to_string()))
        .child(cell(Some(56.0), &p.picks[2].to_string()))
        .child(cell(Some(56.0), &p.picks[3].to_string()))
        .child(cell(Some(64.0), &p.total.to_string()))
        .child(reminder)
}

fn run_row(r: &Run) -> Div {
    let partner = if r.partner.is_empty() { "—".to_string() } else { r.partner.clone() };
    div()
        .flex()
        .items_center()
        .px_3()
        .py_2()
        .border_b_1()
        .border_color(rgb(SOFT))
        .hover(|s| s.bg(rgb(BG)))
        .child(cell(Some(48.0), &r.id.to_string()))
        .child(cell(Some(80.0), &r.run_date))
        .child(cell(Some(110.0), &partner))
        .child(
            div()
                .w(px(56.0))
                .child(if r.is_guest { "陪打" } else { "" }),
        )
        .child(cell(Some(90.0), &r.picks[0]))
        .child(cell(Some(90.0), &r.picks[1]))
        .child(cell(Some(90.0), &r.picks[2]))
        .child(cell(Some(90.0), &r.picks[3]))
        .child(cell(None, &r.note))
}

impl Render for Desktop {
    fn render(&mut self, _window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let content = match self.tab {
            Tab::Overview => self.overview(cx),
            Tab::Runs => self.runs_page(),
            Tab::Drops => self.drops_page(cx),
        };

        let mut root = div()
            .size_full()
            .flex()
            .flex_col()
            .bg(rgb(BG))
            .text_color(rgb(FG))
            .text_sm()
            .child(self.topbar(cx))
            .child(div().flex_1().id("content").overflow_y_scroll().p_6().child(content));

        if let Some((text, is_error)) = &self.notice {
            let color = if *is_error { DANGER } else { FG };
            root = root.child(
                div()
                    .px_4()
                    .py_2()
                    .bg(rgb(color))
                    .text_color(rgb(BG))
                    .font_weight(FontWeight::BOLD)
                    .child(text.clone()),
            );
        }
        root
    }
}

fn main() {
    let source = Source::from_env(std::env::args().nth(1));
    // Source 不是 Clone，視窗只會建立一次，用 Option 把它搬進 closure。
    let mut source = Some(source);

    Application::new().run(move |cx: &mut App| {
        let bounds = Bounds::centered(None, size(px(1120.), px(780.)), cx);
        let source = source.take().expect("window is opened once");
        cx.open_window(
            WindowOptions {
                window_bounds: Some(WindowBounds::Windowed(bounds)),
                ..Default::default()
            },
            move |_, cx| cx.new(|_| Desktop::new(source)),
        )
        .unwrap();
        cx.activate(true);
    });
}

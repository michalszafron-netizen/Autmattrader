//@version=6
strategy(
  title='[IMBUS] STRATEGY v1',
  shorttitle='IMB STRAT',
  overlay=true,
  max_lines_count=500,
  max_labels_count=500,
  max_bars_back=1,
  initial_capital=1000,
  default_qty_type=strategy.percent_of_equity,
  default_qty_value=100,
  pyramiding=0,
  commission_type=strategy.commission.percent,
  commission_value=0.1
)

// ─── Helper functions ───
RoundUp(number, decimals) =>
    factor = math.pow(10, decimals)
    math.ceil(number * factor) / factor

// ─── Inputs ───
strategy_input = input.string(
  title="STRATEGY",
  options=[
    "MANUAL", "UNIVERSAL 15m",
    "===============",
    "---A---", "---B---", "---C---", "---D---", "---E---",
    "---F---", "---G---", "---H---", "---I---", "---J---",
    "---K---", "---L---", "---M---", "---N---", "---O---",
    "---P---", "---Q---", "---R---", "---S---",
    "SOL 5m",
    "---T---", "---U---", "---V---", "---W---", "---X---",
    "---Y---", "---Z---"
  ],
  defval="MANUAL"
)

sensitivity_input = input.float(title='Sensitivity', step=0.1, defval=18)
start_date_input = input.time(defval=timestamp("1 June 2023"), title="Start date")
risk_percent_input = input.float(title="Risk %", step=1, defval=1, group="POSITION")
break_even_target_input = input.string(title="BE target", options=["WITHOUT","1","2","3"], defval="1", group="POSITION")
fixed_stop_input = input.bool(defval=false, title="Fixed stoploss %", group="STOP LOSS")
sl_percent_input = input.float(title="SL %", step=0.1, defval=0.0, group="STOP LOSS")
tp1_percent_input = input.float(title="TP 1 %", step=0.05, defval=1.0, group="TAKE PROFITS", inline="tp1")
tp1_fix_input = input.float(title="Fix %", step=5, defval=40, group="TAKE PROFITS", inline="tp1")
tp2_percent_input = input.float(title="TP 2 %", step=0.05, defval=2.0, group="TAKE PROFITS", inline="tp2")
tp2_fix_input = input.float(title="Fix %", step=5, defval=30, group="TAKE PROFITS", inline="tp2")
tp3_percent_input = input.float(title="TP 3 %", step=0.05, defval=3.0, group="TAKE PROFITS", inline="tp3")
tp3_fix_input = input.float(title="Fix %", step=5, defval=20, group="TAKE PROFITS", inline="tp3")
tp4_percent_input = input.float(title="TP 4 %", step=0.05, defval=4.0, group="TAKE PROFITS", inline="tp4")
tp4_fix_input = input.float(title="Fix %", step=5, defval=10, group="TAKE PROFITS", inline="tp4")
show_tp_sl = input.bool(defval=true, title="Show TP/SL lines", group="VISUALS")
show_labels = input.bool(defval=true, title="Show labels", group="VISUALS")
show_rsi = input.bool(defval=false, title="Show RSI", group="RSI")
rsi_len = input.int(defval=14, title="RSI Length", group="RSI")
rsi_ob = input.int(defval=78, title="Overbought", group="RSI")
rsi_os = input.int(defval=22, title="Oversold", group="RSI")
show_panel = input.bool(defval=true, title="Show info panel", group="PANEL")

// ─── Strategy presets ───
type preset
    float sens
    float risk
    string be
    float tp1p
    float tp1f
    float tp2p
    float tp2f
    float tp3p
    float tp3f
    float tp4p
    float tp4f
    bool fix_sl
    float slp

get_preset(name)=>
    p = preset.new()
    switch name
        "MANUAL" =>
            p.sens := sensitivity_input
            p.risk := risk_percent_input
            p.be := break_even_target_input
            p.tp1p := tp1_percent_input
            p.tp1f := tp1_fix_input
            p.tp2p := tp2_percent_input
            p.tp2f := tp2_fix_input
            p.tp3p := tp3_percent_input
            p.tp3f := tp3_fix_input
            p.tp4p := tp4_percent_input
            p.tp4f := tp4_fix_input
            p.fix_sl := fixed_stop_input
            p.slp := sl_percent_input
        "UNIVERSAL 15m" =>
            p.sens := 20
            p.risk := 1
            p.be := "1"
            p.tp1p := 1
            p.tp1f := 40
            p.tp2p := 2
            p.tp2f := 30
            p.tp3p := 3
            p.tp3f := 20
            p.tp4p := 4
            p.tp4f := 10
        "SOL 5m" =>
            p.sens := 20
            p.risk := 1
            p.be := "1"
            p.tp1p := 1
            p.tp1f := 40
            p.tp2p := 2
            p.tp2f := 30
            p.tp3p := 3
            p.tp3f := 20
            p.tp4p := 4
            p.tp4f := 10
    p

// ─── Apply preset ───
ps = get_preset(strategy_input)
sens = ps.sens * 10
risk_pct = ps.risk
be_target = ps.be

tp1 = ps.tp1p / 100.0
tp1f = ps.tp1f / 100.0
tp2 = ps.tp2p / 100.0
tp2f = ps.tp2f / 100.0
tp3 = ps.tp3p / 100.0
tp3f = ps.tp3f / 100.0
tp4 = ps.tp4p / 100.0
tp4f = ps.tp4f / 100.0

fix_sl = ps.fix_sl
slp = ps.slp / 100.0

// ─── Fibonacci levels ───
h = ta.highest(high, int(sens))
l = ta.lowest(low, int(sens))
rng = h - l
fib236 = h - rng * 0.236
fib382 = h - rng * 0.382
fib500 = h - rng * 0.5
fib618 = h - rng * 0.618
fib786 = h - rng * 0.786

// ─── Trend detection ───
var bool in_long = false
var bool in_short = false
var bool long_just_started = false
var bool short_just_started = false
var int trend_bar = na

can_long  = time >= start_date_input and close >= fib500 and close >= fib236 and not in_long
can_short = time >= start_date_input and close <= fib500 and close <= fib786 and not in_short

if can_long
    in_long := true
    in_short := false
    long_just_started := true
    short_just_started := false
    trend_bar := bar_index
else if can_short
    in_short := true
    in_long := false
    short_just_started := true
    long_just_started := false
    trend_bar := bar_index
else
    long_just_started := false
    short_just_started := false

trend_changed = long_just_started or short_just_started

// ─── Plot fib line ───
plot(fib500, color=in_long[1] ? color.green : color.red, linewidth=3)
plotshape(in_long and long_just_started ? fib500 : na, "Long", shape.triangleup, location.belowbar, color.green, size=size.small)
plotshape(in_short and short_just_started ? fib500 : na, "Short", shape.triangledown, location.abovebar, color.red, size=size.small)

// ─── Entry / Exit logic ───
var float sl_price = na
var float tp1_price = na
var float tp2_price = na
var float tp3_price = na
var float tp4_price = na
var float entry_price = na

if trend_changed
    if strategy.position_size != 0
        strategy.close("Trend Change")

    entry_price := close
    if can_long
        sl_price := fix_sl ? entry_price * (1 - slp) : fib786 * (1 - slp)
    else
        sl_price := fix_sl ? entry_price * (1 + slp) : fib236 * (1 + slp)
    tp1_price := can_long ? entry_price * (1 + tp1) : entry_price * (1 - tp1)
    tp2_price := can_long ? entry_price * (1 + tp2) : entry_price * (1 - tp2)
    tp3_price := can_long ? entry_price * (1 + tp3) : entry_price * (1 - tp3)
    tp4_price := can_long ? entry_price * (1 + tp4) : entry_price * (1 - tp4)

    if can_long
        strategy.entry("L", strategy.long)
        strategy.exit("L_TP1", "L", limit=tp1_price, stop=sl_price, qty_percent=tp1f * 100)
        strategy.exit("L_TP2", "L", limit=tp2_price, qty_percent=tp2f * 100)
        strategy.exit("L_TP3", "L", limit=tp3_price, qty_percent=tp3f * 100)
        strategy.exit("L_TP4", "L", limit=tp4_price, qty_percent=tp4f * 100)
    else if can_short
        strategy.entry("S", strategy.short)
        strategy.exit("S_TP1", "S", limit=tp1_price, stop=sl_price, qty_percent=tp1f * 100)
        strategy.exit("S_TP2", "S", limit=tp2_price, qty_percent=tp2f * 100)
        strategy.exit("S_TP3", "S", limit=tp3_price, qty_percent=tp3f * 100)
        strategy.exit("S_TP4", "S", limit=tp4_price, qty_percent=tp4f * 100)

    if show_tp_sl
        line.new(trend_bar, entry_price, bar_index + 1, entry_price, color=color.new(color.gray, 30), width=2)
        line.new(trend_bar, sl_price, bar_index + 1, sl_price, color=color.new(color.red, 30), style=line.style_dashed, width=2)
        line.new(trend_bar, tp1_price, bar_index + 1, tp1_price, color=color.new(color.green, 30), style=line.style_dashed, width=2)
        line.new(trend_bar, tp2_price, bar_index + 1, tp2_price, color=color.new(color.green, 30), style=line.style_dashed, width=2)
        line.new(trend_bar, tp3_price, bar_index + 1, tp3_price, color=color.new(color.green, 30), style=line.style_dashed, width=2)
        line.new(trend_bar, tp4_price, bar_index + 1, tp4_price, color=color.new(color.green, 30), style=line.style_dashed, width=2)
    if show_labels
        label.new(bar_index, entry_price, "🔰" + str.tostring(math.round_to_mintick(entry_price)), style=label.style_label_left, color=color.new(color.white, 100), textcolor=color.gray)
        label.new(bar_index, sl_price, "⛔" + str.tostring(math.round_to_mintick(sl_price)), style=label.style_label_left, color=color.new(color.white, 100), textcolor=color.red)
        label.new(bar_index, tp1_price, "1️⃣" + str.tostring(math.round_to_mintick(tp1_price)), style=label.style_label_left, color=color.new(color.white, 100), textcolor=color.green)
        label.new(bar_index, tp2_price, "2️⃣" + str.tostring(math.round_to_mintick(tp2_price)), style=label.style_label_left, color=color.new(color.white, 100), textcolor=color.green)
        label.new(bar_index, tp3_price, "3️⃣" + str.tostring(math.round_to_mintick(tp3_price)), style=label.style_label_left, color=color.new(color.white, 100), textcolor=color.green)
        label.new(bar_index, tp4_price, "4️⃣" + str.tostring(math.round_to_mintick(tp4_price)), style=label.style_label_left, color=color.new(color.white, 100), textcolor=color.green)

// ─── RSI markers ───
rsi_val = ta.rsi(close, rsi_len)
plotshape(show_rsi and rsi_val >= rsi_ob ? high : na, color=color.red, style=shape.cross, size=size.tiny, location=location.abovebar)
plotshape(show_rsi and rsi_val <= rsi_os ? low : na, color=color.green, style=shape.cross, size=size.tiny, location=location.belowbar)

// ─── Metrics (global scope for data window) ───
opt_win = strategy.wintrades
opt_loss = strategy.losstrades
opt_total = opt_win + opt_loss
opt_wr = opt_total > 0 ? RoundUp(opt_win / opt_total * 100, 2) : 0.0
opt_profit = strategy.netprofit / strategy.initial_capital * 100
opt_pf = strategy.grossprofit / (strategy.grossloss > 0 ? strategy.grossloss : 1)

// ─── Info panel ───
if show_panel
    tbl = table.new(position.top_right, 2, 9, border_color=color.green, border_width=0)
    table.cell(tbl, 0, 0, "══════════════════════════\n[IMBUS] STRAT\n══════════════════════════", bgcolor=color.new(color.black, 87), text_color=color.green, width=8, height=5, text_size=size.normal)
    table.merge_cells(tbl, 0, 0, 1, 0)
    table.cell(tbl, 0, 1, "Trades:", bgcolor=color.new(color.black, 87), text_color=color.green, text_halign=text.align_left)
    table.cell(tbl, 1, 1, str.tostring(opt_total), bgcolor=color.new(color.black, 87), text_color=color.green)
    table.cell(tbl, 0, 2, "Win:", bgcolor=color.new(color.black, 87), text_color=color.green, text_halign=text.align_left)
    table.cell(tbl, 1, 2, str.tostring(opt_win), bgcolor=color.new(color.black, 87), text_color=color.green)
    table.cell(tbl, 0, 3, "Loss:", bgcolor=color.new(color.black, 87), text_color=color.green, text_halign=text.align_left)
    table.cell(tbl, 1, 3, str.tostring(opt_loss), bgcolor=color.new(color.black, 87), text_color=color.green)
    table.cell(tbl, 0, 4, "Winrate:", bgcolor=color.new(color.black, 87), text_color=color.green, text_halign=text.align_left)
    table.cell(tbl, 1, 4, str.tostring(opt_wr) + "%", bgcolor=color.new(color.black, 87), text_color=color.green)
    table.cell(tbl, 0, 5, "Profit:", bgcolor=color.new(color.black, 87), text_color=color.green, text_halign=text.align_left)
    table.cell(tbl, 1, 5, str.tostring(opt_profit, "#.##") + "%", bgcolor=color.new(color.black, 87), text_color=color.green)
    table.cell(tbl, 0, 6, "PF:", bgcolor=color.new(color.black, 87), text_color=color.green, text_halign=text.align_left)
    table.cell(tbl, 1, 6, str.tostring(opt_pf, "#.##"), bgcolor=color.new(color.black, 87), text_color=color.green)
    table.cell(tbl, 0, 7, "Strategy:", bgcolor=color.new(color.black, 87), text_color=color.green, text_halign=text.align_left)
    table.cell(tbl, 1, 7, strategy_input, bgcolor=color.new(color.black, 87), text_color=color.green)
    table.cell(tbl, 0, 8, "══════════════════════════", bgcolor=color.new(color.black, 87), text_color=color.green, text_halign=text.align_center)
    table.merge_cells(tbl, 0, 8, 1, 8)

// ─── Plots for MCP data window reading (x100 for precision) ───
plot(opt_total, "m_Trades", color=color.new(color.white, 0))
plot(opt_win, "m_Wins", color=color.new(color.white, 0))
plot(opt_loss, "m_Loss", color=color.new(color.white, 0))
plot(int(opt_wr * 100), "m_WR", color=color.new(color.white, 0))
plot(int(opt_profit * 100), "m_Prf", color=color.new(color.white, 0))
plot(int(opt_pf * 100), "m_PF", color=color.new(color.white, 0))

// ══════════════════════════════════════════════════════════════════════════════
// WEBHOOK ALERTS — JSON → tv_webhook.py → Extended Exchange (StarkNet DEX)
// Alert condition MUST be: "alert() function calls only"
// Leave Message field EMPTY — all data is in the alert() calls below.
// Venue: extended | Strategy key: imbus-v1
// ══════════════════════════════════════════════════════════════════════════════

var bool _a_tp1 = false
var bool _a_tp2 = false
var bool _a_tp3 = false
var bool _a_tp4 = false

// Reset TP tracking flags on every new entry
if trend_changed
    _a_tp1 := false
    _a_tp2 := false
    _a_tp3 := false
    _a_tp4 := false

// ── ENTRY ALERTS ─────────────────────────────────────────────────────────────
if trend_changed and can_long
    alert(
        "{\"symbol\":\"" + syminfo.ticker + "\"," +
        "\"side\":\"buy\"," +
        "\"price\":"     + str.format("{0,number,#.##}", close)     + "," +
        "\"sl_price\":"  + str.format("{0,number,#.##}", sl_price)  + "," +
        "\"tp1_price\":" + str.format("{0,number,#.##}", tp1_price) + "," +
        "\"tp2_price\":" + str.format("{0,number,#.##}", tp2_price) + "," +
        "\"tp3_price\":" + str.format("{0,number,#.##}", tp3_price) + "," +
        "\"tp4_price\":" + str.format("{0,number,#.##}", tp4_price) + "," +
        "\"strategy\":\"imbus-v1\",\"venue\":\"extended\",\"risk_pct\":1}",
        alert.freq_once_per_bar_close)

if trend_changed and can_short
    alert(
        "{\"symbol\":\"" + syminfo.ticker + "\"," +
        "\"side\":\"sell\"," +
        "\"price\":"     + str.format("{0,number,#.##}", close)     + "," +
        "\"sl_price\":"  + str.format("{0,number,#.##}", sl_price)  + "," +
        "\"tp1_price\":" + str.format("{0,number,#.##}", tp1_price) + "," +
        "\"tp2_price\":" + str.format("{0,number,#.##}", tp2_price) + "," +
        "\"tp3_price\":" + str.format("{0,number,#.##}", tp3_price) + "," +
        "\"tp4_price\":" + str.format("{0,number,#.##}", tp4_price) + "," +
        "\"strategy\":\"imbus-v1\",\"venue\":\"extended\",\"risk_pct\":1}",
        alert.freq_once_per_bar_close)

// ── PARTIAL CLOSE ALERTS (fire when price crosses each TP level) ──────────────
if strategy.position_size != 0
    if in_long
        if not _a_tp1 and high >= tp1_price
            _a_tp1 := true
            alert(
                "{\"symbol\":\"" + syminfo.ticker + "\"," +
                "\"side\":\"partial_close\",\"close_pct\":40," +
                "\"price\":" + str.format("{0,number,#.##}", tp1_price) + "," +
                "\"strategy\":\"imbus-v1\",\"venue\":\"extended\"}",
                alert.freq_once_per_bar_close)
        if not _a_tp2 and high >= tp2_price
            _a_tp2 := true
            alert(
                "{\"symbol\":\"" + syminfo.ticker + "\"," +
                "\"side\":\"partial_close\",\"close_pct\":30," +
                "\"price\":" + str.format("{0,number,#.##}", tp2_price) + "," +
                "\"strategy\":\"imbus-v1\",\"venue\":\"extended\"}",
                alert.freq_once_per_bar_close)
        if not _a_tp3 and high >= tp3_price
            _a_tp3 := true
            alert(
                "{\"symbol\":\"" + syminfo.ticker + "\"," +
                "\"side\":\"partial_close\",\"close_pct\":20," +
                "\"price\":" + str.format("{0,number,#.##}", tp3_price) + "," +
                "\"strategy\":\"imbus-v1\",\"venue\":\"extended\"}",
                alert.freq_once_per_bar_close)
        if not _a_tp4 and high >= tp4_price
            _a_tp4 := true
            alert(
                "{\"symbol\":\"" + syminfo.ticker + "\"," +
                "\"side\":\"partial_close\",\"close_pct\":10," +
                "\"price\":" + str.format("{0,number,#.##}", tp4_price) + "," +
                "\"strategy\":\"imbus-v1\",\"venue\":\"extended\"}",
                alert.freq_once_per_bar_close)
    else if in_short
        if not _a_tp1 and low <= tp1_price
            _a_tp1 := true
            alert(
                "{\"symbol\":\"" + syminfo.ticker + "\"," +
                "\"side\":\"partial_close\",\"close_pct\":40," +
                "\"price\":" + str.format("{0,number,#.##}", tp1_price) + "," +
                "\"strategy\":\"imbus-v1\",\"venue\":\"extended\"}",
                alert.freq_once_per_bar_close)
        if not _a_tp2 and low <= tp2_price
            _a_tp2 := true
            alert(
                "{\"symbol\":\"" + syminfo.ticker + "\"," +
                "\"side\":\"partial_close\",\"close_pct\":30," +
                "\"price\":" + str.format("{0,number,#.##}", tp2_price) + "," +
                "\"strategy\":\"imbus-v1\",\"venue\":\"extended\"}",
                alert.freq_once_per_bar_close)
        if not _a_tp3 and low <= tp3_price
            _a_tp3 := true
            alert(
                "{\"symbol\":\"" + syminfo.ticker + "\"," +
                "\"side\":\"partial_close\",\"close_pct\":20," +
                "\"price\":" + str.format("{0,number,#.##}", tp3_price) + "," +
                "\"strategy\":\"imbus-v1\",\"venue\":\"extended\"}",
                alert.freq_once_per_bar_close)
        if not _a_tp4 and low <= tp4_price
            _a_tp4 := true
            alert(
                "{\"symbol\":\"" + syminfo.ticker + "\"," +
                "\"side\":\"partial_close\",\"close_pct\":10," +
                "\"price\":" + str.format("{0,number,#.##}", tp4_price) + "," +
                "\"strategy\":\"imbus-v1\",\"venue\":\"extended\"}",
                alert.freq_once_per_bar_close)

// ── CLOSE ALERT (SL hit or forced close by new trend) ────────────────────────
if strategy.position_size == 0 and strategy.position_size[1] != 0
    alert(
        "{\"symbol\":\"" + syminfo.ticker + "\"," +
        "\"side\":\"close\"," +
        "\"price\":" + str.format("{0,number,#.##}", close) + "," +
        "\"strategy\":\"imbus-v1\",\"venue\":\"extended\"}",
        alert.freq_once_per_bar_close)

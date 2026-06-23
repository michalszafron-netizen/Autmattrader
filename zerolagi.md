// This Pine Script™ code is subject to the terms of the Mozilla Public License 2.0 at https://mozilla.org/MPL/2.0/
// Strategy: Zero Lag Trend Signals + K-Means Volatility Clustering
// v4 — Pine v6, redesigned risk management, persistent tables

//@version=6
strategy(
     "ZL Volatility Strategy",
     shorttitle         = "ZL+AV",
     overlay            = true,
     max_labels_count   = 500,
     default_qty_type   = strategy.percent_of_equity,
     default_qty_value  = 10,
     commission_type    = strategy.commission.percent,
     commission_value   = 0.05,
     slippage           = 2,
     pyramiding         = 0,
     calc_on_every_tick = true
 )

// ══════════════════════════════════════════════════════════════════════════════
// ① ZERO LAG SETTINGS
// ══════════════════════════════════════════════════════════════════════════════
length = input.int  (70,  "ZLEMA Length",    group = "① Zero Lag Settings")
mult   = input.float(1.2, "Band Multiplier", group = "① Zero Lag Settings")

// ══════════════════════════════════════════════════════════════════════════════
// ② MTF FILTER
// ══════════════════════════════════════════════════════════════════════════════
use_mtf_filter   = input.bool(true, "Enable MTF Filter", group = "② MTF Filter")
min_tf_agreement = input.int (3,    "Min TF Agreements (of 5)", minval = 1, maxval = 5, group = "② MTF Filter")
t1 = input.timeframe("5",   "Timeframe 1", group = "② MTF Filter")
t2 = input.timeframe("15",  "Timeframe 2", group = "② MTF Filter")
t3 = input.timeframe("60",  "Timeframe 3", group = "② MTF Filter")
t4 = input.timeframe("240", "Timeframe 4", group = "② MTF Filter")
t5 = input.timeframe("1D",  "Timeframe 5", group = "② MTF Filter")

// ══════════════════════════════════════════════════════════════════════════════
// ③ VOLATILITY CLUSTER (K-Means)
// ══════════════════════════════════════════════════════════════════════════════
use_vol_filter       = input.bool (true,  "Enable Volatility Filter",  group = "③ Volatility Cluster")
atr_len              = input.int  (10,    "ATR Length (Clustering)",    group = "③ Volatility Cluster")
training_data_period = input.int  (100,   "Training Data Length",       group = "③ Volatility Cluster")
highvol              = input.float(0.75,  "High Vol Percentile Seed",  maxval = 1, group = "③ Volatility Cluster")
midvol               = input.float(0.5,   "Mid Vol Percentile Seed",   maxval = 1, group = "③ Volatility Cluster")
lowvol               = input.float(0.25,  "Low Vol Percentile Seed",   maxval = 1, group = "③ Volatility Cluster")
trade_high_vol       = input.bool (false, "Trade in HIGH Volatility",  group = "③ Volatility Cluster")
trade_med_vol        = input.bool (true,  "Trade in MEDIUM Volatility",group = "③ Volatility Cluster")
trade_low_vol        = input.bool (true,  "Trade in LOW Volatility",   group = "③ Volatility Cluster")

// ══════════════════════════════════════════════════════════════════════════════
// ④ RISK MANAGEMENT
// ══════════════════════════════════════════════════════════════════════════════
trade_direction = input.string("Both", "Trade Direction",
                  options = ["Long Only", "Short Only", "Both"], group = "④ Risk Management")

sl_atr_mult   = input.float(2.5, "SL: ATR Multiplier", step = 0.1, minval = 1.0, group = "④ Risk Management",
                tooltip = "Stop = entry ± (ATR × this). Higher = wider stop, fewer SL hits, larger losses when hit.")
sl_min_pct    = input.float(0.8, "SL: Minimum % Distance", step = 0.1, minval = 0.1, group = "④ Risk Management",
                tooltip = "Safety floor: SL will never be closer than this % from entry, even if ATR says so.")

tp_rr         = input.float(2.5, "TP: Reward/Risk Ratio", step = 0.1, minval = 1.5, group = "④ Risk Management",
                tooltip = "TP distance = SL distance × this. Minimum 1.5.")

use_trail      = input.bool (true, "Enable Trailing Stop", group = "④ Risk Management")
trail_trigger  = input.float(1.0, "Trail: Activate at X × SL profit", step = 0.1, minval = 0.5, group = "④ Risk Management",
                 tooltip = "After price moves this many SL-distances in your favor, SL trails to breakeven + offset.")
trail_offset   = input.float(0.3, "Trail: Breakeven Offset (× SL)", step = 0.1, minval = 0.0, group = "④ Risk Management",
                 tooltip = "When trailing activates, lock in this fraction of SL distance as guaranteed profit.")

cooldown_bars  = input.int(10, "Cooldown Bars After Entry", minval = 0, group = "④ Risk Management",
                 tooltip = "Min bars before next entry. Higher = fewer trades, more selective.")

// ══════════════════════════════════════════════════════════════════════════════
// ⑤ APPEARANCE
// ══════════════════════════════════════════════════════════════════════════════
green = input.color(#00ffbb, "Bullish Color", group = "⑤ Appearance")
red   = input.color(#ff1100, "Bearish Color", group = "⑤ Appearance")

// ══════════════════════════════════════════════════════════════════════════════
// CORE: ZERO LAG EMA + TREND
// ══════════════════════════════════════════════════════════════════════════════
src      = close
lag      = math.floor((length - 1) / 2)
zlema    = ta.ema(src + (src - src[lag]), length)
vol_band = ta.highest(ta.atr(length), length * 3) * mult

var int trend = 0
if ta.crossover(close, zlema + vol_band)
    trend := 1
if ta.crossunder(close, zlema - vol_band)
    trend := -1

big_bull_raw = ta.crossover (trend, 0)
big_bear_raw = ta.crossunder(trend, 0)

// ══════════════════════════════════════════════════════════════════════════════
// CORE: K-MEANS VOLATILITY CLUSTERING
// ══════════════════════════════════════════════════════════════════════════════
atr_val   = ta.atr(atr_len)
upper_atr = ta.highest(atr_val, training_data_period)
lower_atr = ta.lowest (atr_val, training_data_period)

hv_seed = lower_atr + (upper_atr - lower_atr) * highvol
mv_seed = lower_atr + (upper_atr - lower_atr) * midvol
lv_seed = lower_atr + (upper_atr - lower_atr) * lowvol

var int   cluster = na
var float hv_c    = na
var float mv_c    = na
var float lv_c    = na
var int   sz_high = 0
var int   sz_med  = 0
var int   sz_low  = 0

hv_pts = array.new_float()
mv_pts = array.new_float()
lv_pts = array.new_float()
amean  = array.new_float(1, hv_seed)
bmean  = array.new_float(1, mv_seed)
cmean  = array.new_float(1, lv_seed)

if nz(atr_val) > 0 and bar_index >= training_data_period - 1
    while (amean.size() == 1 ? true : amean.first() != amean.get(1)) or
          (bmean.size() == 1 ? true : bmean.first() != bmean.get(1)) or
          (cmean.size() == 1 ? true : cmean.first() != cmean.get(1))
        hv_pts.clear()
        mv_pts.clear()
        lv_pts.clear()
        for i = training_data_period - 1 to 0
            v  = atr_val[i]
            d1 = math.abs(v - amean.first())
            d2 = math.abs(v - bmean.first())
            d3 = math.abs(v - cmean.first())
            if d1 < d2 and d1 < d3
                hv_pts.unshift(v)
            else if d2 < d1 and d2 < d3
                mv_pts.unshift(v)
            else if d3 < d1 and d3 < d2
                lv_pts.unshift(v)
        amean.unshift(hv_pts.avg())
        bmean.unshift(mv_pts.avg())
        cmean.unshift(lv_pts.avg())
        sz_high := hv_pts.size()
        sz_med  := mv_pts.size()
        sz_low  := lv_pts.size()

hv_c := amean.first()
mv_c := bmean.first()
lv_c := cmean.first()

dist_arr = array.new_float()
dist_arr.push(math.abs(atr_val - hv_c))
dist_arr.push(math.abs(atr_val - mv_c))
dist_arr.push(math.abs(atr_val - lv_c))
cluster := dist_arr.indexof(dist_arr.min())

// ══════════════════════════════════════════════════════════════════════════════
// CORE: MTF TREND
// ══════════════════════════════════════════════════════════════════════════════
s1 = request.security(syminfo.tickerid, t1, trend)
s2 = request.security(syminfo.tickerid, t2, trend)
s3 = request.security(syminfo.tickerid, t3, trend)
s4 = request.security(syminfo.tickerid, t4, trend)
s5 = request.security(syminfo.tickerid, t5, trend)

bull_score = (s1 == 1 ? 1 : 0) + (s2 == 1 ? 1 : 0) + (s3 == 1 ? 1 : 0) + (s4 == 1 ? 1 : 0) + (s5 == 1 ? 1 : 0)
bear_score = (s1 ==-1 ? 1 : 0) + (s2 ==-1 ? 1 : 0) + (s3 ==-1 ? 1 : 0) + (s4 ==-1 ? 1 : 0) + (s5 ==-1 ? 1 : 0)

// ══════════════════════════════════════════════════════════════════════════════
// FILTERS
// ══════════════════════════════════════════════════════════════════════════════
vol_ok       = not use_vol_filter or
               (cluster == 0 and trade_high_vol) or
               (cluster == 1 and trade_med_vol)  or
               (cluster == 2 and trade_low_vol)

mtf_long_ok  = not use_mtf_filter or bull_score >= min_tf_agreement
mtf_short_ok = not use_mtf_filter or bear_score >= min_tf_agreement

can_long     = trade_direction != "Short Only"
can_short    = trade_direction != "Long Only"

var int last_entry_bar = -999
cooled_down = (bar_index - last_entry_bar) >= cooldown_bars

// ══════════════════════════════════════════════════════════════════════════════
// STOP LOSS / TAKE PROFIT CALCULATION
// ══════════════════════════════════════════════════════════════════════════════
f_sl_dist(float entry_price) =>
    atr_based = atr_val * sl_atr_mult
    pct_floor = entry_price * sl_min_pct / 100
    math.max(atr_based, pct_floor)

// ══════════════════════════════════════════════════════════════════════════════
// ENTRY + EXIT EXECUTION
// ══════════════════════════════════════════════════════════════════════════════
long_signal  = big_bull_raw and vol_ok and mtf_long_ok  and can_long  and cooled_down
short_signal = big_bear_raw and vol_ok and mtf_short_ok and can_short and cooled_down

var float entry_price  = na
var float sl_level     = na
var float tp_level     = na
var float sl_distance  = na
var bool  is_long      = false
var bool  trail_active = false

if long_signal
    entry_price  := close
    sl_distance  := f_sl_dist(close)
    sl_level     := close - sl_distance
    tp_level     := close + sl_distance * math.max(tp_rr, 1.5)
    is_long      := true
    trail_active := false
    last_entry_bar := bar_index
    strategy.entry("Long", strategy.long)
    strategy.exit("Exit Long", "Long", stop = sl_level, limit = tp_level)

if short_signal
    entry_price  := close
    sl_distance  := f_sl_dist(close)
    sl_level     := close + sl_distance
    tp_level     := close - sl_distance * math.max(tp_rr, 1.5)
    is_long      := false
    trail_active := false
    last_entry_bar := bar_index
    strategy.entry("Short", strategy.short)
    strategy.exit("Exit Short", "Short", stop = sl_level, limit = tp_level)

if use_trail and strategy.position_size != 0 and not na(entry_price)
    if is_long and strategy.position_size > 0
        profit_dist = high - entry_price
        if profit_dist >= sl_distance * trail_trigger and not trail_active
            new_sl       = entry_price + sl_distance * trail_offset
            sl_level     := math.max(sl_level, new_sl)
            trail_active := true
            strategy.exit("Exit Long", "Long", stop = sl_level, limit = tp_level)
    else if not is_long and strategy.position_size < 0
        profit_dist = entry_price - low
        if profit_dist >= sl_distance * trail_trigger and not trail_active
            new_sl       = entry_price - sl_distance * trail_offset
            sl_level     := math.min(sl_level, new_sl)
            trail_active := true
            strategy.exit("Exit Short", "Short", stop = sl_level, limit = tp_level)

if strategy.position_size == 0 and strategy.position_size[1] != 0
    entry_price  := na
    sl_level     := na
    tp_level     := na
    sl_distance  := na
    trail_active := false

// ══════════════════════════════════════════════════════════════════════════════
// VISUALS
// ══════════════════════════════════════════════════════════════════════════════
zlema_col  = trend == 1 ? color.new(green, 70) : color.new(red, 70)
m_plot     = plot(zlema, "Zero Lag Basis", linewidth = 2, color = zlema_col)
upper_plot = plot(trend == -1 ? zlema + vol_band : na, "Upper Band",
                  style = plot.style_linebr, color = color.new(red, 90))
lower_plot = plot(trend ==  1 ? zlema - vol_band : na, "Lower Band",
                  style = plot.style_linebr, color = color.new(green, 90))

fill(m_plot, upper_plot, (open + close) / 2, zlema + vol_band, color.new(red,   90), color.new(red,   70))
fill(m_plot, lower_plot, (open + close) / 2, zlema - vol_band, color.new(green, 90), color.new(green, 70))

plotshape(big_bear_raw ? zlema + vol_band : na, "Bearish Flip", shape.labeldown,
          location.absolute, red,   text = "▼", textcolor = chart.fg_color, size = size.small)
plotshape(big_bull_raw ? zlema - vol_band : na, "Bullish Flip", shape.labelup,
          location.absolute, green, text = "▲", textcolor = chart.fg_color, size = size.small)

plot(strategy.position_size != 0 ? sl_level : na, "Stop Loss",   color = color.new(red,   30), style = plot.style_linebr, linewidth = 1)
plot(strategy.position_size != 0 ? tp_level : na, "Take Profit", color = color.new(green, 30), style = plot.style_linebr, linewidth = 1)
plot(strategy.position_size != 0 ? entry_price : na, "Entry",    color = color.new(color.white, 50), style = plot.style_linebr, linewidth = 1)

bgcolor(trail_active and strategy.position_size != 0 ? color.new(color.yellow, 93) : na, title = "Trail Active")

// ══════════════════════════════════════════════════════════════════════════════
// TABLE 1 — MTF TREND
// ══════════════════════════════════════════════════════════════════════════════
var mtf_tbl = table.new(position.top_right, columns = 2, rows = 7,
                         bgcolor = chart.bg_color, border_width = 1,
                         border_color = chart.fg_color, frame_color = chart.fg_color, frame_width = 1)

s1a = s1 == 1 ? "Bullish" : "Bearish"
s2a = s2 == 1 ? "Bullish" : "Bearish"
s3a = s3 == 1 ? "Bullish" : "Bearish"
s4a = s4 == 1 ? "Bullish" : "Bearish"
s5a = s5 == 1 ? "Bullish" : "Bearish"

table.cell(mtf_tbl, 0, 0, "MTF TREND",  text_color = color.white, text_halign = text.align_center, bgcolor = color.new(color.gray, 50))
table.cell(mtf_tbl, 1, 0, "Signal",     text_color = color.white, text_halign = text.align_center, bgcolor = color.new(color.gray, 50))
table.cell(mtf_tbl, 0, 1, t1,  text_color = chart.fg_color, text_halign = text.align_center)
table.cell(mtf_tbl, 1, 1, s1a, text_color = chart.fg_color, text_halign = text.align_center, bgcolor = s1a == "Bullish" ? color.new(green, 70) : color.new(red, 70))
table.cell(mtf_tbl, 0, 2, t2,  text_color = chart.fg_color, text_halign = text.align_center)
table.cell(mtf_tbl, 1, 2, s2a, text_color = chart.fg_color, text_halign = text.align_center, bgcolor = s2a == "Bullish" ? color.new(green, 70) : color.new(red, 70))
table.cell(mtf_tbl, 0, 3, t3,  text_color = chart.fg_color, text_halign = text.align_center)
table.cell(mtf_tbl, 1, 3, s3a, text_color = chart.fg_color, text_halign = text.align_center, bgcolor = s3a == "Bullish" ? color.new(green, 70) : color.new(red, 70))
table.cell(mtf_tbl, 0, 4, t4,  text_color = chart.fg_color, text_halign = text.align_center)
table.cell(mtf_tbl, 1, 4, s4a, text_color = chart.fg_color, text_halign = text.align_center, bgcolor = s4a == "Bullish" ? color.new(green, 70) : color.new(red, 70))
table.cell(mtf_tbl, 0, 5, t5,  text_color = chart.fg_color, text_halign = text.align_center)
table.cell(mtf_tbl, 1, 5, s5a, text_color = chart.fg_color, text_halign = text.align_center, bgcolor = s5a == "Bullish" ? color.new(green, 70) : color.new(red, 70))

agree_txt = str.tostring(bull_score) + "B / " + str.tostring(bear_score) + "S"
agree_col = bull_score >= min_tf_agreement ? color.new(green, 50) : bear_score >= min_tf_agreement ? color.new(red, 50) : color.new(color.gray, 50)
table.cell(mtf_tbl, 0, 6, "Score", text_color = chart.fg_color, text_halign = text.align_center)
table.cell(mtf_tbl, 1, 6, agree_txt, text_color = color.white, text_halign = text.align_center, bgcolor = agree_col)

// ══════════════════════════════════════════════════════════════════════════════
// TABLE 2 — VOLATILITY CLUSTER
// ══════════════════════════════════════════════════════════════════════════════
var vol_tbl = table.new(position.bottom_right, columns = 4, rows = 5,
                         bgcolor = chart.bg_color, border_width = 1,
                         border_color = chart.fg_color, frame_color = chart.fg_color, frame_width = 1)

atr_str  = str.format("{0,number,#.##}", atr_val)
h_active = cluster == 0
m_active = cluster == 1
l_active = cluster == 2

table.cell(vol_tbl, 0, 0, "VOLATILITY", text_color = color.white, text_halign = text.align_center, bgcolor = color.new(color.gray, 50))
table.cell(vol_tbl, 1, 0, "Centroid",   text_color = color.white, text_halign = text.align_center, bgcolor = color.new(color.gray, 50))
table.cell(vol_tbl, 2, 0, "Size",       text_color = color.white, text_halign = text.align_center, bgcolor = color.new(color.gray, 50))
table.cell(vol_tbl, 3, 0, "Status",     text_color = color.white, text_halign = text.align_center, bgcolor = color.new(color.gray, 50))

table.cell(vol_tbl, 0, 1, "3 HIGH",   text_color = chart.fg_color, text_halign = text.align_center)
table.cell(vol_tbl, 1, 1, str.format("{0,number,#.##}", hv_c), text_color = chart.fg_color, text_halign = text.align_center)
table.cell(vol_tbl, 2, 1, str.tostring(sz_high), text_color = chart.fg_color, text_halign = text.align_center)
table.cell(vol_tbl, 3, 1, h_active ? "◀ ACTIVE" : "",
           text_color = h_active ? chart.bg_color : chart.fg_color,
           bgcolor = h_active ? color.new(red, 30) : chart.bg_color, text_halign = text.align_center)

table.cell(vol_tbl, 0, 2, "2 MEDIUM", text_color = chart.fg_color, text_halign = text.align_center)
table.cell(vol_tbl, 1, 2, str.format("{0,number,#.##}", mv_c), text_color = chart.fg_color, text_halign = text.align_center)
table.cell(vol_tbl, 2, 2, str.tostring(sz_med), text_color = chart.fg_color, text_halign = text.align_center)
table.cell(vol_tbl, 3, 2, m_active ? "◀ ACTIVE" : "",
           text_color = m_active ? chart.bg_color : chart.fg_color,
           bgcolor = m_active ? color.new(color.yellow, 30) : chart.bg_color, text_halign = text.align_center)

table.cell(vol_tbl, 0, 3, "1 LOW",    text_color = chart.fg_color, text_halign = text.align_center)
table.cell(vol_tbl, 1, 3, str.format("{0,number,#.##}", lv_c), text_color = chart.fg_color, text_halign = text.align_center)
table.cell(vol_tbl, 2, 3, str.tostring(sz_low), text_color = chart.fg_color, text_halign = text.align_center)
table.cell(vol_tbl, 3, 3, l_active ? "◀ ACTIVE" : "",
           text_color = l_active ? chart.bg_color : chart.fg_color,
           bgcolor = l_active ? color.new(green, 30) : chart.bg_color, text_halign = text.align_center)

trade_ok = (trade_high_vol and h_active) or (trade_med_vol and m_active) or (trade_low_vol and l_active)
table.cell(vol_tbl, 0, 4, "ATR",      text_color = chart.fg_color, text_halign = text.align_center)
table.cell(vol_tbl, 1, 4, atr_str,    text_color = color.white,    text_halign = text.align_center, bgcolor = color.new(color.gray, 50))
table.cell(vol_tbl, 2, 4, "",         text_color = chart.fg_color, text_halign = text.align_center)
table.cell(vol_tbl, 3, 4, trade_ok ? "TRADEABLE" : "BLOCKED",
           text_color = color.white, text_halign = text.align_center,
           bgcolor = trade_ok ? color.new(green, 50) : color.new(red, 50))

// ══════════════════════════════════════════════════════════════════════════════
// TABLE 3 — POSITION STATUS
// ══════════════════════════════════════════════════════════════════════════════
var pos_tbl = table.new(position.bottom_left, columns = 2, rows = 6,
                         bgcolor = chart.bg_color, border_width = 1,
                         border_color = chart.fg_color, frame_color = chart.fg_color, frame_width = 1)

in_trade     = strategy.position_size != 0
pos_dir      = strategy.position_size > 0 ? "LONG" : strategy.position_size < 0 ? "SHORT" : "FLAT"
pos_col      = strategy.position_size > 0 ? color.new(green, 50) : strategy.position_size < 0 ? color.new(red, 50) : color.new(color.gray, 50)
cur_pnl      = in_trade ? (is_long ? close - entry_price : entry_price - close) : 0.0
cur_pnl_pct  = in_trade and not na(entry_price) and entry_price > 0 ? (cur_pnl / entry_price) * 100 : 0.0
pnl_col      = cur_pnl >= 0 ? color.new(green, 50) : color.new(red, 50)
trail_txt    = trail_active ? "YES — SL locked" : use_trail ? "Waiting..." : "OFF"
trail_col    = trail_active ? color.new(color.yellow, 50) : color.new(color.gray, 70)
dist_to_sl   = in_trade and not na(sl_level)  ? math.abs(close - sl_level)  : 0.0
dist_to_tp   = in_trade and not na(tp_level)  ? math.abs(close - tp_level)  : 0.0

table.cell(pos_tbl, 0, 0, "POSITION",  text_color = color.white, text_halign = text.align_center, bgcolor = color.new(color.gray, 50))
table.cell(pos_tbl, 1, 0, pos_dir,     text_color = color.white, text_halign = text.align_center, bgcolor = pos_col)
table.cell(pos_tbl, 0, 1, "Entry",     text_color = chart.fg_color, text_halign = text.align_center)
table.cell(pos_tbl, 1, 1, in_trade and not na(entry_price) ? str.format("{0,number,#.##}", entry_price) : "—",
           text_color = chart.fg_color, text_halign = text.align_center)
table.cell(pos_tbl, 0, 2, "Stop Loss", text_color = chart.fg_color, text_halign = text.align_center)
table.cell(pos_tbl, 1, 2, in_trade and not na(sl_level) ? str.format("{0,number,#.##}", sl_level) + " (" + str.format("{0,number,#.##}", dist_to_sl) + " away)" : "—",
           text_color = color.new(red, 30), text_halign = text.align_center)
table.cell(pos_tbl, 0, 3, "Take Profit", text_color = chart.fg_color, text_halign = text.align_center)
table.cell(pos_tbl, 1, 3, in_trade and not na(tp_level) ? str.format("{0,number,#.##}", tp_level) + " (" + str.format("{0,number,#.##}", dist_to_tp) + " away)" : "—",
           text_color = color.new(green, 30), text_halign = text.align_center)
table.cell(pos_tbl, 0, 4, "Unrealized", text_color = chart.fg_color, text_halign = text.align_center)
table.cell(pos_tbl, 1, 4, in_trade ? str.format("{0,number,#.##}", cur_pnl) + " (" + str.format("{0,number,#.##}", cur_pnl_pct) + "%)" : "—",
           text_color = cur_pnl >= 0 ? color.new(green, 30) : color.new(red, 30), text_halign = text.align_center)
table.cell(pos_tbl, 0, 5, "Trailing",  text_color = chart.fg_color, text_halign = text.align_center)
table.cell(pos_tbl, 1, 5, trail_txt,   text_color = color.white, text_halign = text.align_center, bgcolor = trail_col)

// ══════════════════════════════════════════════════════════════════════════════
// ALERTS — JSON format (webhook reads sl_price + tp_price for bracket orders)
// IMPORTANT: TV alert condition must be "alert() function calls only"
// ══════════════════════════════════════════════════════════════════════════════
if long_signal
    _sl = close - f_sl_dist(close)
    _tp = close + f_sl_dist(close) * math.max(tp_rr, 1.5)
    alert(
        "{\"symbol\":\"" + syminfo.ticker + "\"," +
        "\"side\":\"buy\"," +
        "\"price\":"    + str.format("{0,number,#.####}", close) + "," +
        "\"sl_price\":" + str.format("{0,number,#.####}", _sl)   + "," +
        "\"tp_price\":" + str.format("{0,number,#.####}", _tp)   + "," +
        "\"strategy\":\"zl-volatility-v1\",\"risk_pct\":1}",
        alert.freq_once_per_bar_close)

if short_signal
    _sl = close + f_sl_dist(close)
    _tp = close - f_sl_dist(close) * math.max(tp_rr, 1.5)
    alert(
        "{\"symbol\":\"" + syminfo.ticker + "\"," +
        "\"side\":\"sell\"," +
        "\"price\":"    + str.format("{0,number,#.####}", close) + "," +
        "\"sl_price\":" + str.format("{0,number,#.####}", _sl)   + "," +
        "\"tp_price\":" + str.format("{0,number,#.####}", _tp)   + "," +
        "\"strategy\":\"zl-volatility-v1\",\"risk_pct\":1}",
        alert.freq_once_per_bar_close)

if strategy.position_size == 0 and strategy.position_size[1] != 0
    alert(
        "{\"symbol\":\"" + syminfo.ticker + "\"," +
        "\"side\":\"close\"," +
        "\"price\":"    + str.format("{0,number,#.####}", close) + "," +
        "\"strategy\":\"zl-volatility-v1\"}",
        alert.freq_once_per_bar_close)

if trail_active and not trail_active[1]
    alert(
        "{\"symbol\":\"" + syminfo.ticker + "\"," +
        "\"side\":\"update_sl\"," +
        "\"price\":"    + str.format("{0,number,#.####}", close)    + "," +
        "\"sl_price\":" + str.format("{0,number,#.####}", sl_level) + "," +
        "\"strategy\":\"zl-volatility-v1\"}",
        alert.freq_once_per_bar_close)

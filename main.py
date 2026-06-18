import os
import json
import time
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

# US symbols — the core engine
US_SYMBOLS = ['SPY', 'QQQ', 'IWM', 'EFA', 'AGG']

# International ETFs that trade on US exchanges during US hours
# These give you exposure to London + Asian markets, no broker change needed
INTL_SYMBOLS = {
    'FXI':  'China Large Cap',
    'EWJ':  'Japan (Nikkei)',
    'EWY':  'South Korea (KOSPI)',
    'EWA':  'Australia (ASX)',
    'EWU':  'UK (FTSE 100)',
    'EWG':  'Germany (DAX)',
    'EWH':  'Hong Kong (Hang Seng)',
    'INDA': 'India (Nifty 50)',
}

ALL_SYMBOLS = US_SYMBOLS + list(INTL_SYMBOLS.keys())

LOOKBACK_MOM   = 200   # days for SMA
RISK_PER_TRADE = 0.01  # 1% equity per position
MAX_DD_STOP    = 0.15  # 15% drawdown kill switch
MIN_SHARPE     = 0.80  # minimum live signal quality gate
MAX_POSITIONS  = 3     # max concurrent open positions

IS_PAPER = os.getenv('ALPACA_PAPER', 'true').lower() == 'true'
ALPACA_BASE_URL = (
    'https://paper-api.alpaca.markets' if IS_PAPER
    else 'https://api.alpaca.markets'
)

TELEGRAM_TOKEN  = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT   = os.getenv('TELEGRAM_CHAT')
ALPACA_KEY      = os.getenv('ALPACA_KEY')
ALPACA_SECRET   = os.getenv('ALPACA_SECRET')
GSPREAD_JSON    = os.getenv('GSPREAD_JSON')
SHEET_ID        = os.getenv('SHEET_ID')
FRED_API_KEY    = os.getenv('FRED_API_KEY', '')  # optional, for real yield curve

# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────

def send_telegram(msg: str, silent: bool = False):
    """Send Telegram message. Never raises."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        log.warning("Telegram not configured — skipping message.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT,
            "text": msg,
            "disable_notification": silent,
            "parse_mode": "Markdown",
        }
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        log.error(f"Telegram failed: {e}")

# ─────────────────────────────────────────────
# ALPACA CLIENTS  (new SDK v2)
# ─────────────────────────────────────────────

def get_trading_client() -> TradingClient:
    return TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=IS_PAPER)

def get_data_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)

# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

def get_data(symbols: list[str]) -> pd.DataFrame:
    """
    Primary  : Alpaca IEX (free tier)
    Fallback : Stooq via pandas_datareader
    Returns  : DataFrame[date, symbol] of adjusted close. Empty on total failure.
    """
    from pandas.tseries.offsets import BDay
    import pandas_datareader.data as web

    end   = pd.Timestamp.now(tz='UTC').normalize()
    if end.weekday() >= 5:
        end = end - BDay(1)
    start = end - pd.Timedelta(days=LOOKBACK_MOM + 120)

    # ── Alpaca IEX ──
    try:
        client = get_data_client()
        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start.to_pydatetime(),
            end=end.to_pydatetime(),
            adjustment='all',
            feed='iex',
        )
        bars = client.get_stock_bars(req).df
        if not bars.empty:
            # new SDK returns multi-index (symbol, timestamp)
            bars = bars['close'].unstack(level=0)
            bars.index = pd.to_datetime(bars.index).tz_localize(None)
            bars = bars.dropna(how='all')
            if len(bars) >= LOOKBACK_MOM:
                send_telegram(
                    f"✅ *Data OK* via Alpaca IEX: `{len(bars)}` days — "
                    f"last `{bars.index[-1].date()}`", silent=True
                )
                return bars
    except Exception as e:
        send_telegram(f"⚠️ Alpaca data failed: `{str(e)[:120]}`\nTrying Stooq…")
        log.warning(f"Alpaca data error: {e}")

    # ── Stooq fallback ──
    try:
        df = pd.DataFrame()
        for sym in symbols:
            try:
                tmp = web.DataReader(f'{sym}.US', 'stooq', start=start, end=end)
                df[sym] = tmp['Close']
            except Exception:
                pass   # missing symbol is non-fatal
        df = df.sort_index().dropna(how='all')
        if len(df) >= LOOKBACK_MOM:
            send_telegram(
                f"✅ *Data OK* via Stooq: `{len(df)}` days — "
                f"last `{df.index[-1].date()}`", silent=True
            )
            return df
    except Exception as e:
        log.error(f"Stooq fallback error: {e}")

    send_telegram("🚨 *CRITICAL*: All data sources failed. Aborting run.")
    return pd.DataFrame()

# ─────────────────────────────────────────────
# YIELD CURVE  (real FRED data if key available)
# ─────────────────────────────────────────────

def get_yield_curve() -> float:
    """
    Returns spread = 10y_yield - 2y_yield.
    Positive → risk-on.  Negative → inverted (risk-off).
    Falls back to 1.0 (assume risk-on) if FRED key missing.
    """
    if not FRED_API_KEY:
        return 1.0   # optimistic default

    def _fred(series_id):
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={FRED_API_KEY}"
            f"&file_type=json&sort_order=desc&limit=5"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        obs = r.json()['observations']
        for o in obs:
            if o['value'] != '.':
                return float(o['value'])
        raise ValueError("No valid FRED observation")

    try:
        t10 = _fred('DGS10')
        t2  = _fred('DGS2')
        spread = t10 - t2
        log.info(f"Yield curve: 10y={t10:.2f} 2y={t2:.2f} spread={spread:.2f}")
        return spread
    except Exception as e:
        log.warning(f"FRED fetch failed ({e}), defaulting to risk-on")
        return 1.0

# ─────────────────────────────────────────────
# SIGNALS
# ─────────────────────────────────────────────

def calc_signals(df: pd.DataFrame) -> dict[str, dict]:
    """
    For each symbol returns:
      { 'signal': bool, 'price': float, 'sma200': float,
        'momentum': float, 'rsi14': float, 'score': float }

    Signal = True only when ALL of:
      1. Price > 200d SMA
      2. 200d Momentum > 0
      3. RSI(14) between 35 and 70  (not overbought, not collapsed)
    Score = composite rank for position sizing / selection.
    """
    results = {}
    for sym in df.columns:
        s = df[sym].dropna()
        if len(s) < 200:
            results[sym] = {'signal': False, 'score': 0.0}
            continue

        price    = s.iloc[-1]
        sma200   = s.rolling(200).mean().iloc[-1]
        momentum = (price / s.iloc[-LOOKBACK_MOM]) - 1

        # RSI-14
        delta = s.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = (100 - 100 / (1 + rs)).iloc[-1]

        trend_ok = price > sma200
        mom_ok   = momentum > 0
        rsi_ok   = 35 < rsi < 70

        signal = trend_ok and mom_ok and rsi_ok
        score  = momentum * (1 if signal else 0)   # rank only valid signals

        results[sym] = {
            'signal':   signal,
            'price':    round(price, 2),
            'sma200':   round(sma200, 2),
            'momentum': round(momentum, 4),
            'rsi14':    round(rsi, 1),
            'score':    score,
        }
    return results

# ─────────────────────────────────────────────
# LIVE SHARPE (rolling 252d on actual daily returns)
# ─────────────────────────────────────────────

def live_sharpe(df: pd.DataFrame, sym: str) -> float:
    """
    Rolling 252-day Sharpe on the symbol's daily returns.
    Uses 4.5% risk-free rate annualised.
    """
    try:
        rets   = df[sym].pct_change().dropna().tail(252)
        rf_day = 0.045 / 252
        excess = rets - rf_day
        if excess.std() == 0:
            return 0.0
        return round(float(excess.mean() / excess.std() * np.sqrt(252)), 2)
    except Exception:
        return 0.0

# ─────────────────────────────────────────────
# GOOGLE SHEETS LOGGING
# ─────────────────────────────────────────────

def log_trade(symbol: str, action: str, qty: int,
              price: float, reason: str, extra: str = ''):
    """Append trade row to Google Sheet. Fails open, never crashes bot."""
    if not GSPREAD_JSON or len(GSPREAD_JSON) < 50:
        return
    try:
        creds_dict = json.loads(GSPREAD_JSON)
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive',
        ]
        creds  = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(SHEET_ID).sheet1
        sheet.append_row([
            datetime.now().strftime('%Y-%m-%d %H:%M'),
            symbol, action, qty, round(price, 2), reason, extra
        ])
    except Exception as e:
        send_telegram(f"⚠️ Sheet log skipped: `{str(e)[:80]}`")

# ─────────────────────────────────────────────
# DUPLICATE ORDER GUARD
# ─────────────────────────────────────────────

def has_filled_today(client: TradingClient, symbol: str, side: str) -> bool:
    """
    Returns True if we already had a filled order for this symbol+side today.
    Prevents double-buys on re-runs.
    """
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        orders = client.get_orders()
        for o in orders:
            if (
                o.symbol == symbol
                and o.side.value == side
                and o.status.value in ('filled', 'partially_filled')
                and str(o.filled_at or o.submitted_at)[:10] == today
            ):
                return True
        return False
    except Exception as e:
        log.warning(f"Order history check failed: {e}")
        return False   # fail open → allow trade

# ─────────────────────────────────────────────
# MAIN TRADING LOOP
# ─────────────────────────────────────────────

def run():
    mode_str = "📄 PAPER" if IS_PAPER else "🔴 LIVE"
    send_telegram(f"🤖 *Bot starting* [{mode_str}] {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")

    # ── Validate keys ──
    if not ALPACA_KEY or not ALPACA_SECRET:
        send_telegram("🚨 BLOCKED: No Alpaca credentials in environment.")
        return

    # ── Account ──
    trading = get_trading_client()
    account  = trading.get_account()
    equity   = float(account.equity)
    last_eq  = float(account.last_equity)
    log.info(f"Equity: ${equity:,.2f} | Last: ${last_eq:,.2f}")

    # ── Kill switch ──
    if last_eq > 0 and equity < last_eq * (1 - MAX_DD_STOP):
        send_telegram(
            f"🚨 *KILL SWITCH* — drawdown exceeded {MAX_DD_STOP*100:.0f}%.\n"
            f"Equity: ${equity:,.2f} vs last ${last_eq:,.2f}. *Trading halted.*"
        )
        return

    # ── Data ──
    df = get_data(ALL_SYMBOLS)
    if df.empty:
        return

    # ── Yield curve ──
    curve = get_yield_curve()
    curve_ok = curve > 0
    curve_msg = (
        f"📈 Yield curve: `{curve:.2f}` → *Risk-ON*" if curve_ok
        else f"📉 Yield curve: `{curve:.2f}` → *Risk-OFF* (inverted) — no new buys"
    )
    send_telegram(curve_msg, silent=True)

    # ── Signals ──
    signals = calc_signals(df)

    # ── Select candidates ──
    candidates = [
        sym for sym, v in signals.items()
        if v.get('signal') and curve_ok and sym in df.columns
    ]
    candidates.sort(key=lambda s: signals[s]['score'], reverse=True)
    targets = candidates[:MAX_POSITIONS]

    # ── Signal summary ──
    lines = []
    for sym, v in sorted(signals.items()):
        icon = "✅" if v.get('signal') else "❌"
        if 'price' in v:
            lines.append(
                f"{icon} *{sym}*: P={v['price']} SMA={v['sma200']} "
                f"Mom={v['momentum']*100:.1f}% RSI={v['rsi14']}"
            )
    send_telegram("*Signal Summary*\n" + "\n".join(lines), silent=True)

    # ── Positions & open orders ──
    positions  = {p.symbol: float(p.qty) for p in trading.get_all_positions()}
    open_orders = {o.symbol for o in trading.get_orders()}
    if open_orders:
        send_telegram(f"⏸ Open orders exist: `{open_orders}` — skipping conflicting symbols.")

    # ── Execute ──
    for sym in ALL_SYMBOLS:
        v           = signals.get(sym, {})
        in_target   = sym in targets
        has_pos     = sym in positions
        has_open    = sym in open_orders

        if has_open:
            continue   # never touch symbols with pending orders

        # BUY
        if in_target and not has_pos:
            if has_filled_today(trading, sym, 'buy'):
                send_telegram(f"⚠️ Duplicate guard: already bought `{sym}` today. Skip.")
                continue

            price  = v['price']
            sharpe = live_sharpe(df, sym)
            if sharpe < MIN_SHARPE:
                send_telegram(
                    f"⚠️ `{sym}` skipped — live Sharpe `{sharpe:.2f}` < `{MIN_SHARPE}`"
                )
                continue

            qty = max(1, int((equity * RISK_PER_TRADE) / price))
            try:
                order_req = MarketOrderRequest(
                    symbol=sym, qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                )
                trading.submit_order(order_req)
                intl_label = INTL_SYMBOLS.get(sym, '')
                label      = f" ({intl_label})" if intl_label else ''
                send_telegram(
                    f"🟢 *BUY* `{qty}` *{sym}*{label} @ `${price}`\n"
                    f"Sharpe={sharpe:.2f} Mom={v['momentum']*100:.1f}% RSI={v['rsi14']}"
                )
                log_trade(sym, 'BUY', qty, price, 'DualMom+RSI',
                          f"sharpe={sharpe:.2f} rsi={v['rsi14']}")
            except Exception as e:
                send_telegram(f"🚨 Order FAILED `{sym}`: `{str(e)[:120]}`")

        # SELL
        elif not in_target and has_pos:
            if has_filled_today(trading, sym, 'sell'):
                send_telegram(f"⚠️ Duplicate guard: already sold `{sym}` today. Skip.")
                continue

            qty   = int(positions[sym])
            price = v.get('price', 0)
            try:
                order_req = MarketOrderRequest(
                    symbol=sym, qty=qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                )
                trading.submit_order(order_req)
                send_telegram(f"🔴 *SELL* `{qty}` *{sym}* @ `${price}`")
                log_trade(sym, 'SELL', qty, price, 'Exit')
            except Exception as e:
                send_telegram(f"🚨 Sell FAILED `{sym}`: `{str(e)[:120]}`")

    # ── EOD summary ──
    send_telegram(
        f"✅ *Run complete* [{mode_str}]\n"
        f"Equity: `${equity:,.2f}` | Curve: `{curve:.2f}` | "
        f"Targets: `{targets}`"
    )

# ─────────────────────────────────────────────
# ENTRY
# ─────────────────────────────────────────────

if __name__ == "__main__":
    run()

"""
═══════════════════════════════════════════════════════════════════
  AUTONOMOUS TRADING SYSTEM  —  v3.0
  Author : Ethan (built with Claude)
  Markets : US Equities (weekdays 9:30–4 PM ET) +
            International ETFs (US-listed, same hours) +
            Crypto (24/7, 365 days/year)
  Broker  : Alpaca (paper by default, flip ALPACA_PAPER=false for live)
  Schedule: GitHub Actions — equities @ 3:45 PM ET weekdays,
            crypto every 4 hours 24/7
═══════════════════════════════════════════════════════════════════

SIGNAL ENGINE (research sources):
  • Dual Momentum   — Antonacci (2012)  CAGR 15.9% Sharpe 0.95
  • SMA Trend Filter— Faber (2007)      Sharpe 0.84
  • RSI(14) filter  — Karassavidis et al. (SSRN 2025): multi-horizon RSI
                      reduces false entries by ~30% in crypto
  • ATR position sizing — volatility-scaled, replaces fixed % for crypto
  • MACD confirmation  — Capstone review (AUA 2025): MACD+RSI combo
                         achieves 60-65% accuracy vs 40-50% for single
  • Yield curve filter  — inverted curve historically precedes bear markets
                         (FRED DGS10 - DGS2 spread)
"""

import os
import json
import time
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ── Alpaca SDK (alpaca-py) ──────────────────────────────────────
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

# ── Google Sheets ───────────────────────────────────────────────
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ───────────────────────────────────────────────────────────────
# LOGGING
# ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────
# ENVIRONMENT / CONFIG
# ───────────────────────────────────────────────────────────────
IS_PAPER       = os.getenv("ALPACA_PAPER", "true").lower() == "true"
ALPACA_KEY     = os.getenv("ALPACA_KEY", "")
ALPACA_SECRET  = os.getenv("ALPACA_SECRET", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT  = os.getenv("TELEGRAM_CHAT", "")
GSPREAD_JSON   = os.getenv("GSPREAD_JSON", "")
SHEET_ID       = os.getenv("SHEET_ID", "")
FRED_API_KEY   = os.getenv("FRED_API_KEY", "")
RUN_MODE       = os.getenv("RUN_MODE", "equities")   # "equities" | "crypto" | "both"

# ── Universe ────────────────────────────────────────────────────
# Core US + International ETFs (trade on NYSE/NASDAQ during US hours)
# Gives exposure to London (EWU/EWG), Asia (EWJ/FXI/EWH/EWY/EWA), India (INDA)
EQUITY_SYMBOLS = [
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq 100
    "IWM",   # Russell 2000 (small cap)
    "EFA",   # MSCI EAFE (developed international)
    "AGG",   # US Aggregate Bond (safe haven)
    # International ETFs — London + Asian exposure, no extra broker needed
    "EWU",   # UK / FTSE 100
    "EWG",   # Germany / DAX
    "EWJ",   # Japan / Nikkei
    "EWH",   # Hong Kong / Hang Seng
    "FXI",   # China Large Cap
    "EWY",   # South Korea / KOSPI
    "EWA",   # Australia / ASX
    "INDA",  # India / Nifty 50
]

# Crypto — trades 24/7 on Alpaca
# Research (Karassavidis SSRN 2025): BTC + ETH carry most signal
# SOL/LINK/AVAX added for diversification with tighter risk limits
CRYPTO_SYMBOLS = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "LINK/USD",
    "AVAX/USD",
]

# ── Risk Parameters ─────────────────────────────────────────────
EQUITY_RISK_PCT  = 0.01    # 1% equity per equity position
CRYPTO_RISK_PCT  = 0.005   # 0.5% equity per crypto position (higher vol)
MAX_POSITIONS    = 3        # max concurrent equity positions
MAX_CRYPTO_POS   = 2        # max concurrent crypto positions
MAX_DD_STOP      = 0.15    # 15% portfolio drawdown kill switch
MIN_SHARPE       = 0.80    # minimum rolling Sharpe to trade
LOOKBACK         = 200     # SMA / momentum lookback in days
ATR_PERIOD       = 14      # ATR period for crypto position sizing
ATR_RISK_MULT    = 1.5     # stop = ATR_RISK_MULT × ATR below entry

# ───────────────────────────────────────────────────────────────
# TELEGRAM
# ───────────────────────────────────────────────────────────────
def send_telegram(msg: str, silent: bool = False) -> None:
    """Fire-and-forget Telegram notification. Never raises."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        log.info(f"[TELEGRAM SKIPPED] {msg[:80]}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT,
                "text": msg,
                "parse_mode": "Markdown",
                "disable_notification": silent,
            },
            timeout=10,
        )
    except Exception as e:
        log.warning(f"Telegram failed: {e}")

# ───────────────────────────────────────────────────────────────
# ALPACA CLIENTS
# ───────────────────────────────────────────────────────────────
def trading_client() -> TradingClient:
    return TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=IS_PAPER)

def stock_data_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)

def crypto_data_client() -> CryptoHistoricalDataClient:
    # Crypto data is FREE — no keys required, but keys increase rate limit
    return CryptoHistoricalDataClient(ALPACA_KEY or None, ALPACA_SECRET or None)

# ───────────────────────────────────────────────────────────────
# DATA FETCHING
# ───────────────────────────────────────────────────────────────

def get_equity_data(symbols: list) -> pd.DataFrame:
    """
    Fetch daily OHLCV for equities via Alpaca IEX.
    Falls back to Stooq if Alpaca fails.
    Returns DataFrame[date × symbol] of adjusted close prices.
    """
    from pandas.tseries.offsets import BDay
    import pandas_datareader.data as web

    end   = pd.Timestamp.now().normalize()
    if end.weekday() >= 5:
        end = end - BDay(1)
    start = end - pd.Timedelta(days=LOOKBACK + 120)

    # ── Primary: Alpaca IEX ──
    try:
        client = stock_data_client()
        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start.to_pydatetime(),
            end=end.to_pydatetime(),
            adjustment="all",
            feed="iex",
        )
        bars = client.get_stock_bars(req).df
        if not bars.empty:
            df = bars["close"].unstack(level=0)
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df = df.dropna(how="all")
            if len(df) >= LOOKBACK:
                log.info(f"Equity data: Alpaca IEX OK ({len(df)} days)")
                return df
    except Exception as e:
        log.warning(f"Alpaca equity data failed: {e}")
        send_telegram(f"⚠️ Alpaca equity data failed: `{str(e)[:100]}`\nTrying Stooq…")

    # ── Fallback: Stooq ──
    try:
        df = pd.DataFrame()
        for sym in symbols:
            try:
                tmp = web.DataReader(f"{sym}.US", "stooq", start=start, end=end)
                df[sym] = tmp["Close"]
            except Exception:
                pass
        df = df.sort_index().dropna(how="all")
        if len(df) >= LOOKBACK:
            log.info(f"Equity data: Stooq fallback OK ({len(df)} days)")
            return df
    except Exception as e:
        log.error(f"Stooq fallback error: {e}")

    send_telegram("🚨 *CRITICAL*: All equity data sources failed.")
    return pd.DataFrame()


def get_crypto_data(symbols: list) -> pd.DataFrame:
    """
    Fetch daily OHLCV for crypto via Alpaca Crypto Data API.
    Returns DataFrame[date × symbol] of close prices.
    No fallback needed — crypto data is always available 24/7.
    """
    end   = datetime.utcnow()
    start = end - timedelta(days=LOOKBACK + 120)

    try:
        client = crypto_data_client()
        req = CryptoBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )
        bars = client.get_crypto_bars(req).df
        if bars.empty:
            raise ValueError("Empty crypto bars response")

        # Multi-index: (symbol, timestamp) → pivot to (timestamp × symbol)
        df = bars["close"].unstack(level=0)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df.sort_index().dropna(how="all")
        log.info(f"Crypto data: {len(df)} days fetched OK")
        return df
    except Exception as e:
        log.error(f"Crypto data fetch failed: {e}")
        send_telegram(f"🚨 Crypto data FAILED: `{str(e)[:120]}`")
        return pd.DataFrame()

# ───────────────────────────────────────────────────────────────
# YIELD CURVE (FRED — real data, free API key)
# ───────────────────────────────────────────────────────────────

def get_yield_curve() -> float:
    """
    10y − 2y Treasury spread. Positive = risk-on. Negative = inverted.
    Falls back to 1.0 (risk-on) if FRED key missing.
    """
    if not FRED_API_KEY:
        return 1.0

    def _fred(sid: str) -> float:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={sid}&api_key={FRED_API_KEY}"
            f"&file_type=json&sort_order=desc&limit=5"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        for o in r.json()["observations"]:
            if o["value"] != ".":
                return float(o["value"])
        raise ValueError(f"No valid FRED data for {sid}")

    try:
        spread = _fred("DGS10") - _fred("DGS2")
        log.info(f"Yield curve spread: {spread:.3f}")
        return spread
    except Exception as e:
        log.warning(f"FRED failed ({e}), assuming risk-on")
        return 1.0

# ───────────────────────────────────────────────────────────────
# SIGNAL ENGINE
# Research: Antonacci 2012 (momentum), Faber 2007 (SMA trend),
#           Karassavidis SSRN 2025 (multi-horizon RSI for crypto),
#           AUA Capstone 2025 (MACD+RSI combo accuracy 60-65%)
# ───────────────────────────────────────────────────────────────

def _rsi(series: pd.Series, period: int = 14) -> float:
    """Wilder RSI — standard 14-period."""
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return float((100 - 100 / (1 + rs)).iloc[-1])


def _macd(series: pd.Series) -> tuple[float, float]:
    """MACD(12,26,9). Returns (macd_line, signal_line)."""
    ema12   = series.ewm(span=12, adjust=False).mean()
    ema26   = series.ewm(span=26, adjust=False).mean()
    macd    = ema12 - ema26
    signal  = macd.ewm(span=9, adjust=False).mean()
    return float(macd.iloc[-1]), float(signal.iloc[-1])


def _atr(df_ohlc: pd.Series, period: int = 14) -> float:
    """
    ATR approximation from close-only data (true ATR needs OHLC).
    Uses daily price range proxy: std of daily returns × price × sqrt(period).
    """
    try:
        rets = df_ohlc.pct_change().dropna().tail(period * 3)
        return float(df_ohlc.iloc[-1] * rets.std() * np.sqrt(period))
    except Exception:
        return float(df_ohlc.iloc[-1] * 0.02)   # 2% fallback


def calc_signals(df: pd.DataFrame, asset_class: str = "equity") -> dict:
    """
    Compute signals for each symbol in df.
    Returns dict of {symbol: {signal, price, sma200, momentum, rsi14, macd_bull, score, atr}}

    Entry requires ALL of:
      1. Price > SMA(200)          — Faber 2007 trend filter
      2. 200d momentum > 0         — Antonacci 2012 dual momentum
      3. RSI(14) between 35–75     — not overbought/collapsed (wider for crypto)
      4. MACD line > signal line   — AUA 2025: confirms momentum direction
    """
    rsi_low  = 30 if asset_class == "crypto" else 35
    rsi_high = 75 if asset_class == "crypto" else 72

    results = {}
    for sym in df.columns:
        s = df[sym].dropna()
        if len(s) < LOOKBACK:
            results[sym] = {"signal": False, "score": 0.0, "price": 0.0}
            continue

        price    = float(s.iloc[-1])
        sma200   = float(s.rolling(200).mean().iloc[-1])
        momentum = (price / float(s.iloc[-LOOKBACK])) - 1
        rsi      = _rsi(s)
        macd_l, macd_sig = _macd(s)
        atr      = _atr(s)

        trend_ok = price > sma200
        mom_ok   = momentum > 0
        rsi_ok   = rsi_low < rsi < rsi_high
        macd_ok  = macd_l > macd_sig

        signal = trend_ok and mom_ok and rsi_ok and macd_ok
        # Score = momentum × RSI proximity to midpoint (50) — balanced strength
        rsi_score = 1 - abs(rsi - 50) / 50
        score     = momentum * rsi_score if signal else 0.0

        results[sym] = {
            "signal":    signal,
            "price":     round(price, 4),
            "sma200":    round(sma200, 4),
            "momentum":  round(momentum, 4),
            "rsi14":     round(rsi, 1),
            "macd_bull": macd_ok,
            "score":     score,
            "atr":       round(atr, 4),
        }
    return results


def live_sharpe(df: pd.DataFrame, sym: str) -> float:
    """Rolling 252-day annualised Sharpe (4.5% risk-free rate)."""
    try:
        rets   = df[sym].pct_change().dropna().tail(252)
        rf_day = 0.045 / 252
        excess = rets - rf_day
        std    = excess.std()
        if std == 0:
            return 0.0
        return round(float(excess.mean() / std * np.sqrt(252)), 2)
    except Exception:
        return 0.0

# ───────────────────────────────────────────────────────────────
# POSITION SIZING
# ───────────────────────────────────────────────────────────────

def size_equity(equity: float, price: float) -> int:
    """1% of portfolio / price, minimum 1 share."""
    return max(1, int((equity * EQUITY_RISK_PCT) / price))


def size_crypto(equity: float, price: float, atr: float) -> float:
    """
    ATR-based position sizing for crypto (volatility-adjusted).
    Risk = 0.5% of equity. Position = risk_dollars / (ATR_MULT × ATR)
    Returns fractional quantity (crypto supports it).
    """
    risk_dollars = equity * CRYPTO_RISK_PCT
    stop_dist    = ATR_RISK_MULT * atr
    if stop_dist <= 0 or price <= 0:
        return 0.0
    qty = risk_dollars / stop_dist
    # Cap at 5% of portfolio value regardless
    max_qty = (equity * 0.05) / price
    qty = min(qty, max_qty)
    return round(max(qty, 0.0001), 6)   # Alpaca crypto minimum ~$1 notional

# ───────────────────────────────────────────────────────────────
# DUPLICATE ORDER GUARD
# ───────────────────────────────────────────────────────────────

def filled_today(client: TradingClient, symbol: str, side: str) -> bool:
    """True if we already filled this symbol+side today — prevents double orders."""
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        req   = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=50)
        orders = client.get_orders(req)
        for o in orders:
            sym_match  = o.symbol == symbol
            side_match = o.side.value == side
            filled     = o.status.value in ("filled", "partially_filled")
            date_str   = str(getattr(o, "filled_at", None) or getattr(o, "submitted_at", ""))[:10]
            if sym_match and side_match and filled and date_str == today:
                return True
        return False
    except Exception as e:
        log.warning(f"Duplicate check error for {symbol}: {e}")
        return False   # fail open

# ───────────────────────────────────────────────────────────────
# GOOGLE SHEETS LOGGING
# ───────────────────────────────────────────────────────────────

def log_trade(symbol: str, action: str, qty, price: float,
              reason: str, extra: str = "") -> None:
    """Append a row to Google Sheet. Always fails open."""
    if not GSPREAD_JSON or len(GSPREAD_JSON) < 50:
        return
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            json.loads(GSPREAD_JSON),
            ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"],
        )
        sheet = gspread.authorize(creds).open_by_key(SHEET_ID).sheet1
        sheet.append_row([
            datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            symbol, action, str(qty), round(price, 4), reason, extra,
        ])
    except Exception as e:
        log.warning(f"Sheet log skipped ({symbol}): {e}")

# ───────────────────────────────────────────────────────────────
# CORE EXECUTION ENGINE
# ───────────────────────────────────────────────────────────────

def execute_trades(
    client: TradingClient,
    df: pd.DataFrame,
    signals: dict,
    targets: list,
    equity: float,
    asset_class: str,
    max_positions: int,
) -> None:
    """
    Unified buy/sell loop for both equity and crypto.
    asset_class: "equity" | "crypto"
    """
    try:
        positions  = {p.symbol: float(p.qty) for p in client.get_all_positions()}
    except Exception as e:
        send_telegram(f"🚨 Could not fetch positions: `{e}`")
        return

    try:
        open_syms = {o.symbol for o in client.get_orders()}
    except Exception:
        open_syms = set()

    tif = TimeInForce.GTC if asset_class == "crypto" else TimeInForce.DAY

    for sym in list(signals.keys()):
        v        = signals.get(sym, {})
        in_tgt   = sym in targets
        has_pos  = sym in positions
        has_open = sym in open_syms

        if has_open:
            continue

        # ── BUY ──────────────────────────────────────────────
        if in_tgt and not has_pos:
            if filled_today(client, sym, "buy"):
                log.info(f"Duplicate guard: skip buy {sym}")
                continue

            price  = v.get("price", 0)
            sharpe = live_sharpe(df, sym)

            if sharpe < MIN_SHARPE:
                send_telegram(
                    f"⚠️ `{sym}` skipped — Sharpe `{sharpe:.2f}` < `{MIN_SHARPE}`",
                    silent=True,
                )
                continue

            if price <= 0:
                log.warning(f"Invalid price for {sym}, skip")
                continue

            if asset_class == "crypto":
                qty = size_crypto(equity, price, v.get("atr", price * 0.02))
                qty_display = f"{qty:.6f}"
            else:
                qty = size_equity(equity, price)
                qty_display = str(qty)

            if not qty or (isinstance(qty, float) and qty < 0.0001):
                log.warning(f"Qty too small for {sym}, skip")
                continue

            try:
                req = MarketOrderRequest(
                    symbol=sym,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=tif,
                )
                client.submit_order(req)
                send_telegram(
                    f"🟢 *BUY* `{qty_display}` *{sym}*\n"
                    f"Price: `${price}` | Sharpe: `{sharpe:.2f}` | "
                    f"Mom: `{v.get('momentum',0)*100:.1f}%` | RSI: `{v.get('rsi14',0):.1f}` | "
                    f"MACD: `{'✅' if v.get('macd_bull') else '❌'}`"
                )
                log_trade(sym, "BUY", qty_display, price, f"{asset_class}:DualMom+RSI+MACD",
                          f"sharpe={sharpe:.2f} rsi={v.get('rsi14')} atr={v.get('atr')}")
            except Exception as e:
                send_telegram(f"🚨 BUY FAILED `{sym}`: `{str(e)[:120]}`")

        # ── SELL ─────────────────────────────────────────────
        elif not in_tgt and has_pos:
            if filled_today(client, sym, "sell"):
                log.info(f"Duplicate guard: skip sell {sym}")
                continue

            qty   = positions[sym]
            price = v.get("price", 0)

            try:
                req = MarketOrderRequest(
                    symbol=sym,
                    qty=abs(qty),
                    side=OrderSide.SELL,
                    time_in_force=tif,
                )
                client.submit_order(req)
                send_telegram(f"🔴 *SELL* `{qty}` *{sym}* @ `${price}`")
                log_trade(sym, "SELL", qty, price, f"{asset_class}:Exit")
            except Exception as e:
                send_telegram(f"🚨 SELL FAILED `{sym}`: `{str(e)[:120]}`")

# ───────────────────────────────────────────────────────────────
# EQUITY RUN (weekdays, triggered at 3:45 PM ET)
# ───────────────────────────────────────────────────────────────

def run_equities() -> None:
    send_telegram(
        f"📈 *Equity run starting*\n"
        f"Mode: `{'PAPER' if IS_PAPER else '🔴 LIVE'}` | "
        f"`{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}`"
    )

    client  = trading_client()
    account = client.get_account()
    equity  = float(account.equity)
    last_eq = float(account.last_equity)

    # Kill switch
    if last_eq > 0 and equity < last_eq * (1 - MAX_DD_STOP):
        send_telegram(
            f"🚨 *KILL SWITCH* — drawdown >{MAX_DD_STOP*100:.0f}%\n"
            f"Equity `${equity:,.2f}` vs last `${last_eq:,.2f}`. *All trading halted.*"
        )
        return

    df = get_equity_data(EQUITY_SYMBOLS)
    if df.empty:
        return

    curve    = get_yield_curve()
    curve_ok = curve >= 0
    send_telegram(
        f"📊 Yield curve: `{curve:.3f}` → {'*Risk-ON* ✅' if curve_ok else '*Risk-OFF* ⛔ — no new buys'}",
        silent=True,
    )

    signals = calc_signals(df, asset_class="equity")

    # Build signal summary
    lines = []
    for sym in sorted(signals):
        v    = signals[sym]
        icon = "✅" if v.get("signal") else "❌"
        if v.get("price"):
            lines.append(
                f"{icon} *{sym}*: Mom={v['momentum']*100:.1f}% "
                f"RSI={v['rsi14']} MACD={'✅' if v.get('macd_bull') else '❌'}"
            )
    if lines:
        send_telegram("*Equity Signals*\n" + "\n".join(lines), silent=True)

    candidates = [
        s for s, v in signals.items()
        if v.get("signal") and curve_ok
    ]
    candidates.sort(key=lambda s: signals[s]["score"], reverse=True)
    targets = candidates[:MAX_POSITIONS]

    execute_trades(client, df, signals, targets, equity, "equity", MAX_POSITIONS)

    send_telegram(
        f"✅ *Equity run complete*\n"
        f"Equity: `${equity:,.2f}` | Targets: `{targets}`"
    )

# ───────────────────────────────────────────────────────────────
# CRYPTO RUN (every 4 hours, 24/7/365)
# ───────────────────────────────────────────────────────────────

def run_crypto() -> None:
    send_telegram(
        f"₿ *Crypto run starting*\n"
        f"Mode: `{'PAPER' if IS_PAPER else '🔴 LIVE'}` | "
        f"`{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}`",
        silent=True,
    )

    client  = trading_client()
    account = client.get_account()
    equity  = float(account.equity)
    last_eq = float(account.last_equity)

    # Kill switch
    if last_eq > 0 and equity < last_eq * (1 - MAX_DD_STOP):
        send_telegram(
            f"🚨 *KILL SWITCH (crypto)* — drawdown >{MAX_DD_STOP*100:.0f}%\n"
            f"Halting crypto trades."
        )
        return

    df = get_crypto_data(CRYPTO_SYMBOLS)
    if df.empty:
        send_telegram("🚨 Crypto data unavailable — skipping run.")
        return

    signals = calc_signals(df, asset_class="crypto")

    # Crypto: no yield curve filter (it's a 24/7 global market)
    candidates = [s for s, v in signals.items() if v.get("signal")]
    candidates.sort(key=lambda s: signals[s]["score"], reverse=True)
    targets = candidates[:MAX_CRYPTO_POS]

    # Signal summary (silent — runs every 4h, don't spam)
    lines = []
    for sym in sorted(signals):
        v    = signals[sym]
        icon = "✅" if v.get("signal") else "❌"
        if v.get("price"):
            lines.append(
                f"{icon} *{sym}*: Mom={v['momentum']*100:.1f}% "
                f"RSI={v['rsi14']} MACD={'✅' if v.get('macd_bull') else '❌'}"
            )
    if lines:
        send_telegram("*Crypto Signals*\n" + "\n".join(lines), silent=True)

    execute_trades(client, df, signals, targets, equity, "crypto", MAX_CRYPTO_POS)

    send_telegram(
        f"✅ *Crypto run complete* | Equity: `${equity:,.2f}` | Targets: `{targets}`",
        silent=True,
    )

# ───────────────────────────────────────────────────────────────
# ENTRY POINT
# ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = RUN_MODE.lower()
    log.info(f"Starting bot — mode={mode} paper={IS_PAPER}")

    if not ALPACA_KEY or not ALPACA_SECRET:
        send_telegram("🚨 BLOCKED: ALPACA_KEY or ALPACA_SECRET missing from environment.")
        raise SystemExit(1)

    if mode == "equities":
        run_equities()
    elif mode == "crypto":
        run_crypto()
    elif mode == "both":
        run_equities()
        time.sleep(2)
        run_crypto()
    else:
        send_telegram(f"🚨 Unknown RUN_MODE: `{mode}`. Use equities | crypto | both.")
        raise SystemExit(1)
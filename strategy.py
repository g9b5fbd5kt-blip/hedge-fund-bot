import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

@dataclass
class Signal:
    symbol: str
    direction: str
    score: float
    price: float
    atr: float
    setup_type: str
    regime: str
    reasons: list

def analyze_symbol(symbol, is_crypto, clients):
    try:
        from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        def get_bars(tf_amount, tf_unit, limit):
            tf = TimeFrame(tf_amount, tf_unit)
            if is_crypto:
                req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf, limit=limit)
                df = clients["crypto"].get_crypto_bars(req).df
            else:
                req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, limit=limit)
                df = clients["stock"].get_stock_bars(req).df
            if 'symbol' in df.columns:
                df = df.xs(symbol, level='symbol')
            return df

        df5 = get_bars(5, TimeFrameUnit.Minute, 100)
        df1h = get_bars(1, TimeFrameUnit.Hour, 100)
        df4h = get_bars(4, TimeFrameUnit.Hour, 60)

        if len(df5) < 30:
            return None

        c5, c1, c4 = df5['close'], df1h['close'], df4h['close']
        ema9_5 = c5.ewm(9).mean().iloc[-1]
        ema21_5 = c5.ewm(21).mean().iloc[-1]
        ema21_4 = c4.ewm(21).mean().iloc[-1]
        ema50_4 = c4.ewm(50).mean().iloc[-1]

        tr = pd.concat([
            df5['high'] - df5['low'],
            (df5['high'] - c5.shift()).abs(),
            (df5['low'] - c5.shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.ewm(14).mean().iloc[-1]

        score, reasons = 0, []
        if c4.iloc[-1] > ema21_4 > ema50_4:
            score += 3
            reasons.append("4h_up")
        if c1.iloc[-1] > c1.ewm(21).mean().iloc[-1]:
            score += 2
            reasons.append("1h_up")
        if ema9_5 > ema21_5:
            score += 2
            reasons.append("5m_up")
        if c5.iloc[-1] > df5['close'].rolling(20).mean().iloc[-1]:
            score += 1
            reasons.append("above_vwap")

        rsi = 100 - (100 / (1 + c5.diff().clip(lower=0).ewm(14).mean() / (-c5.diff().clip(upper=0).ewm(14).mean()).replace(0, 0.001)))
        if 40 < rsi.iloc[-1] < 65:
            score += 1
            reasons.append("rsi_ok")

        regime = "trending" if score >= 6 else "ranging"
        setup = "trend_follow" if "4h_up" in reasons else "breakout"

        return Signal(
            symbol,
            "BUY" if score >= 5.5 else "HOLD",
            score,
            float(c5.iloc[-1]),
            float(atr),
            setup,
            regime,
            reasons
        )
    except:
        return None

def analyze_all(symbols, is_crypto_map, clients):
    signals = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(analyze_symbol, s, is_crypto_map[s], clients): s for s in symbols}
        for f in as_completed(futures):
            sig = f.result()
            if sig and sig.direction == "BUY":
                signals.append(sig)
    return sorted(signals, key=lambda x: x.score, reverse=True)

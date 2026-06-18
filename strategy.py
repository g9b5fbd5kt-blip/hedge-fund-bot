def analyze_data(data):
    signals = {}
    stocks = data.get('stocks', {}).get('bars', {})
    # Add everything you want to trade during market hours
    for symbol in ['NVDA', 'QQQ', 'SPY', 'AAPL', 'TSLA', 'MSFT', 'AMD']:
        bars = stocks.get(symbol, [])
        signals[symbol] = simple_breakout(bars)
    
    crypto = data.get('crypto', {}).get('bars', {})
    # Alpaca crypto trades 24/7 — this is your true 24/7 engine
    for symbol in ['BTC/USD', 'ETH/USD', 'LTC/USD', 'DOGE/USD', 'SOL/USD']:
        bars = crypto.get(symbol, [])
        signals[symbol] = simple_breakout(bars)
    return signals
import aiohttp, asyncio, time, os
from async_lru import alru_cache

class RateLimiter:
    def __init__(self, max_calls=180, window=60):
        self.max_calls = max_calls
        self.window = window
        self.calls = []
    
    async def acquire(self):
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.window]
        if len(self.calls) >= self.max_calls:
            await asyncio.sleep(self.window - (now - self.calls[0]) + 0.1)
        self.calls.append(time.time())

limiter = RateLimiter()

HEADERS = {
    "APCA-API-KEY-ID": os.getenv("APCA_API_KEY_ID", ""),
    "APCA-API-SECRET-KEY": os.getenv("APCA_API_SECRET_KEY", "")
}

@alru_cache(maxsize=128, ttl=25)
async def fetch_bars(session, url):
    await limiter.acquire()
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=8)) as r:
        return await r.json()

async def get_all_data():
    connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with asyncio.TaskGroup() as tg:
            tasks = {}
            stocks_url = "https://data.alpaca.markets/v2/stocks/bars?symbols=NVDA,QQQ&timeframe=15Min&limit=20"
            tasks['stocks'] = tg.create_task(fetch_bars(session, stocks_url))
            crypto_url = "https://data.alpaca.markets/v1beta3/crypto/us/bars?symbols=BTC/USD,ETH/USD&timeframe=15Min&limit=20"
            tasks['crypto'] = tg.create_task(fetch_bars(session, crypto_url))
            account_url = "https://paper-api.alpaca.markets/v2/account"
            tasks['account'] = tg.create_task(fetch_bars(session, account_url))
            positions_url = "https://paper-api.alpaca.markets/v2/positions"
            tasks['positions'] = tg.create_task(fetch_bars(session, positions_url))
        
        return {k: t.result() for k, t in tasks.items()}

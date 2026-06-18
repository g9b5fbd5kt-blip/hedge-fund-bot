#!/usr/bin/env python3
import asyncio, aiohttp, os, json
from data_fetcher import get_all_data
from risk_orchestrator import RiskOrchestrator
from strategy import analyze_data
from telegram_bot import send_telegram, format_message

async def execute_trade(session, symbol, side, qty):
    url = "https://paper-api.alpaca.markets/v2/orders"
    headers = {
        "APCA-API-KEY-ID": os.getenv("APCA_API_KEY_ID"),
        "APCA-API-SECRET-KEY": os.getenv("APCA_API_SECRET_KEY"),
        "Content-Type": "application/json"
    }
    order = {
        "symbol": symbol.replace("/USD", ""),
        "qty": str(qty),
        "side": side.lower(),
        "type": "market",
        "time_in_force": "day"
    }
    try:
        async with session.post(url, headers=headers, json=order) as r:
            return await r.json()
    except Exception as e:
        return {"error": str(e)}

async def main():
    print("Starting v9.2 bot...")
    data = await get_all_data()
    account = data.get('account', {})
    positions = data.get('positions', [])
    
    risk = RiskOrchestrator(account, positions)
    signals = analyze_data(data)
    
    actions = []
    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        for symbol, (signal, price) in signals.items():
            if signal in ["BUY", "SELL"]:
                can_trade, reason = risk.can_trade(symbol, signal)
                if can_trade:
                    size = risk.position_size(symbol)
                    qty = round(size / price, 6) if "USD" in symbol else int(size / price)
                    if qty > 0:
                        result = await execute_trade(session, symbol, signal, qty)
                        if "id" in result:
                            actions.append(f"{signal} {qty} {symbol} @ ${price:.2f}")
                else:
                    actions.append(f"SKIP {symbol}: {reason}")
        
        message = format_message(account, positions, signals, actions)
        await send_telegram(session, message)
    
    print("Bot run complete")

if __name__ == "__main__":
    asyncio.run(main())
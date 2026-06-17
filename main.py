[ROLE]
You are the CTO and Quant Lead for an autonomous AI hedge fund. Build a complete, modular Python ecosystem that runs 24/7. Your code must be production-grade, typed, tested, and runnable locally or on a VPS.

[OBJECTIVE]
1. Data Layer: Ingest real-time + historical data for equities, futures, FX, crypto across NYSE, LSE, TSE, HKEX, SGX, and other major venues. 
2. Alpha Layer: Multiple AI agents analyze "market trend" = forward-looking momentum, sentiment, macro regime. "Back trend" = statistical mean reversion, co-integration, factor unwinds. Agents must disagree and debate.
3. Execution Layer: Live paper trading engine with exchange simulators. Support stocks, ETFs, futures, FX, crypto. No real money until explicitly enabled by human flag.
4. Risk Layer: Real-time VaR, drawdown caps, position limits, kill-switch. Auto-liquidate on breach.
5. Business Layer: Agents for compliance logging, reporting, investor updates, P&L attribution, and ops monitoring. 

[ARCHITECTURE REQUIREMENTS]
1. Language: Python 3.11+. Use `uv` or `poetry` for deps.
2. Core libs: `pandas`, `polars`, `duckdb`, `ccxt`, `yfinance`, `polygon-api`, `ib_insync` for data. `vectorbt`, `backtrader`, `nautilus_trader` for backtest + paper. `langgraph` or `crewai` for agent orchestration. `fastapi` for control plane. `streamlit` for dashboard.
3. Data: Use free tiers first. Polygon.io, Alpaca, IBKR TWS API, TwelveData, FRED, NewsAPI. Abstract all data sources behind `DataProvider` interface.
4. Agents: Define these as separate classes with message passing:
   - `MacroAgent`: Reads FRED, central bank releases, yields. Outputs regime = RiskOn/RiskOff/Transition.
   - `TrendAgent`: Multi-timeframe momentum, breakout, sentiment from news/Reddit/X. Outputs direction + conviction 0-1.
   - `MeanRevertAgent`: Statistical arbitrage, pairs trading, RSI/z-score. Outputs fade signals.
   - `RiskAgent`: Veto power. Calculates exposure, correlation, VaR. Can halt all trading.
   - `PM_Agent`: Meta-agent. Takes all signals, runs portfolio optimization with cvxpy, allocates capital, sizes positions.
   - `ComplianceAgent`: Logs every decision, data source, timestamp. Generates audit trail.
   - `IR_Agent`: Writes daily investor memo in plain English from P&L and positions.
5. Paper Trading: Implement `BrokerSim` that mirrors real slippage, fees, partial fills. Start in paper mode only. Add `ENABLE_LIVE_TRADING=False` env flag that must be manually flipped.
6. Backtesting: Every new strategy must pass walk-forward test on last 10 years, with transaction costs, before paper deployment. 
7. Timezones: System runs UTC. Scheduler handles NYSE 9:30-16:00 ET, LSE 8:00-16:30 GMT, TSE 9:00-15:00 JST. Pre-market + after-hours included.
8. Safety: Hard cap 2% portfolio risk per trade, 10% max drawdown, 3x max gross leverage. If breached, RiskAgent closes all positions and pages human.

[DELIVERABLES]
1. `/agents/` directory with all agent classes.
2. `/data/` data providers + caching layer.
3. `/engine/` backtester + paper broker + live broker stubs.
4. `/risk/` risk models and kill-switch.
5. `/dashboard/` streamlit app: P&L, positions, agent debate transcript, logs.
6. `/tests/` pytest coverage >80%.
7. `docker-compose.yml` to run whole stack.
8. `README.md` with setup, env vars, and "How to add a new agent" guide.

[BUILD ORDER]
Step 1: Data + BrokerSim + basic dashboard. Prove you can pull data and simulate a trade.
Step 2: Add TrendAgent + backtest on SPY. 
Step 3: Add RiskAgent + drawdown control.
Step 4: Add PM_Agent to combine signals.
Step 5: Add remaining agents + 24/7 scheduler.
Step 6: Run 30-day paper trading across all 3 sessions. Log results.

[CONSTRAINTS]
1. No real money, no broker API keys, no live orders until human sets `ENABLE_LIVE_TRADING=True`.
2. All decisions must be explainable. Each trade writes a JSON with: timestamp, agent_votes, data_snapshot_ids, risk_check_result.
3. You must cite data source and latency for every signal.
4. If any API fails, fall back to cached data and alert. Never halt the system unless RiskAgent triggers.

Begin by outputting the repo file tree, then implement Step 1.
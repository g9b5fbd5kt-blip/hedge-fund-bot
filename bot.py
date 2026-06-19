2026-06-19T21:30:51.5604979Z ##[group]Run python bot.py
2026-06-19T21:30:51.5605292Z [36;1mpython bot.py[0m
2026-06-19T21:30:51.5641738Z shell: /usr/bin/bash -e {0}
2026-06-19T21:30:51.5642020Z env:
2026-06-19T21:30:51.5642317Z   pythonLocation: /opt/hostedtoolcache/Python/3.11.15/x64
2026-06-19T21:30:51.5642791Z   PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.11.15/x64/lib/pkgconfig
2026-06-19T21:30:51.5643224Z   Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.15/x64
2026-06-19T21:30:51.5643624Z   Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.15/x64
2026-06-19T21:30:51.5644020Z   Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.15/x64
2026-06-19T21:30:51.5644408Z   LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.11.15/x64/lib
2026-06-19T21:30:51.5645248Z   ALPACA_KEY: ***
2026-06-19T21:30:51.5645589Z   ALPACA_SECRET: ***
2026-06-19T21:30:51.5645929Z   TELEGRAM_TOKEN: ***
2026-06-19T21:30:51.5646192Z   TELEGRAM_CHAT: ***
2026-06-19T21:30:51.5646419Z   DATABASE_URL: 
2026-06-19T21:30:51.5646647Z ##[endgroup]
2026-06-19T21:30:52.4406933Z Traceback (most recent call last):
2026-06-19T21:30:52.4414053Z   File "/home/runner/work/hedge-fund-bot/hedge-fund-bot/bot.py", line 1, in <module>
2026-06-19T21:30:52.4414623Z     import json, os, requests, yfinance as yf
2026-06-19T21:30:52.4415033Z ModuleNotFoundError: No module named 'yfinance'
2026-06-19T21:30:52.4589971Z ##[error]Process completed with exit code 1.

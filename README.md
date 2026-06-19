# TrendGuard AI — Forex & Crypto Signal Bot

A Telegram bot that scans Forex pairs, Gold, and major cryptocurrencies for high-confidence trading setups using multi-timeframe technical analysis, then delivers structured trade plans (entry, stop loss, take profits, lot sizing) straight to chat.

Built with Python, deployed on Railway, powered by the [TwelveData](https://twelvedata.com) API.

---

## ✨ Features

- **8-indicator confluence scoring** — RSI, MACD, Stochastic, Bollinger %B, ATR, ADX, CCI, Williams %R
- **Multi-timeframe analysis** — signals require agreement across multiple timeframes before being shown
- **Daily trend gate** — flags or blocks setups that fight a strong, established daily trend
- **Support/Resistance awareness** — downgrades confidence for entries sitting too close to a key level
- **News filter** — avoids signaling around high-impact economic events
- **Confidence threshold** — only shows signals at or above a configurable confidence floor (default: 65%), so low-conviction noise doesn't reach you
- **Full trade plan per signal** — Entry, SL, TP1/TP2/TP3, Partial TP, Invalidation level, lot size, and risk amount based on your account balance
- **Market regime context** — trend direction, volatility, session quality (London/NY/Overlap), ADX strength
- **Candle pattern detection** — flags patterns like doji, three black crows, etc. on relevant timeframes
- **Crypto runs 24/7** — independent of Forex market hours
- **Auto-scan** — background job re-checks the market on an interval and can notify proactively

---

## 🤖 Commands

| Command | Description |
|---|---|
| `/start` | Welcome message and command list |
| `/signal` | Full scan — Forex + Gold + Crypto (weekdays) |
| `/crypto` | Crypto-only scan, available 24/7 |
| `/setbalance` | Set your trading balance (used for lot sizing & risk calc) |
| `/status` | Current session info + upcoming high-impact news |
| `/help` | Usage guide |

---

## 📊 Pairs Covered

**Forex:** EUR/USD · GBP/USD · USD/JPY · USD/CHF · AUD/USD · USD/CAD
**Metals:** XAU/USD (Gold)
**Crypto:** BTC/USD · ETH/USD · BNB/USD · SOL/USD

---

## 🧠 How a Signal Is Built

1. Fetch OHLCV data across multiple timeframes (1H, 4H, 1Day) from TwelveData.
2. Compute all 8 indicators per timeframe.
3. Vote direction (BUY/SELL) per timeframe; require multi-timeframe alignment.
4. Score confluence on the primary timeframe (minimum indicators must agree).
5. Check the daily trend — penalize or block counter-trend setups.
6. Check proximity to support/resistance — penalize entries too close to a level.
7. Combine into a single confidence score (0–99%).
8. **Only signals at or above the confidence threshold are shown.**
9. Calculate ATR-based SL/TP levels, lot size, and risk in USD.
10. Format and send to Telegram.

---

## ⚙️ Tech Stack

- **Language:** Python (async/`asyncio`)
- **Telegram integration:** `python-telegram-bot`
- **Data:** [TwelveData API](https://twelvedata.com)
- **Data processing:** pandas, numpy
- **Scheduling:** APScheduler (auto-scan job)
- **Hosting:** [Railway](https://railway.app)

---

## 🚀 Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/samolaojo100-ui/Forex-bot.git
   cd Forex-bot
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set environment variables (locally in a `.env` file, or in Railway's project variables):
   ```
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token
   TWELVEDATA_API_KEY=your_twelvedata_api_key
   ```

4. Run the bot:
   ```bash
   python main.py
   ```

### Deploying on Railway

- Connect this GitHub repo to a Railway project.
- Set the same environment variables under **Variables**.
- Railway auto-deploys on every push to `main`.

---

## ⚠️ Disclaimer

This bot is for educational and informational purposes only. It does not constitute financial advice. Trading Forex and cryptocurrencies carries significant risk of loss. Always do your own research and never risk money you cannot afford to lose.

---

## 📄 License

This project is provided as-is, without warranty of any kind.

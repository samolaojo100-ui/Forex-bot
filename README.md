# 📈 Forex Signal Bot

Professional-grade Telegram forex signal bot with multi-timeframe analysis, auto-signals during peak sessions, and risk-managed lot sizing.

---

## ✅ Features

| Feature | Detail |
|---|---|
| **Pairs scanned** | 47 pairs — majors, minors & exotics |
| **Timeframes** | 15min + 1h + 4h (all 3 must agree) |
| **Indicators** | EMA(9/21/50/200), MACD, RSI, Stochastic, Bollinger Bands, ADX, Volume |
| **Signal score** | 0–10; only ≥6 sent |
| **Lot sizing** | 1% account risk, auto-calculated |
| **SL / TP** | ATR-based, min 15 pips SL, 1:2 RR default |
| **Auto-signals** | Every 30 min during London / New York / overlaps |
| **Free** | TwelveData free tier (800 req/day) + Railway free hosting |

---

## 🚀 Step-by-Step Setup

### Step 1 — Create Telegram Bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Give it a name (e.g. `My Forex Signal Bot`)
4. Give it a username (e.g. `myforexsignals_bot`)
5. Copy the **bot token** — looks like `7123456789:AAF...`

### Step 2 — Get your Telegram Chat ID

1. Start a chat with your bot
2. Message **@userinfobot** on Telegram
3. It replies with your numeric chat ID (e.g. `123456789`)

### Step 3 — Get free TwelveData API key

1. Go to [https://twelvedata.com](https://twelvedata.com)
2. Click **Get Free API Key**
3. Sign up (free, no card needed)
4. Copy your API key from the dashboard

### Step 4 — Push code to your GitHub repo

```bash
# Clone your empty repo
git clone https://github.com/YOUR_USERNAME/Forex-bot.git
cd Forex-bot

# Copy all bot files into the folder, then:
git add .
git commit -m "Initial forex bot setup"
git push origin main
```

### Step 5 — Deploy FREE on Railway

1. Go to [https://railway.app](https://railway.app)
2. Sign in with GitHub
3. Click **New Project** → **Deploy from GitHub repo**
4. Select your `Forex-bot` repo
5. Click **Add Variables** and set:

```
BOT_TOKEN          = your telegram bot token
TWELVEDATA_API_KEY = your twelvedata key
CHAT_IDS           = your telegram chat id
ACCOUNT_BALANCE    = 1000
```

6. Railway auto-detects the `Procfile` and starts the bot
7. You'll see logs showing `🤖 Forex Signal Bot started!`

---

## 💬 Bot Commands

| Command | Description |
|---|---|
| `/start` | Introduction & feature list |
| `/signal` | Manually trigger full market scan |
| `/status` | Show current session & auto-scan status |
| `/help` | Full help & explanation |

---

## 📊 Sample Signal Output

```
━━━━━━━━━━━━━━━━━━━━━━━
🟢 BUY EUR/USD 🔥
━━━━━━━━━━━━━━━━━━━━━━━
📊 Signal Score: 8.3/10 — HIGH
🕐 Timeframes: 15min, 1h, 4h

💹 Entry Price:  1.08542
🛑 Stop Loss:    1.08212  (33 pips)
🎯 Take Profit:  1.09202  (66 pips)
⚖️ Risk:Reward:  1:2.0
📦 Lot Size:     0.30 lots

📝 Confirmations:
  [15min] ✅ EMA aligned with trend
  [1h] ✅ MACD confirms direction
  [4h] ✅ ADX 28.4 — strong trend
  [1h] ✅ Volume spike 1.8×
```

---

## ⚙️ Configuration

Edit `config.py` to customize:

- `RISK_PERCENT` — % of balance to risk per trade (default 1%)
- `MIN_SL_PIPS` — minimum SL distance (default 15)
- `DEFAULT_RR_RATIO` — risk:reward (default 2.0)
- `MIN_SIGNAL_SCORE` — minimum score to send (default 6)
- `AUTO_SIGNAL_INTERVAL` — minutes between auto-scans (default 30)

---

## 📁 File Structure

```
forex-bot/
├── bot.py            # Entry point
├── config.py         # All settings
├── handlers.py       # Telegram command handlers
├── signal_engine.py  # Core analysis & signal generation
├── indicators.py     # EMA, MACD, RSI, ATR, ADX, Bollinger, Stochastic
├── data_fetcher.py   # TwelveData API client
├── formatter.py      # Telegram message formatter
├── scheduler.py      # Auto-signal job scheduler
├── session_manager.py# Trading session detection
├── requirements.txt
├── Procfile          # For Railway/Render deployment
└── .env.example      # Environment variable template
```

---

## ⚠️ Disclaimer

This bot is for **educational purposes**. Forex trading involves significant risk. Always use proper risk management and never risk money you cannot afford to lose.

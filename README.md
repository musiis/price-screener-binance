# Lighter.xyz Price Screener

A real-time cryptocurrency price monitoring tool for the Lighter.xyz exchange that alerts you via Telegram when the last traded price deviates significantly from the mark price.

## Features

- Monitors ALL trading pairs on Lighter.xyz automatically
- Compares last traded price against mark price
- Configurable percentage-based deviation threshold
- Telegram notifications for price alerts
- Two implementation options:
  - **REST API version** (`price_screener.py`) - Polls at regular intervals
  - **WebSocket version** (`price_screener_ws.py`) - Real-time streaming updates (recommended)
- Alert cooldown to prevent notification spam
- Comprehensive logging

## Prerequisites

- Python 3.8 or higher
- Telegram account
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))

## Setup Instructions

### 1. Clone or Download

Save all files to a directory on your computer.

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

This will install:
- `lighter-python` - Official Lighter.xyz Python SDK
- `python-telegram-bot` - Telegram bot integration
- `python-dotenv` - Environment variable management
- `websockets` - WebSocket client for real-time updates
- `aiohttp` - HTTP client library

### 3. Create Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow the instructions
3. Copy the **Bot Token** (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)
4. Send a message to your new bot (any message)
5. Get your Chat ID:
   - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Replace `<YOUR_BOT_TOKEN>` with your actual token
   - Look for `"chat":{"id":` in the response - that's your Chat ID

### 4. Configure Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321

# Price Deviation Alert Configuration (percentage)
DEVIATION_THRESHOLD_PERCENT=5.0

# Polling Interval (seconds) - only for REST version
POLL_INTERVAL=60
```

### 5. Run the Screener

**Option A: WebSocket Version (Recommended for real-time monitoring)**

```bash
python price_screener_ws.py
```

**Option B: REST API Version (Polling-based)**

```bash
python price_screener.py
```

## Configuration Options

### DEVIATION_THRESHOLD_PERCENT
Default: `5.0`

The percentage deviation that triggers an alert. For example:
- `5.0` = Alert when price deviates 5% or more from mark price
- `1.0` = Alert when price deviates 1% or more (more sensitive)
- `10.0` = Alert when price deviates 10% or more (less sensitive)

### POLL_INTERVAL
Default: `60` (seconds)

How often the REST version checks prices. WebSocket version doesn't use this setting as it receives real-time updates.

### Alert Cooldown
Default: 300 seconds (5 minutes)

The minimum time between alerts for the same trading pair. This prevents notification spam if a pair stays in deviation state.

You can modify this in the code by changing `self.alert_cooldown` in either script.

## How It Works

### REST API Version (`price_screener.py`)
1. Fetches all available trading pairs from Lighter.xyz
2. For each pair, gets the most recent trade
3. Fetches market statistics to get mark price
4. Calculates deviation percentage
5. Sends Telegram alert if deviation exceeds threshold
6. Waits for POLL_INTERVAL seconds
7. Repeats from step 2

### WebSocket Version (`price_screener_ws.py`)
1. Connects to Lighter.xyz WebSocket API
2. Subscribes to `market_stats` channel for all markets
3. Receives real-time updates including:
   - Mark price
   - Last trade price
   - Index price
   - 24h volume
4. Calculates deviation on each update
5. Sends immediate Telegram alert if deviation exceeds threshold

## Alert Format

When a deviation is detected, you'll receive a Telegram message like:

```
🚨 Price Alert

Market ID: BTC_PERP
Last Trade Price: $43,250.00
Mark Price: $42,000.00
Index Price: $42,100.00
Deviation: 2.98% above
Threshold: 2.5%
24h Volume: 1,234,567
Time: 2026-01-06 15:30:45
```

## Troubleshooting

### No alerts appearing
- Check that `.env` file is in the same directory as the script
- Verify your Telegram Bot Token and Chat ID are correct
- Ensure you've sent at least one message to your bot
- Check the console output for errors

### "No mark price available" messages
- The REST version may not have access to mark price for all markets
- Try using the WebSocket version instead
- Some markets may not have recent trading activity

### WebSocket disconnects
- The WebSocket version automatically reconnects with exponential backoff
- Check your internet connection
- Lighter.xyz API might be experiencing issues

### Rate limiting
- REST version is subject to API rate limits (60 requests/minute for standard accounts)
- Consider using longer POLL_INTERVAL if you hit rate limits
- WebSocket version is not subject to REST rate limits

## Files

- `price_screener.py` - Main REST API implementation
- `price_screener_ws.py` - WebSocket real-time implementation
- `requirements.txt` - Python dependencies
- `.env.example` - Example configuration file
- `README.md` - This file

## API Documentation

- [Lighter.xyz API Docs](https://apidocs.lighter.xyz)
- [Lighter.xyz Main Docs](https://docs.lighter.xyz)
- [Official Python SDK](https://github.com/elliottech/lighter-python)

## Tips

- Start with a higher threshold (e.g., 5%) to test the system
- Lower the threshold once you're comfortable with alert frequency
- Use the WebSocket version for faster, real-time alerts
- Monitor the console output to see what prices are being tracked
- Consider running the screener on a server or cloud instance for 24/7 monitoring

## Advanced Usage

### Running in Background

**Linux/Mac:**
```bash
nohup python price_screener_ws.py > screener.log 2>&1 &
```

**Windows:**
Use Task Scheduler or install `pythonw.exe`:
```bash
pythonw price_screener_ws.py
```

### Docker (Optional)

Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "price_screener_ws.py"]
```

Build and run:
```bash
docker build -t lighter-screener .
docker run -d --env-file .env lighter-screener
```

## License

This project is provided as-is for educational and personal use.

## Disclaimer

This tool is for informational purposes only. Always verify prices and do your own research before making trading decisions. The authors are not responsible for any trading losses.

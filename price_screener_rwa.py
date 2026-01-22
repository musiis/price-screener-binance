"""
Real World Assets (RWA) Price Screener
Monitors Lighter.xyz and Hyperliquid xyz RWA markets using Hyperliquid's real-time oracle
Sends Telegram alerts when deviation exceeds configured threshold
"""

import asyncio
import os
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Set
from dotenv import load_dotenv
import lighter
import requests
from telegram import Bot
from telegram.error import TelegramError

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Lighter symbol -> Hyperliquid xyz symbol mapping
# Used to find matching oracle prices from Hyperliquid
LIGHTER_TO_HYPERLIQUID = {
    # Equities - direct match
    'TSLA': 'TSLA',
    'AAPL': 'AAPL',
    'GOOGL': 'GOOGL',
    'MSFT': 'MSFT',
    'NVDA': 'NVDA',
    'AMZN': 'AMZN',
    'META': 'META',
    'PLTR': 'PLTR',
    'COIN': 'COIN',
    'HOOD': 'HOOD',
    'MSTR': 'MSTR',
    'AMD': 'AMD',
    # Commodities
    'XAU': 'GOLD',
    'XAG': 'SILVER',
    'PAXG': 'GOLD',
    # Forex
    'EURUSD': 'EUR',
    'USDJPY': 'JPY',
    'GBPUSD': 'GBP',
    'AUDUSD': 'AUD',
    'NZDUSD': 'NZD',
    'USDCAD': 'CAD',
    'USDCHF': 'CHF',
}



# Load config from JSON file
def load_config() -> tuple[Set[str], Dict[str, float]]:
    """Load blacklist and custom thresholds from config.json"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        blacklist = set(config.get('symbol_blacklist', []))
        thresholds = config.get('custom_thresholds', {})
        logger.info(f"Loaded config: {len(blacklist)} blacklisted, {len(thresholds)} custom thresholds")
        return blacklist, thresholds
    except FileNotFoundError:
        logger.warning(f"Config file not found at {config_path}, using empty defaults")
        return set(), {}
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing config.json: {e}")
        return set(), {}

SYMBOL_BLACKLIST, CUSTOM_THRESHOLDS = load_config()


class RWAPriceScreener:
    """Monitor RWA markets on Lighter.xyz and Hyperliquid xyz using Hyperliquid oracle"""

    def __init__(self):
        self.deviation_threshold = float(os.getenv('DEVIATION_THRESHOLD_PERCENT', '0.5'))
        self.poll_interval = int(os.getenv('POLL_INTERVAL', '60'))

        # Telegram configuration
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.bot = None

        if self.telegram_token and self.telegram_chat_id:
            self.bot = Bot(token=self.telegram_token)
            logger.info("Telegram bot initialized")
        else:
            logger.warning("Telegram credentials not configured - alerts will only be logged")

        # Track last alert time to avoid spam
        self.last_alert: Dict[str, float] = {}
        self.alert_cooldown = 300  # 5 minutes between alerts for same pair

        # Track consecutive alerts for blacklisting
        self.consecutive_alerts: Dict[str, int] = {}
        self.blacklisted: Dict[str, float] = {}  # market_key -> blacklist timestamp
        self.blacklist_duration = 86400  # 24 hours in seconds

        # Lighter API client
        self.client = lighter.ApiClient()
        self.order_api = lighter.OrderApi(self.client)

    async def send_alert(self, market_key: str, message: str):
        """Send alert via Telegram and/or console"""
        current_time = asyncio.get_event_loop().time()

        # Check if blacklisted
        if market_key in self.blacklisted:
            time_since_blacklist = current_time - self.blacklisted[market_key]
            if time_since_blacklist < self.blacklist_duration:
                # Still blacklisted
                remaining_hours = (self.blacklist_duration - time_since_blacklist) / 3600
                logger.debug(
                    f"Market {market_key} is blacklisted for {remaining_hours:.1f} more hours "
                    f"(too many consecutive alerts)"
                )
                return
            else:
                # Blacklist expired, remove it
                logger.info(f"Blacklist expired for {market_key}, re-enabling alerts")
                del self.blacklisted[market_key]
                self.consecutive_alerts[market_key] = 0

        logger.warning(f"ALERT [{market_key}]: {message}")

        # Track consecutive alerts (regardless of cooldown)
        self.consecutive_alerts[market_key] = self.consecutive_alerts.get(market_key, 0) + 1
        logger.info(
            f"Consecutive alerts for {market_key}: {self.consecutive_alerts[market_key]}/2"
        )

        # If we've hit 2 consecutive alerts, blacklist for 24h
        if self.consecutive_alerts[market_key] >= 2:
            self.blacklisted[market_key] = current_time
            logger.warning(
                f"Market {market_key} blacklisted for 24h due to 2 consecutive alerts"
            )
            if self.bot:
                try:
                    blacklist_msg = (
                        f"⛔ *AUTO-BLACKLISTED*\n\n"
                        f"Market: `{market_key}`\n"
                        f"Reason: 2 consecutive alerts\n"
                        f"Duration: 24 hours\n\n"
                        f"This market will be ignored until blacklist expires."
                    )
                    await self.bot.send_message(
                        chat_id=self.telegram_chat_id,
                        text=blacklist_msg,
                        parse_mode='Markdown'
                    )
                except TelegramError as e:
                    logger.error(f"Failed to send blacklist notification: {e}")
            return

        # Check cooldown
        if market_key in self.last_alert:
            if current_time - self.last_alert[market_key] < self.alert_cooldown:
                logger.debug(f"Alert cooldown active for {market_key}, skipping Telegram notification")
                return

        # Send to Telegram
        if self.bot:
            try:
                formatted_message = f"🚨 *RWA Price Alert*\n\n{message}"
                await self.bot.send_message(
                    chat_id=self.telegram_chat_id,
                    text=formatted_message,
                    parse_mode='Markdown'
                )
                self.last_alert[market_key] = current_time
                logger.info(f"Telegram alert sent for {market_key}")
            except TelegramError as e:
                logger.error(f"Failed to send Telegram message: {e}")


    async def fetch_lighter_rwa_prices(self) -> Dict[str, dict]:
        """Fetch RWA prices from Lighter.xyz"""
        try:
            stats = await self.order_api.exchange_stats()

            if hasattr(stats, 'order_book_stats'):
                order_book_stats = stats.order_book_stats
            else:
                order_book_stats = []

            prices = {}

            # RWA symbols to look for (only those that have Hyperliquid mapping)
            rwa_symbols = set(LIGHTER_TO_HYPERLIQUID.keys())

            for stat in order_book_stats:
                if isinstance(stat, dict):
                    symbol = stat.get('symbol')
                    last_price = stat.get('last_trade_price')
                    trades_count = stat.get('daily_trades_count', 0)
                else:
                    symbol = getattr(stat, 'symbol', None)
                    last_price = getattr(stat, 'last_trade_price', None)
                    trades_count = getattr(stat, 'daily_trades_count', 0)

                if symbol in rwa_symbols and last_price and last_price > 0:
                    prices[symbol] = {
                        'last_trade_price': float(last_price),
                        'trades_count': trades_count
                    }

            logger.info(f"Fetched prices for {len(prices)} Lighter RWA markets")
            return prices

        except Exception as e:
            logger.error(f"Error fetching Lighter RWA prices: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    def fetch_hyperliquid_xyz_prices(self) -> Dict[str, dict]:
        """Fetch RWA prices from Hyperliquid xyz (HIP-3)"""
        try:
            url = "https://api.hyperliquid.xyz/info"
            data = {"type": "metaAndAssetCtxs", "dex": "xyz"}

            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()

            meta_data = response.json()

            if not isinstance(meta_data, list) or len(meta_data) < 2:
                logger.error("Unexpected metaAndAssetCtxs response format")
                return {}

            universe = meta_data[0].get('universe', [])
            contexts = meta_data[1]

            prices = {}
            for i, market in enumerate(universe):
                if i >= len(contexts):
                    break

                symbol = market.get('name', '')

                # Remove 'xyz:' prefix if present
                if symbol.startswith('xyz:'):
                    symbol = symbol[4:]

                ctx = contexts[i]

                oracle_px = ctx.get('oraclePx')
                impact_pxs = ctx.get('impactPxs')
                day_volume = ctx.get('dayNtlVlm')

                if not oracle_px or not impact_pxs or len(impact_pxs) != 2:
                    continue

                # Skip markets with very low volume (< $50k in 24h)
                volume_usd = float(day_volume) if day_volume is not None else 0
                if volume_usd < 50000:
                    logger.debug(f"Skipping {symbol}: volume ${volume_usd:.0f} < $50k")
                    continue

                try:
                    prices[symbol] = {
                        'oracle_price': float(oracle_px),
                        'best_bid': float(impact_pxs[0]),
                        'best_ask': float(impact_pxs[1]),
                        'volume_24h': volume_usd
                    }
                except (ValueError, TypeError):
                    continue

            logger.info(f"Fetched prices for {len(prices)} Hyperliquid xyz RWA markets")
            return prices

        except Exception as e:
            logger.error(f"Error fetching Hyperliquid xyz prices: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    def calculate_deviation(self, price: float, oracle_price: float) -> float:
        """Calculate percentage deviation from oracle price"""
        if oracle_price == 0:
            return 0.0
        return ((price - oracle_price) / oracle_price) * 100

    def check_lighter_market(self, symbol: str, lighter_data: dict, oracle_price: float):
        """Check a single Lighter market for price deviation using Hyperliquid oracle"""
        try:
            # Skip blacklisted symbols
            if symbol in SYMBOL_BLACKLIST:
                logger.debug(f"Skipping {symbol}: in blacklist")
                return None

            lighter_price = lighter_data.get('last_trade_price')
            if not lighter_price:
                return None

            # Calculate deviation
            deviation = self.calculate_deviation(lighter_price, oracle_price)

            logger.debug(
                f"Lighter {symbol}: Price=${lighter_price:.4f}, HL Oracle=${oracle_price:.4f}, "
                f"Deviation={deviation:.2f}%"
            )

            market_key = f"LT-{symbol}"

            # Get threshold (custom or default)
            threshold = CUSTOM_THRESHOLDS.get(symbol, self.deviation_threshold)

            # Alert if deviation exceeds threshold
            if abs(deviation) >= threshold:
                direction = "↑" if deviation > 0 else "↓"
                emoji = "📈" if deviation > 0 else "📉"

                message = (
                    f"{emoji} *LIGHTER - {symbol}*\n"
                    f"Last Trade: `${lighter_price:.4f}`\n"
                    f"HL Oracle: `${oracle_price:.4f}`\n"
                    f"Deviation: *{direction}{abs(deviation):.2f}%*\n"
                    f"Threshold: {threshold}%\n"
                    f"🔗 https://app.lighter.xyz/trade/{symbol}"
                )
                return (market_key, message)
            return None

        except Exception as e:
            logger.error(f"Error checking Lighter market {symbol}: {e}")
            return None

    def check_hyperliquid_xyz_market(self, symbol: str, hl_data: dict):
        """Check a single Hyperliquid xyz market for bid/ask deviation from oracle"""
        try:
            # Skip blacklisted symbols
            if symbol in SYMBOL_BLACKLIST:
                logger.debug(f"Skipping {symbol}: in blacklist")
                return None

            oracle_price = hl_data.get('oracle_price')
            best_bid = hl_data.get('best_bid')
            best_ask = hl_data.get('best_ask')

            if not oracle_price or not best_bid or not best_ask:
                return None

            # Calculate deviations from Hyperliquid's own oracle
            bid_deviation = self.calculate_deviation(best_bid, oracle_price)
            ask_deviation = self.calculate_deviation(best_ask, oracle_price)

            logger.debug(
                f"HL xyz {symbol}: Bid=${best_bid:.4f} ({bid_deviation:.2f}%), "
                f"Ask=${best_ask:.4f} ({ask_deviation:.2f}%), "
                f"Oracle=${oracle_price:.4f}"
            )

            bid_key = f"HL-xyz-{symbol}-BID"
            ask_key = f"HL-xyz-{symbol}-ASK"
            alerts = []

            # Get threshold (custom or default)
            threshold = CUSTOM_THRESHOLDS.get(symbol, self.deviation_threshold)

            # Alert if best bid deviates from oracle (sell opportunity)
            if abs(bid_deviation) >= threshold:
                direction = "↑" if bid_deviation > 0 else "↓"
                emoji = "📈" if bid_deviation > 0 else "📉"
                message = (
                    f"{emoji} *HYPERLIQUID xyz - {symbol} (SELL)*\n"
                    f"Best Bid: `${best_bid:.4f}`\n"
                    f"Oracle: `${oracle_price:.4f}`\n"
                    f"Deviation: *{direction}{abs(bid_deviation):.2f}%*\n"
                    f"Threshold: {threshold}%\n"
                    f"🔗 https://app.hyperliquid.xyz/trade/xyz:{symbol}"
                )
                alerts.append((bid_key, message))

            # Alert if best ask deviates from oracle (buy opportunity)
            if abs(ask_deviation) >= threshold:
                direction = "↑" if ask_deviation > 0 else "↓"
                emoji = "📈" if ask_deviation > 0 else "📉"
                message = (
                    f"{emoji} *HYPERLIQUID xyz - {symbol} (BUY)*\n"
                    f"Best Ask: `${best_ask:.4f}`\n"
                    f"Oracle: `${oracle_price:.4f}`\n"
                    f"Deviation: *{direction}{abs(ask_deviation):.2f}%*\n"
                    f"Threshold: {threshold}%\n"
                    f"🔗 https://app.hyperliquid.xyz/trade/xyz:{symbol}"
                )
                alerts.append((ask_key, message))

            return alerts if alerts else None

        except Exception as e:
            logger.error(f"Error checking Hyperliquid xyz market {symbol}: {e}")
            return None

    async def scan_all_markets(self):
        """Scan all RWA markets for price deviations using Hyperliquid oracle"""
        # Fetch Hyperliquid xyz prices (includes oracle prices)
        hyperliquid_prices = self.fetch_hyperliquid_xyz_prices()

        if not hyperliquid_prices:
            logger.warning("No Hyperliquid oracle prices available, skipping scan")
            return

        # Build oracle price lookup from Hyperliquid data
        hl_oracle_prices = {}
        for hl_symbol, hl_data in hyperliquid_prices.items():
            oracle_price = hl_data.get('oracle_price')
            if oracle_price:
                hl_oracle_prices[hl_symbol] = oracle_price

        # Fetch Lighter prices
        lighter_prices = await self.fetch_lighter_rwa_prices()

        logger.info(
            f"Scanning {len(lighter_prices)} Lighter + {len(hyperliquid_prices)} Hyperliquid xyz markets "
            f"using Hyperliquid oracle..."
        )

        alerts = []

        # Check Lighter markets using Hyperliquid oracle
        for symbol, lighter_data in lighter_prices.items():
            # Map Lighter symbol to Hyperliquid symbol
            hl_symbol = LIGHTER_TO_HYPERLIQUID.get(symbol)
            if not hl_symbol:
                logger.debug(f"No Hyperliquid mapping for Lighter symbol {symbol}")
                continue

            # Get Hyperliquid oracle price for this symbol
            oracle_price = hl_oracle_prices.get(hl_symbol)
            if not oracle_price:
                logger.debug(f"No Hyperliquid oracle price for {symbol} (HL: {hl_symbol})")
                continue

            result = self.check_lighter_market(symbol, lighter_data, oracle_price)
            if result:
                alerts.append(result)

        # Check Hyperliquid xyz markets (uses Hyperliquid's own oracle)
        for symbol, hl_data in hyperliquid_prices.items():
            result = self.check_hyperliquid_xyz_market(symbol, hl_data)
            if result:
                # Result is a list of alerts
                alerts.extend(result)

        # Send all alerts
        for alert_key, message in alerts:
            await self.send_alert(alert_key, message)

        if alerts:
            logger.info(f"Scan complete - {len(alerts)} alerts triggered")
        else:
            logger.info("Scan complete - no deviations detected")

    async def run(self):
        """Main loop - continuously monitor markets"""
        logger.info(f"Starting RWA Price Screener")
        logger.info(f"Monitoring: Lighter.xyz + Hyperliquid xyz")
        logger.info(f"Oracle: Hyperliquid (real-time)")
        logger.info(f"Deviation threshold: {self.deviation_threshold}%")
        logger.info(f"Poll interval: {self.poll_interval} seconds")

        try:
            # Continuous monitoring loop
            while True:
                try:
                    await self.scan_all_markets()
                except Exception as e:
                    logger.error(f"Error during scan: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

                # Wait before next scan
                await asyncio.sleep(self.poll_interval)

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await self.client.close()

    async def close(self):
        """Cleanup resources"""
        await self.client.close()


async def main():
    """Entry point"""
    screener = RWAPriceScreener()
    try:
        await screener.run()
    finally:
        await screener.close()


if __name__ == "__main__":
    asyncio.run(main())

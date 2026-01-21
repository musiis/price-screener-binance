"""
Real World Assets (RWA) Price Screener
Monitors Lighter.xyz and Hyperliquid xyz RWA markets against Pyth Network oracle prices
Sends Telegram alerts when deviation exceeds configured threshold
"""

import asyncio
import os
import logging
from datetime import datetime
from typing import Dict, Optional
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


# Pyth Network price feed IDs for RWA assets (from Pyth Hermes API)
PYTH_FEED_IDS = {
    # Equities (Stocks) - Using standard USD feeds (not PRE/POST/ON)
    'TSLA': '16dad506d7db8da01c87581c87ca897a012a153557d4d578c3b9c9e1bc0632f1',  # Equity.US.TSLA/USD
    'AAPL': '49f6b65cb1de6b10eaf75e7c03ca029c306d0357e91b5311b175084a5ad55688',  # Equity.US.AAPL/USD
    'GOOGL': '88d0800b1649d98e21b8bf9c3f42ab548034d62874ad5d80e1c1b730566d7f61',  # Equity.US.GOOGL/USD
    'MSFT': '8f98f8267ddddeeb61b4fd11f21dc0c2842c417622b4d685243fa73b5830131f',  # Equity.US.MSFT/USD
    'NVDA': '61c4ca5b9731a79e285a01e24432d57d89f0ecdd4cd7828196ca8992d5eafef6',  # Equity.US.NVDA/USD
    'AMZN': '82c59e36a8e0247e15283748d6cd51f5fa1019d73fbf3ab6d927e17d9e357a7f',  # Equity.US.AMZN/USD
    'META': '399f1e8f1c4a517859963b56f104727a7a3c7f0f8fee56d34fa1f72e5a4b78ef',  # Equity.US.META/USD
    'PLTR': '3a4c922ec7e8cd86a6fa4005827e723a134a16f4ffe836eac91e7820c61f75a1',  # Equity.US.PLTR/USD
    'COIN': 'fee33f2a978bf32dd6b662b65ba8083c6773b494f8401194ec1870c640860245',  # Equity.US.COIN/USD
    'HOOD': '52ecf79ab14d988ca24fbd282a7cb91d41d36cb76aa3c9075a3eabce9ff63e2f',  # Equity.US.HOOD/USD
    'MSTR': 'd8b856d7e17c467877d2d947f27b832db0d65b362ddb6f728797d46b0a8b54c0',  # Equity.US.MSTR/USD
    'AMD': '7178689d88cdd76574b64438fc57f4e57efaf0bf5f9593ee19c10e46a3c5b5cf',  # Equity.US.AMD/USD

    # Commodities
    'XAU': '765d2ba906dbc32ca17cc11f5310a89e9ee1f6420508c63861f2f8ba4ee34bb2',  # Metal.XAU/USD (Gold)
    'XAG': 'f2fb02c32b055c805e7238d628e5e9dadef274376114eb1f012337cabe93871e',  # Metal.XAG/USD (Silver)
    'PAXG': '765d2ba906dbc32ca17cc11f5310a89e9ee1f6420508c63861f2f8ba4ee34bb2',  # Tokenized Gold (use XAU)

    # Forex
    'EURUSD': 'a995d00bb36a63cef7fd2c287dc105fc8f3d93779f062f09551b0af3e81ec30b',  # FX.EUR/USD
    'USDJPY': 'ef2c98c804ba503c6a707e38be4dfbb16683775f195b091252bf24693042fd52',  # FX.USD/JPY
    'GBPUSD': '84c2dde9633d93d1bcad84e7dc41c9d56578b7ec52fabedc1f335d673df0a7c1',  # FX.GBP/USD
    'AUDUSD': '67a6f93030420c1c9e3fe37c1ab6b77966af82f995944a9fefce357a22854a80',  # FX.AUD/USD
    'NZDUSD': '92eea8ba1b00078cdc2ef6f64f091f262e8c7d0576ee4677572f314ebfafa4c7',  # FX.NZD/USD
    'USDCAD': '3112b03a41c910ed446852aacf67118cb1bec67b2cd0b9a214c58cc0eaa2ecca',  # FX.USD/CAD
    'USDCHF': '0b1e3297e69f162877b577b0d6a47a0d63b2392bc8499e6540da4187a63e28f8',  # FX.USD/CHF
    'USDKRW': 'e539120487c29b4defdf9a53d337316ea022a2688978a468f9efd847201be7e3',  # FX.USD/KRW
}

# Symbol mapping: Lighter symbol -> Hyperliquid xyz symbol
SYMBOL_MAPPING = {
    'EURUSD': 'EUR',
    'USDJPY': 'JPY',
    'GBPUSD': 'GBP',
    'XAU': 'GOLD',
    'XAG': 'SILVER',
}


class RWAPriceScreener:
    """Monitor RWA markets on Lighter.xyz and Hyperliquid xyz against Pyth oracle"""

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

        # Pyth Hermes API base URL
        self.pyth_base_url = 'https://hermes.pyth.network'

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

                # Track consecutive alerts
                self.consecutive_alerts[market_key] = self.consecutive_alerts.get(market_key, 0) + 1
                logger.info(
                    f"Consecutive alerts for {market_key}: {self.consecutive_alerts[market_key]}/2"
                )

                # If we've hit 2 consecutive alerts, blacklist for 24h
                if self.consecutive_alerts[market_key] >= 2:
                    self.blacklisted[market_key] = current_time
                    logger.warning(
                        f"Market {market_key} blacklisted for 24h due to consecutive false alerts"
                    )
                    # Send notification about blacklisting
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
                logger.error(f"Failed to send Telegram message: {e}")

    def fetch_pyth_oracle_prices(self) -> Dict[str, float]:
        """Fetch oracle prices from Pyth Network Hermes API (FREE)"""
        try:
            # Get all feed IDs
            feed_ids = list(PYTH_FEED_IDS.values())

            url = f'{self.pyth_base_url}/api/latest_price_feeds'
            params = {'ids[]': feed_ids}

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            prices = {}
            for symbol, feed_id in PYTH_FEED_IDS.items():
                # Find matching feed in response
                for item in data:
                    if item['id'] == feed_id:
                        price_data = item['price']
                        price_raw = int(price_data['price'])
                        expo = int(price_data['expo'])
                        price = price_raw * (10 ** expo)

                        if price > 0:
                            prices[symbol] = price
                        break

            logger.info(f"Fetched {len(prices)} oracle prices from Pyth Network")
            return prices

        except Exception as e:
            logger.error(f"Error fetching Pyth oracle prices: {e}")
            return {}

    async def fetch_lighter_rwa_prices(self) -> Dict[str, dict]:
        """Fetch RWA prices from Lighter.xyz"""
        try:
            stats = await self.order_api.exchange_stats()

            if hasattr(stats, 'order_book_stats'):
                order_book_stats = stats.order_book_stats
            else:
                order_book_stats = []

            prices = {}

            # RWA symbols to look for
            rwa_symbols = set(PYTH_FEED_IDS.keys())

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
        """Check a single Lighter market for price deviation"""
        try:
            lighter_price = lighter_data.get('last_trade_price')
            if not lighter_price:
                return None

            # Calculate deviation
            deviation = self.calculate_deviation(lighter_price, oracle_price)

            logger.debug(
                f"Lighter {symbol}: Price=${lighter_price:.4f}, Oracle=${oracle_price:.4f}, "
                f"Deviation={deviation:.2f}%"
            )

            market_key = f"LT-{symbol}"

            # Alert if deviation exceeds threshold
            if abs(deviation) >= self.deviation_threshold:
                direction = "↑" if deviation > 0 else "↓"
                emoji = "📈" if deviation > 0 else "📉"

                message = (
                    f"{emoji} *LIGHTER - {symbol}*\n"
                    f"Last Trade: `${lighter_price:.4f}`\n"
                    f"Pyth Oracle: `${oracle_price:.4f}`\n"
                    f"Deviation: *{direction}{abs(deviation):.2f}%*\n"
                    f"Threshold: {self.deviation_threshold}%\n"
                    f"🔗 https://app.lighter.xyz/trade/{symbol}"
                )
                return (market_key, message)
            else:
                # Deviation is below threshold - reset consecutive alerts counter
                if market_key in self.consecutive_alerts:
                    logger.debug(f"Deviation normalized for {market_key}, resetting consecutive alerts")
                    self.consecutive_alerts[market_key] = 0

            return None

        except Exception as e:
            logger.error(f"Error checking Lighter market {symbol}: {e}")
            return None

    def check_hyperliquid_xyz_market(self, symbol: str, hl_data: dict):
        """Check a single Hyperliquid xyz market for bid/ask deviation from oracle"""
        try:
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

            # RWA threshold: 2.5%
            rwa_threshold = 2.5

            # Alert if best bid deviates from oracle (sell opportunity)
            if abs(bid_deviation) >= rwa_threshold:
                direction = "↑" if bid_deviation > 0 else "↓"
                emoji = "📈" if bid_deviation > 0 else "📉"
                message = (
                    f"{emoji} *HYPERLIQUID xyz - {symbol} (SELL)*\n"
                    f"Best Bid: `${best_bid:.4f}`\n"
                    f"Oracle: `${oracle_price:.4f}`\n"
                    f"Deviation: *{direction}{abs(bid_deviation):.2f}%*\n"
                    f"Threshold: {rwa_threshold}%\n"
                    f"🔗 https://app.hyperliquid.xyz/trade/xyz:{symbol}"
                )
                alerts.append((bid_key, message))
            else:
                if bid_key in self.consecutive_alerts:
                    logger.debug(f"Deviation normalized for {bid_key}, resetting consecutive alerts")
                    self.consecutive_alerts[bid_key] = 0

            # Alert if best ask deviates from oracle (buy opportunity)
            if abs(ask_deviation) >= rwa_threshold:
                direction = "↑" if ask_deviation > 0 else "↓"
                emoji = "📈" if ask_deviation > 0 else "📉"
                message = (
                    f"{emoji} *HYPERLIQUID xyz - {symbol} (BUY)*\n"
                    f"Best Ask: `${best_ask:.4f}`\n"
                    f"Oracle: `${oracle_price:.4f}`\n"
                    f"Deviation: *{direction}{abs(ask_deviation):.2f}%*\n"
                    f"Threshold: {rwa_threshold}%\n"
                    f"🔗 https://app.hyperliquid.xyz/trade/xyz:{symbol}"
                )
                alerts.append((ask_key, message))
            else:
                if ask_key in self.consecutive_alerts:
                    logger.debug(f"Deviation normalized for {ask_key}, resetting consecutive alerts")
                    self.consecutive_alerts[ask_key] = 0

            return alerts if alerts else None

        except Exception as e:
            logger.error(f"Error checking Hyperliquid xyz market {symbol}: {e}")
            return None

    async def scan_all_markets(self):
        """Scan all RWA markets for price deviations"""
        # Fetch Pyth oracle prices (reference prices)
        pyth_prices = self.fetch_pyth_oracle_prices()

        if not pyth_prices:
            logger.warning("No Pyth oracle prices available, skipping scan")
            return

        # Fetch exchange prices
        lighter_prices = await self.fetch_lighter_rwa_prices()
        hyperliquid_prices = self.fetch_hyperliquid_xyz_prices()

        if not lighter_prices and not hyperliquid_prices:
            logger.warning("No exchange prices available, skipping scan")
            return

        logger.info(
            f"Scanning {len(lighter_prices)} Lighter + {len(hyperliquid_prices)} Hyperliquid xyz markets "
            f"against {len(pyth_prices)} Pyth oracle prices..."
        )

        alerts = []

        # Check Lighter markets
        for symbol, lighter_data in lighter_prices.items():
            # Get Pyth oracle price for this symbol
            oracle_price = pyth_prices.get(symbol)
            if not oracle_price:
                logger.debug(f"No Pyth oracle price for {symbol}")
                continue

            result = self.check_lighter_market(symbol, lighter_data, oracle_price)
            if result:
                alerts.append(result)

        # Check Hyperliquid xyz markets (uses Hyperliquid's own oracle, not Pyth)
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
        logger.info(f"Monitoring: Lighter.xyz + Hyperliquid xyz vs Pyth Network Oracle")
        logger.info(f"Deviation threshold: {self.deviation_threshold}%")
        logger.info(f"Poll interval: {self.poll_interval} seconds")
        logger.info(f"Using Pyth Hermes API (FREE) for oracle prices")

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

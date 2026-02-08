"""
Multi-Exchange Price Screener with Binance Mark Price
Compares Lighter.xyz and Hyperliquid prices against Binance Futures mark prices
Alerts when significant deviations are detected
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

# Load config from JSON file
def load_config() -> dict:
    """Load all settings from config.json"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        logger.info(f"Loaded config: threshold={config.get('default_threshold', 0.5)}%, "
                   f"poll={config.get('poll_interval', 60)}s, "
                   f"{len(config.get('symbol_blacklist', []))} blacklisted")
        return config
    except FileNotFoundError:
        logger.warning(f"Config file not found at {config_path}, using defaults")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing config.json: {e}")
        return {}

CONFIG = load_config()
SYMBOL_BLACKLIST = set(CONFIG.get('symbol_blacklist', []))
CUSTOM_THRESHOLDS = CONFIG.get('custom_thresholds', {})


class BinancePriceScreener:
    """Monitor Lighter.xyz and Hyperliquid markets against Binance mark prices"""

    def __init__(self):
        self.deviation_threshold = float(CONFIG.get('default_threshold', 0.5))
        self.poll_interval = int(CONFIG.get('poll_interval', 60))

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

        # Track consecutive alerts for auto-blacklisting
        self.consecutive_alerts: Dict[str, int] = {}
        self.blacklisted: Dict[str, float] = {}  # market_key -> blacklist timestamp
        self.blacklist_duration = 86400  # 24 hours in seconds

        # Lighter API client
        self.client = lighter.ApiClient()
        self.order_api = lighter.OrderApi(self.client)

        # Market data cache
        self.lighter_markets: Dict[int, dict] = {}
        self.binance_prices: Dict[str, float] = {}

        # Mapping of Lighter market IDs to Binance symbols
        # We'll populate this dynamically by matching symbols
        self.market_to_binance: Dict[int, str] = {}

    def get_binance_symbol(self, lighter_symbol: str) -> Optional[str]:
        """Convert Lighter symbol to Binance futures symbol"""
        # Lighter symbols are like "BTC", "ETH", "SOL", "AAVE", etc.
        # Binance futures symbols are like "BTCUSDT", "ETHUSDT", "SOLUSDT", "AAVEUSDT"

        if not lighter_symbol:
            return None

        # Clean up the symbol and convert to uppercase
        base = lighter_symbol.strip().upper()

        # Skip symbols that are obviously not standard crypto pairs
        # (too long, or known non-standard ones)
        if len(base) > 10 or not base:
            return None

        # Map to Binance futures symbol
        binance_symbol = f"{base}USDT"

        return binance_symbol

    async def fetch_binance_mark_prices(self) -> Dict[str, float]:
        """Fetch mark prices from Binance Futures"""
        try:
            response = requests.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                timeout=10
            )
            response.raise_for_status()

            data = response.json()

            prices = {}
            for item in data:
                symbol = item.get('symbol')
                mark_price = item.get('markPrice')

                if symbol and mark_price:
                    try:
                        prices[symbol] = float(mark_price)
                    except (ValueError, TypeError):
                        continue

            logger.info(f"Fetched {len(prices)} mark prices from Binance")
            return prices

        except Exception as e:
            logger.error(f"Error fetching Binance prices: {e}")
            return {}

    async def fetch_lighter_markets(self):
        """Fetch all available Lighter markets"""
        try:
            orderbooks_response = await self.order_api.order_books()

            # Handle the OrderBooks object
            if hasattr(orderbooks_response, 'data'):
                orderbooks = orderbooks_response.data
            elif hasattr(orderbooks_response, 'order_books'):
                orderbooks = orderbooks_response.order_books
            elif hasattr(orderbooks_response, '__dict__'):
                orderbooks = list(orderbooks_response.__dict__.values())[0] if orderbooks_response.__dict__ else []
            else:
                orderbooks = orderbooks_response

            if isinstance(orderbooks, list):
                for orderbook in orderbooks:
                    # Extract market_id and symbol
                    if isinstance(orderbook, dict):
                        market_id = orderbook.get('market_id') or orderbook.get('order_book_id') or orderbook.get('id')
                        symbol = orderbook.get('symbol', '')
                    else:
                        market_id = getattr(orderbook, 'market_id', None) or getattr(orderbook, 'order_book_id', None) or getattr(orderbook, 'id', None)
                        symbol = getattr(orderbook, 'symbol', '')

                    if market_id is not None:
                        market_id = int(market_id)
                        self.lighter_markets[market_id] = {
                            'symbol': symbol,
                            'data': orderbook
                        }

                        # Try to map to Binance symbol
                        binance_symbol = self.get_binance_symbol(symbol)
                        if binance_symbol:
                            self.market_to_binance[market_id] = binance_symbol

            logger.info(f"Fetched {len(self.lighter_markets)} Lighter markets")

            # Log first few Lighter symbols to debug
            for i, (market_id, info) in enumerate(list(self.lighter_markets.items())[:10]):
                symbol = info['symbol']
                logger.info(f"  Sample Lighter symbol: '{symbol}' (ID:{market_id})")

            logger.info(f"Mapped {len(self.market_to_binance)} markets to Binance symbols")

            # Log first few mappings for verification
            if self.market_to_binance:
                for i, (market_id, binance_sym) in enumerate(list(self.market_to_binance.items())[:5]):
                    lighter_sym = self.lighter_markets[market_id]['symbol']
                    logger.info(f"  Mapping: {lighter_sym} (ID:{market_id}) -> {binance_sym}")
            else:
                logger.warning("No markets were mapped! Check symbol format.")

            return self.lighter_markets

        except Exception as e:
            logger.error(f"Error fetching Lighter markets: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    async def fetch_all_lighter_prices(self) -> Dict[str, float]:
        """Fetch last trade prices for ALL markets using bulk endpoint"""
        try:
            stats_response = await self.order_api.exchange_stats()

            prices = {}

            # Parse the response
            if hasattr(stats_response, 'order_book_stats'):
                order_book_stats = stats_response.order_book_stats
            elif isinstance(stats_response, dict):
                order_book_stats = stats_response.get('order_book_stats', [])
            else:
                logger.warning(f"Unexpected stats response type: {type(stats_response)}")
                return {}

            # Extract last_trade_price for each market
            for stat in order_book_stats:
                if isinstance(stat, dict):
                    symbol = stat.get('symbol')
                    last_price = stat.get('last_trade_price')
                    trades_count = stat.get('daily_trades_count', 0)
                else:
                    symbol = getattr(stat, 'symbol', None)
                    last_price = getattr(stat, 'last_trade_price', None)
                    trades_count = getattr(stat, 'daily_trades_count', 0)

                if symbol and last_price and last_price > 0:
                    # Store with symbol as key (easier to match later)
                    prices[symbol] = {
                        'last_trade_price': float(last_price),
                        'trades_count': trades_count
                    }

            logger.info(f"Fetched prices for {len(prices)} Lighter markets (bulk)")
            return prices

        except Exception as e:
            logger.error(f"Error fetching Lighter prices (bulk): {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    async def fetch_hyperliquid_prices(self) -> Dict[str, dict]:
        """Fetch bid/ask prices for ALL Hyperliquid perp markets using metaAndAssetCtxs endpoint"""
        try:
            url = "https://api.hyperliquid.xyz/info"
            data = {"type": "metaAndAssetCtxs"}

            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()

            meta_data = response.json()

            # meta_data[0] = universe (market definitions)
            # meta_data[1] = contexts (market data)
            if not isinstance(meta_data, list) or len(meta_data) < 2:
                logger.error("Unexpected metaAndAssetCtxs response format")
                return {}

            universe = meta_data[0].get('universe', [])
            contexts = meta_data[1]

            perp_prices = {}
            for i, market in enumerate(universe):
                if i >= len(contexts):
                    break

                symbol = market.get('name')
                ctx = contexts[i]

                # Extract bid/ask from impactPxs
                impact_pxs = ctx.get('impactPxs')
                mid_px = ctx.get('midPx')
                day_volume = ctx.get('dayNtlVlm')  # Daily notional volume in USD

                if not symbol or not impact_pxs or len(impact_pxs) != 2:
                    continue

                # Skip if no mid price (market might be inactive)
                if mid_px is None:
                    continue

                # Skip markets with low volume (< $150k in 24h)
                volume_usd = float(day_volume) if day_volume is not None else 0
                if volume_usd < 150000:
                    logger.debug(f"Skipping {symbol}: volume ${volume_usd:.0f} < $150k")
                    continue

                try:
                    perp_prices[symbol] = {
                        'best_bid': float(impact_pxs[0]),
                        'best_ask': float(impact_pxs[1]),
                        'mid_price': float(mid_px),
                        'volume_24h': volume_usd
                    }
                except (ValueError, TypeError):
                    continue

            logger.info(f"Fetched prices for {len(perp_prices)} Hyperliquid perp markets (bulk)")
            return perp_prices

        except Exception as e:
            logger.error(f"Error fetching Hyperliquid prices: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    def calculate_deviation(self, lighter_price: float, binance_price: float) -> float:
        """Calculate percentage deviation"""
        if binance_price == 0:
            return 0.0
        return ((lighter_price - binance_price) / binance_price) * 100

    async def send_alert(self, market_id: int, message: str):
        """Send alert via Telegram and/or console"""
        current_time = asyncio.get_event_loop().time()
        alert_key = str(market_id)

        # Check if blacklisted
        if alert_key in self.blacklisted:
            time_since_blacklist = current_time - self.blacklisted[alert_key]
            if time_since_blacklist < self.blacklist_duration:
                remaining_hours = (self.blacklist_duration - time_since_blacklist) / 3600
                logger.debug(
                    f"Market {alert_key} is blacklisted for {remaining_hours:.1f} more hours"
                )
                return
            else:
                logger.info(f"Blacklist expired for {alert_key}, re-enabling alerts")
                del self.blacklisted[alert_key]
                self.consecutive_alerts[alert_key] = 0

        logger.warning(f"ALERT [Market {market_id}]: {message}")

        # Track consecutive alerts (regardless of cooldown)
        self.consecutive_alerts[alert_key] = self.consecutive_alerts.get(alert_key, 0) + 1
        logger.info(
            f"Consecutive alerts for {alert_key}: {self.consecutive_alerts[alert_key]}/2"
        )

        # If we've hit 2 consecutive alerts, blacklist for 24h
        if self.consecutive_alerts[alert_key] >= 2:
            self.blacklisted[alert_key] = current_time
            logger.warning(
                f"Market {alert_key} blacklisted for 24h due to 2 consecutive alerts"
            )
            if self.bot:
                try:
                    blacklist_msg = (
                        f"⛔ *AUTO-BLACKLISTED*\n\n"
                        f"Market: `{alert_key}`\n"
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
        if alert_key in self.last_alert:
            if current_time - self.last_alert[alert_key] < self.alert_cooldown:
                logger.debug(f"Alert cooldown active for {market_id}, skipping Telegram notification")
                return

        # Send to Telegram
        if self.bot:
            try:
                formatted_message = f"🚨 *Price Alert*\n\n{message}"
                await self.bot.send_message(
                    chat_id=self.telegram_chat_id,
                    text=formatted_message,
                    parse_mode='Markdown'
                )
                self.last_alert[alert_key] = current_time
                logger.info(f"Telegram alert sent for market {market_id}")
            except TelegramError as e:
                logger.error(f"Failed to send Telegram message: {e}")

    def check_market(self, symbol: str, lighter_data: dict, binance_symbol: str):
        """Check a single market for price deviation (synchronous)"""
        try:
            # Skip blacklisted symbols
            if symbol in SYMBOL_BLACKLIST:
                logger.debug(f"Skipping {symbol}: in blacklist")
                return None

            # Get Binance mark price
            binance_price = self.binance_prices.get(binance_symbol)
            if not binance_price:
                logger.debug(f"No Binance price for {binance_symbol}")
                return None

            # Get Lighter price from pre-fetched data
            lighter_price = lighter_data.get('last_trade_price')
            if not lighter_price:
                logger.debug(f"No Lighter price for {symbol}")
                return None

            # Calculate deviation
            deviation = self.calculate_deviation(lighter_price, binance_price)

            logger.debug(
                f"{symbol}: Lighter=${lighter_price:.4f}, Binance=${binance_price:.4f}, "
                f"Deviation={deviation:.2f}%"
            )

            # Get threshold (custom or default)
            threshold = CUSTOM_THRESHOLDS.get(symbol, self.deviation_threshold)

            # Skip if deviation is too large (likely different tokens)
            # But skip this check for symbols with custom thresholds
            if symbol not in CUSTOM_THRESHOLDS and abs(deviation) > 30:
                logger.debug(f"Skipping {symbol}: deviation {deviation:.2f}% exceeds 30% (likely symbol mismatch)")
                return None

            # Alert if deviation exceeds threshold
            if abs(deviation) >= threshold:
                direction = "↑" if deviation > 0 else "↓"
                emoji = "📈" if deviation > 0 else "📉"

                message = (
                    f"{emoji} *TRADE OPPORTUNITY*\n"
                    f"*{symbol}* @ Lighter\n"
                    f"Last Trade: `${lighter_price:.2f}`\n"
                    f"Mark Price: `${binance_price:.2f}`\n"
                    f"Deviation: *{direction}{abs(deviation):.2f}%*\n"
                    f"🔗 https://app.lighter.xyz/trade/{symbol}"
                )
                return (f"LT-{symbol}", message)

            return None

        except Exception as e:
            logger.error(f"Error checking market {symbol}: {e}")
            return None

    def check_hyperliquid_market(self, symbol: str, hl_data: dict, binance_symbol: str):
        """Check a single Hyperliquid market for bid/ask deviation (synchronous)"""
        try:
            # Skip blacklisted symbols
            if symbol in SYMBOL_BLACKLIST:
                logger.debug(f"Skipping {symbol}: in blacklist")
                return None

            # Get Binance mark price
            binance_price = self.binance_prices.get(binance_symbol)
            if not binance_price:
                logger.debug(f"No Binance price for {binance_symbol}")
                return None

            # Get Hyperliquid bid/ask from pre-fetched data
            best_bid = hl_data.get('best_bid')
            best_ask = hl_data.get('best_ask')

            if not best_bid or not best_ask:
                logger.debug(f"No Hyperliquid bid/ask for {symbol}")
                return None

            # Calculate deviations for bid and ask separately
            bid_deviation = self.calculate_deviation(best_bid, binance_price)
            ask_deviation = self.calculate_deviation(best_ask, binance_price)

            logger.debug(
                f"{symbol}: Bid=${best_bid:.4f} ({bid_deviation:.2f}%), "
                f"Ask=${best_ask:.4f} ({ask_deviation:.2f}%), "
                f"Binance=${binance_price:.4f}"
            )

            # Get threshold (custom or default)
            threshold = CUSTOM_THRESHOLDS.get(symbol, self.deviation_threshold)

            # Skip if either deviation is too large (likely different tokens)
            # But skip this check for symbols with custom thresholds
            if symbol not in CUSTOM_THRESHOLDS and (abs(bid_deviation) > 30 or abs(ask_deviation) > 30):
                logger.debug(f"Skipping {symbol}: deviation exceeds 30% (likely symbol mismatch)")
                return None

            # Check if either bid or ask deviates beyond threshold
            alerts = []

            if abs(bid_deviation) >= threshold:
                direction = "↑" if bid_deviation > 0 else "↓"
                emoji = "📈" if bid_deviation > 0 else "📉"
                message = (
                    f"{emoji} *SELL OPPORTUNITY*\n"
                    f"*{symbol}* @ Hyperliquid\n"
                    f"Best Bid: `${best_bid:.2f}`\n"
                    f"Mark Price: `${binance_price:.2f}`\n"
                    f"Deviation: *{direction}{abs(bid_deviation):.2f}%*\n"
                    f"🔗 https://app.hyperliquid.xyz/trade/{symbol}"
                )
                alerts.append((f"HL-{symbol}-BID", message))

            if abs(ask_deviation) >= threshold:
                direction = "↑" if ask_deviation > 0 else "↓"
                emoji = "📈" if ask_deviation > 0 else "📉"
                message = (
                    f"{emoji} *BUY OPPORTUNITY*\n"
                    f"*{symbol}* @ Hyperliquid\n"
                    f"Best Ask: `${best_ask:.2f}`\n"
                    f"Mark Price: `${binance_price:.2f}`\n"
                    f"Deviation: *{direction}{abs(ask_deviation):.2f}%*\n"
                    f"🔗 https://app.hyperliquid.xyz/trade/{symbol}"
                )
                alerts.append((f"HL-{symbol}-ASK", message))

            return alerts if alerts else None

        except Exception as e:
            logger.error(f"Error checking Hyperliquid market {symbol}: {e}")
            return None

    async def scan_all_markets(self):
        """Scan all markets for price deviations"""
        # Refresh Binance prices (1 API call)
        self.binance_prices = await self.fetch_binance_mark_prices()

        if not self.binance_prices:
            logger.warning("No Binance prices available, skipping scan")
            return

        # Fetch ALL Lighter prices in ONE call
        lighter_prices = await self.fetch_all_lighter_prices()

        # Fetch ALL Hyperliquid prices in ONE call
        hyperliquid_prices = await self.fetch_hyperliquid_prices()

        if not lighter_prices and not hyperliquid_prices:
            logger.warning("No exchange prices available, skipping scan")
            return

        logger.info(f"Scanning {len(lighter_prices)} Lighter + {len(hyperliquid_prices)} Hyperliquid markets...")

        # Check markets synchronously (data already fetched)
        alerts = []

        # Check Lighter markets
        for symbol, lighter_data in lighter_prices.items():
            # Map Lighter symbol to Binance symbol
            binance_symbol = self.get_binance_symbol(symbol)
            if not binance_symbol:
                continue

            # Skip if Binance doesn't have this symbol
            if binance_symbol not in self.binance_prices:
                continue

            # Check for deviation
            result = self.check_market(symbol, lighter_data, binance_symbol)
            if result:
                alerts.append(result)

        # Check Hyperliquid markets
        for symbol, hl_data in hyperliquid_prices.items():
            # Map Hyperliquid symbol to Binance symbol
            binance_symbol = self.get_binance_symbol(symbol)
            if not binance_symbol:
                continue

            # Skip if Binance doesn't have this symbol
            if binance_symbol not in self.binance_prices:
                continue

            # Check for deviation (returns list of alerts or None)
            result = self.check_hyperliquid_market(symbol, hl_data, binance_symbol)
            if result:
                # Result is a list of alerts (bid and/or ask)
                alerts.extend(result)

        # Send all alerts
        for symbol, message in alerts:
            await self.send_alert(symbol, message)

        if alerts:
            logger.info(f"Scan complete - {len(alerts)} alerts triggered")
        else:
            logger.info("Scan complete - no deviations detected")

    async def run(self):
        """Main loop - continuously monitor markets"""
        logger.info(f"Starting Multi-Exchange Price Screener (Optimized)")
        logger.info(f"Monitoring: Lighter.xyz + Hyperliquid vs Binance")
        logger.info(f"Deviation threshold: {self.deviation_threshold}%")
        logger.info(f"Poll interval: {self.poll_interval} seconds")
        logger.info(f"Using bulk endpoints - only 3 API calls per scan (1 Binance + 1 Lighter + 1 Hyperliquid)!")

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
    screener = BinancePriceScreener()
    try:
        await screener.run()
    finally:
        await screener.close()


if __name__ == "__main__":
    asyncio.run(main())

"""
Lighter.xyz Price Screener
Monitors all trading pairs for price deviations between last trade price and mark price
Sends Telegram alerts when deviation exceeds configured threshold
"""

import asyncio
import os
import logging
from datetime import datetime
from typing import Dict, Optional
from dotenv import load_dotenv
import lighter
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


class PriceScreener:
    """Monitor Lighter.xyz markets for price deviations"""

    def __init__(self):
        self.deviation_threshold = float(os.getenv('DEVIATION_THRESHOLD_PERCENT', '5.0'))
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

        # Lighter API client
        self.client = lighter.ApiClient()
        self.order_api = lighter.OrderApi(self.client)

        # Market data cache
        self.markets: Dict[str, dict] = {}

    async def send_alert(self, market_id: str, message: str):
        """Send alert via Telegram and/or console"""
        logger.warning(f"ALERT [{market_id}]: {message}")

        # Check cooldown
        current_time = asyncio.get_event_loop().time()
        if market_id in self.last_alert:
            if current_time - self.last_alert[market_id] < self.alert_cooldown:
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
                self.last_alert[market_id] = current_time
                logger.info(f"Telegram alert sent for {market_id}")
            except TelegramError as e:
                logger.error(f"Failed to send Telegram message: {e}")

    async def fetch_markets(self):
        """Fetch all available markets/orderbooks"""
        try:
            orderbooks_response = await self.order_api.order_books()

            # Handle the OrderBooks object - it might have a data or orderbooks attribute
            if hasattr(orderbooks_response, 'data'):
                orderbooks = orderbooks_response.data
            elif hasattr(orderbooks_response, 'order_books'):
                orderbooks = orderbooks_response.order_books
            elif hasattr(orderbooks_response, '__dict__'):
                # Try to get the actual list from the object
                orderbooks = list(orderbooks_response.__dict__.values())[0] if orderbooks_response.__dict__ else []
            else:
                orderbooks = orderbooks_response

            logger.info(f"Fetched {len(orderbooks) if isinstance(orderbooks, list) else 'unknown'} markets")
            logger.info(f"Orderbooks type: {type(orderbooks)}, is list: {isinstance(orderbooks, list)}")

            if isinstance(orderbooks, list):
                logger.info(f"Processing {len(orderbooks)} orderbooks...")
                for i, orderbook in enumerate(orderbooks):
                    if i < 2:  # Log first 2 for debugging
                        logger.info(f"Orderbook {i}: type={type(orderbook)}, value={orderbook}")
                    # Extract data from dict or object
                    if isinstance(orderbook, dict):
                        market_id = orderbook.get('market_id') or orderbook.get('order_book_id') or orderbook.get('id')
                        symbol = orderbook.get('symbol', f'Market_{market_id}')
                    else:
                        market_id = getattr(orderbook, 'market_id', None) or getattr(orderbook, 'order_book_id', None) or getattr(orderbook, 'id', None)
                        symbol = getattr(orderbook, 'symbol', f'Market_{market_id}')

                    if market_id:
                        # Log first few to see the data structure
                        if len(self.markets) < 3:
                            logger.info(f"Sample market data: id={market_id}, symbol={symbol}, type={type(orderbook)}")
                            if isinstance(orderbook, dict):
                                logger.info(f"Fields: {list(orderbook.keys())}")
                            else:
                                logger.info(f"Attributes: {dir(orderbook)}")

                        self.markets[str(market_id)] = {
                            'symbol': symbol,
                            'data': orderbook,
                            'numeric_id': market_id
                        }

            logger.info(f"Populated {len(self.markets)} markets into dictionary")
            return self.markets
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    async def fetch_recent_trades(self, market_id: str) -> Optional[dict]:
        """Fetch most recent trade for a market"""
        try:
            # Use recent_trades endpoint to get latest trades
            trades = await self.order_api.recent_trades(market_id=market_id, limit=1)
            if trades and len(trades) > 0:
                return trades[0]
            return None
        except Exception as e:
            logger.debug(f"Error fetching trades for {market_id}: {e}")
            return None

    async def get_market_stats(self, market_id: str) -> Optional[dict]:
        """
        Get market statistics including mark price
        Note: This uses REST API. For real-time monitoring, WebSocket would be better.
        """
        try:
            # Try to get orderbook details which may include mark price
            # If not available via REST, we'll need to use WebSocket
            orderbook_details = await self.order_api.order_book_details(market_id=market_id)
            return orderbook_details
        except Exception as e:
            logger.debug(f"Error fetching market stats for {market_id}: {e}")
            return None

    def calculate_deviation(self, last_price: float, mark_price: float) -> float:
        """Calculate percentage deviation between last price and mark price"""
        if mark_price == 0:
            return 0.0
        return abs((last_price - mark_price) / mark_price * 100)

    async def check_market(self, market_id: str, market_info: dict):
        """Check a single market for price deviation"""
        try:
            # Use numeric ID for API calls
            numeric_id = market_info.get('numeric_id', market_id)

            # Get recent trade
            recent_trade = await self.fetch_recent_trades(numeric_id)
            if not recent_trade:
                logger.debug(f"No recent trades for {market_id}")
                return

            # Extract last trade price
            last_price = float(recent_trade.get('price', 0))
            if last_price == 0:
                logger.debug(f"Invalid price for {market_id}")
                return

            # Get market stats for mark price
            # Note: Mark price might not be available via REST API
            # In that case, we compare against recent average or use WebSocket
            market_stats = await self.get_market_stats(numeric_id)

            # Try to extract mark price from various possible fields
            mark_price = None
            if market_stats:
                # Check common field names for mark price
                for field in ['mark_price', 'markPrice', 'fair_price', 'fairPrice', 'index_price', 'indexPrice']:
                    if field in market_stats:
                        mark_price = float(market_stats[field])
                        break

            # If mark price not available, use orderbook mid price as approximation
            if mark_price is None:
                if market_stats and 'best_bid' in market_stats and 'best_ask' in market_stats:
                    best_bid = float(market_stats['best_bid'])
                    best_ask = float(market_stats['best_ask'])
                    mark_price = (best_bid + best_ask) / 2
                else:
                    logger.debug(f"No mark price available for {market_id}, skipping")
                    return

            # Calculate deviation
            deviation = self.calculate_deviation(last_price, mark_price)

            symbol = market_info.get('symbol', market_id)

            logger.debug(
                f"{symbol}: Last=${last_price:.4f}, Mark=${mark_price:.4f}, "
                f"Deviation={deviation:.2f}%"
            )

            # Alert if deviation exceeds threshold
            if deviation >= self.deviation_threshold:
                direction = "above" if last_price > mark_price else "below"
                message = (
                    f"*Market:* {symbol}\n"
                    f"*Last Trade Price:* ${last_price:.4f}\n"
                    f"*Mark Price:* ${mark_price:.4f}\n"
                    f"*Deviation:* {deviation:.2f}% {direction}\n"
                    f"*Threshold:* {self.deviation_threshold}%\n"
                    f"*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                await self.send_alert(market_id, message)

        except Exception as e:
            logger.error(f"Error checking market {market_id}: {e}")

    async def scan_all_markets(self):
        """Scan all markets for price deviations"""
        if not self.markets:
            await self.fetch_markets()

        logger.info(f"Scanning {len(self.markets)} markets...")

        # Check all markets concurrently
        tasks = [
            self.check_market(market_id, market_info)
            for market_id, market_info in self.markets.items()
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Scan complete")

    async def run(self):
        """Main loop - continuously monitor markets"""
        logger.info(f"Starting Price Screener")
        logger.info(f"Deviation threshold: {self.deviation_threshold}%")
        logger.info(f"Poll interval: {self.poll_interval} seconds")

        try:
            # Initial market fetch
            await self.fetch_markets()

            # Continuous monitoring loop
            while True:
                try:
                    await self.scan_all_markets()
                except Exception as e:
                    logger.error(f"Error during scan: {e}")

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
    screener = PriceScreener()
    try:
        await screener.run()
    finally:
        await screener.close()


if __name__ == "__main__":
    asyncio.run(main())

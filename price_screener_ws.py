"""
Lighter.xyz Price Screener (WebSocket Version)
Real-time monitoring using Lighter SDK's WsClient
Monitors price deviations between last trade price and mark price
"""

import asyncio
import os
import logging
from datetime import datetime
from typing import Dict, List
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


class WebSocketPriceScreener:
    """Real-time monitor for Lighter.xyz markets using SDK's WsClient"""

    def __init__(self):
        self.deviation_threshold = float(os.getenv('DEVIATION_THRESHOLD_PERCENT', '5.0'))

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
        self.last_alert: Dict[int, float] = {}
        self.alert_cooldown = 300  # 5 minutes between alerts for same pair

        # Lighter API client for initial market fetch
        self.api_client = lighter.ApiClient()
        self.order_api = lighter.OrderApi(self.api_client)

        # Market info cache (market_id -> market details)
        self.markets: Dict[int, dict] = {}

        # Store last trade prices from order book updates
        self.last_prices: Dict[int, float] = {}

    async def send_alert(self, market_id: int, message: str):
        """Send alert via Telegram and/or console"""
        logger.warning(f"ALERT [Market {market_id}]: {message}")

        # Check cooldown
        loop = asyncio.get_event_loop()
        current_time = loop.time()

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
                logger.info(f"Telegram alert sent for market {market_id}")
            except TelegramError as e:
                logger.error(f"Failed to send Telegram message: {e}")

    def calculate_deviation(self, last_price: float, mark_price: float) -> float:
        """Calculate percentage deviation between last price and mark price"""
        if mark_price == 0:
            return 0.0
        return abs((last_price - mark_price) / mark_price * 100)

    def on_order_book_update(self, market_id: int, order_book):
        """Callback when order book is updated"""
        try:
            # Log the structure to understand what data we receive
            if market_id not in self.last_prices:
                logger.info(f"First update for market {market_id}")
                logger.info(f"OrderBook type: {type(order_book)}")
                logger.info(f"OrderBook data: {order_book}")

                # Try to log attributes if it's an object
                if hasattr(order_book, '__dict__'):
                    logger.info(f"OrderBook attributes: {order_book.__dict__}")

            # Extract relevant data from order book
            # The exact structure depends on what Lighter SDK provides
            # Common fields might include: best_bid, best_ask, last_price, mark_price, etc.

            mark_price = None
            last_price = None

            # Try different possible attribute/key names
            if isinstance(order_book, dict):
                mark_price = order_book.get('mark_price') or order_book.get('markPrice')
                last_price = order_book.get('last_price') or order_book.get('lastPrice') or order_book.get('last_trade_price')

                # If no mark price, calculate from mid price
                if not mark_price and order_book.get('best_bid') and order_book.get('best_ask'):
                    best_bid = float(order_book['best_bid'])
                    best_ask = float(order_book['best_ask'])
                    mark_price = (best_bid + best_ask) / 2
            else:
                # It's an object, try attributes
                mark_price = getattr(order_book, 'mark_price', None) or getattr(order_book, 'markPrice', None)
                last_price = (getattr(order_book, 'last_price', None) or
                            getattr(order_book, 'lastPrice', None) or
                            getattr(order_book, 'last_trade_price', None))

                # If no mark price, calculate from mid price
                if not mark_price:
                    best_bid = getattr(order_book, 'best_bid', None) or getattr(order_book, 'bestBid', None)
                    best_ask = getattr(order_book, 'best_ask', None) or getattr(order_book, 'bestAsk', None)
                    if best_bid and best_ask:
                        mark_price = (float(best_bid) + float(best_ask)) / 2

            if not mark_price or not last_price:
                logger.debug(f"Missing price data for market {market_id}")
                return

            mark_price = float(mark_price)
            last_price = float(last_price)

            if mark_price == 0 or last_price == 0:
                return

            # Store last price
            self.last_prices[market_id] = last_price

            # Calculate deviation
            deviation = self.calculate_deviation(last_price, mark_price)

            symbol = self.markets.get(market_id, {}).get('symbol', f'Market_{market_id}')

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

                # Need to schedule the async alert in the event loop
                asyncio.create_task(self.send_alert(market_id, message))

        except Exception as e:
            logger.error(f"Error processing order book update for market {market_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def fetch_all_markets(self) -> List[int]:
        """Fetch all available markets and return list of market IDs"""
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

            market_ids = []

            if isinstance(orderbooks, list):
                for orderbook in orderbooks:
                    # Extract market_id
                    if isinstance(orderbook, dict):
                        market_id = orderbook.get('market_id') or orderbook.get('order_book_id') or orderbook.get('id')
                        symbol = orderbook.get('symbol', f'Market_{market_id}')
                    else:
                        market_id = getattr(orderbook, 'market_id', None) or getattr(orderbook, 'order_book_id', None) or getattr(orderbook, 'id', None)
                        symbol = getattr(orderbook, 'symbol', f'Market_{market_id}')

                    if market_id is not None:
                        market_id = int(market_id)
                        market_ids.append(market_id)
                        self.markets[market_id] = {
                            'symbol': symbol,
                            'data': orderbook
                        }

            logger.info(f"Fetched {len(market_ids)} markets")
            return market_ids

        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    async def run(self):
        """Main entry point"""
        logger.info(f"Starting WebSocket Price Screener (SDK Version)")
        logger.info(f"Deviation threshold: {self.deviation_threshold}%")

        try:
            # First, fetch all available markets
            logger.info("Fetching all markets...")
            market_ids = await self.fetch_all_markets()

            if not market_ids:
                logger.error("No markets found! Cannot start WebSocket client.")
                return

            logger.info(f"Subscribing to {len(market_ids)} markets via WebSocket...")

            # Create WebSocket client with all market IDs
            # Note: WsClient.run() is blocking, so we run it in the current async context
            ws_client = lighter.WsClient(
                order_book_ids=market_ids,
                on_order_book_update=self.on_order_book_update
            )

            logger.info("WebSocket client created, starting stream...")

            # Run the WebSocket client (this is a blocking call)
            ws_client.run()

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"Error in WebSocket screener: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            await self.api_client.close()


async def main():
    """Entry point"""
    screener = WebSocketPriceScreener()
    await screener.run()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import lighter

async def main():
    client = lighter.ApiClient()
    order_api = lighter.OrderApi(client)
    
    # 1. Check exchange_stats for MSTR, XPL, AERO
    print("=== EXCHANGE STATS ===")
    stats = await order_api.exchange_stats()
    
    targets = ["MSTR", "XPL", "AERO"]
    
    if hasattr(stats, "order_book_stats"):
        for stat in stats.order_book_stats:
            symbol = getattr(stat, "symbol", None)
            if symbol in targets:
                print()
                print(symbol + ":")
                for key, val in stat.__dict__.items():
                    if not key.startswith("_"):
                        print("  " + str(key) + ": " + str(val))
    
    # 2. Check order_books for these symbols - look for bid/ask data
    print()
    print()
    print("=== ORDER BOOKS ===")
    orderbooks = await order_api.order_books()
    
    if hasattr(orderbooks, "data"):
        obs = orderbooks.data
    elif hasattr(orderbooks, "order_books"):
        obs = orderbooks.order_books
    else:
        obs = orderbooks
    
    market_ids = {}
    if isinstance(obs, list):
        for ob in obs:
            sym = getattr(ob, "symbol", "") if not isinstance(ob, dict) else ob.get("symbol", "")
            mid = getattr(ob, "market_id", None) if not isinstance(ob, dict) else ob.get("market_id", None)
            if sym in targets:
                market_ids[sym] = mid
                print()
                print(sym + " (market_id=" + str(mid) + "):")
                if hasattr(ob, "__dict__"):
                    for key, val in ob.__dict__.items():
                        if not key.startswith("_"):
                            print("  " + str(key) + ": " + str(val))
    
    # 3. Try to get actual orderbook depth / best bid ask
    print()
    print()
    print("=== TRYING ORDERBOOK DEPTH ===")
    # Check what methods are available on order_api
    methods = [m for m in dir(order_api) if not m.startswith("_")]
    print("Available methods: " + str(methods))
    
    # Try different methods to get actual bid/ask
    for sym, mid in market_ids.items():
        print()
        print("Trying to get depth for " + sym + " (market_id=" + str(mid) + ")...")
        
        # Try order_book (singular)
        try:
            ob = await order_api.order_book(market_id=mid)
            print("  order_book() result type: " + str(type(ob)))
            if hasattr(ob, "__dict__"):
                for key, val in ob.__dict__.items():
                    if not key.startswith("_"):
                        if isinstance(val, list) and len(val) > 5:
                            print("    " + str(key) + ": [" + str(val[0]) + ", " + str(val[1]) + ", ...] (" + str(len(val)) + " items)")
                        else:
                            print("    " + str(key) + ": " + str(val))
        except Exception as e:
            print("  order_book() failed: " + str(e))
        
        # Try orders
        try:
            orders = await order_api.orders(market_id=mid)
            print("  orders() result type: " + str(type(orders)))
            if hasattr(orders, "__dict__"):
                for key, val in orders.__dict__.items():
                    if not key.startswith("_"):
                        if isinstance(val, list):
                            print("    " + str(key) + ": " + str(len(val)) + " items")
                            if len(val) > 0:
                                first = val[0]
                                if hasattr(first, "__dict__"):
                                    print("      first item: " + str(first.__dict__))
                                else:
                                    print("      first item: " + str(first))
                        else:
                            print("    " + str(key) + ": " + str(val))
        except Exception as e:
            print("  orders() failed: " + str(e))
    
    # 4. Try to find best bid/ask or recent trades
    print()
    print()
    print("=== CHECKING FOR TRADE/CANDLE ENDPOINTS ===")
    # Check if there are candle or trade endpoints
    api_methods = [m for m in dir(lighter) if not m.startswith("_")]
    print("lighter module contents: " + str(api_methods))
    
    # Check for other API classes
    for name in api_methods:
        obj = getattr(lighter, name)
        if isinstance(obj, type) and "Api" in name:
            sub_methods = [m for m in dir(obj) if not m.startswith("_") and callable(getattr(obj, m, None))]
            print("  " + name + " methods: " + str(sub_methods))
    
    await client.close()

asyncio.run(main())

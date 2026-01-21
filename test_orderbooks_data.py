"""
Test what data we get from order_books() endpoint
"""

import asyncio
import lighter
import json


async def test_orderbooks():
    client = lighter.ApiClient()
    order_api = lighter.OrderApi(client)

    print("Fetching all orderbooks...")
    orderbooks_response = await order_api.order_books()

    # Parse the response
    if hasattr(orderbooks_response, 'data'):
        orderbooks = orderbooks_response.data
    elif hasattr(orderbooks_response, 'order_books'):
        orderbooks = orderbooks_response.order_books
    elif hasattr(orderbooks_response, '__dict__'):
        orderbooks = list(orderbooks_response.__dict__.values())[0]
    else:
        orderbooks = orderbooks_response

    print(f"\nTotal orderbooks: {len(orderbooks) if isinstance(orderbooks, list) else 'unknown'}")
    print(f"Type: {type(orderbooks)}")

    if isinstance(orderbooks, list) and len(orderbooks) > 0:
        print("\n=== First orderbook sample ===")
        first = orderbooks[0]

        if isinstance(first, dict):
            print(json.dumps(first, indent=2))
            print(f"\nAvailable fields: {list(first.keys())}")
        else:
            print(f"Type: {type(first)}")
            print(f"Attributes: {dir(first)}")

            # Try to print some attributes
            for attr in ['market_id', 'symbol', 'volume_24h', 'last_price', 'mark_price']:
                if hasattr(first, attr):
                    print(f"{attr}: {getattr(first, attr)}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(test_orderbooks())

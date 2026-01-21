"""
Test if there's an endpoint that gives volume/stats for all markets at once
"""

import asyncio
import lighter
import json


async def test_stats():
    client = lighter.ApiClient()
    order_api = lighter.OrderApi(client)

    print("=== Testing different endpoints ===\n")

    # Try to find methods that might return bulk stats
    print("Available methods on OrderApi:")
    methods = [m for m in dir(order_api) if not m.startswith('_')]
    for method in methods:
        print(f"  - {method}")

    # Test if there's a stats endpoint
    try:
        print("\n=== Testing order_book_details for one market ===")
        details = await order_api.order_book_details(market_id=2)  # SOL

        print(f"Type: {type(details)}")

        if isinstance(details, dict):
            print(f"Keys: {list(details.keys())}")

            # Look for volume-related fields
            for key in details.keys():
                if 'volume' in key.lower() or 'trade' in key.lower():
                    print(f"  {key}: {details[key]}")
        else:
            print(f"Attributes: {dir(details)}")
            for attr in dir(details):
                if 'volume' in attr.lower() or 'trade' in attr.lower() or 'stat' in attr.lower():
                    if hasattr(details, attr):
                        print(f"  {attr}: {getattr(details, attr)}")

    except Exception as e:
        print(f"Error: {e}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(test_stats())

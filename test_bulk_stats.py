"""
Test if exchange_stats returns data for all markets at once
"""

import asyncio
import lighter
import json


async def test_exchange_stats():
    client = lighter.ApiClient()
    order_api = lighter.OrderApi(client)

    print("=== Testing exchange_stats endpoint ===\n")

    try:
        stats = await order_api.exchange_stats()

        print(f"Type: {type(stats)}")
        print(f"\nFull response:")
        print(stats)

        if hasattr(stats, 'to_dict'):
            stats_dict = stats.to_dict()
            print(f"\nAs dict:")
            print(json.dumps(stats_dict, indent=2, default=str))

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    await client.close()


if __name__ == "__main__":
    asyncio.run(test_exchange_stats())

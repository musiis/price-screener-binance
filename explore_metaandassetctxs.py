"""
Explore metaAndAssetCtxs endpoint to see if it has bid/ask data
"""

import requests
import json

url = "https://api.hyperliquid.xyz/info"
data = {"type": "metaAndAssetCtxs"}

response = requests.post(url, json=data, timeout=10)
meta_data = response.json()

print(f"Response type: {type(meta_data)}")
print(f"Response length: {len(meta_data)}")

# meta_data[0] = universe (market definitions)
# meta_data[1] = contexts (market data)

universe = meta_data[0]['universe']
contexts = meta_data[1]

print(f"\nTotal markets: {len(universe)}")
print(f"Total contexts: {len(contexts)}")

# Check first market in detail
print("\n=== First Market (BTC) ===")
print(f"Universe entry: {json.dumps(universe[0], indent=2)}")
print(f"\nContext entry: {json.dumps(contexts[0], indent=2)}")

# Check if there are any fields that might be bid/ask
print("\n=== All available fields in context ===")
for key in contexts[0].keys():
    print(f"  - {key}: {contexts[0][key]}")

# Check a few more markets to see the pattern
print("\n=== Sample of 5 markets ===")
for i in range(min(5, len(universe))):
    symbol = universe[i]['name']
    ctx = contexts[i]

    mark_px = ctx.get('markPx', 'N/A')
    mid_px = ctx.get('midPx', 'N/A')
    oracle_px = ctx.get('oraclePx', 'N/A')

    print(f"\n{symbol}:")
    print(f"  markPx: {mark_px}")
    print(f"  midPx: {mid_px}")
    print(f"  oraclePx: {oracle_px}")

    # Check for any bid/ask related fields
    for key in ctx.keys():
        if 'bid' in key.lower() or 'ask' in key.lower() or 'book' in key.lower():
            print(f"  {key}: {ctx[key]}")

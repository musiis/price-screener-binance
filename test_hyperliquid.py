"""
Test Hyperliquid API to see what data we can get
"""

import requests
import json

# Test 1: Get all mid prices (simplest)
print("=== Testing allMids endpoint ===")
url = "https://api.hyperliquid.xyz/info"
data = {"type": "allMids"}

response = requests.post(url, json=data)
all_mids = response.json()

print(f"\nTotal markets: {len(all_mids)}")
print("\nFirst 10 markets:")
for symbol, price in list(all_mids.items())[:10]:
    print(f"  {symbol}: ${price}")

# Test 2: Get comprehensive market data
print("\n\n=== Testing metaAndAssetCtxs endpoint ===")
data = {"type": "metaAndAssetCtxs"}

response = requests.post(url, json=data)
meta_data = response.json()

print(f"\nResponse type: {type(meta_data)}")

if isinstance(meta_data, list) and len(meta_data) >= 2:
    print(f"Response length: {len(meta_data)}")
    universe = meta_data[0].get('universe', [])
    contexts = meta_data[1]

    print(f"\nTotal assets in universe: {len(universe)}")
    print("\nFirst 5 assets:")
    for i, asset in enumerate(universe[:5]):
        print(f"  {i}: {asset}")

    print(f"\nTotal contexts: {len(contexts)}")
    print("\nFirst 3 contexts:")
    for i, ctx in enumerate(contexts[:3]):
        print(f"  Context {i}:")
        for key, value in ctx.items():
            print(f"    {key}: {value}")

"""
Check what volumes Hyperliquid markets have
"""

import requests

url = "https://api.hyperliquid.xyz/info"
data = {"type": "metaAndAssetCtxs"}

response = requests.post(url, json=data, timeout=10)
meta_data = response.json()

universe = meta_data[0]['universe']
contexts = meta_data[1]

print("Hyperliquid 24h volumes:\n")

volumes = []
for i, market in enumerate(universe):  # Check ALL markets
    if i >= len(contexts):
        break

    symbol = market.get('name')
    ctx = contexts[i]
    day_volume = ctx.get('dayNtlVlm')

    if day_volume:
        volumes.append((symbol, float(day_volume)))

# Sort by volume
volumes.sort(key=lambda x: x[1], reverse=True)

print("Top 20 by volume:")
for symbol, vol in volumes[:20]:
    print(f"  {symbol:8s}: ${vol:,.0f}")

print("\nBottom 10 by volume:")
for symbol, vol in volumes[-10:]:
    print(f"  {symbol:8s}: ${vol:,.0f}")

print(f"\nMarkets with > $250k volume: {len([v for s,v in volumes if v > 250000])}")
print(f"Markets with > $100k volume: {len([v for s,v in volumes if v > 100000])}")
print(f"Markets with > $50k volume: {len([v for s,v in volumes if v > 50000])}")
print(f"Total markets checked: {len(volumes)}")

# Show markets below $250k
below_250k = [(s, v) for s, v in volumes if v < 250000]
print(f"\n\nMarkets with < $250k volume ({len(below_250k)} markets):")
print("=" * 60)
for symbol, vol in below_250k:
    print(f"  {symbol:10s}: ${vol:>12,.0f}")

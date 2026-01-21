"""
Verify if impactPxs is [bid, ask] by checking if midPx = average
"""

import requests

url = "https://api.hyperliquid.xyz/info"
data = {"type": "metaAndAssetCtxs"}

response = requests.post(url, json=data, timeout=10)
meta_data = response.json()

universe = meta_data[0]['universe']
contexts = meta_data[1]

print("Verifying if impactPxs = [bid, ask]:\n")
print("Checking if midPx = (impactPxs[0] + impactPxs[1]) / 2\n")

matches = 0
total = 0

for i in range(min(20, len(contexts))):
    symbol = universe[i]['name']
    ctx = contexts[i]

    mid_px = ctx.get('midPx')
    impact_pxs = ctx.get('impactPxs')

    if mid_px is None or impact_pxs is None or len(impact_pxs) != 2:
        continue

    total += 1
    calculated_mid = (float(impact_pxs[0]) + float(impact_pxs[1])) / 2

    # Check if they match (within small tolerance)
    if abs(float(mid_px) - calculated_mid) < 0.01:
        matches += 1
        status = "OK"
    else:
        status = "MISMATCH"

    print(f"{symbol:8s}: impactPxs={impact_pxs}, midPx={mid_px}, calculated={(float(impact_pxs[0]) + float(impact_pxs[1])) / 2:.2f} [{status}]")

print(f"\n{matches}/{total} matched → impactPxs is likely [bid, ask] or [sell_impact, buy_impact]")

# Check documentation hint
print("\n=== Interpretation ===")
print("impactPxs[0] = likely best_bid (or impact price for selling)")
print("impactPxs[1] = likely best_ask (or impact price for buying)")

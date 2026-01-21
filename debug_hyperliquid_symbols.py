"""
Debug: Check what symbols Hyperliquid actually returns
"""

import requests
import json

# Get all mids from Hyperliquid
url = "https://api.hyperliquid.xyz/info"
data = {"type": "allMids"}

response = requests.post(url, json=data)
all_mids = response.json()

# Filter perps only (exclude spot markets starting with @)
perp_symbols = [s for s in all_mids.keys() if not s.startswith('@')]

print(f"Total Hyperliquid perp symbols: {len(perp_symbols)}")
print(f"\nFirst 30 symbols:")
for i, symbol in enumerate(sorted(perp_symbols)[:30]):
    price = all_mids[symbol]
    print(f"  {symbol}: ${price}")

# Check for some suspicious symbols (user reported these)
suspicious = ['STRAX', 'STG', 'RDNT', 'AI', 'PIXEL', 'NTRN', 'OMNI']
print(f"\n\nChecking suspicious symbols:")
for symbol in suspicious:
    if symbol in all_mids:
        print(f"  [OK] {symbol}: ${all_mids[symbol]} (EXISTS in Hyperliquid)")
    else:
        print(f"  [NO] {symbol}: NOT FOUND")

# Get Binance symbols for comparison
print(f"\n\nFetching Binance futures symbols...")
binance_response = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex")
binance_data = binance_response.json()
binance_symbols = [item['symbol'] for item in binance_data]

print(f"Total Binance futures: {len(binance_symbols)}")

# Check if suspicious symbols exist on Binance
print(f"\nChecking if suspicious symbols exist on Binance:")
for symbol in suspicious:
    binance_symbol = f"{symbol}USDT"
    if binance_symbol in binance_symbols:
        # Find the price
        price_data = next((item for item in binance_data if item['symbol'] == binance_symbol), None)
        if price_data:
            print(f"  [OK] {binance_symbol}: ${price_data['markPrice']} (EXISTS in Binance)")
    else:
        print(f"  [NO] {binance_symbol}: NOT FOUND")

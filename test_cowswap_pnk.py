#!/usr/bin/env python3
"""
Test script to sell 1 PNK for sDAI using CowSwap on Gnosis Chain.
"""
import os
import time
from decimal import Decimal

from src.helpers.cowswap_trade import build_order, sign_order, submit_order, get_order

# Token addresses on Gnosis Chain
PNK_TOKEN_ADDRESS = "0x37b60f4E9A31A64cCc0024dce7D0fD07eAA0F7B3"  # PNK on Gnosis
SDAI_TOKEN_ADDRESS = os.environ["SDAI_TOKEN_ADDRESS"]

# Build order to sell 1 PNK for sDAI
order = build_order(
    sell_token=PNK_TOKEN_ADDRESS,
    buy_token=SDAI_TOKEN_ADDRESS,
    sell_amount=Decimal("1"),  # 1 PNK
    # No buy_amount specified - let CowSwap find the best price
)

print(f"Order details:")
print(f"  Sell: 1 PNK ({PNK_TOKEN_ADDRESS})")
print(f"  Buy: sDAI ({SDAI_TOKEN_ADDRESS})")
print(f"  Valid for: {order['validTo'] - int(time.time())} seconds")

# Sign the order
signature = sign_order(order)
print(f"\nOrder signed with signature: {signature[:20]}...")

# Submit to CowSwap
try:
    uid = submit_order(order, signature)
    print(f"\nOrder submitted successfully!")
    print(f"Order UID: {uid}")
    print(f"View on CowSwap Explorer: https://explorer.cow.fi/gc/orders/{uid}")
    
    # Wait a bit and check status
    print("\nWaiting 10 seconds before checking status...")
    time.sleep(10)
    
    status = get_order(uid)
    print(f"\nOrder status: {status.get('status', 'unknown')}")
    if 'executedSellAmount' in status:
        print(f"Executed amount: {status['executedSellAmount']}")
        
except Exception as e:
    print(f"\nError submitting order: {e}")
    print("Make sure you have:")
    print("1. PNK tokens in your wallet")
    print("2. Approved CowSwap settlement contract for PNK")
#!/usr/bin/env python3
"""
Minimal EIP-7702 test for Gnosis Chain
======================================
"""

import os
import sys
from web3 import Web3
from eth_account import Account
from eth_utils import to_hex

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.helpers.eip7702_builder import EIP7702TransactionBuilder

# Load environment
from dotenv import load_dotenv
load_dotenv('.env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF')

# Setup
rpc_url = os.getenv("RPC_URL", "https://rpc.gnosischain.com")
private_key = os.getenv("PRIVATE_KEY")

print(f"Testing EIP-7702 on Gnosis Chain")
print(f"RPC: {rpc_url}")

# Connect
w3 = Web3(Web3.HTTPProvider(rpc_url))
account = Account.from_key(private_key)

print(f"Account: {account.address}")
print(f"Balance: {w3.from_wei(w3.eth.get_balance(account.address), 'ether')} xDAI")

# Build minimal EIP-7702 tx
builder = EIP7702TransactionBuilder(w3, "0x0000000000000000000000000000000000000001")
builder.add_call(account.address, 0, b'')  # Self call with empty data

# Get proper gas price for Gnosis
gas_price = w3.eth.gas_price
if gas_price == 0:
    gas_price = w3.to_wei(1, 'gwei')  # Gnosis minimum

print(f"Gas price: {w3.from_wei(gas_price, 'gwei')} gwei")

try:
    # Build tx
    tx = builder.build_transaction(account, gas_params={
        'gas': 200000,
        'maxFeePerGas': gas_price * 2,
        'maxPriorityFeePerGas': gas_price
    })
    
    print(f"\nTransaction built:")
    print(f"  Type: {tx['type']}")
    print(f"  To: {tx['to']}")
    print(f"  Gas: {tx['gas']:,}")
    
    # Sign and send
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    
    print(f"\n✅ SUCCESS! Transaction sent:")
    print(f"Hash: {to_hex(tx_hash)}")
    print(f"View: https://gnosisscan.io/tx/{to_hex(tx_hash)}")
    
    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"\nStatus: {'Success' if receipt.status == 1 else 'Failed'}")
    print(f"Block: {receipt.blockNumber}")
    print(f"Gas used: {receipt.gasUsed:,}")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    if "unsupported transaction type" in str(e).lower():
        print("\nEIP-7702 might not be supported by this RPC endpoint.")
        print("Try using the official Gnosis RPC: https://rpc.gnosischain.com")
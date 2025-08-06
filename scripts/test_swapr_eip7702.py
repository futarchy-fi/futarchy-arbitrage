#!/usr/bin/env python3
"""
Test Swapr swap with EIP-7702 bundled transaction.
Focuses on getting the Swapr interface encoding correct.
"""

import os
import sys
import time
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from eth_abi import encode

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.bundle_helpers import (
    encode_approval_call,
    calculate_bundle_gas_params,
    get_token_balance
)

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

IMPLEMENTATION_ADDRESS = os.environ.get("FUTARCHY_BATCH_EXECUTOR_ADDRESS", "0x65eb5a03635c627a0f254707712812B234753F31")

# Contracts
SWAPR_ROUTER = os.environ["SWAPR_ROUTER_ADDRESS"]

# Tokens
SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]
SDAI_YES = os.environ["SWAPR_SDAI_YES_ADDRESS"]
SDAI_NO = os.environ["SWAPR_SDAI_NO_ADDRESS"]
COMPANY_YES = os.environ["SWAPR_GNO_YES_ADDRESS"]
COMPANY_NO = os.environ["SWAPR_GNO_NO_ADDRESS"]


def encode_swapr_exact_in_simple(
    router: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    amount_out_min: int,
    recipient: str
):
    """
    Encode a simple Swapr exactInputSingle swap.
    Uses the actual Swapr interface on Gnosis.
    """
    deadline = int(time.time()) + 600
    
    # Based on the actual Swapr router interface from swapr_swap.py
    # The params tuple format: (tokenIn, tokenOut, recipient, deadline, amountIn, amountOutMin, sqrtPriceLimit)
    params = (
        Web3.to_checksum_address(token_in),
        Web3.to_checksum_address(token_out),
        Web3.to_checksum_address(recipient),
        deadline,
        amount_in,
        amount_out_min,
        0  # sqrtPriceLimitX96
    )
    
    # Function selector for exactInputSingle
    # The actual function signature based on swapr_swap.py
    from eth_utils import keccak
    function_selector = keccak(text="exactInputSingle((address,address,address,uint256,uint256,uint256,uint160))")[:4]
    
    # Encode the parameters directly as a tuple
    encoded_params = encode(
        ['(address,address,address,uint256,uint256,uint256,uint160)'],
        [params]
    )
    
    return {
        'target': Web3.to_checksum_address(router),
        'value': 0,
        'data': function_selector + encoded_params
    }


def test_swapr_swap(amount_sdai: float = 0.001, swap_type: str = "YES"):
    """
    Test a single Swapr swap with EIP-7702.
    
    Args:
        amount_sdai: Amount of sDAI to swap (in ether units)
        swap_type: "YES" or "NO" - which conditional token to swap
    """
    print(f"=== Testing Swapr {swap_type} Swap with EIP-7702 ===\n")
    
    # Determine tokens based on swap type
    if swap_type.upper() == "YES":
        token_in = SDAI_YES
        token_out = COMPANY_YES
        token_name = "YES"
    else:
        token_in = SDAI_NO
        token_out = COMPANY_NO
        token_name = "NO"
    
    # Check balance
    balance = get_token_balance(w3, token_in, account.address)
    print(f"Current {token_name} conditional sDAI balance: {w3.from_wei(balance, 'ether')}")
    
    if balance == 0:
        print(f"\n❌ No {token_name} conditional sDAI to swap!")
        print("Please run a split operation first to get conditional tokens.")
        return
    
    # Amount to swap (use smaller of balance or requested amount)
    amount_wei = min(w3.to_wei(amount_sdai, 'ether'), balance)
    print(f"Will swap: {w3.from_wei(amount_wei, 'ether')} {token_name} conditional sDAI")
    
    # Build the swap call
    swap_call = encode_swapr_exact_in_simple(
        SWAPR_ROUTER,
        token_in,
        token_out,
        amount_wei,
        0,  # amount_out_min (0 for test, should calculate properly in production)
        account.address
    )
    
    # Build approval if needed
    from eth_abi import decode
    # Check allowance
    allowance_selector = Web3.keccak(text="allowance(address,address)")[:4]
    allowance_data = allowance_selector + encode(['address', 'address'], [account.address, SWAPR_ROUTER])
    allowance_result = w3.eth.call({'to': token_in, 'data': allowance_data})
    current_allowance = int.from_bytes(allowance_result, 'big')
    
    calls = []
    if current_allowance < amount_wei:
        print(f"Setting approval for {token_name} conditional sDAI...")
        approval_call = encode_approval_call(token_in, SWAPR_ROUTER, 2**256 - 1)
        calls.append(approval_call)
    
    calls.append(swap_call)
    
    # Build EIP-7702 transaction
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    for call in calls:
        builder.add_call(call['target'], call['value'], call['data'])
    
    print("\nBuilding EIP-7702 transaction...")
    gas_params = calculate_bundle_gas_params(w3)
    gas_params['gas'] = 1000000
    
    tx = builder.build_transaction(account, gas_params)
    print(f"Transaction type: {tx['type']} (should be 4)")
    print(f"Authorization list: {len(tx.get('authorizationList', []))} items")
    
    # Sign and send
    signed_tx = account.sign_transaction(tx)
    
    print("\nSending transaction...")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"✅ Transaction sent: {tx_hash.hex()}")
    print(f"View on Gnosisscan: https://gnosisscan.io/tx/{tx_hash.hex()}")
    
    # Wait for receipt
    print("\nWaiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    
    if receipt.status == 1:
        print(f"\n✅ SWAP SUCCESSFUL!")
        print(f"Gas used: {receipt.gasUsed}")
        
        # Check new balance
        new_balance = get_token_balance(w3, token_out, account.address)
        print(f"\nNew {token_name} conditional Company balance: {w3.from_wei(new_balance, 'ether')}")
        
    else:
        print(f"\n❌ Transaction failed!")
        print("This likely means the Swapr interface encoding still needs adjustment.")


def test_both_swaps(amount_sdai: float = 0.001):
    """Test both YES and NO swaps."""
    print("Testing Swapr Swaps with EIP-7702")
    print("=" * 50)
    
    # Test YES swap
    test_swapr_swap(amount_sdai, "YES")
    
    print("\n" + "=" * 50 + "\n")
    
    # Test NO swap
    test_swapr_swap(amount_sdai, "NO")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Test Swapr swaps with EIP-7702')
    parser.add_argument('--amount', type=float, default=0.001, help='Amount of sDAI to swap (default: 0.001)')
    parser.add_argument('--type', choices=['YES', 'NO', 'BOTH'], default='BOTH', help='Which swap to test (default: BOTH)')
    
    args = parser.parse_args()
    
    if args.type == 'BOTH':
        test_both_swaps(args.amount)
    else:
        test_swapr_swap(args.amount, args.type)


if __name__ == "__main__":
    main()
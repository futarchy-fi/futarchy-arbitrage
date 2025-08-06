#!/usr/bin/env python3
"""
Swapr swap with EIP-7702 using the exact encoding from the working swapr_swap.py.
This should definitely work since we're using the proven encoding method.
"""

import os
import sys
import time
from decimal import Decimal
from web3 import Web3
from eth_account import Account

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import the working Swapr encoding from the actual helpers
from src.helpers.swapr_swap import router as swapr_router
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
SDAI_YES = os.environ["SWAPR_SDAI_YES_ADDRESS"]
SDAI_NO = os.environ["SWAPR_SDAI_NO_ADDRESS"]
COMPANY_YES = os.environ["SWAPR_GNO_YES_ADDRESS"]
COMPANY_NO = os.environ["SWAPR_GNO_NO_ADDRESS"]


def build_swapr_exact_in_call(
    token_in: str,
    token_out: str,
    amount_in: int,
    amount_out_min: int,
    recipient: str
):
    """
    Build Swapr exactInputSingle call using the proven encoding from swapr_swap.py.
    """
    deadline = int(time.time()) + 600
    
    # Use the exact same parameter format as swapr_swap.py
    params = (
        w3.to_checksum_address(token_in),
        w3.to_checksum_address(token_out),
        w3.to_checksum_address(recipient),
        deadline,
        int(amount_in),
        int(amount_out_min),
        0  # sqrtPriceLimitX96
    )
    
    # Use the router's encode_abi method directly (web3.py v7)
    data = swapr_router.encode_abi(abi_element_identifier="exactInputSingle", args=[params])
    
    return {
        'target': w3.to_checksum_address(SWAPR_ROUTER),
        'value': 0,
        'data': data
    }


def build_swapr_exact_out_call(
    token_in: str,
    token_out: str,
    amount_out: int,
    amount_in_max: int,
    recipient: str
):
    """
    Build Swapr exactOutputSingle call using the proven encoding from swapr_swap.py.
    """
    deadline = int(time.time()) + 600
    
    # Use the exact same parameter format as swapr_swap.py
    params = (
        w3.to_checksum_address(token_in),
        w3.to_checksum_address(token_out),
        500,  # fee (0.05%)
        w3.to_checksum_address(recipient),
        deadline,
        int(amount_out),
        int(amount_in_max),
        0  # sqrtPriceLimitX96
    )
    
    # Use the router's encode_abi method directly (web3.py v7)
    data = swapr_router.encode_abi(abi_element_identifier="exactOutputSingle", args=[params])
    
    return {
        'target': w3.to_checksum_address(SWAPR_ROUTER),
        'value': 0,
        'data': data
    }


def execute_swapr_swap_eip7702(
    token_type: str = "YES",
    amount: float = 0.001,
    exact_type: str = "IN"
):
    """
    Execute a Swapr swap using EIP-7702 with proven encoding.
    
    Args:
        token_type: "YES" or "NO"
        amount: Amount in ether units
        exact_type: "IN" for exactInputSingle, "OUT" for exactOutputSingle
    """
    print(f"=== Swapr {token_type} Swap via EIP-7702 (Exact {exact_type}) ===\n")
    
    # Select tokens
    if token_type.upper() == "YES":
        token_in = SDAI_YES
        token_out = COMPANY_YES
    else:
        token_in = SDAI_NO
        token_out = COMPANY_NO
    
    # Check balance
    balance = get_token_balance(w3, token_in, account.address)
    print(f"Current {token_type} conditional sDAI balance: {w3.from_wei(balance, 'ether')}")
    
    if balance == 0:
        print(f"\n❌ No {token_type} conditional sDAI available!")
        return False
    
    amount_wei = w3.to_wei(amount, 'ether')
    
    # Build the appropriate swap call
    if exact_type.upper() == "IN":
        # Exact input: swap exact amount of sDAI for Company tokens
        swap_amount = min(amount_wei, balance)
        print(f"Swapping exactly {w3.from_wei(swap_amount, 'ether')} {token_type} sDAI")
        
        swap_call = build_swapr_exact_in_call(
            token_in,
            token_out,
            swap_amount,
            0,  # No minimum output for test
            account.address
        )
    else:
        # Exact output: get exact amount of Company tokens
        print(f"Getting exactly {w3.from_wei(amount_wei, 'ether')} {token_type} Company tokens")
        
        swap_call = build_swapr_exact_out_call(
            token_in,
            token_out,
            amount_wei,
            balance,  # Use full balance as max input
            account.address
        )
    
    # Check and build approval if needed
    from eth_abi import encode
    allowance_selector = Web3.keccak(text="allowance(address,address)")[:4]
    allowance_data = allowance_selector + encode(['address', 'address'], [account.address, SWAPR_ROUTER])
    allowance_result = w3.eth.call({'to': token_in, 'data': allowance_data})
    current_allowance = int.from_bytes(allowance_result, 'big')
    
    calls = []
    if current_allowance < balance:
        print(f"Adding approval for {token_type} conditional sDAI...")
        approval_call = encode_approval_call(token_in, SWAPR_ROUTER, 2**256 - 1)
        calls.append(approval_call)
    
    calls.append(swap_call)
    
    # Build EIP-7702 bundle
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    for call in calls:
        builder.add_call(call['target'], call['value'], call['data'])
    
    print(f"\nBuilding EIP-7702 transaction with {len(calls)} calls...")
    gas_params = calculate_bundle_gas_params(w3)
    gas_params['gas'] = 1500000  # Higher gas limit for swap
    
    tx = builder.build_transaction(account, gas_params)
    print(f"Transaction type: {tx['type']} (EIP-7702)")
    print(f"Batch calls: {len(builder.calls)}")
    
    # Sign and send
    signed_tx = account.sign_transaction(tx)
    
    print("\nSending transaction...")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"Transaction hash: {tx_hash.hex()}")
    print(f"View on Gnosisscan: https://gnosisscan.io/tx/{tx_hash.hex()}")
    
    # Wait for confirmation
    print("\nWaiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    
    if receipt.status == 1:
        print(f"\n✅ SUCCESS! Swapr swap executed via EIP-7702")
        print(f"Gas used: {receipt.gasUsed}")
        
        # Check results
        new_out_balance = get_token_balance(w3, token_out, account.address)
        new_in_balance = get_token_balance(w3, token_in, account.address)
        
        print(f"\nBalances after swap:")
        print(f"  {token_type} sDAI: {w3.from_wei(new_in_balance, 'ether')}")
        print(f"  {token_type} Company: {w3.from_wei(new_out_balance, 'ether')}")
        
        return True
    else:
        print(f"\n❌ Transaction failed!")
        return False


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Execute Swapr swaps via EIP-7702')
    parser.add_argument('--type', choices=['YES', 'NO'], default='YES', 
                       help='Token type to swap (default: YES)')
    parser.add_argument('--amount', type=float, default=0.001,
                       help='Amount to swap in ether units (default: 0.001)')
    parser.add_argument('--exact', choices=['IN', 'OUT'], default='IN',
                       help='Swap type: IN for exactInputSingle, OUT for exactOutputSingle (default: IN)')
    
    args = parser.parse_args()
    
    print("Swapr EIP-7702 Swap Execution")
    print("=" * 50)
    
    success = execute_swapr_swap_eip7702(
        token_type=args.type,
        amount=args.amount,
        exact_type=args.exact
    )
    
    if success:
        print("\n🎉 Swapr swap successfully executed with EIP-7702!")
        print("This proves the EIP-7702 bundling works with proper Swapr encoding.")
    else:
        print("\n⚠️ Swap failed. Check the transaction for details.")


if __name__ == "__main__":
    main()
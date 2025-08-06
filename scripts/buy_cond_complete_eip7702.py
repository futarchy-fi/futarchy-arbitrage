#!/usr/bin/env python3
"""
Complete buy conditional flow with EIP-7702 using working Swapr encoding.
This implements the full arbitrage cycle with proper Swapr interface.
"""

import os
import sys
import time
from decimal import Decimal
from web3 import Web3
from eth_account import Account

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import working components
from src.helpers.swapr_swap import router as swapr_router
from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.bundle_helpers import (
    encode_approval_call,
    encode_split_position_call,
    encode_merge_positions_call,
    encode_balancer_swap_call,
    calculate_bundle_gas_params,
    get_token_balance
)

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

IMPLEMENTATION_ADDRESS = os.environ.get("FUTARCHY_BATCH_EXECUTOR_ADDRESS", "0x65eb5a03635c627a0f254707712812B234753F31")

# Contracts
FUTARCHY_ROUTER = os.environ["FUTARCHY_ROUTER_ADDRESS"]
SWAPR_ROUTER = os.environ["SWAPR_ROUTER_ADDRESS"]
BALANCER_VAULT = os.environ["BALANCER_VAULT_ADDRESS"]
FUTARCHY_PROPOSAL = os.environ["FUTARCHY_PROPOSAL_ADDRESS"]

# Tokens
SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]
COMPANY_TOKEN = os.environ["COMPANY_TOKEN_ADDRESS"]
SDAI_YES = os.environ["SWAPR_SDAI_YES_ADDRESS"]
SDAI_NO = os.environ["SWAPR_SDAI_NO_ADDRESS"]
COMPANY_YES = os.environ["SWAPR_GNO_YES_ADDRESS"]
COMPANY_NO = os.environ["SWAPR_GNO_NO_ADDRESS"]

# Pool
BALANCER_POOL_ID = os.environ.get("BALANCER_POOL_ID", "")


def build_working_swapr_call(
    token_in: str,
    token_out: str,
    amount_in: int,
    recipient: str,
    exact_type: str = "IN"
):
    """Build a working Swapr call using proven encoding."""
    deadline = int(time.time()) + 600
    
    if exact_type == "IN":
        params = (
            w3.to_checksum_address(token_in),
            w3.to_checksum_address(token_out),
            w3.to_checksum_address(recipient),
            deadline,
            int(amount_in),
            0,  # amountOutMin
            0   # sqrtPriceLimitX96
        )
        data = swapr_router.encode_abi(abi_element_identifier="exactInputSingle", args=[params])
    else:
        params = (
            w3.to_checksum_address(token_in),
            w3.to_checksum_address(token_out),
            500,  # fee
            w3.to_checksum_address(recipient),
            deadline,
            int(amount_in),  # Actually amount_out for exactOutputSingle
            int(amount_in * 2),  # amount_in_max
            0
        )
        data = swapr_router.encode_abi(abi_element_identifier="exactOutputSingle", args=[params])
    
    return {
        'target': w3.to_checksum_address(SWAPR_ROUTER),
        'value': 0,
        'data': data
    }


def execute_buy_conditional_bundle(amount_sdai: float = 0.01, skip_balancer: bool = False):
    """
    Execute complete buy conditional flow with EIP-7702.
    
    Steps:
    1. Split sDAI into YES/NO conditional sDAI
    2. Swap YES sDAI -> YES Company
    3. Swap NO sDAI -> NO Company
    4. Merge YES/NO Company back to Company
    5. (Optional) Sell Company for sDAI on Balancer
    
    Args:
        amount_sdai: Amount of sDAI to use
        skip_balancer: Skip the final Balancer swap (default: False)
    """
    print("=== Complete Buy Conditional Flow with EIP-7702 ===\n")
    
    amount_wei = w3.to_wei(amount_sdai, 'ether')
    
    # Check balances
    sdai_balance = get_token_balance(w3, SDAI_TOKEN, account.address)
    print(f"sDAI balance: {w3.from_wei(sdai_balance, 'ether')}")
    
    if sdai_balance < amount_wei:
        print(f"❌ Insufficient sDAI balance!")
        return False
    
    # Build bundle calls
    calls = []
    
    # 1. Approve sDAI for split
    print("Building bundle:")
    print("  1. Approve sDAI for FutarchyRouter")
    calls.append(encode_approval_call(SDAI_TOKEN, FUTARCHY_ROUTER, amount_wei))
    
    # 2. Split sDAI
    print("  2. Split sDAI into YES/NO conditional")
    calls.append(encode_split_position_call(
        FUTARCHY_ROUTER,
        FUTARCHY_PROPOSAL,
        SDAI_TOKEN,
        amount_wei
    ))
    
    # 3. Approve YES sDAI for Swapr
    print("  3. Approve YES sDAI for Swapr")
    calls.append(encode_approval_call(SDAI_YES, SWAPR_ROUTER, amount_wei))
    
    # 4. Swap YES sDAI -> YES Company
    print("  4. Swap YES sDAI -> YES Company")
    calls.append(build_working_swapr_call(
        SDAI_YES,
        COMPANY_YES,
        amount_wei,
        account.address,
        "IN"
    ))
    
    # 5. Approve NO sDAI for Swapr
    print("  5. Approve NO sDAI for Swapr")
    calls.append(encode_approval_call(SDAI_NO, SWAPR_ROUTER, amount_wei))
    
    # 6. Swap NO sDAI -> NO Company
    print("  6. Swap NO sDAI -> NO Company")
    calls.append(build_working_swapr_call(
        SDAI_NO,
        COMPANY_NO,
        amount_wei,
        account.address,
        "IN"
    ))
    
    # 7. Approve Company tokens for merge
    print("  7. Approve YES Company for merge")
    calls.append(encode_approval_call(COMPANY_YES, FUTARCHY_ROUTER, 2**256 - 1))
    
    print("  8. Approve NO Company for merge")
    calls.append(encode_approval_call(COMPANY_NO, FUTARCHY_ROUTER, 2**256 - 1))
    
    # 8. Merge Company tokens
    # Note: We should calculate the min amount from swaps, using a conservative estimate for now
    merge_amount = int(amount_wei * 0.95)  # Assume 95% efficiency
    print(f"  9. Merge Company tokens (estimated: {w3.from_wei(merge_amount, 'ether')})")
    calls.append(encode_merge_positions_call(
        FUTARCHY_ROUTER,
        FUTARCHY_PROPOSAL,
        COMPANY_TOKEN,
        merge_amount
    ))
    
    # 9. Optional: Sell Company for sDAI on Balancer
    if not skip_balancer and BALANCER_POOL_ID:
        print("  10. Approve Company for Balancer")
        calls.append(encode_approval_call(COMPANY_TOKEN, BALANCER_VAULT, merge_amount))
        
        print("  11. Sell Company for sDAI on Balancer")
        calls.append(encode_balancer_swap_call(
            BALANCER_VAULT,
            BALANCER_POOL_ID,
            COMPANY_TOKEN,
            SDAI_TOKEN,
            merge_amount,
            account.address,
            account.address
        ))
    
    # Check if we're within the 10-call limit
    if len(calls) > 10:
        print(f"\n⚠️ Warning: {len(calls)} calls exceed the 10-call limit!")
        print("Consider pre-setting approvals or splitting into multiple transactions.")
    
    # Build EIP-7702 transaction
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    for call in calls[:10]:  # Limit to 10 calls
        builder.add_call(call['target'], call['value'], call['data'])
    
    print(f"\nBuilding EIP-7702 bundle with {len(builder.calls)} calls...")
    gas_params = calculate_bundle_gas_params(w3)
    gas_params['gas'] = 2000000  # High gas limit for complete bundle
    
    tx = builder.build_transaction(account, gas_params)
    print(f"Transaction type: {tx['type']} (EIP-7702)")
    
    # Sign and send
    signed_tx = account.sign_transaction(tx)
    
    print("\nSending bundled transaction...")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"Transaction hash: {tx_hash.hex()}")
    print(f"View on Gnosisscan: https://gnosisscan.io/tx/{tx_hash.hex()}")
    
    # Wait for confirmation
    print("\nWaiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    
    if receipt.status == 1:
        print(f"\n✅ SUCCESS! Complete buy conditional flow executed")
        print(f"Gas used: {receipt.gasUsed}")
        
        # Check final balances
        print("\nFinal balances:")
        company_balance = get_token_balance(w3, COMPANY_TOKEN, account.address)
        sdai_final = get_token_balance(w3, SDAI_TOKEN, account.address)
        
        print(f"  Company tokens: {w3.from_wei(company_balance, 'ether')}")
        print(f"  sDAI: {w3.from_wei(sdai_final, 'ether')}")
        
        if not skip_balancer:
            profit = sdai_final - (sdai_balance - amount_wei)
            print(f"  Net profit: {w3.from_wei(profit, 'ether')} sDAI")
        
        return True
    else:
        print(f"\n❌ Transaction failed!")
        return False


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Execute complete buy conditional flow with EIP-7702')
    parser.add_argument('--amount', type=float, default=0.01,
                       help='Amount of sDAI to use (default: 0.01)')
    parser.add_argument('--skip-balancer', action='store_true',
                       help='Skip the final Balancer swap')
    
    args = parser.parse_args()
    
    print("Complete Buy Conditional EIP-7702 Bundle")
    print("=" * 50)
    
    success = execute_buy_conditional_bundle(
        amount_sdai=args.amount,
        skip_balancer=args.skip_balancer
    )
    
    if success:
        print("\n🎉 Complete buy conditional flow successful!")
        print("All operations executed atomically via EIP-7702.")
    else:
        print("\n⚠️ Bundle execution failed. Check transaction for details.")


if __name__ == "__main__":
    main()
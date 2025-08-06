#!/usr/bin/env python3
"""
Test each step of the buy conditional flow individually.
"""

import os
import sys
from web3 import Web3
from eth_account import Account

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.bundle_helpers import (
    encode_split_position_call,
    encode_swapr_exact_in_call,
    encode_merge_positions_call,
    encode_balancer_swap_call,
    calculate_bundle_gas_params,
    get_token_balance
)

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

IMPLEMENTATION_ADDRESS = os.environ.get("FUTARCHY_BATCH_EXECUTOR_ADDRESS", "0x65eb5a03635c627a0f254707712812B234753F31")

# Contracts and tokens
FUTARCHY_ROUTER = os.environ["FUTARCHY_ROUTER_ADDRESS"]
SWAPR_ROUTER = os.environ["SWAPR_ROUTER_ADDRESS"]
BALANCER_VAULT = os.environ["BALANCER_VAULT_ADDRESS"]
PROPOSAL_ADDRESS = os.environ["FUTARCHY_PROPOSAL_ADDRESS"]

SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]
COMPANY_TOKEN = os.environ["COMPANY_TOKEN_ADDRESS"]
SDAI_YES = os.environ["SWAPR_SDAI_YES_ADDRESS"]
SDAI_NO = os.environ["SWAPR_SDAI_NO_ADDRESS"]
COMPANY_YES = os.environ["SWAPR_GNO_YES_ADDRESS"]
COMPANY_NO = os.environ["SWAPR_GNO_NO_ADDRESS"]

# No need for BALANCER_POOL_ID - will use single swap like light_bot


def execute_single_call(call, description):
    """Execute a single call with EIP-7702."""
    print(f"\n=== {description} ===")
    
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    builder.add_call(call['target'], call['value'], call['data'])
    
    gas_params = calculate_bundle_gas_params(w3)
    gas_params['gas'] = 1000000
    
    tx = builder.build_transaction(account, gas_params)
    signed_tx = account.sign_transaction(tx)
    
    print("Sending transaction...")
    try:
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"✅ Sent: {tx_hash.hex()}")
        
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt.status == 1:
            print(f"✅ SUCCESS - Gas: {receipt.gasUsed}")
            return True
        else:
            print(f"❌ FAILED")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


def test_steps():
    """Test each step individually."""
    print("Testing Individual Steps")
    print("=" * 50)
    
    amount = w3.to_wei(0.0001, 'ether')  # Very small amount
    deadline = w3.eth.get_block('latest').timestamp + 3600
    
    # Step 1: Split position (already tested and works)
    print("\n1. Split Position - SKIPPING (already confirmed working)")
    
    # Step 2: Swap sDAI YES to Company YES
    print("\n2. Testing Swapr Swap (sDAI YES → Company YES)")
    
    # Check balances
    sdai_yes_balance = get_token_balance(w3, SDAI_YES, account.address)
    print(f"sDAI YES balance: {w3.from_wei(sdai_yes_balance, 'ether')}")
    
    if sdai_yes_balance > 0:
        swap_amount = min(amount, sdai_yes_balance)
        swap_call = encode_swapr_exact_in_call(
            SWAPR_ROUTER,
            SDAI_YES,
            COMPANY_YES,
            swap_amount,
            1,  # Min out
            account.address,
            deadline
        )
        
        success = execute_single_call(swap_call, "Swapr Swap YES")
        if not success:
            print("❌ Swapr swap failed! This might be the issue.")
            return
    
    # Step 3: Swap sDAI NO to Company NO
    print("\n3. Testing Swapr Swap (sDAI NO → Company NO)")
    
    sdai_no_balance = get_token_balance(w3, SDAI_NO, account.address)
    print(f"sDAI NO balance: {w3.from_wei(sdai_no_balance, 'ether')}")
    
    if sdai_no_balance > 0:
        swap_amount = min(amount, sdai_no_balance)
        swap_call = encode_swapr_exact_in_call(
            SWAPR_ROUTER,
            SDAI_NO,
            COMPANY_NO,
            swap_amount,
            1,  # Min out
            account.address,
            deadline
        )
        
        success = execute_single_call(swap_call, "Swapr Swap NO")
        if not success:
            print("❌ Swapr swap failed! This might be the issue.")
            return
    
    # Step 4: Merge positions
    print("\n4. Testing Merge Positions")
    
    company_yes_balance = get_token_balance(w3, COMPANY_YES, account.address)
    company_no_balance = get_token_balance(w3, COMPANY_NO, account.address)
    print(f"Company YES balance: {w3.from_wei(company_yes_balance, 'ether')}")
    print(f"Company NO balance: {w3.from_wei(company_no_balance, 'ether')}")
    
    merge_amount = min(company_yes_balance, company_no_balance)
    if merge_amount > 0:
        merge_call = encode_merge_positions_call(
            FUTARCHY_ROUTER,
            PROPOSAL_ADDRESS,
            COMPANY_TOKEN,
            merge_amount
        )
        
        success = execute_single_call(merge_call, "Merge Positions")
        if not success:
            print("❌ Merge failed! This might be the issue.")
            return
    
    # Step 5: Balancer swap (single swap)
    print("\n5. Testing Balancer Single Swap")
    
    company_balance = get_token_balance(w3, COMPANY_TOKEN, account.address)
    print(f"Company token balance: {w3.from_wei(company_balance, 'ether')}")
    
    if company_balance > 0:
        # Use encode_balancer_swap_call which handles single swap internally
        from src.config.pools import get_pool_config
        pool_config = get_pool_config()
        pool_id = pool_config['balancer_pool']['pool_id']
        
        swap_call = encode_balancer_swap_call(
            BALANCER_VAULT,
            pool_id,
            COMPANY_TOKEN,
            SDAI_TOKEN,
            company_balance,
            1,  # Min out
            account.address,
            deadline
        )
        
        success = execute_single_call(swap_call, "Balancer Swap")
        if not success:
            print("❌ Balancer swap failed! This might be the issue.")
            return
    
    print("\n✅ All steps completed successfully!")


def main():
    """Run the tests."""
    test_steps()


if __name__ == "__main__":
    main()
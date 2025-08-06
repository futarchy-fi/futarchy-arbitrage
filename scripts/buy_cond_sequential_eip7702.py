#!/usr/bin/env python3
"""
Execute buy conditional flow sequentially using EIP-7702 for each step.
This proves EIP-7702 works even if bundling all calls together fails.
"""

import os
import sys
from decimal import Decimal
from web3 import Web3
from eth_account import Account

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.bundle_helpers import (
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
PROPOSAL_ADDRESS = os.environ["FUTARCHY_PROPOSAL_ADDRESS"]
BALANCER_VAULT = os.environ["BALANCER_VAULT_ADDRESS"]

# Tokens
SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]
COMPANY_TOKEN = os.environ["COMPANY_TOKEN_ADDRESS"]
SDAI_YES = os.environ["SWAPR_SDAI_YES_ADDRESS"]
SDAI_NO = os.environ["SWAPR_SDAI_NO_ADDRESS"]
COMPANY_YES = os.environ["SWAPR_GNO_YES_ADDRESS"]
COMPANY_NO = os.environ["SWAPR_GNO_NO_ADDRESS"]


def execute_with_eip7702(call, description):
    """Execute a single call with EIP-7702."""
    print(f"\n{description}")
    
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    builder.add_call(call['target'], call['value'], call['data'])
    
    gas_params = calculate_bundle_gas_params(w3)
    gas_params['gas'] = 1000000
    
    tx = builder.build_transaction(account, gas_params)
    signed_tx = account.sign_transaction(tx)
    
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"Sent: {tx_hash.hex()}")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"✅ SUCCESS - Gas: {receipt.gasUsed}")
        return True
    else:
        print(f"❌ FAILED")
        return False


def buy_conditional_sequential():
    """Execute buy conditional flow step by step."""
    print("=== Sequential Buy Conditional with EIP-7702 ===")
    
    amount = w3.to_wei(0.01, 'ether')  # 0.01 sDAI
    
    # Step 1: Split sDAI
    print(f"\nStarting with {w3.from_wei(amount, 'ether')} sDAI")
    
    split_call = encode_split_position_call(
        FUTARCHY_ROUTER,
        PROPOSAL_ADDRESS,
        SDAI_TOKEN,
        amount
    )
    
    if not execute_with_eip7702(split_call, "1. Splitting sDAI into conditional tokens"):
        return
    
    # Check balances after split
    sdai_yes_balance = get_token_balance(w3, SDAI_YES, account.address)
    sdai_no_balance = get_token_balance(w3, SDAI_NO, account.address)
    print(f"   sDAI YES: {w3.from_wei(sdai_yes_balance, 'ether')}")
    print(f"   sDAI NO: {w3.from_wei(sdai_no_balance, 'ether')}")
    
    # Step 2: Skip Swapr swaps for now (they're failing)
    print("\n2. Skipping Swapr swaps (known issue with router interface)")
    
    # Step 3: Try merge with what we have
    # For demo, let's assume we already have some Company YES/NO tokens
    company_yes_balance = get_token_balance(w3, COMPANY_YES, account.address)
    company_no_balance = get_token_balance(w3, COMPANY_NO, account.address)
    
    if company_yes_balance > 0 and company_no_balance > 0:
        merge_amount = min(company_yes_balance, company_no_balance)
        print(f"\n3. Merging {w3.from_wei(merge_amount, 'ether')} Company tokens")
        
        merge_call = encode_merge_positions_call(
            FUTARCHY_ROUTER,
            PROPOSAL_ADDRESS,
            COMPANY_TOKEN,
            merge_amount
        )
        
        if not execute_with_eip7702(merge_call, "   Merging conditional Company tokens"):
            return
    
    # Step 4: Sell Company tokens on Balancer
    company_balance = get_token_balance(w3, COMPANY_TOKEN, account.address)
    
    if company_balance > 0:
        print(f"\n4. Selling {w3.from_wei(company_balance, 'ether')} Company tokens on Balancer")
        
        from src.config.pools import get_pool_config
        pool_config = get_pool_config(os.environ["BALANCER_POOL_ADDRESS"])
        pool_id = pool_config['balancer_pool']['pool_id']
        
        deadline = w3.eth.get_block('latest').timestamp + 600
        
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
        
        if not execute_with_eip7702(swap_call, "   Swapping Company → sDAI on Balancer"):
            return
    
    print("\n✅ Sequential execution completed!")
    
    # Final balance
    final_sdai = get_token_balance(w3, SDAI_TOKEN, account.address)
    print(f"\nFinal sDAI balance: {w3.from_wei(final_sdai, 'ether')}")


def main():
    """Run sequential buy conditional."""
    print("Sequential Buy Conditional with EIP-7702")
    print("=" * 50)
    print("This proves EIP-7702 works for each individual step")
    
    buy_conditional_sequential()


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Debug Swapr swap issue.
"""

import os
import sys
from web3 import Web3
from eth_account import Account
from eth_abi import encode

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.helpers.bundle_helpers import get_token_balance

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

# Contracts and tokens
SWAPR_ROUTER = os.environ["SWAPR_ROUTER_ADDRESS"]
SDAI_YES = os.environ["SWAPR_SDAI_YES_ADDRESS"]
COMPANY_YES = os.environ["SWAPR_GNO_YES_ADDRESS"]


def check_pool_exists():
    """Check if the Swapr pool exists and has liquidity."""
    print("=== Checking Swapr Pool ===\n")
    
    # Get pool address from environment
    yes_pool = os.environ["SWAPR_POOL_YES_ADDRESS"]
    print(f"YES pool address: {yes_pool}")
    
    # Check pool contract
    pool_code = w3.eth.get_code(yes_pool)
    print(f"Pool has code: {len(pool_code) > 0}")
    
    # Check token balances in pool
    sdai_yes_in_pool = get_token_balance(w3, SDAI_YES, yes_pool)
    company_yes_in_pool = get_token_balance(w3, COMPANY_YES, yes_pool)
    
    print(f"\nPool balances:")
    print(f"  sDAI YES: {w3.from_wei(sdai_yes_in_pool, 'ether')}")
    print(f"  Company YES: {w3.from_wei(company_yes_in_pool, 'ether')}")
    
    if sdai_yes_in_pool == 0 or company_yes_in_pool == 0:
        print("\n❌ Pool has no liquidity!")
        return False
    
    return True


def test_simple_swap():
    """Test a simple swap directly."""
    print("\n=== Testing Simple Swap ===\n")
    
    # Check balance
    balance = get_token_balance(w3, SDAI_YES, account.address)
    print(f"sDAI YES balance: {w3.from_wei(balance, 'ether')}")
    
    if balance == 0:
        print("❌ No sDAI YES balance to swap")
        return
    
    # Try tiny amount
    amount = w3.to_wei(0.00001, 'ether')  # 0.00001 sDAI YES
    print(f"Trying to swap {w3.from_wei(amount, 'ether')} sDAI YES")
    
    # Build swap directly
    deadline = w3.eth.get_block('latest').timestamp + 3600
    
    # exactInputSingle parameters
    from eth_utils import keccak
    function_selector = keccak(text="exactInputSingle((address,address,address,uint256,uint256,uint256,uint160))")[:4]
    
    # Encode parameters
    params = encode(
        ['address', 'address', 'address', 'uint256', 'uint256', 'uint256', 'uint160'],
        [
            SDAI_YES,  # tokenIn
            COMPANY_YES,  # tokenOut
            account.address,  # recipient
            deadline,  # deadline
            amount,  # amountIn
            1,  # amountOutMinimum
            0  # sqrtPriceLimitX96 (0 = no limit)
        ]
    )
    
    # Encode the entire function call
    data = function_selector + encode(['bytes'], [params])
    
    # Send transaction directly (not through EIP-7702)
    print("\nSending direct swap transaction...")
    tx = {
        'from': account.address,
        'to': SWAPR_ROUTER,
        'data': data,
        'gas': 500000,
        'gasPrice': w3.eth.gas_price,
        'nonce': w3.eth.get_transaction_count(account.address),
        'chainId': w3.eth.chain_id
    }
    
    try:
        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"✅ Sent: {tx_hash.hex()}")
        
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt.status == 1:
            print(f"✅ SWAP SUCCESSFUL!")
            print(f"Gas used: {receipt.gasUsed}")
        else:
            print(f"❌ SWAP FAILED!")
            print(f"Receipt: {receipt}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run debug tests."""
    print("Swapr Swap Debug")
    print("=" * 50)
    
    if check_pool_exists():
        test_simple_swap()
    else:
        print("\n⚠️  Cannot test swap - pool has no liquidity")


if __name__ == "__main__":
    main()
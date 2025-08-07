#!/usr/bin/env python3
"""
Setup pre-approvals for EIP-7702 operations to reduce bundle size.

This script sets up all necessary token approvals so that the main
arbitrage bundles don't need to include approval operations, allowing
us to fit more operations within the 10-call limit.

Usage:
    python scripts/setup_eip7702_approvals.py [--revoke]
"""

import os
import sys
from web3 import Web3
from eth_account import Account
from eth_abi import encode
from eth_utils import keccak

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Initialize Web3 and account
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

# Contract addresses
FUTARCHY_ROUTER = os.environ["FUTARCHY_ROUTER_ADDRESS"]
SWAPR_ROUTER = os.environ["SWAPR_ROUTER_ADDRESS"]
BALANCER_ROUTER = os.environ.get("BALANCER_ROUTER_ADDRESS", "0xBA12222222228d8Ba445958a75a0704d566BF2C8")
BALANCER_VAULT = os.environ.get("BALANCER_VAULT_ADDRESS", "0xBA12222222228d8Ba445958a75a0704d566BF2C8")

# Token addresses
SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]
COMPANY_TOKEN = os.environ["COMPANY_TOKEN_ADDRESS"]
SDAI_YES = os.environ["SWAPR_SDAI_YES_ADDRESS"]
SDAI_NO = os.environ["SWAPR_SDAI_NO_ADDRESS"]
COMPANY_YES = os.environ["SWAPR_GNO_YES_ADDRESS"]
COMPANY_NO = os.environ["SWAPR_GNO_NO_ADDRESS"]

# Max approval amount
MAX_UINT256 = 2**256 - 1


def build_approval_tx(token_address: str, spender_address: str, amount: int):
    """Build an approval transaction."""
    # approve(address,uint256)
    function_selector = keccak(text="approve(address,uint256)")[:4]
    encoded_params = encode(['address', 'uint256'], [Web3.to_checksum_address(spender_address), amount])
    data = function_selector + encoded_params
    
    return {
        'to': Web3.to_checksum_address(token_address),
        'from': account.address,
        'value': 0,
        'data': data.hex(),
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 100000,
        'gasPrice': w3.eth.gas_price
    }


def check_allowance(token_address: str, spender_address: str) -> int:
    """Check current allowance."""
    # allowance(address,address)
    function_selector = keccak(text="allowance(address,address)")[:4]
    encoded_params = encode(['address', 'address'], [account.address, spender_address])
    data = function_selector + encoded_params
    
    result = w3.eth.call({
        'to': Web3.to_checksum_address(token_address),
        'data': data.hex()
    })
    
    return int.from_bytes(result, 'big')


def setup_approvals(revoke: bool = False):
    """Setup or revoke all necessary approvals."""
    
    approval_amount = 0 if revoke else MAX_UINT256
    action = "Revoking" if revoke else "Setting up"
    
    print(f"{action} approvals for EIP-7702 operations...")
    print(f"Account: {account.address}\n")
    
    # Define all necessary approvals
    approvals = [
        # For buy flow
        (SDAI_TOKEN, FUTARCHY_ROUTER, "sDAI → FutarchyRouter (for split)"),
        (SDAI_YES, SWAPR_ROUTER, "YES sDAI → Swapr"),
        (SDAI_NO, SWAPR_ROUTER, "NO sDAI → Swapr"),
        (COMPANY_YES, FUTARCHY_ROUTER, "YES Company → FutarchyRouter (for merge)"),
        (COMPANY_NO, FUTARCHY_ROUTER, "NO Company → FutarchyRouter (for merge)"),
        (COMPANY_TOKEN, BALANCER_VAULT, "Company → Balancer (for sell)"),
        
        # For sell flow
        (SDAI_TOKEN, BALANCER_ROUTER, "sDAI → Balancer (for buy)"),
        (COMPANY_TOKEN, FUTARCHY_ROUTER, "Company → FutarchyRouter (for split)"),
        (COMPANY_YES, SWAPR_ROUTER, "YES Company → Swapr"),
        (COMPANY_NO, SWAPR_ROUTER, "NO Company → Swapr"),
        (SDAI_YES, FUTARCHY_ROUTER, "YES sDAI → FutarchyRouter (for merge)"),
        (SDAI_NO, FUTARCHY_ROUTER, "NO sDAI → FutarchyRouter (for merge)"),
    ]
    
    # Check and set approvals
    nonce = w3.eth.get_transaction_count(account.address)
    tx_hashes = []
    
    for token, spender, description in approvals:
        try:
            current_allowance = check_allowance(token, spender)
            
            if revoke:
                if current_allowance > 0:
                    print(f"❌ {description}")
                    print(f"   Current: {current_allowance}")
                    print(f"   Revoking...")
                    
                    tx = build_approval_tx(token, spender, 0)
                    tx['nonce'] = nonce
                    signed_tx = account.sign_transaction(tx)
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                    tx_hashes.append((description, tx_hash))
                    nonce += 1
                else:
                    print(f"⏭️  {description} - Already revoked")
            else:
                if current_allowance < 10**18:  # Less than 1 token approved
                    print(f"✅ {description}")
                    print(f"   Current: {current_allowance}")
                    print(f"   Setting to: MAX")
                    
                    tx = build_approval_tx(token, spender, MAX_UINT256)
                    tx['nonce'] = nonce
                    signed_tx = account.sign_transaction(tx)
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                    tx_hashes.append((description, tx_hash))
                    nonce += 1
                else:
                    print(f"⏭️  {description} - Already approved")
                    print(f"   Current allowance: {w3.from_wei(current_allowance, 'ether')} tokens")
        except Exception as e:
            print(f"⚠️  {description} - Error: {e}")
    
    # Wait for confirmations
    if tx_hashes:
        print(f"\n⏳ Waiting for {len(tx_hashes)} transactions to confirm...")
        for description, tx_hash in tx_hashes:
            print(f"   {description}: {tx_hash.hex()}")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status != 1:
                print(f"   ❌ Failed!")
        print(f"\n✅ All approvals {action.lower()} successfully!")
    else:
        print(f"\n✅ No approvals needed - all already {action.lower()}!")
    
    # Summary
    print("\n📊 Approval Summary:")
    print("With these pre-approvals, the arbitrage bundles can skip approval operations")
    print("This allows the sell flow to fit within the 10-operation limit")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Setup pre-approvals for EIP-7702 operations'
    )
    parser.add_argument(
        '--revoke',
        action='store_true',
        help='Revoke all approvals instead of setting them'
    )
    
    args = parser.parse_args()
    
    try:
        setup_approvals(revoke=args.revoke)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
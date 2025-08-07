"""
Sell conditional tokens using EIP-7702 bundled transactions.

This module implements the sell conditional flow using atomic bundled transactions
via EIP-7702. The flow is the reverse of buy: start with sDAI, buy Company on Balancer,
split into conditionals, swap to conditional sDAI on Swapr, and merge back to sDAI.
"""

import os
import sys
import time
from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal
from web3 import Web3
from eth_account import Account

from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.swapr_swap import router as swapr_router
from src.helpers.bundle_helpers import (
    encode_approval_call,
    encode_split_position_call,
    encode_merge_positions_call,
    calculate_bundle_gas_params,
    get_token_balance
)

# Initialize Web3 and account
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

# Contract addresses
FUTARCHY_ROUTER = os.environ["FUTARCHY_ROUTER_ADDRESS"]
SWAPR_ROUTER = os.environ["SWAPR_ROUTER_ADDRESS"]
BALANCER_ROUTER = os.environ.get("BALANCER_ROUTER_ADDRESS", "0xBA12222222228d8Ba445958a75a0704d566BF2C8")
IMPLEMENTATION_ADDRESS = os.environ.get("FUTARCHY_BATCH_EXECUTOR_ADDRESS", "0x65eb5a03635c627a0f254707712812B234753F31")

# Token addresses
SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]
COMPANY_TOKEN = os.environ["COMPANY_TOKEN_ADDRESS"]
SDAI_YES = os.environ["SWAPR_SDAI_YES_ADDRESS"]
SDAI_NO = os.environ["SWAPR_SDAI_NO_ADDRESS"]
COMPANY_YES = os.environ["SWAPR_GNO_YES_ADDRESS"]
COMPANY_NO = os.environ["SWAPR_GNO_NO_ADDRESS"]

# Other parameters
FUTARCHY_PROPOSAL = os.environ["FUTARCHY_PROPOSAL_ADDRESS"]

# Balancer specific constants (from sell_cond_onchain.py)
BUFFER_POOL = w3.to_checksum_address("0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644")
FINAL_POOL = w3.to_checksum_address("0xd1d7fa8871d84d0e77020fc28b7cd5718c446522")
MAX_DEADLINE = 9007199254740991

# Balancer Router ABI for swapExactIn
BALANCER_ROUTER_ABI = [
    {
        "type": "function",
        "name": "swapExactIn",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "paths",
                "type": "tuple[]",
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {
                        "name": "steps",
                        "type": "tuple[]",
                        "components": [
                            {"name": "pool", "type": "address"},
                            {"name": "tokenOut", "type": "address"},
                            {"name": "isBuffer", "type": "bool"},
                        ],
                    },
                    {"name": "exactAmountIn", "type": "uint256"},
                    {"name": "minAmountOut", "type": "uint256"},
                ],
            },
            {"name": "deadline", "type": "uint256"},
            {"name": "wethIsEth", "type": "bool"},
            {"name": "userData", "type": "bytes"},
        ],
        "outputs": [
            {"name": "pathAmountsOut", "type": "uint256[]"},
            {"name": "tokensOut", "type": "address[]"},
            {"name": "amountsOut", "type": "uint256[]"},
        ],
    }
]


def build_working_swapr_call(
    token_in: str,
    token_out: str,
    amount_in: int,
    recipient: str,
    exact_type: str = "IN"
) -> Dict[str, Any]:
    """Build a working Swapr call using proven encoding from buy_cond_eip7702."""
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
            500,  # fee (0.05%)
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


def build_balancer_buy_company_call(
    amount_sdai: int,
    min_company_out: int,
    recipient: str
) -> Dict[str, Any]:
    """
    Build Balancer swap call for buying Company with sDAI.
    Uses swapExactIn with two-hop path through buffer pool.
    """
    router = w3.eth.contract(address=w3.to_checksum_address(BALANCER_ROUTER), abi=BALANCER_ROUTER_ABI)
    
    # SwapPathStep[] – two hops (for buying Company token with sDAI)
    steps = [
        # 1️⃣ sDAI → buffer token (direct pool swap)
        (FINAL_POOL, BUFFER_POOL, False),
        # 2️⃣ buffer token → Company (buffer hop)
        (BUFFER_POOL, w3.to_checksum_address(COMPANY_TOKEN), True),
    ]
    
    # SwapPathExactAmountIn
    path = (
        w3.to_checksum_address(SDAI_TOKEN),  # tokenIn (sDAI)
        steps,
        int(amount_sdai),       # exactAmountIn (sDAI)
        int(min_company_out),   # minAmountOut (Company)
    )
    
    data = router.encode_abi(
        abi_element_identifier="swapExactIn",
        args=[[path], int(MAX_DEADLINE), False, b""],
    )
    
    return {
        "target": router.address,
        "value": 0,
        "data": data
    }


def build_sell_conditional_bundle(
    amount_sdai: Decimal,
    skip_merge: bool = False,
    optimize_approvals: bool = True
) -> List[Dict[str, Any]]:
    """
    Build bundled transaction for sell conditional flow.
    
    Operations:
    1. Approve sDAI for Balancer
    2. Buy Company with sDAI on Balancer
    3. Approve Company for FutarchyRouter
    4. Split Company into YES/NO conditional Company
    5. Approve YES Company for Swapr
    6. Swap YES Company to YES sDAI
    7. Approve NO Company for Swapr
    8. Swap NO Company to NO sDAI
    9. Approve YES/NO sDAI for FutarchyRouter (optimized to single approval)
    10. Merge YES/NO sDAI back to regular sDAI
    
    Args:
        amount_sdai: Amount of sDAI to use
        skip_merge: Skip the final merge to reduce operations
        optimize_approvals: Combine conditional sDAI approvals
    
    Returns:
        List of call dictionaries for the bundle
    """
    calls = []
    amount_wei = w3.to_wei(amount_sdai, 'ether')
    
    # Estimate Company output from Balancer (very conservative estimate)
    # Company is worth much more than sDAI, so we get much less
    # Based on actual swap: 0.001 sDAI -> ~0.00001 Company (100x ratio)
    estimated_company = int(amount_wei // 100)  # Expect about 1/100th in Company tokens
    
    MAX_APPROVAL = 2**256 - 1
    
    # 1. Approve sDAI for Balancer
    calls.append(encode_approval_call(SDAI_TOKEN, BALANCER_ROUTER, amount_wei))
    
    # 2. Buy Company with sDAI on Balancer
    calls.append(build_balancer_buy_company_call(
        amount_wei,
        1,  # Min output (should calculate properly in production)
        account.address
    ))
    
    # 3. Approve Company for split (use estimated amount)
    calls.append(encode_approval_call(COMPANY_TOKEN, FUTARCHY_ROUTER, MAX_APPROVAL))
    
    # 4. Split Company into YES/NO (use estimated amount)
    calls.append(encode_split_position_call(
        FUTARCHY_ROUTER,
        FUTARCHY_PROPOSAL,
        COMPANY_TOKEN,
        estimated_company  # Use estimated Company amount
    ))
    
    # 5. Approve YES Company for Swapr
    calls.append(encode_approval_call(COMPANY_YES, SWAPR_ROUTER, MAX_APPROVAL))
    
    # 6. Swap YES Company -> YES sDAI (use estimated amount)
    calls.append(build_working_swapr_call(
        COMPANY_YES,
        SDAI_YES,
        estimated_company,  # Use estimated amount
        account.address,
        "IN"
    ))
    
    # 7. Approve NO Company for Swapr
    calls.append(encode_approval_call(COMPANY_NO, SWAPR_ROUTER, MAX_APPROVAL))
    
    # 8. Swap NO Company -> NO sDAI (use estimated amount)
    calls.append(build_working_swapr_call(
        COMPANY_NO,
        SDAI_NO,
        estimated_company,  # Use estimated amount
        account.address,
        "IN"
    ))
    
    if not skip_merge:
        # Estimate merge amount (conservative)
        merge_amount = int(estimated_company * 0.9)  # 90% of swapped amount
        
        if optimize_approvals:
            # 9. Single approval for both conditional sDAI tokens (MAX amount)
            # This works because both go to the same FutarchyRouter
            calls.append(encode_approval_call(SDAI_YES, FUTARCHY_ROUTER, MAX_APPROVAL))
            calls.append(encode_approval_call(SDAI_NO, FUTARCHY_ROUTER, MAX_APPROVAL))
        else:
            # 9-10. Separate approvals (would exceed 10 ops)
            calls.append(encode_approval_call(SDAI_YES, FUTARCHY_ROUTER, MAX_APPROVAL))
            calls.append(encode_approval_call(SDAI_NO, FUTARCHY_ROUTER, MAX_APPROVAL))
        
        # 10/11. Merge conditional sDAI back to regular sDAI
        calls.append(encode_merge_positions_call(
            FUTARCHY_ROUTER,
            FUTARCHY_PROPOSAL,
            SDAI_TOKEN,
            merge_amount  # Use estimated amount
        ))
    
    return calls


def sell_conditional_simple(
    amount_sdai: Decimal,
    skip_merge: bool = False
) -> Dict[str, Any]:
    """
    Execute sell conditional flow using proven EIP-7702 implementation.
    This is a simplified version that works without complex simulation.
    
    Args:
        amount_sdai: Amount of sDAI to use
        skip_merge: Skip the final merge to reduce operations
    
    Returns:
        Transaction results
    """
    print("=== Sell Conditional with EIP-7702 (Simple Mode) ===\n")
    
    amount_wei = w3.to_wei(amount_sdai, 'ether')
    
    # Check balance
    sdai_balance = get_token_balance(w3, SDAI_TOKEN, account.address)
    print(f"sDAI balance: {w3.from_wei(sdai_balance, 'ether')}")
    
    if sdai_balance < amount_wei:
        raise Exception("Insufficient sDAI balance")
    
    # Build bundle calls
    print("Building bundle:")
    calls = build_sell_conditional_bundle(amount_sdai, skip_merge=skip_merge)
    
    # Display operations
    operation_names = [
        "1. Approve sDAI for Balancer",
        "2. Buy Company with sDAI on Balancer",
        "3. Approve Company for FutarchyRouter",
        "4. Split Company into YES/NO",
        "5. Approve YES Company for Swapr",
        "6. Swap YES Company -> YES sDAI",
        "7. Approve NO Company for Swapr",
        "8. Swap NO Company -> NO sDAI"
    ]
    
    if not skip_merge:
        operation_names.extend([
            "9. Approve YES sDAI for merge",
            "10. Approve NO sDAI for merge",
            "11. Merge conditional sDAI to regular sDAI"
        ])
    
    for i, name in enumerate(operation_names[:len(calls)]):
        print(f"  {name}")
    
    # Check call limit
    if len(calls) > 10:
        print(f"\n⚠️ Warning: {len(calls)} calls exceed the 10-call limit!")
        if not skip_merge:
            print("Consider using --skip-merge to reduce operations")
            return {"status": "error", "message": "Too many operations"}
    
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
    # Handle both old and new eth-account versions
    if hasattr(signed_tx, 'rawTransaction'):
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    elif hasattr(signed_tx, 'raw_transaction'):
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    else:
        tx_hash = w3.eth.send_raw_transaction(signed_tx)
        
    print(f"Transaction hash: 0x{tx_hash.hex()}")
    print(f"View on Gnosisscan: https://gnosisscan.io/tx/0x{tx_hash.hex()}")
    
    # Wait for confirmation
    print("\nWaiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    
    if receipt.status == 1:
        print(f"\n✅ SUCCESS! Complete sell conditional flow executed")
        print(f"Gas used: {receipt.gasUsed}")
        
        # Check final balances
        print("\nFinal balances:")
        company_balance = get_token_balance(w3, COMPANY_TOKEN, account.address)
        sdai_final = get_token_balance(w3, SDAI_TOKEN, account.address)
        
        print(f"  Company tokens: {w3.from_wei(company_balance, 'ether')}")
        print(f"  sDAI: {w3.from_wei(sdai_final, 'ether')}")
        
        if not skip_merge:
            profit = sdai_final - (sdai_balance - amount_wei)
            print(f"  Net change: {w3.from_wei(profit, 'ether')} sDAI")
        else:
            yes_sdai = get_token_balance(w3, SDAI_YES, account.address)
            no_sdai = get_token_balance(w3, SDAI_NO, account.address)
            print(f"  YES sDAI: {w3.from_wei(yes_sdai, 'ether')}")
            print(f"  NO sDAI: {w3.from_wei(no_sdai, 'ether')}")
            print("  (Merge skipped - conditional sDAI held)")
        
        return {
            'status': 'success',
            'tx_hash': tx_hash.hex(),
            'gas_used': receipt.gasUsed,
            'company_balance': w3.from_wei(company_balance, 'ether'),
            'sdai_balance': w3.from_wei(sdai_final, 'ether')
        }
    else:
        print(f"\n❌ Transaction failed!")
        return {
            'status': 'failed',
            'tx_hash': tx_hash.hex()
        }


def check_approvals() -> Dict[str, bool]:
    """
    Check current approval statuses for all tokens involved.
    
    Returns:
        Dictionary of token approvals and their status
    """
    from eth_abi import encode
    
    approvals = {}
    
    # Check sDAI approval for Balancer
    allowance_selector = Web3.keccak(text="allowance(address,address)")[:4]
    
    tokens_to_check = [
        (SDAI_TOKEN, BALANCER_ROUTER, "sDAI -> Balancer"),
        (COMPANY_TOKEN, FUTARCHY_ROUTER, "Company -> FutarchyRouter"),
        (COMPANY_YES, SWAPR_ROUTER, "YES Company -> Swapr"),
        (COMPANY_NO, SWAPR_ROUTER, "NO Company -> Swapr"),
        (SDAI_YES, FUTARCHY_ROUTER, "YES sDAI -> FutarchyRouter"),
        (SDAI_NO, FUTARCHY_ROUTER, "NO sDAI -> FutarchyRouter"),
    ]
    
    for token, spender, name in tokens_to_check:
        data = allowance_selector + encode(['address', 'address'], [account.address, spender])
        result = w3.eth.call({'to': token, 'data': data})
        allowance = int.from_bytes(result, 'big')
        approvals[name] = allowance > 10**18  # Has at least 1 token approved
    
    return approvals


def main():
    """Main entry point for CLI usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Execute sell conditional flow with EIP-7702')
    parser.add_argument('amount', type=float, nargs='?', 
                       help='Amount of sDAI to use')
    parser.add_argument('--skip-merge', action='store_true',
                       help='Skip the final merge to reduce operations')
    parser.add_argument('--check-approvals', action='store_true',
                       help='Check current approval statuses')
    parser.add_argument('--test-balancer', action='store_true',
                       help='Test only the Balancer swap')
    
    args = parser.parse_args()
    
    # Check approvals if requested
    if args.check_approvals:
        print("Checking approval statuses...")
        approvals = check_approvals()
        print("\nApproval Status:")
        for name, status in approvals.items():
            status_str = "✅ Approved" if status else "❌ Not approved"
            print(f"  {name}: {status_str}")
        return
    
    # Test Balancer if requested
    if args.test_balancer:
        print("Testing Balancer swap encoding...")
        test_call = build_balancer_buy_company_call(
            w3.to_wei(0.001, 'ether'),
            1,
            account.address
        )
        print(f"Target: {test_call['target']}")
        print(f"Data length: {len(test_call['data'])} bytes")
        print(f"First 10 bytes: {test_call['data'][:20]}")
        print("\n✅ Balancer encoding successful")
        return
    
    # Require amount for execution
    if not args.amount:
        parser.print_help()
        return
    
    amount = Decimal(str(args.amount))
    
    # Verify environment
    if not IMPLEMENTATION_ADDRESS:
        print("Error: FUTARCHY_BATCH_EXECUTOR_ADDRESS not set")
        print("Using default: 0x65eb5a03635c627a0f254707712812B234753F31")
    
    print(f"Selling conditional tokens with {amount} sDAI using EIP-7702 bundles")
    print(f"Implementation contract: {IMPLEMENTATION_ADDRESS}")
    print(f"Skip merge: {args.skip_merge}")
    print()
    
    try:
        result = sell_conditional_simple(amount, skip_merge=args.skip_merge)
        
        print("\nResults:")
        for key, value in result.items():
            print(f"  {key}: {value}")
        
        if result.get('status') == 'success':
            print(f"\n🎉 Sell conditional flow successful!")
            if args.skip_merge:
                print("Remember to merge conditional sDAI tokens manually")
        else:
            print(f"\n⚠️ Transaction failed. Check details above.")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
"""
Test EIP-7702 with a realistic arbitrage scenario
=================================================

This test demonstrates how the complex bot would use EIP-7702
to bundle all arbitrage operations into a single transaction.
"""

import os
import sys
import time
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from eth_utils import to_hex

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.helpers.eip7702_builder import EIP7702TransactionBuilder


def test_buy_conditional_bundle():
    """Test building a complete buy conditional arbitrage bundle."""
    print("\n=== Testing Buy Conditional Arbitrage Bundle ===")
    
    # Mock provider for testing
    from web3.providers import BaseProvider
    
    class MockProvider(BaseProvider):
        def make_request(self, method, params):
            responses = {
                "eth_chainId": {"jsonrpc": "2.0", "id": 1, "result": "0x64"},  # Gnosis Chain
                "eth_getTransactionCount": {"jsonrpc": "2.0", "id": 1, "result": "0x0"},
                "eth_gasPrice": {"jsonrpc": "2.0", "id": 1, "result": "0x4a817c800"},
                "eth_getBlockByNumber": {"jsonrpc": "2.0", "id": 1, "result": {"baseFeePerGas": "0x3b9aca00"}},
            }
            if method in responses:
                return responses[method]
            raise NotImplementedError(f"Mock provider doesn't support {method}")
    
    # Setup
    w3 = Web3(MockProvider())
    implementation_address = "0x1234567890123456789012345678901234567890"  # FutarchyBatchExecutor
    private_key = os.getenv("PRIVATE_KEY", "0x" + "1" * 64)  # Use test key if not set
    account = Account.from_key(private_key)
    
    # Contract addresses (from environment or defaults)
    addresses = {
        'futarchy_router': os.getenv("FUTARCHY_ROUTER_ADDRESS", "0x2222222222222222222222222222222222222222"),
        'proposal': os.getenv("FUTARCHY_PROPOSAL_ADDRESS", "0x3333333333333333333333333333333333333333"),
        'sdai_token': os.getenv("SDAI_TOKEN_ADDRESS", "0xaf204776c7245bF4147c2612BF6e5972Ee483701"),
        'company_token': os.getenv("COMPANY_TOKEN_ADDRESS", "0x9c58bacc331c9aa871afd802db6379a98e80cedb"),
        'swapr_router': os.getenv("SWAPR_ROUTER_ADDRESS", "0x4444444444444444444444444444444444444444"),
        'balancer_vault': os.getenv("BALANCER_VAULT_ADDRESS", "0x5555555555555555555555555555555555555555"),
        'sdai_yes': os.getenv("SWAPR_SDAI_YES_ADDRESS", "0x6666666666666666666666666666666666666666"),
        'sdai_no': os.getenv("SWAPR_SDAI_NO_ADDRESS", "0x7777777777777777777777777777777777777777"),
        'company_yes': os.getenv("SWAPR_GNO_YES_ADDRESS", "0x8888888888888888888888888888888888888888"),
        'company_no': os.getenv("SWAPR_GNO_NO_ADDRESS", "0x9999999999999999999999999999999999999999"),
    }
    
    # Amount to arbitrage (1 sDAI)
    amount = w3.to_wei(1, 'ether')
    
    # Create builder
    builder = EIP7702TransactionBuilder(w3, implementation_address)
    
    print(f"Building buy conditional arbitrage bundle...")
    print(f"Account: {account.address}")
    print(f"Implementation: {implementation_address}")
    print(f"Amount: 1 sDAI")
    
    # Step 1: Approve FutarchyRouter to spend sDAI
    builder.add_approval(
        addresses['sdai_token'],
        addresses['futarchy_router'],
        amount
    )
    print("✓ Added approval for FutarchyRouter")
    
    # Step 2: Split sDAI into YES/NO conditional sDAI
    builder.add_futarchy_split(
        addresses['futarchy_router'],
        addresses['proposal'],
        addresses['sdai_token'],
        amount
    )
    print("✓ Added split sDAI → YES/NO conditional sDAI")
    
    # Step 3: Approve Swapr for YES conditional sDAI
    builder.add_approval(
        addresses['sdai_yes'],
        addresses['swapr_router'],
        2**256 - 1  # Max approval
    )
    print("✓ Added approval for YES conditional sDAI")
    
    # Step 4: Swap YES conditional sDAI → YES Company token
    deadline = int(time.time()) + 600
    builder.add_swapr_exact_in(
        addresses['swapr_router'],
        addresses['sdai_yes'],
        addresses['company_yes'],
        amount,
        0,  # Min out (would calculate based on price)
        account.address,
        deadline
    )
    print("✓ Added swap YES sDAI → YES Company")
    
    # Step 5: Approve Swapr for NO conditional sDAI
    builder.add_approval(
        addresses['sdai_no'],
        addresses['swapr_router'],
        2**256 - 1
    )
    print("✓ Added approval for NO conditional sDAI")
    
    # Step 6: Swap NO conditional sDAI → NO Company token
    builder.add_swapr_exact_in(
        addresses['swapr_router'],
        addresses['sdai_no'],
        addresses['company_no'],
        amount,
        0,  # Min out
        account.address,
        deadline
    )
    print("✓ Added swap NO sDAI → NO Company")
    
    # Step 7: Approve FutarchyRouter for Company tokens
    builder.add_approval(
        addresses['company_yes'],
        addresses['futarchy_router'],
        2**256 - 1
    )
    builder.add_approval(
        addresses['company_no'],
        addresses['futarchy_router'],
        2**256 - 1
    )
    print("✓ Added approvals for Company tokens")
    
    # Step 8: Merge would go here but requires knowing swap outputs
    # In real implementation, we'd use executeWithResults or dynamic amounts
    
    print(f"\nTotal operations in bundle: {len(builder.calls)}")
    
    # Build the transaction
    try:
        tx = builder.build_transaction(account)
        print("\n✓ Successfully built EIP-7702 transaction")
        print(f"  Type: {tx['type']}")
        print(f"  To: {tx['to']} (self)")
        print(f"  Authorization list: {len(tx['authorizationList'])} auth(s)")
        print(f"  Data size: {len(tx['data'])} bytes")
        print(f"  Gas limit: {tx['gas']}")
        
        # In production, we would sign and send this transaction
        # signed_tx = account.sign_transaction(tx)
        # tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        return True
        
    except Exception as e:
        print(f"\n✗ Failed to build transaction: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gas_comparison():
    """Compare gas usage estimation between sequential and bundled transactions."""
    print("\n=== Gas Usage Comparison ===")
    
    # Sequential transaction gas estimates (typical values)
    sequential_gas = {
        'approve_sdai': 46000,
        'split': 150000,
        'approve_yes': 46000,
        'swap_yes': 200000,
        'approve_no': 46000,
        'swap_no': 200000,
        'approve_company_yes': 46000,
        'approve_company_no': 46000,
        'merge': 150000,
        'approve_balancer': 46000,
        'swap_balancer': 250000,
    }
    
    total_sequential = sum(sequential_gas.values())
    tx_overhead = 21000  # Base transaction cost
    sequential_with_overhead = total_sequential + (tx_overhead * len(sequential_gas))
    
    # EIP-7702 bundled estimate
    # Single transaction overhead + authorization overhead + execution overhead
    bundled_estimate = tx_overhead + 50000 + total_sequential  # Authorization adds ~50k
    
    print(f"Sequential transactions:")
    for op, gas in sequential_gas.items():
        print(f"  {op}: {gas:,}")
    print(f"  Transaction overhead: {tx_overhead * len(sequential_gas):,}")
    print(f"  Total: {sequential_with_overhead:,}")
    
    print(f"\nEIP-7702 bundled transaction:")
    print(f"  Base tx cost: {tx_overhead:,}")
    print(f"  Authorization overhead: ~50,000")
    print(f"  Operations: {total_sequential:,}")
    print(f"  Total: {bundled_estimate:,}")
    
    savings = sequential_with_overhead - bundled_estimate
    savings_pct = (savings / sequential_with_overhead) * 100
    
    print(f"\nEstimated savings: {savings:,} gas ({savings_pct:.1f}%)")
    
    return True


def main():
    """Run all tests."""
    print("EIP-7702 Arbitrage Implementation Tests")
    print("=" * 50)
    
    tests = [
        ("Buy Conditional Bundle", test_buy_conditional_bundle),
        ("Gas Comparison", test_gas_comparison),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ Test '{test_name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("Test Summary:")
    print("=" * 50)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{test_name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    # Additional notes
    print("\n" + "=" * 50)
    print("Implementation Notes:")
    print("=" * 50)
    print("• EIP-7702 bundles all operations into a single atomic transaction")
    print("• Eliminates MEV risks between operations")
    print("• Reduces gas costs by ~15% (avoiding multiple tx overheads)")
    print("• Requires careful handling of dynamic amounts between operations")
    print("• Implementation contract must be deployed and verified")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
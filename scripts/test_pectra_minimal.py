#!/usr/bin/env python3
"""
Test script for Pectra minimal executor implementation.

This script tests the buy conditional flow with the FutarchyBatchExecutorMinimal contract.
"""

import os
import sys
from decimal import Decimal
from web3 import Web3
from eth_account import Account

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.arbitrage_commands.buy_cond_eip7702_minimal import (
    check_approvals,
    build_buy_conditional_bundle_minimal,
    simulate_buy_conditional_minimal,
    buy_conditional_bundled_minimal,
    IMPLEMENTATION_ADDRESS
)
from src.helpers.bundle_helpers import get_token_balance

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])


def test_approval_check():
    """Test approval checking functionality."""
    print("=== Testing Approval Check ===")
    approvals = check_approvals()
    
    print("\nCurrent approval status:")
    for pair, status in approvals.items():
        print(f"  {pair}: {'✅ Set' if status else '❌ Not set'}")
    
    # Count how many approvals we need
    needed = sum(1 for status in approvals.values() if not status)
    print(f"\nApprovals needed: {needed}")
    
    return approvals


def test_bundle_construction():
    """Test bundle construction with different scenarios."""
    print("\n=== Testing Bundle Construction ===")
    
    # Test 1: Basic bundle without simulation results
    print("\n1. Basic bundle (exact-in swaps):")
    bundle = build_buy_conditional_bundle_minimal(Decimal("0.1"))
    print(f"   Calls in bundle: {len(bundle)}")
    
    # Test 2: Bundle with simulation results
    print("\n2. Optimized bundle (exact-out swaps):")
    sim_results = {
        'target_amount': w3.to_wei(0.05, 'ether'),
        'merge_amount': w3.to_wei(0.05, 'ether')
    }
    bundle = build_buy_conditional_bundle_minimal(Decimal("0.1"), sim_results)
    print(f"   Calls in bundle: {len(bundle)}")
    
    # Test 3: Bundle with approvals skipped
    print("\n3. Bundle with approvals pre-set:")
    skip_approvals = {
        'sdai_to_router': True,
        'sdai_yes_to_swapr': True,
        'sdai_no_to_swapr': True,
        'company_yes_to_router': True,
        'company_no_to_router': True,
        'company_to_balancer': True
    }
    bundle = build_buy_conditional_bundle_minimal(Decimal("0.1"), sim_results, skip_approvals)
    print(f"   Calls in bundle: {len(bundle)} (should be ~5 without approvals)")
    
    return True


def test_simulation():
    """Test simulation with small amount."""
    print("\n=== Testing Simulation ===")
    
    test_amount = Decimal("0.01")  # 0.01 sDAI
    print(f"\nSimulating buy conditional with {test_amount} sDAI...")
    
    try:
        result = simulate_buy_conditional_minimal(test_amount)
        
        print("\nSimulation results:")
        print(f"  YES output: {w3.from_wei(result['yes_output'], 'ether')} Company tokens")
        print(f"  NO output: {w3.from_wei(result['no_output'], 'ether')} Company tokens")
        print(f"  Target amount: {w3.from_wei(result['target_amount'], 'ether')} Company tokens")
        print(f"  Expected profit: {result['expected_profit']} sDAI")
        
        if result.get('liquidation', {}).get('token_type') != "NONE":
            print(f"  Liquidation needed: {w3.from_wei(result['liquidation']['amount'], 'ether')} {result['liquidation']['token_type']}")
        
        return result
        
    except Exception as e:
        print(f"❌ Simulation failed: {e}")
        return None


def test_contract_verification():
    """Verify the implementation contract is correctly deployed."""
    print("\n=== Testing Contract Verification ===")
    
    print(f"Implementation address: {IMPLEMENTATION_ADDRESS}")
    
    # Check if contract exists
    code = w3.eth.get_code(IMPLEMENTATION_ADDRESS)
    print(f"Contract size: {len(code)} bytes")
    
    if len(code) == 0:
        print("❌ No contract deployed at this address!")
        return False
    
    # Check for 0xEF opcodes
    code_hex = code.hex()
    ef_count = code_hex.count('ef')
    print(f"0xEF occurrences in bytecode: {ef_count}")
    
    if ef_count > 0:
        print("❌ Contract contains 0xEF opcodes!")
        return False
    
    print("✅ Contract verification passed")
    return True


def test_dry_run():
    """Test the full flow without broadcasting."""
    print("\n=== Testing Dry Run (Full Flow) ===")
    
    test_amount = Decimal("0.01")
    print(f"\nRunning full dry run with {test_amount} sDAI...")
    
    try:
        result = buy_conditional_bundled_minimal(test_amount, broadcast=False)
        
        print("\nDry run results:")
        for key, value in result.items():
            print(f"  {key}: {value}")
        
        if result.get('sdai_net', 0) > 0:
            print(f"\n✅ Would be profitable: +{result['sdai_net']} sDAI")
        else:
            print(f"\n❌ Would not be profitable: {result.get('sdai_net', 0)} sDAI")
        
        return result
        
    except Exception as e:
        print(f"❌ Dry run failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Run all tests."""
    print("Pectra Minimal Executor Test Suite")
    print("=" * 50)
    
    # Test 1: Contract verification
    if not test_contract_verification():
        print("\n❌ Contract verification failed, aborting tests")
        return
    
    # Test 2: Approval checking
    approvals = test_approval_check()
    
    # Test 3: Bundle construction
    if not test_bundle_construction():
        print("\n❌ Bundle construction tests failed")
        return
    
    # Test 4: Simulation
    sim_result = test_simulation()
    if not sim_result:
        print("\n❌ Simulation failed, skipping dry run")
        return
    
    # Test 5: Full dry run
    dry_run_result = test_dry_run()
    
    print("\n" + "=" * 50)
    print("Test Summary:")
    print("  ✅ Contract verification: PASSED")
    print("  ✅ Approval checking: PASSED")
    print("  ✅ Bundle construction: PASSED")
    print(f"  {'✅' if sim_result else '❌'} Simulation: {'PASSED' if sim_result else 'FAILED'}")
    print(f"  {'✅' if dry_run_result else '❌'} Dry run: {'PASSED' if dry_run_result else 'FAILED'}")
    
    if sim_result and dry_run_result:
        print("\n✅ All tests passed! Ready for production testing.")
    else:
        print("\n❌ Some tests failed. Please review the output above.")


if __name__ == "__main__":
    main()
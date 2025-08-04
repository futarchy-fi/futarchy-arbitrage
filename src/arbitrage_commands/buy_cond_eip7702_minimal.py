"""
Buy conditional tokens using EIP-7702 bundled transactions with FutarchyBatchExecutorMinimal.

This module implements the buy conditional flow using atomic bundled transactions
via EIP-7702 and the minimal executor contract that supports up to 10 calls.
"""

import os
import sys
import time
from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal, InvalidOperation

from web3 import Web3
from eth_account import Account
from eth_abi import encode, decode

from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.bundle_helpers import (
    encode_approval_call,
    encode_split_position_call,
    encode_merge_positions_call,
    encode_swapr_exact_in_call,
    encode_swapr_exact_out_call,
    encode_balancer_swap_call,
    calculate_liquidation_amount,
    build_liquidation_calls,
    decode_revert_reason,
    calculate_bundle_gas_params,
    verify_bundle_profitability,
    simulate_bundle_with_state_tracking,
    extract_outputs_from_state_changes,
    get_token_balance
)

# Initialize Web3 and account
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

# Contract addresses
FUTARCHY_ROUTER = os.environ["FUTARCHY_ROUTER_ADDRESS"]
SWAPR_ROUTER = os.environ["SWAPR_ROUTER_ADDRESS"]
BALANCER_VAULT = os.environ["BALANCER_VAULT_ADDRESS"]
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
BALANCER_POOL = os.environ["BALANCER_POOL_ADDRESS"]


def check_approvals() -> Dict[str, bool]:
    """
    Check if required approvals are already set to max.
    
    Returns:
        Dictionary of approval status for each required pair
    """
    approvals = {}
    
    # Check sDAI -> FutarchyRouter
    allowance = get_allowance(w3, SDAI_TOKEN, account.address, FUTARCHY_ROUTER)
    approvals['sdai_to_router'] = allowance >= 2**255  # Close to max
    
    # Check YES/NO conditional sDAI -> Swapr
    allowance = get_allowance(w3, SDAI_YES, account.address, SWAPR_ROUTER)
    approvals['sdai_yes_to_swapr'] = allowance >= 2**255
    
    allowance = get_allowance(w3, SDAI_NO, account.address, SWAPR_ROUTER)
    approvals['sdai_no_to_swapr'] = allowance >= 2**255
    
    # Check Company tokens -> FutarchyRouter
    allowance = get_allowance(w3, COMPANY_YES, account.address, FUTARCHY_ROUTER)
    approvals['company_yes_to_router'] = allowance >= 2**255
    
    allowance = get_allowance(w3, COMPANY_NO, account.address, FUTARCHY_ROUTER)
    approvals['company_no_to_router'] = allowance >= 2**255
    
    # Check Company -> Balancer
    allowance = get_allowance(w3, COMPANY_TOKEN, account.address, BALANCER_VAULT)
    approvals['company_to_balancer'] = allowance >= 2**255
    
    return approvals


def get_allowance(w3: Web3, token: str, owner: str, spender: str) -> int:
    """Get ERC20 allowance."""
    # allowance(address,address)
    selector = Web3.keccak(text="allowance(address,address)")[:4]
    data = selector + encode(['address', 'address'], [Web3.to_checksum_address(owner), Web3.to_checksum_address(spender)])
    
    result = w3.eth.call({
        'to': Web3.to_checksum_address(token),
        'data': data
    })
    
    return int.from_bytes(result, 'big')


def build_buy_conditional_bundle_minimal(
    amount_sdai: Decimal,
    simulation_results: Optional[Dict[str, Any]] = None,
    skip_approvals: Optional[Dict[str, bool]] = None
) -> List[Dict[str, Any]]:
    """
    Build bundled transaction for buy conditional flow (max 10 calls).
    
    This creates all the necessary calls to:
    1. Split sDAI into YES/NO conditional sDAI
    2. Swap conditional sDAI to conditional Company tokens
    3. Merge conditional Company tokens
    4. Swap Company token to sDAI on Balancer
    5. Handle any imbalanced amounts via liquidation
    
    Args:
        amount_sdai: Amount of sDAI to use for arbitrage
        simulation_results: Results from pre-bundle simulation (for exact-out amounts)
        skip_approvals: Dictionary of approvals to skip (already set to max)
    
    Returns:
        List of Call dictionaries for the bundle
    """
    calls = []
    amount_wei = w3.to_wei(amount_sdai, 'ether')
    
    if skip_approvals is None:
        skip_approvals = {}
    
    # Count calls as we go to ensure we don't exceed 10
    call_count = 0
    
    # Step 1: Approve sDAI to FutarchyRouter (if needed)
    if not skip_approvals.get('sdai_to_router', False):
        calls.append(encode_approval_call(SDAI_TOKEN, FUTARCHY_ROUTER, amount_wei))
        call_count += 1
    
    # Step 2: Split sDAI into YES/NO conditional sDAI
    calls.append(encode_split_position_call(
        FUTARCHY_ROUTER, FUTARCHY_PROPOSAL, SDAI_TOKEN, amount_wei
    ))
    call_count += 1
    
    # Steps 3-6: Swap conditional sDAI to conditional Company tokens
    if simulation_results and 'target_amount' in simulation_results:
        # Use exact-out swaps based on simulation
        target_amount = simulation_results['target_amount']
        max_input = int(amount_wei * 1.1)  # 10% slippage buffer
        
        # YES swap (exact-out)
        if not skip_approvals.get('sdai_yes_to_swapr', False):
            calls.append(encode_approval_call(SDAI_YES, SWAPR_ROUTER, max_input))
            call_count += 1
        calls.append(encode_swapr_exact_out_call(
            SWAPR_ROUTER, SDAI_YES, COMPANY_YES, target_amount, max_input, account.address
        ))
        call_count += 1
        
        # NO swap (exact-out)
        if not skip_approvals.get('sdai_no_to_swapr', False):
            calls.append(encode_approval_call(SDAI_NO, SWAPR_ROUTER, max_input))
            call_count += 1
        calls.append(encode_swapr_exact_out_call(
            SWAPR_ROUTER, SDAI_NO, COMPANY_NO, target_amount, max_input, account.address
        ))
        call_count += 1
    else:
        # Use exact-in swaps for initial simulation
        # YES swap (exact-in)
        if not skip_approvals.get('sdai_yes_to_swapr', False):
            calls.append(encode_approval_call(SDAI_YES, SWAPR_ROUTER, amount_wei))
            call_count += 1
        calls.append(encode_swapr_exact_in_call(
            SWAPR_ROUTER, SDAI_YES, COMPANY_YES, amount_wei, 0, account.address
        ))
        call_count += 1
        
        # NO swap (exact-in)
        if not skip_approvals.get('sdai_no_to_swapr', False):
            calls.append(encode_approval_call(SDAI_NO, SWAPR_ROUTER, amount_wei))
            call_count += 1
        calls.append(encode_swapr_exact_in_call(
            SWAPR_ROUTER, SDAI_NO, COMPANY_NO, amount_wei, 0, account.address
        ))
        call_count += 1
    
    # Check if we have room for merge operations
    if call_count >= 8:
        print(f"Warning: Bundle has {call_count} calls, may not fit all operations")
    
    # Steps 7-9: Merge Company tokens
    merge_amount = simulation_results.get('merge_amount', 0) if simulation_results else 0
    
    if not skip_approvals.get('company_yes_to_router', False) and call_count < 10:
        calls.append(encode_approval_call(COMPANY_YES, FUTARCHY_ROUTER, 2**256 - 1))
        call_count += 1
    
    if not skip_approvals.get('company_no_to_router', False) and call_count < 10:
        calls.append(encode_approval_call(COMPANY_NO, FUTARCHY_ROUTER, 2**256 - 1))
        call_count += 1
    
    if call_count < 10:
        calls.append(encode_merge_positions_call(
            FUTARCHY_ROUTER, FUTARCHY_PROPOSAL, COMPANY_TOKEN, merge_amount
        ))
        call_count += 1
    
    # Steps 10-11: Swap Company token to sDAI on Balancer
    # This is critical for completing the arbitrage
    if call_count < 10 and not skip_approvals.get('company_to_balancer', False):
        calls.append(encode_approval_call(COMPANY_TOKEN, BALANCER_VAULT, 2**256 - 1))
        call_count += 1
    
    if call_count < 10:
        calls.append(encode_balancer_swap_call(
            BALANCER_VAULT, BALANCER_POOL, COMPANY_TOKEN, SDAI_TOKEN,
            merge_amount, account.address, account.address
        ))
        call_count += 1
    else:
        print("Warning: No room for Balancer swap - bundle incomplete!")
    
    # Liquidation calls would go here if there's room
    if simulation_results and 'liquidation' in simulation_results and call_count < 10:
        liq = simulation_results['liquidation']
        if liq['amount'] > 0 and liq['token_type'] == "YES":
            # Only simple YES liquidation fits
            remaining = 10 - call_count
            if remaining >= 2:
                calls.append(encode_approval_call(SDAI_YES, SWAPR_ROUTER, liq['amount']))
                calls.append(encode_swapr_exact_in_call(
                    SWAPR_ROUTER, SDAI_YES, SDAI_TOKEN, liq['amount'], 0, account.address
                ))
                call_count += 2
    
    print(f"Bundle created with {call_count} calls")
    return calls


def simulate_buy_conditional_minimal(amount: Decimal) -> Dict[str, Any]:
    """
    Perform simulation for buy conditional flow using state tracking.
    
    Since FutarchyBatchExecutorMinimal doesn't return data, we track token
    balance changes to determine swap outputs.
    
    Args:
        amount: Amount of sDAI to use
    
    Returns:
        Simulation results including optimal parameters
    """
    amount_wei = w3.to_wei(amount, 'ether')
    
    # Check which approvals are already set
    approvals = check_approvals()
    print("Approval status:")
    for key, value in approvals.items():
        print(f"  {key}: {'✓' if value else '✗'}")
    
    # Tokens to track during simulation
    tokens_to_track = [
        SDAI_TOKEN,
        SDAI_YES,
        SDAI_NO,
        COMPANY_YES,
        COMPANY_NO,
        COMPANY_TOKEN
    ]
    
    # Step 1: Discovery simulation with exact-in swaps
    print("\nStep 1: Discovery simulation with exact-in swaps...")
    discovery_bundle = build_buy_conditional_bundle_minimal(amount, skip_approvals=approvals)
    
    # Run simulation with state tracking
    sim_result = simulate_bundle_with_state_tracking(
        w3,
        account.address,
        IMPLEMENTATION_ADDRESS,
        discovery_bundle,
        tokens_to_track
    )
    
    if not sim_result['success']:
        raise Exception(f"Discovery simulation failed: {sim_result.get('revert_reason', sim_result.get('error'))}")
    
    # Extract outputs from balance changes
    balance_changes = sim_result['balance_changes']
    yes_out = balance_changes.get(COMPANY_YES, 0)
    no_out = balance_changes.get(COMPANY_NO, 0)
    
    print(f"  YES output: {w3.from_wei(yes_out, 'ether')} Company tokens")
    print(f"  NO output: {w3.from_wei(no_out, 'ether')} Company tokens")
    
    # Check if profitable
    sdai_change = balance_changes.get(SDAI_TOKEN, 0)
    print(f"  sDAI change: {w3.from_wei(sdai_change, 'ether')}")
    
    # Step 2: Balanced simulation with exact-out swaps
    print("\nStep 2: Balanced simulation with exact-out swaps...")
    target_amount = min(yes_out, no_out)
    
    balanced_sim_params = {
        'target_amount': target_amount,
        'merge_amount': target_amount
    }
    
    balanced_bundle = build_buy_conditional_bundle_minimal(amount, balanced_sim_params, skip_approvals=approvals)
    
    balanced_result = simulate_bundle_with_state_tracking(
        w3,
        account.address,
        IMPLEMENTATION_ADDRESS,
        balanced_bundle,
        tokens_to_track
    )
    
    if not balanced_result['success']:
        print(f"Warning: Balanced simulation failed, using discovery results")
        return {
            'target_amount': target_amount,
            'yes_output': yes_out,
            'no_output': no_out,
            'sdai_net': sdai_change,
            'expected_profit': w3.from_wei(sdai_change, 'ether')
        }
    
    # Extract final results
    final_balance_changes = balanced_result['balance_changes']
    final_sdai_change = final_balance_changes.get(SDAI_TOKEN, 0)
    
    # Check for imbalances
    yes_sdai_remaining = final_balance_changes.get(SDAI_YES, 0)
    no_sdai_remaining = final_balance_changes.get(SDAI_NO, 0)
    
    print(f"  Target amount: {w3.from_wei(target_amount, 'ether')} Company tokens")
    print(f"  Final sDAI change: {w3.from_wei(final_sdai_change, 'ether')}")
    
    if yes_sdai_remaining > 0 or no_sdai_remaining > 0:
        print(f"  Conditional sDAI remaining - YES: {w3.from_wei(yes_sdai_remaining, 'ether')}, NO: {w3.from_wei(no_sdai_remaining, 'ether')}")
    
    return {
        'target_amount': target_amount,
        'yes_output': yes_out,
        'no_output': no_out,
        'sdai_net': final_sdai_change,
        'expected_profit': w3.from_wei(final_sdai_change, 'ether'),
        'liquidation': {
            'amount': max(yes_sdai_remaining, no_sdai_remaining),
            'token_type': "YES" if yes_sdai_remaining > no_sdai_remaining else "NO" if no_sdai_remaining > 0 else "NONE"
        }
    }


def buy_conditional_bundled_minimal(
    amount: Decimal,
    broadcast: bool = False
) -> Dict[str, Any]:
    """
    Execute buy conditional flow using EIP-7702 bundled transactions.
    
    This is the main entry point that performs simulation and optional execution.
    
    Args:
        amount: Amount of sDAI to use for arbitrage
        broadcast: If True, execute the transaction; if False, only simulate
    
    Returns:
        Dictionary with results (simulation or execution)
    """
    # Always run simulation first to get optimal parameters
    try:
        simulation_results = simulate_buy_conditional_minimal(amount)
    except Exception as e:
        print(f"Simulation failed: {e}")
        return {
            'status': 'simulation_failed',
            'error': str(e),
            'sdai_net': Decimal('0')
        }
    
    if not broadcast:
        # Return simulation results
        return {
            'status': 'simulated',
            'sdai_in': amount,
            'sdai_net': w3.from_wei(simulation_results['sdai_net'], 'ether'),
            'yes_output': w3.from_wei(simulation_results['yes_output'], 'ether'),
            'no_output': w3.from_wei(simulation_results['no_output'], 'ether'),
            'target_amount': w3.from_wei(simulation_results['target_amount'], 'ether'),
            'expected_profit': simulation_results['expected_profit'],
            'gas_estimate': 1500000  # Conservative estimate for minimal executor
        }
    
    # Execute transaction
    print("\nBroadcasting bundled transaction...")
    
    # Check approvals again before execution
    approvals = check_approvals()
    
    # Build optimized bundle based on simulation
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    final_bundle = build_buy_conditional_bundle_minimal(
        amount, 
        simulation_results,
        skip_approvals=approvals
    )
    
    # Add calls to builder
    for call in final_bundle:
        builder.add_call(call['target'], call['value'], call['data'])
    
    # Build and sign transaction
    tx = builder.build_transaction(account, calculate_bundle_gas_params(w3))
    signed_tx = account.sign_transaction(tx)
    
    # Send transaction
    if hasattr(signed_tx, 'rawTransaction'):
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    elif hasattr(signed_tx, 'raw_transaction'):
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    else:
        tx_hash = w3.eth.send_raw_transaction(signed_tx)
    
    print(f"Transaction sent: {tx_hash.hex()}")
    
    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    # Calculate actual profit from events
    actual_profit = calculate_profit_from_receipt(receipt)
    
    return {
        'status': 'success' if receipt.status == 1 else 'failed',
        'tx_hash': tx_hash.hex(),
        'gas_used': receipt.gasUsed,
        'effective_gas_price': receipt.effectiveGasPrice,
        'block_number': receipt.blockNumber,
        'sdai_net': actual_profit,
        'gas_cost_eth': w3.from_wei(receipt.gasUsed * receipt.effectiveGasPrice, 'ether')
    }


def calculate_profit_from_receipt(receipt) -> Decimal:
    """Calculate actual sDAI profit from transaction receipt."""
    # Parse Transfer events for sDAI
    sdai_in = Decimal('0')
    sdai_out = Decimal('0')
    
    transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)")
    
    for log in receipt.logs:
        if len(log.topics) >= 3 and log.topics[0] == transfer_topic:
            if log.address.lower() == SDAI_TOKEN.lower():
                from_addr = '0x' + log.topics[1].hex()[-40:]
                to_addr = '0x' + log.topics[2].hex()[-40:]
                amount = int(log.data.hex(), 16)
                
                if to_addr.lower() == account.address.lower():
                    sdai_in += w3.from_wei(amount, 'ether')
                elif from_addr.lower() == account.address.lower():
                    sdai_out += w3.from_wei(amount, 'ether')
    
    return sdai_in - sdai_out


def main():
    """Main entry point for CLI usage."""
    SEND_FLAG = {"--send", "-s"}
    broadcast = any(flag in sys.argv for flag in SEND_FLAG)
    sys.argv = [arg for arg in sys.argv if arg not in SEND_FLAG]
    
    if len(sys.argv) < 2:
        print("Usage: python buy_cond_eip7702_minimal.py <amount> [--send]")
        sys.exit(1)
    
    try:
        amount = Decimal(sys.argv[1])
    except (ValueError, InvalidOperation):
        print("Error: Invalid amount")
        sys.exit(1)
    
    # Verify environment
    if not IMPLEMENTATION_ADDRESS:
        print("Error: FUTARCHY_BATCH_EXECUTOR_ADDRESS not set")
        print("Using default: 0x65eb5a03635c627a0f254707712812B234753F31")
    
    print(f"Buying conditional tokens with {amount} sDAI using EIP-7702 bundles (Minimal)")
    print(f"Implementation contract: {IMPLEMENTATION_ADDRESS}")
    print(f"Max calls per bundle: 10")
    print(f"Broadcast: {broadcast}")
    print()
    
    try:
        result = buy_conditional_bundled_minimal(amount, broadcast=broadcast)
        
        print("\nResults:")
        for key, value in result.items():
            print(f"  {key}: {value}")
        
        if result.get('sdai_net', 0) > 0:
            print(f"\n✅ Profitable: +{result['sdai_net']} sDAI")
        else:
            print(f"\n❌ Not profitable: {result.get('sdai_net', 0)} sDAI")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
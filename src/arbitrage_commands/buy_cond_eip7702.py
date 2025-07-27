"""
Buy conditional tokens using EIP-7702 bundled transactions.

This module implements the buy conditional flow using atomic bundled transactions
via EIP-7702, replacing the sequential transaction approach with a single
atomic operation.
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
    parse_bundle_results,
    extract_swap_outputs,
    calculate_liquidation_amount,
    build_liquidation_calls,
    decode_revert_reason,
    calculate_bundle_gas_params,
    verify_bundle_profitability
)

# Initialize Web3 and account
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

# Contract addresses
FUTARCHY_ROUTER = os.environ["FUTARCHY_ROUTER_ADDRESS"]
SWAPR_ROUTER = os.environ["SWAPR_ROUTER_ADDRESS"]
BALANCER_VAULT = os.environ["BALANCER_VAULT_ADDRESS"]
IMPLEMENTATION_ADDRESS = os.environ.get("FUTARCHY_BATCH_EXECUTOR_ADDRESS", "")

# Token addresses
SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]
COMPANY_TOKEN = os.environ["COMPANY_TOKEN_ADDRESS"]
SDAI_YES = os.environ["SWAPR_SDAI_YES_ADDRESS"]
SDAI_NO = os.environ["SWAPR_SDAI_NO_ADDRESS"]
COMPANY_YES = os.environ["SWAPR_GNO_YES_ADDRESS"]
COMPANY_NO = os.environ["SWAPR_GNO_NO_ADDRESS"]

# Other parameters
FUTARCHY_PROPOSAL = os.environ["FUTARCHY_PROPOSAL_ADDRESS"]
BALANCER_POOL_ID = os.environ.get("BALANCER_POOL_ID", "")


def build_buy_conditional_bundle(
    amount_sdai: Decimal,
    simulation_results: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Build bundled transaction for buy conditional flow.
    
    This creates all the necessary calls to:
    1. Split sDAI into YES/NO conditional sDAI
    2. Swap conditional sDAI to conditional Company tokens
    3. Merge conditional Company tokens
    4. Swap Company token to sDAI on Balancer
    5. Handle any imbalanced amounts via liquidation
    
    Args:
        amount_sdai: Amount of sDAI to use for arbitrage
        simulation_results: Results from pre-bundle simulation (for exact-out amounts)
    
    Returns:
        List of Call dictionaries for the bundle
    """
    calls = []
    amount_wei = w3.to_wei(amount_sdai, 'ether')
    
    # Step 1: Approve sDAI to FutarchyRouter
    calls.append(encode_approval_call(SDAI_TOKEN, FUTARCHY_ROUTER, amount_wei))
    
    # Step 2: Split sDAI into YES/NO conditional sDAI
    calls.append(encode_split_position_call(
        FUTARCHY_ROUTER, FUTARCHY_PROPOSAL, SDAI_TOKEN, amount_wei
    ))
    
    # Steps 3-6: Swap conditional sDAI to conditional Company tokens
    if simulation_results and 'target_amount' in simulation_results:
        # Use exact-out swaps based on simulation
        target_amount = simulation_results['target_amount']
        max_input = int(amount_wei * 1.1)  # 10% slippage buffer
        
        # YES swap (exact-out)
        calls.append(encode_approval_call(SDAI_YES, SWAPR_ROUTER, max_input))
        calls.append(encode_swapr_exact_out_call(
            SWAPR_ROUTER, SDAI_YES, COMPANY_YES, target_amount, max_input, account.address
        ))
        
        # NO swap (exact-out)
        calls.append(encode_approval_call(SDAI_NO, SWAPR_ROUTER, max_input))
        calls.append(encode_swapr_exact_out_call(
            SWAPR_ROUTER, SDAI_NO, COMPANY_NO, target_amount, max_input, account.address
        ))
    else:
        # Use exact-in swaps for initial simulation
        # YES swap (exact-in)
        calls.append(encode_approval_call(SDAI_YES, SWAPR_ROUTER, amount_wei))
        calls.append(encode_swapr_exact_in_call(
            SWAPR_ROUTER, SDAI_YES, COMPANY_YES, amount_wei, 0, account.address
        ))
        
        # NO swap (exact-in)
        calls.append(encode_approval_call(SDAI_NO, SWAPR_ROUTER, amount_wei))
        calls.append(encode_swapr_exact_in_call(
            SWAPR_ROUTER, SDAI_NO, COMPANY_NO, amount_wei, 0, account.address
        ))
    
    # Steps 7-9: Merge Company tokens
    # Note: In actual execution, this amount will be dynamic based on swap outputs
    merge_amount = simulation_results.get('merge_amount', 0) if simulation_results else 0
    
    calls.append(encode_approval_call(COMPANY_YES, FUTARCHY_ROUTER, 2**256 - 1))
    calls.append(encode_approval_call(COMPANY_NO, FUTARCHY_ROUTER, 2**256 - 1))
    calls.append(encode_merge_positions_call(
        FUTARCHY_ROUTER, FUTARCHY_PROPOSAL, COMPANY_TOKEN, merge_amount
    ))
    
    # Steps 10-11: Swap Company token to sDAI on Balancer
    calls.append(encode_approval_call(COMPANY_TOKEN, BALANCER_VAULT, 2**256 - 1))
    calls.append(encode_balancer_swap_call(
        BALANCER_VAULT, BALANCER_POOL_ID, COMPANY_TOKEN, SDAI_TOKEN,
        merge_amount, account.address, account.address
    ))
    
    # Step 12: Add liquidation calls if needed (from simulation results)
    if simulation_results and 'liquidation' in simulation_results:
        liq = simulation_results['liquidation']
        if liq['amount'] > 0:
            liquidation_calls = build_liquidation_calls(
                liq['amount'], liq['token_type'], SWAPR_ROUTER, FUTARCHY_ROUTER
            )
            calls.extend(liquidation_calls)
    
    return calls


def dry_run_bundle(
    tx_data: bytes,
    from_address: str,
    value: int = 0
) -> bytes:
    """
    Execute a dry-run of the bundle using eth_call.
    
    This simulates the transaction without making state changes,
    using state overrides to simulate EIP-7702 delegation.
    
    Args:
        tx_data: Encoded transaction data
        from_address: Address that would send the transaction
        value: ETH value (usually 0)
    
    Returns:
        Raw result bytes that can be decoded
    """
    # State overrides to simulate EIP-7702 delegation
    state_overrides = {
        from_address: {
            'code': w3.eth.get_code(IMPLEMENTATION_ADDRESS)
        }
    }
    
    # Prepare call parameters
    call_params = {
        'from': from_address,
        'to': from_address,  # Self-call with delegated code
        'data': tx_data,
        'value': value,
        'gas': 10000000,  # High gas limit for simulation
    }
    
    try:
        # Execute eth_call with state overrides
        result = w3.eth.call(call_params, 'latest', state_overrides)
        return result
    except Exception as e:
        # Extract revert reason if available
        if hasattr(e, 'data'):
            error_msg = decode_revert_reason(e.data)
            raise Exception(f"Dry run failed: {error_msg}")
        raise


def simulate_buy_conditional_bundle(amount: Decimal) -> Dict[str, Any]:
    """
    Perform the 3-step simulation approach for buy conditional flow.
    
    Steps:
    1. Discovery simulation with exact-in swaps
    2. Balanced simulation with exact-out swaps using min(YES, NO)
    3. Final simulation including liquidation
    
    Args:
        amount: Amount of sDAI to use
    
    Returns:
        Simulation results including optimal parameters
    """
    amount_wei = w3.to_wei(amount, 'ether')
    
    # Helper function to run a simulation
    def run_simulation(bundle_calls: List[Dict]) -> bytes:
        # Get calldata for executeWithResults
        execute_selector = w3.keccak(text="executeWithResults((address,uint256,bytes)[])")[:4]
        calls_data = [(call['target'], call['value'], call['data']) for call in bundle_calls]
        encoded_calls = encode(['(address,uint256,bytes)[]'], [calls_data])
        tx_data = execute_selector + encoded_calls
        return dry_run_bundle(tx_data, account.address)
    
    # Step 1: Discovery simulation (exact-in)
    print("Step 1: Discovery simulation with exact-in swaps...")
    discovery_bundle = build_buy_conditional_bundle(amount)
    discovery_result = run_simulation(discovery_bundle)
    
    # Parse discovery results
    discovery_map = {
        0: ('approval', 'sdai_to_router'),
        1: ('split', 'split_sdai'),
        2: ('approval', 'yes_to_swapr'),
        3: ('swap', 'yes_swap_exact_in'),
        4: ('approval', 'no_to_swapr'),
        5: ('swap', 'no_swap_exact_in'),
        6: ('approval', 'yes_company_to_router'),
        7: ('approval', 'no_company_to_router'),
        8: ('merge', 'merge_company'),
        9: ('approval', 'company_to_balancer'),
        10: ('balancer_swap', 'final_swap')
    }
    
    parsed_discovery = parse_bundle_results(discovery_result, discovery_map)
    yes_out, no_out = extract_swap_outputs(parsed_discovery)
    
    print(f"  YES output: {w3.from_wei(yes_out, 'ether')} Company tokens")
    print(f"  NO output: {w3.from_wei(no_out, 'ether')} Company tokens")
    
    # Step 2: Balanced simulation (exact-out)
    print("\nStep 2: Balanced simulation with exact-out swaps...")
    target_amount = min(yes_out, no_out)
    
    balanced_bundle = build_buy_conditional_bundle(amount, {
        'target_amount': target_amount,
        'merge_amount': target_amount
    })
    balanced_result = run_simulation(balanced_bundle)
    
    # Parse balanced results to get actual amounts used
    parsed_balanced = parse_bundle_results(balanced_result, discovery_map)
    
    # Extract amounts used for each swap
    yes_used = amount_wei  # Default to full amount
    no_used = amount_wei
    
    if 'yes_swap_exact_in' in parsed_balanced:
        if 'amount_in' in parsed_balanced['yes_swap_exact_in']:
            yes_used = parsed_balanced['yes_swap_exact_in']['amount_in']
    
    if 'no_swap_exact_in' in parsed_balanced:
        if 'amount_in' in parsed_balanced['no_swap_exact_in']:
            no_used = parsed_balanced['no_swap_exact_in']['amount_in']
    
    # Calculate liquidation needs
    liquidation_amount, liquidation_type = calculate_liquidation_amount(
        target_amount, target_amount, yes_used, no_used
    )
    
    print(f"  Target amount: {w3.from_wei(target_amount, 'ether')} Company tokens")
    print(f"  Liquidation needed: {w3.from_wei(liquidation_amount, 'ether')} {liquidation_type} sDAI")
    
    # Step 3: Final simulation with liquidation
    print("\nStep 3: Final simulation with liquidation...")
    
    final_simulation = {
        'target_amount': target_amount,
        'merge_amount': target_amount,
        'liquidation': {
            'amount': liquidation_amount,
            'token_type': liquidation_type
        }
    }
    
    final_bundle = build_buy_conditional_bundle(amount, final_simulation)
    final_result = run_simulation(final_bundle)
    
    # Parse final results
    # Update operation map to include liquidation operations
    final_map = discovery_map.copy()
    if liquidation_type != "NONE":
        next_idx = len(discovery_map)
        if liquidation_type == "YES":
            final_map[next_idx] = ('approval', 'liquidate_yes_approval')
            final_map[next_idx + 1] = ('swap', 'liquidate_yes_swap')
        else:  # NO liquidation is more complex
            final_map[next_idx] = ('approval', 'liquidate_buy_yes_approval')
            final_map[next_idx + 1] = ('swap', 'liquidate_buy_yes')
            final_map[next_idx + 2] = ('approval', 'liquidate_merge_yes_approval')
            final_map[next_idx + 3] = ('approval', 'liquidate_merge_no_approval')
            final_map[next_idx + 4] = ('merge', 'liquidate_merge')
    
    parsed_final = parse_bundle_results(final_result, final_map)
    
    # Calculate expected sDAI output from Balancer swap
    sdai_out = 0
    if 'final_swap' in parsed_final and 'amount_out' in parsed_final['final_swap']:
        sdai_out = parsed_final['final_swap']['amount_out']
    
    # Add liquidation output if applicable
    if liquidation_type == "YES" and 'liquidate_yes_swap' in parsed_final:
        if 'amount_out' in parsed_final['liquidate_yes_swap']:
            sdai_out += parsed_final['liquidate_yes_swap']['amount_out']
    elif liquidation_type == "NO" and 'liquidate_merge' in parsed_final:
        # After merge, we get sDAI back
        sdai_out += liquidation_amount  # Approximate
    
    sdai_net = sdai_out - amount_wei
    print(f"  Expected sDAI out: {w3.from_wei(sdai_out, 'ether')}")
    print(f"  Net profit: {w3.from_wei(sdai_net, 'ether')} sDAI")
    
    return {
        'target_amount': target_amount,
        'yes_output': yes_out,
        'no_output': no_out,
        'liquidation': {
            'amount': liquidation_amount,
            'token_type': liquidation_type
        },
        'sdai_out': sdai_out,
        'sdai_net': sdai_net,
        'expected_profit': w3.from_wei(sdai_net, 'ether')
    }


def buy_conditional_bundled(
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
    # Run 3-step simulation
    simulation_results = simulate_buy_conditional_bundle(amount)
    
    # Build final optimized bundle
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    final_bundle = build_buy_conditional_bundle(amount, simulation_results)
    
    # Add calls to builder
    for call in final_bundle:
        builder.add_call(call['target'], call['value'], call['data'])
    
    if broadcast:
        print("\nBroadcasting bundled transaction...")
        
        # Build and sign transaction
        tx = builder.build_transaction(account, calculate_bundle_gas_params(w3))
        signed_tx = account.sign_transaction(tx)
        
        # Send transaction
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        print(f"Transaction sent: {tx_hash.hex()}")
        
        # Wait for receipt
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        # Calculate profit from events
        # TODO: Parse Transfer events to calculate actual profit
        
        return {
            'status': 'success' if receipt.status == 1 else 'failed',
            'tx_hash': tx_hash.hex(),
            'gas_used': receipt.gasUsed,
            'effective_gas_price': receipt.effectiveGasPrice,
            'block_number': receipt.blockNumber,
            'sdai_net': Decimal('0')  # To be calculated from events
        }
    else:
        # Return simulation results
        sdai_in = amount
        sdai_out = amount + simulation_results.get('expected_profit', Decimal('0'))
        
        return {
            'status': 'simulated',
            'sdai_in': sdai_in,
            'sdai_out': sdai_out,
            'sdai_net': sdai_out - sdai_in,
            'yes_output': w3.from_wei(simulation_results['yes_output'], 'ether'),
            'no_output': w3.from_wei(simulation_results['no_output'], 'ether'),
            'target_amount': w3.from_wei(simulation_results['target_amount'], 'ether'),
            'gas_estimate': 2000000  # Conservative estimate
        }


def main():
    """Main entry point for CLI usage."""
    SEND_FLAG = {"--send", "-s"}
    broadcast = any(flag in sys.argv for flag in SEND_FLAG)
    sys.argv = [arg for arg in sys.argv if arg not in SEND_FLAG]
    
    if len(sys.argv) < 2:
        print("Usage: python buy_cond_eip7702.py <amount> [--send]")
        sys.exit(1)
    
    try:
        amount = Decimal(sys.argv[1])
    except (ValueError, InvalidOperation):
        print("Error: Invalid amount")
        sys.exit(1)
    
    # Verify environment
    if not IMPLEMENTATION_ADDRESS:
        print("Error: FUTARCHY_BATCH_EXECUTOR_ADDRESS not set")
        print("Run deployment script first: python -m src.setup.deploy_batch_executor")
        sys.exit(1)
    
    print(f"Buying conditional tokens with {amount} sDAI using EIP-7702 bundles")
    print(f"Implementation contract: {IMPLEMENTATION_ADDRESS}")
    print(f"Broadcast: {broadcast}")
    print()
    
    try:
        result = buy_conditional_bundled(amount, broadcast=broadcast)
        
        print("\nResults:")
        for key, value in result.items():
            print(f"  {key}: {value}")
        
        if result.get('sdai_net', 0) > 0:
            print(f"\n✅ Profitable: +{result['sdai_net']} sDAI")
        else:
            print(f"\n❌ Not profitable: {result.get('sdai_net', 0)} sDAI")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
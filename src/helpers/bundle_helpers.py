"""
Helper functions for building EIP-7702 bundled transactions.

This module provides utilities for encoding calls, parsing results, and managing
state in bundled transaction execution for the Pectra arbitrage bot.
"""

import os
import time
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal
from web3 import Web3
from eth_abi import encode, decode
from eth_utils import keccak

# Transfer event signature for tracking token movements
TRANSFER_EVENT_SIGNATURE = Web3.keccak(text="Transfer(address,address,uint256)")


def encode_approval_call(token: str, spender: str, amount: int) -> Dict[str, Any]:
    """
    Encode an ERC20 approval call.
    
    Args:
        token: Token contract address
        spender: Address to approve
        amount: Amount to approve (use 2**256-1 for max)
    
    Returns:
        Call dictionary with target, value, and data
    """
    # approve(address,uint256)
    function_selector = keccak(text="approve(address,uint256)")[:4]
    encoded_params = encode(['address', 'uint256'], [Web3.to_checksum_address(spender), amount])
    
    return {
        'target': Web3.to_checksum_address(token),
        'value': 0,
        'data': function_selector + encoded_params
    }


def encode_split_position_call(router: str, proposal: str, collateral: str, amount: int) -> Dict[str, Any]:
    """
    Encode a FutarchyRouter splitPosition call.
    
    Args:
        router: FutarchyRouter address
        proposal: Proposal address
        collateral: Collateral token address (e.g., sDAI)
        amount: Amount to split (in wei)
    
    Returns:
        Call dictionary
    """
    # splitPosition(address,address,uint256)
    function_selector = keccak(text="splitPosition(address,address,uint256)")[:4]
    encoded_params = encode(
        ['address', 'address', 'uint256'],
        [Web3.to_checksum_address(proposal), Web3.to_checksum_address(collateral), amount]
    )
    
    return {
        'target': Web3.to_checksum_address(router),
        'value': 0,
        'data': function_selector + encoded_params
    }


def encode_merge_positions_call(router: str, proposal: str, collateral: str, amount: int) -> Dict[str, Any]:
    """
    Encode a FutarchyRouter mergePositions call.
    
    Args:
        router: FutarchyRouter address
        proposal: Proposal address
        collateral: Collateral token address (e.g., Company token)
        amount: Amount to merge (in wei)
    
    Returns:
        Call dictionary
    """
    # mergePositions(address,address,uint256)
    function_selector = keccak(text="mergePositions(address,address,uint256)")[:4]
    encoded_params = encode(
        ['address', 'address', 'uint256'],
        [Web3.to_checksum_address(proposal), Web3.to_checksum_address(collateral), amount]
    )
    
    return {
        'target': Web3.to_checksum_address(router),
        'value': 0,
        'data': function_selector + encoded_params
    }


def encode_swapr_exact_in_params(
    token_in: str,
    token_out: str, 
    amount_in: int,
    amount_out_min: int,
    recipient: str,
    deadline: Optional[int] = None
) -> bytes:
    """
    Encode parameters for Swapr exactInputSingle call.
    
    Returns encoded parameters for the ExactInputSingleParams struct.
    """
    if deadline is None:
        deadline = int(time.time()) + 600  # 10 minutes
    
    # Encode struct parameters
    return encode(
        ['address', 'address', 'address', 'uint256', 'uint256', 'uint256', 'uint160'],
        [
            Web3.to_checksum_address(token_in),
            Web3.to_checksum_address(token_out),
            Web3.to_checksum_address(recipient),
            deadline,
            amount_in,
            amount_out_min,
            0  # sqrtPriceLimitX96 = 0 (no limit)
        ]
    )


def encode_swapr_exact_in_call(
    router: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    amount_out_min: int,
    recipient: str,
    deadline: Optional[int] = None
) -> Dict[str, Any]:
    """
    Encode a Swapr exactInputSingle swap call.
    
    Returns:
        Call dictionary for exact-in swap
    """
    # exactInputSingle((address,address,address,uint256,uint256,uint256,uint160))
    function_selector = keccak(text="exactInputSingle((address,address,address,uint256,uint256,uint256,uint160))")[:4]
    
    params = encode_swapr_exact_in_params(
        token_in, token_out, amount_in, amount_out_min, recipient, deadline
    )
    
    # Encode the entire function call
    data = function_selector + encode(['bytes'], [params])
    
    return {
        'target': Web3.to_checksum_address(router),
        'value': 0,
        'data': data
    }


def encode_swapr_exact_out_params(
    token_in: str,
    token_out: str,
    amount_out: int,
    amount_in_max: int,
    recipient: str,
    deadline: Optional[int] = None
) -> bytes:
    """
    Encode parameters for Swapr exactOutputSingle call.
    
    Returns encoded parameters for the ExactOutputSingleParams struct.
    """
    if deadline is None:
        deadline = int(time.time()) + 600  # 10 minutes
    
    # Encode struct parameters
    return encode(
        ['address', 'address', 'address', 'uint256', 'uint256', 'uint256', 'uint160'],
        [
            Web3.to_checksum_address(token_in),
            Web3.to_checksum_address(token_out),
            Web3.to_checksum_address(recipient),
            deadline,
            amount_out,
            amount_in_max,
            0  # sqrtPriceLimitX96 = 0 (no limit)
        ]
    )


def encode_swapr_exact_out_call(
    router: str,
    token_in: str,
    token_out: str,
    amount_out: int,
    amount_in_max: int,
    recipient: str,
    deadline: Optional[int] = None
) -> Dict[str, Any]:
    """
    Encode a Swapr exactOutputSingle swap call.
    
    Returns:
        Call dictionary for exact-out swap
    """
    # exactOutputSingle((address,address,address,uint256,uint256,uint256,uint160))
    function_selector = keccak(text="exactOutputSingle((address,address,address,uint256,uint256,uint256,uint160))")[:4]
    
    params = encode_swapr_exact_out_params(
        token_in, token_out, amount_out, amount_in_max, recipient, deadline
    )
    
    # Encode the entire function call
    data = function_selector + encode(['bytes'], [params])
    
    return {
        'target': Web3.to_checksum_address(router),
        'value': 0,
        'data': data
    }


def encode_balancer_swap_call(
    vault: str,
    pool_id: str,
    asset_in: str,
    asset_out: str,
    amount: int,
    sender: str,
    recipient: str,
    deadline: Optional[int] = None
) -> Dict[str, Any]:
    """
    Encode a Balancer V2 swap call.
    
    Args:
        vault: Balancer vault address
        pool_id: Pool ID for the swap
        asset_in: Input token address
        asset_out: Output token address
        amount: Amount to swap (for GIVEN_IN)
        sender: Address sending tokens
        recipient: Address receiving tokens
        deadline: Unix timestamp deadline
    
    Returns:
        Call dictionary for Balancer swap
    """
    if deadline is None:
        deadline = int(time.time()) + 600  # 10 minutes
    
    # swap(SingleSwap,FundManagement,uint256,uint256)
    function_selector = keccak(text="swap((bytes32,uint8,address,address,uint256,bytes),(address,bool,address,bool),uint256,uint256)")[:4]
    
    # SingleSwap struct
    single_swap = [
        bytes.fromhex(pool_id.replace('0x', '')),  # poolId as bytes32
        0,  # kind: 0 = GIVEN_IN
        Web3.to_checksum_address(asset_in),
        Web3.to_checksum_address(asset_out),
        amount,
        b''  # userData (empty)
    ]
    
    # FundManagement struct
    fund_management = [
        Web3.to_checksum_address(sender),
        False,  # fromInternalBalance
        Web3.to_checksum_address(recipient),
        False   # toInternalBalance
    ]
    
    # Encode all parameters
    encoded_params = encode(
        ['(bytes32,uint8,address,address,uint256,bytes)', '(address,bool,address,bool)', 'uint256', 'uint256'],
        [single_swap, fund_management, 0, deadline]
    )
    
    return {
        'target': Web3.to_checksum_address(vault),
        'value': 0,
        'data': function_selector + encoded_params
    }


def parse_swap_result(result_bytes: bytes, swap_type: str) -> Dict[str, Any]:
    """
    Parse swap result from executeWithResults output.
    
    Args:
        result_bytes: Raw bytes returned from swap
        swap_type: "exactIn" or "exactOut"
    
    Returns:
        Dictionary with swap results
    """
    if len(result_bytes) == 0:
        return {'error': 'Empty result'}
    
    try:
        if swap_type == "exactIn":
            # For exact-in swaps, return value is amount out
            amount_out = decode(['uint256'], result_bytes)[0]
            return {'amount_out': amount_out, 'type': 'exactIn'}
        else:  # exactOut
            # For exact-out swaps, return value is amount in used
            amount_in = decode(['uint256'], result_bytes)[0]
            return {'amount_in': amount_in, 'type': 'exactOut'}
    except Exception as e:
        return {'error': f'Failed to decode: {str(e)}'}


def parse_bundle_results(results_bytes: bytes, operation_map: Dict[int, Tuple[str, str]]) -> Dict[str, Any]:
    """
    Parse complete bundle results from executeWithResults.
    
    Args:
        results_bytes: Raw bytes from executeWithResults
        operation_map: Mapping of indices to (operation_type, operation_name)
    
    Returns:
        Dictionary with parsed results for each operation
    """
    try:
        # Decode the outer bytes array
        decoded = decode(['bytes[]'], results_bytes)
        results = decoded[0]
        
        parsed = {}
        for idx, (op_type, op_name) in operation_map.items():
            if idx < len(results):
                result = results[idx]
                
                if op_type == 'approval':
                    # Approval returns bool
                    if len(result) > 0:
                        success = decode(['bool'], result)[0]
                        parsed[op_name] = {'success': success}
                    else:
                        parsed[op_name] = {'success': True}  # Assume success if no return
                
                elif op_type == 'split':
                    # Split might return (yesAmount, noAmount) or nothing
                    parsed[op_name] = {'executed': True}
                
                elif op_type == 'swap':
                    # Determine swap type from operation name
                    if 'exact_in' in op_name:
                        parsed[op_name] = parse_swap_result(result, 'exactIn')
                    else:
                        parsed[op_name] = parse_swap_result(result, 'exactOut')
                
                elif op_type == 'merge':
                    # Merge typically doesn't return data
                    parsed[op_name] = {'executed': True}
                
                elif op_type == 'balancer_swap':
                    # Balancer returns amount out
                    if len(result) > 0:
                        amount_out = decode(['uint256'], result)[0]
                        parsed[op_name] = {'amount_out': amount_out}
                    else:
                        parsed[op_name] = {'error': 'No result from Balancer'}
                
                else:
                    parsed[op_name] = {'raw': result.hex()}
        
        return parsed
    
    except Exception as e:
        return {'error': f'Failed to parse bundle results: {str(e)}'}


def extract_swap_outputs(parsed_results: Dict[str, Any]) -> Tuple[int, int]:
    """
    Extract YES and NO swap output amounts from parsed results.
    
    Returns:
        Tuple of (yes_amount, no_amount) in wei
    """
    yes_amount = 0
    no_amount = 0
    
    # Look for YES swap result
    for key, value in parsed_results.items():
        if 'yes' in key.lower() and 'swap' in key.lower():
            if 'amount_out' in value:
                yes_amount = value['amount_out']
            elif 'amount_in' in value and value.get('type') == 'exactOut':
                # For exact-out, we know the output from the operation name
                # This would need to be passed in or stored elsewhere
                pass
        
        elif 'no' in key.lower() and 'swap' in key.lower():
            if 'amount_out' in value:
                no_amount = value['amount_out']
            elif 'amount_in' in value and value.get('type') == 'exactOut':
                # Similar handling for NO swap
                pass
    
    return yes_amount, no_amount


def calculate_liquidation_amount(yes_amount: int, no_amount: int, yes_used: int, no_used: int) -> Tuple[int, str]:
    """
    Calculate liquidation amount for imbalanced conditional tokens.
    
    Args:
        yes_amount: YES tokens received from swap
        no_amount: NO tokens received from swap
        yes_used: YES conditional sDAI used in swap
        no_used: NO conditional sDAI used in swap
    
    Returns:
        Tuple of (liquidation_amount, token_type)
        token_type is "YES" or "NO" indicating which token to liquidate
    """
    # After swaps, we have remaining conditional sDAI
    yes_remaining = yes_used - yes_amount if yes_amount < no_amount else 0
    no_remaining = no_used - no_amount if no_amount < yes_amount else 0
    
    if yes_remaining > no_remaining:
        return yes_remaining, "YES"
    elif no_remaining > yes_remaining:
        return no_remaining, "NO"
    else:
        return 0, "NONE"


def build_liquidation_calls(
    liquidation_amount: int,
    token_type: str,
    swapr_router: str,
    futarchy_router: str
) -> List[Dict[str, Any]]:
    """
    Build liquidation calls for imbalanced conditional sDAI.
    
    Args:
        liquidation_amount: Amount to liquidate
        token_type: "YES" or "NO"
        swapr_router: Swapr router address
        futarchy_router: FutarchyRouter address
    
    Returns:
        List of call dictionaries for liquidation
    """
    calls = []
    
    if token_type == "YES":
        # Direct swap YES conditional sDAI → sDAI
        sdai_yes = os.environ["SWAPR_SDAI_YES_ADDRESS"]
        sdai = os.environ["SDAI_TOKEN_ADDRESS"]
        
        calls.append(encode_approval_call(sdai_yes, swapr_router, liquidation_amount))
        calls.append(encode_swapr_exact_in_call(
            swapr_router, sdai_yes, sdai, liquidation_amount, 0, os.environ["FUTARCHY_BATCH_EXECUTOR_ADDRESS"]
        ))
    
    elif token_type == "NO":
        # More complex: Buy YES with sDAI, then merge
        sdai = os.environ["SDAI_TOKEN_ADDRESS"]
        sdai_yes = os.environ["SWAPR_SDAI_YES_ADDRESS"]
        sdai_no = os.environ["SWAPR_SDAI_NO_ADDRESS"]
        
        # Estimate sDAI needed (with 10% buffer)
        estimated_sdai = int(liquidation_amount * 1.1)
        
        # Buy YES conditional sDAI
        calls.append(encode_approval_call(sdai, swapr_router, estimated_sdai))
        calls.append(encode_swapr_exact_out_call(
            swapr_router, sdai, sdai_yes, liquidation_amount, estimated_sdai, 
            os.environ["FUTARCHY_BATCH_EXECUTOR_ADDRESS"]
        ))
        
        # Approve both for merge
        calls.append(encode_approval_call(sdai_yes, futarchy_router, liquidation_amount))
        calls.append(encode_approval_call(sdai_no, futarchy_router, liquidation_amount))
        
        # Merge back to sDAI
        calls.append(encode_merge_positions_call(
            futarchy_router, os.environ["FUTARCHY_PROPOSAL_ADDRESS"], sdai, liquidation_amount
        ))
    
    return calls


def decode_revert_reason(error_data: bytes) -> str:
    """
    Decode revert reason from transaction error.
    
    Args:
        error_data: Error data from failed transaction
    
    Returns:
        Human-readable error message
    """
    if len(error_data) < 4:
        return "Unknown error (no data)"
    
    # Standard Error(string) selector: 0x08c379a0
    if error_data[:4] == bytes.fromhex('08c379a0'):
        try:
            # Skip selector and decode string
            error_msg = decode(['string'], error_data[4:])[0]
            return f"Error: {error_msg}"
        except:
            return "Error: Failed to decode error message"
    
    # Custom error selectors from FutarchyBatchExecutor
    error_selectors = {
        bytes.fromhex('1234abcd'): 'CallFailed',  # Update with actual selectors
        bytes.fromhex('5678ef01'): 'InvalidAuthority',
        bytes.fromhex('9abcdef0'): 'InsufficientBalance'
    }
    
    selector = error_data[:4]
    if selector in error_selectors:
        return f"Custom Error: {error_selectors[selector]}"
    
    return f"Unknown error (selector: 0x{selector.hex()})"


def calculate_bundle_gas_params(w3: Web3, priority_multiplier: float = 1.5) -> Dict[str, int]:
    """
    Calculate gas parameters for bundle transaction.
    
    Args:
        w3: Web3 instance
        priority_multiplier: Multiplier for priority fee (default 1.5x)
    
    Returns:
        Dictionary with gas, maxFeePerGas, and maxPriorityFeePerGas
    """
    latest_block = w3.eth.get_block('latest')
    base_fee = latest_block.get('baseFeePerGas', w3.eth.gas_price)
    
    # Conservative priority fee
    priority_fee = w3.to_wei(2, 'gwei') * priority_multiplier
    
    return {
        'gas': 2000000,  # Conservative estimate for complex bundles
        'maxFeePerGas': int(base_fee * 1.2 + priority_fee),
        'maxPriorityFeePerGas': int(priority_fee)
    }


def verify_bundle_profitability(
    sdai_in: Decimal,
    sdai_out: Decimal,
    gas_used: int,
    gas_price: int,
    w3: Web3
) -> Tuple[Decimal, bool]:
    """
    Calculate net profit from bundle execution.
    
    Args:
        sdai_in: Initial sDAI amount
        sdai_out: Final sDAI amount
        gas_used: Gas used in execution
        gas_price: Gas price in wei
        w3: Web3 instance for conversions
    
    Returns:
        Tuple of (net_profit, is_profitable)
    """
    # Gross profit
    gross_profit = sdai_out - sdai_in
    
    # Gas cost in ETH
    gas_cost_wei = gas_used * gas_price
    gas_cost_eth = w3.from_wei(gas_cost_wei, 'ether')
    
    # TODO: Convert ETH to sDAI using oracle or pool price
    # For now, assume 1 ETH = 2000 sDAI (placeholder)
    eth_to_sdai_rate = Decimal('2000')
    gas_cost_sdai = gas_cost_eth * eth_to_sdai_rate
    
    # Net profit
    net_profit = gross_profit - gas_cost_sdai
    
    return net_profit, net_profit > 0
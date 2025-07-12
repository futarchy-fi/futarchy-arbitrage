#!/usr/bin/env python3
"""
Encode multicall data for buy conditional arbitrage operation.
This creates the calldata array needed for the multicall arbitrage contract.
"""
import os
import time
from decimal import Decimal
from web3 import Web3
from eth_abi import encode

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))

def encode_erc20_transfer_from(from_addr, to_addr, amount):
    """Encode ERC20 transferFrom call"""
    sig = Web3.keccak(text="transferFrom(address,address,uint256)")[:4]
    data = sig + encode(['address', 'address', 'uint256'], [from_addr, to_addr, amount])
    return data

def encode_erc20_approve(spender, amount):
    """Encode ERC20 approve call"""
    sig = Web3.keccak(text="approve(address,uint256)")[:4]
    data = sig + encode(['address', 'uint256'], [spender, amount])
    return data

def encode_erc20_transfer(to_addr, amount):
    """Encode ERC20 transfer call"""
    sig = Web3.keccak(text="transfer(address,uint256)")[:4]
    data = sig + encode(['address', 'uint256'], [to_addr, amount])
    return data

def encode_futarchy_split(proposal, collateral_token, amount):
    """Encode FutarchyRouter splitPosition call"""
    sig = Web3.keccak(text="splitPosition(address,address,uint256)")[:4]
    data = sig + encode(['address', 'address', 'uint256'], [proposal, collateral_token, amount])
    return data

def encode_futarchy_merge(proposal, collateral_token, amount):
    """Encode FutarchyRouter mergePositions call"""
    sig = Web3.keccak(text="mergePositions(address,address,uint256)")[:4]
    data = sig + encode(['address', 'address', 'uint256'], [proposal, collateral_token, amount])
    return data

def encode_swapr_exact_input(token_in, token_out, recipient, deadline, amount_in, amount_out_min, sqrt_price_limit):
    """Encode Swapr exactInputSingle call"""
    sig = Web3.keccak(text="exactInputSingle(address,address,address,uint256,uint256,uint256,uint160)")[:4]
    data = sig + encode(
        ['address', 'address', 'address', 'uint256', 'uint256', 'uint256', 'uint160'],
        [token_in, token_out, recipient, deadline, amount_in, amount_out_min, sqrt_price_limit]
    )
    return data

def encode_balancer_swap(pool_id, kind, asset_in, asset_out, amount, sender, recipient, limit, deadline):
    """Encode Balancer swap call"""
    # Function signature for swap(SingleSwap,FundManagement,uint256,uint256)
    sig = Web3.keccak(text="swap((bytes32,uint8,address,address,uint256,bytes),(address,bool,address,bool),uint256,uint256)")[:4]
    
    # Encode SingleSwap struct
    single_swap = encode(
        ['bytes32', 'uint8', 'address', 'address', 'uint256', 'bytes'],
        [pool_id, kind, asset_in, asset_out, amount, b'']
    )
    
    # Encode FundManagement struct
    fund_management = encode(
        ['address', 'bool', 'address', 'bool'],
        [sender, False, recipient, False]
    )
    
    # Combine all parameters
    data = sig + encode(
        ['bytes32', 'bytes32', 'uint256', 'uint256'],
        [single_swap[:32], fund_management[:32], limit, deadline]
    )
    
    # Note: This is a simplified encoding. The actual encoding is more complex
    # due to the struct parameters. We'll use the contract's encoding instead.
    return None  # Will implement proper encoding below

def create_buy_conditional_calls(params):
    """Create multicall array for buy conditional arbitrage"""
    calls = []
    
    # Get contract addresses
    executor_address = params['executor_address']
    owner_address = params['owner_address']
    
    # 1. Pull sDAI from owner to executor
    calls.append({
        'target': params['sdai_token'],
        'callData': encode_erc20_transfer_from(
            owner_address,
            executor_address,
            params['amount_wei']
        ).hex()
    })
    
    # 2. Approve FutarchyRouter to spend sDAI
    calls.append({
        'target': params['sdai_token'],
        'callData': encode_erc20_approve(
            params['futarchy_router'],
            params['amount_wei']
        ).hex()
    })
    
    # 3. Split sDAI into conditional tokens
    calls.append({
        'target': params['futarchy_router'],
        'callData': encode_futarchy_split(
            params['proposal_address'],
            params['sdai_token'],
            params['amount_wei']
        ).hex()
    })
    
    # 4. Approve Swapr router for YES tokens
    calls.append({
        'target': params['sdai_yes_token'],
        'callData': encode_erc20_approve(
            params['swapr_router'],
            2**256 - 1  # MAX_UINT
        ).hex()
    })
    
    # 5. Swap YES sDAI to YES Company tokens
    deadline = int(time.time()) + 300  # 5 minutes
    calls.append({
        'target': params['swapr_router'],
        'callData': encode_swapr_exact_input(
            params['sdai_yes_token'],
            params['company_yes_token'],
            executor_address,
            deadline,
            params['amount_wei'],  # Will swap full balance
            0,  # Min out for now
            0   # No sqrt price limit
        ).hex()
    })
    
    # 6. Approve Swapr router for NO tokens
    calls.append({
        'target': params['sdai_no_token'],
        'callData': encode_erc20_approve(
            params['swapr_router'],
            2**256 - 1  # MAX_UINT
        ).hex()
    })
    
    # 7. Swap NO sDAI to NO Company tokens
    calls.append({
        'target': params['swapr_router'],
        'callData': encode_swapr_exact_input(
            params['sdai_no_token'],
            params['company_no_token'],
            executor_address,
            deadline,
            params['amount_wei'],  # Will swap full balance
            0,  # Min out for now
            0   # No sqrt price limit
        ).hex()
    })
    
    # Note: The actual merge and Balancer swap would require dynamic amounts
    # based on the results of the Swapr swaps. This would typically be handled
    # by a more sophisticated contract or by breaking the operation into steps.
    
    print("\n=== Multicall Data for Buy Conditional Arbitrage ===")
    print(f"Total calls: {len(calls)}")
    print("\nCalls:")
    for i, call in enumerate(calls):
        print(f"\n{i+1}. Target: {call['target']}")
        print(f"   Data: {call['callData'][:10]}...{call['callData'][-8:]}")
    
    return calls

def main():
    # Load environment variables
    executor_address = os.getenv('ARBITRAGE_EXECUTOR_ADDRESS')
    if not executor_address:
        print("Error: ARBITRAGE_EXECUTOR_ADDRESS not set")
        return
    
    owner_address = os.getenv('OWNER_ADDRESS')
    if not owner_address:
        # Try to derive from private key
        private_key = os.getenv('PRIVATE_KEY')
        if private_key:
            account = w3.eth.account.from_key(private_key)
            owner_address = account.address
        else:
            print("Error: OWNER_ADDRESS or PRIVATE_KEY not set")
            return
    
    # Prepare parameters
    params = {
        'executor_address': w3.to_checksum_address(executor_address),
        'owner_address': w3.to_checksum_address(owner_address),
        'proposal_address': w3.to_checksum_address(os.environ['FUTARCHY_PROPOSAL_ADDRESS']),
        'futarchy_router': w3.to_checksum_address(os.environ['FUTARCHY_ROUTER_ADDRESS']),
        'swapr_router': w3.to_checksum_address(os.environ['SWAPR_ROUTER_ADDRESS']),
        'balancer_vault': w3.to_checksum_address(os.environ['BALANCER_VAULT_ADDRESS']),
        'sdai_token': w3.to_checksum_address(os.environ['SDAI_TOKEN_ADDRESS']),
        'company_token': w3.to_checksum_address(os.environ['COMPANY_TOKEN_ADDRESS']),
        'sdai_yes_token': w3.to_checksum_address(os.environ['SWAPR_SDAI_YES_ADDRESS']),
        'sdai_no_token': w3.to_checksum_address(os.environ['SWAPR_SDAI_NO_ADDRESS']),
        'company_yes_token': w3.to_checksum_address(os.environ['SWAPR_GNO_YES_ADDRESS']),
        'company_no_token': w3.to_checksum_address(os.environ['SWAPR_GNO_NO_ADDRESS']),
        'amount_wei': int(0.01 * 10**18)  # 0.01 sDAI
    }
    
    # Create multicall data
    calls = create_buy_conditional_calls(params)
    
    # Save to file for use in execution script
    import json
    with open('buy_conditional_multicall.json', 'w') as f:
        json.dump({
            'params': params,
            'calls': calls
        }, f, indent=2)
    
    print("\n✅ Multicall data saved to buy_conditional_multicall.json")

if __name__ == "__main__":
    main()
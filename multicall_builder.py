#!/usr/bin/env python3
"""
Helper to build multicall data using existing contract interfaces.
This properly encodes complex calls like Balancer swaps.
"""
import os
import time
from web3 import Web3
from src.config.abis import ERC20_ABI
from src.config.abis.futarchy import FUTARCHY_ROUTER_ABI
from src.config.abis.swapr import SWAPR_ROUTER_ABI
from src.config.abis.balancer import BALANCER_VAULT_ABI

w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))

class MulticallBuilder:
    def __init__(self, executor_address, owner_address):
        self.executor_address = w3.to_checksum_address(executor_address)
        self.owner_address = w3.to_checksum_address(owner_address)
        self.calls = []
    
    def add_erc20_transfer_from(self, token_address, from_addr, to_addr, amount):
        """Add ERC20 transferFrom call"""
        token = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        data = token.encodeABI(
            fn_name='transferFrom',
            args=[from_addr, to_addr, amount]
        )
        self.calls.append({
            'target': token_address,
            'callData': data
        })
        return self
    
    def add_erc20_approve(self, token_address, spender, amount):
        """Add ERC20 approve call"""
        token = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        data = token.encodeABI(
            fn_name='approve',
            args=[spender, amount]
        )
        self.calls.append({
            'target': token_address,
            'callData': data
        })
        return self
    
    def add_futarchy_split(self, router_address, proposal, collateral_token, amount):
        """Add FutarchyRouter splitPosition call"""
        router = w3.eth.contract(address=router_address, abi=FUTARCHY_ROUTER_ABI)
        data = router.encodeABI(
            fn_name='splitPosition',
            args=[proposal, collateral_token, amount]
        )
        self.calls.append({
            'target': router_address,
            'callData': data
        })
        return self
    
    def add_futarchy_merge(self, router_address, proposal, collateral_token, amount):
        """Add FutarchyRouter mergePositions call"""
        router = w3.eth.contract(address=router_address, abi=FUTARCHY_ROUTER_ABI)
        data = router.encodeABI(
            fn_name='mergePositions',
            args=[proposal, collateral_token, amount]
        )
        self.calls.append({
            'target': router_address,
            'callData': data
        })
        return self
    
    def add_swapr_exact_input(self, router_address, params):
        """Add Swapr exactInputSingle call with proper parameter encoding"""
        router = w3.eth.contract(address=router_address, abi=SWAPR_ROUTER_ABI)
        
        # Swapr expects a tuple of parameters
        swap_params = (
            params['tokenIn'],
            params['tokenOut'],
            params.get('recipient', self.executor_address),
            params.get('deadline', int(time.time()) + 300),
            params['amountIn'],
            params.get('amountOutMinimum', 0),
            params.get('sqrtPriceLimitX96', 0)
        )
        
        data = router.encodeABI(
            fn_name='exactInputSingle',
            args=[swap_params]
        )
        
        self.calls.append({
            'target': router_address,
            'callData': data
        })
        return self
    
    def add_balancer_swap(self, vault_address, pool_id, token_in, token_out, amount_in, min_amount_out):
        """Add Balancer swap call with proper struct encoding"""
        vault = w3.eth.contract(address=vault_address, abi=BALANCER_VAULT_ABI)
        
        # SingleSwap struct
        single_swap = {
            'poolId': pool_id,
            'kind': 0,  # GIVEN_IN
            'assetIn': token_in,
            'assetOut': token_out,
            'amount': amount_in,
            'userData': b''
        }
        
        # FundManagement struct
        funds = {
            'sender': self.executor_address,
            'fromInternalBalance': False,
            'recipient': self.executor_address,
            'toInternalBalance': False
        }
        
        deadline = int(time.time()) + 300
        
        data = vault.encodeABI(
            fn_name='swap',
            args=[single_swap, funds, min_amount_out, deadline]
        )
        
        self.calls.append({
            'target': vault_address,
            'callData': data
        })
        return self
    
    def build(self):
        """Return the built calls array"""
        return self.calls
    
    def print_summary(self):
        """Print a summary of the multicall"""
        print(f"\n=== Multicall Summary ===")
        print(f"Total calls: {len(self.calls)}")
        print(f"Executor: {self.executor_address}")
        print(f"Owner: {self.owner_address}")
        print("\nCalls:")
        for i, call in enumerate(self.calls):
            print(f"\n{i+1}. Target: {call['target']}")
            print(f"   Data: {call['callData'][:10]}...{call['callData'][-8:]}")

def build_buy_conditional_multicall(amount_sdai):
    """Build multicall for buy conditional arbitrage"""
    
    # Get addresses from environment
    executor = os.getenv('ARBITRAGE_EXECUTOR_ADDRESS')
    owner = os.getenv('OWNER_ADDRESS')
    if not owner:
        private_key = os.getenv('PRIVATE_KEY')
        if private_key:
            account = w3.eth.account.from_key(private_key)
            owner = account.address
    
    builder = MulticallBuilder(executor, owner)
    
    # Convert amount to wei
    amount_wei = int(amount_sdai * 10**18)
    
    # Get contract addresses
    sdai_token = w3.to_checksum_address(os.environ['SDAI_TOKEN_ADDRESS'])
    company_token = w3.to_checksum_address(os.environ['COMPANY_TOKEN_ADDRESS'])
    futarchy_router = w3.to_checksum_address(os.environ['FUTARCHY_ROUTER_ADDRESS'])
    swapr_router = w3.to_checksum_address(os.environ['SWAPR_ROUTER_ADDRESS'])
    balancer_vault = w3.to_checksum_address(os.environ['BALANCER_VAULT_ADDRESS'])
    proposal = w3.to_checksum_address(os.environ['FUTARCHY_PROPOSAL_ADDRESS'])
    
    # Conditional token addresses
    sdai_yes = w3.to_checksum_address(os.environ['SWAPR_SDAI_YES_ADDRESS'])
    sdai_no = w3.to_checksum_address(os.environ['SWAPR_SDAI_NO_ADDRESS'])
    company_yes = w3.to_checksum_address(os.environ['SWAPR_GNO_YES_ADDRESS'])
    company_no = w3.to_checksum_address(os.environ['SWAPR_GNO_NO_ADDRESS'])
    
    # Balancer pool ID
    balancer_pool_id = bytes.fromhex(os.environ['BALANCER_POOL_ID'].replace('0x', ''))
    
    # Build the multicall
    builder \
        .add_erc20_transfer_from(sdai_token, owner, executor, amount_wei) \
        .add_erc20_approve(sdai_token, futarchy_router, amount_wei) \
        .add_futarchy_split(futarchy_router, proposal, sdai_token, amount_wei) \
        .add_erc20_approve(sdai_yes, swapr_router, 2**256 - 1) \
        .add_swapr_exact_input(swapr_router, {
            'tokenIn': sdai_yes,
            'tokenOut': company_yes,
            'amountIn': amount_wei,
            'amountOutMinimum': 0
        }) \
        .add_erc20_approve(sdai_no, swapr_router, 2**256 - 1) \
        .add_swapr_exact_input(swapr_router, {
            'tokenIn': sdai_no,
            'tokenOut': company_no,
            'amountIn': amount_wei,
            'amountOutMinimum': 0
        })
    
    # Note: Merge and Balancer swap would require knowing the output amounts
    # from the Swapr swaps, which would need to be handled differently
    
    builder.print_summary()
    return builder.build()

def main():
    print("Building buy conditional arbitrage multicall...")
    calls = build_buy_conditional_multicall(0.01)  # 0.01 sDAI
    
    # Save to file
    import json
    with open('multicall_data.json', 'w') as f:
        json.dump({
            'calls': calls,
            'executor': os.getenv('ARBITRAGE_EXECUTOR_ADDRESS'),
            'amount': '0.01 sDAI'
        }, f, indent=2)
    
    print("\n✅ Multicall data saved to multicall_data.json")

if __name__ == "__main__":
    main()
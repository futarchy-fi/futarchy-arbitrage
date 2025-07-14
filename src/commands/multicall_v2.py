"""
Multicall V2 command builder for the simplified FutarchyArbitrageExecutorV2 contract.
"""
from typing import List, Tuple, Dict, Any, Optional
from web3 import Web3
from eth_abi import encode
from decimal import Decimal

class MulticallV2Builder:
    """
    Builder for the simplified FutarchyArbitrageExecutorV2 contract.
    
    This version removes pullToken/pushToken and focuses on executing
    swaps directly from the contract's balance.
    """
    
    def __init__(self, executor_address: str, w3: Web3):
        self.executor_address = Web3.to_checksum_address(executor_address)
        self.w3 = w3
        self.calls: List[Tuple[str, bytes]] = []
    
    def add_call(self, target: str, calldata: bytes) -> "MulticallV2Builder":
        """Add a raw call to the multicall."""
        self.calls.append((Web3.to_checksum_address(target), calldata))
        return self
    
    def add_token_approval(self, token: str, spender: str, amount: int) -> "MulticallV2Builder":
        """
        Add ERC20 approve call.
        
        Args:
            token: Token contract address
            spender: Address to approve
            amount: Amount to approve (use 2**256-1 for max)
        """
        # approve(address,uint256)
        sig = Web3.keccak(text="approve(address,uint256)")[:4]
        data = sig + encode(['address', 'uint256'], [Web3.to_checksum_address(spender), amount])
        return self.add_call(token, data)
    
    def add_futarchy_split(self, router: str, proposal: str, collateral_token: str, amount: int) -> "MulticallV2Builder":
        """
        Add FutarchyRouter splitPosition call.
        
        Args:
            router: FutarchyRouter address
            proposal: Proposal address
            collateral_token: Token to split (e.g., sDAI)
            amount: Amount to split
        """
        # splitPosition(address,address,uint256)
        sig = Web3.keccak(text="splitPosition(address,address,uint256)")[:4]
        data = sig + encode(
            ['address', 'address', 'uint256'],
            [Web3.to_checksum_address(proposal), Web3.to_checksum_address(collateral_token), amount]
        )
        return self.add_call(router, data)
    
    def add_futarchy_merge(self, router: str, proposal: str, collateral_token: str, amount: int) -> "MulticallV2Builder":
        """
        Add FutarchyRouter mergePositions call.
        
        Args:
            router: FutarchyRouter address
            proposal: Proposal address
            collateral_token: Token to merge (e.g., Company token)
            amount: Amount to merge
        """
        # mergePositions(address,address,uint256)
        sig = Web3.keccak(text="mergePositions(address,address,uint256)")[:4]
        data = sig + encode(
            ['address', 'address', 'uint256'],
            [Web3.to_checksum_address(proposal), Web3.to_checksum_address(collateral_token), amount]
        )
        return self.add_call(router, data)
    
    def add_balancer_swap(self, vault: str, swap_params: Dict[str, Any]) -> "MulticallV2Builder":
        """
        Add Balancer swap call.
        
        Args:
            vault: Balancer Vault address
            swap_params: Dictionary with swap parameters:
                - pool_id: bytes32
                - asset_in: address
                - asset_out: address
                - amount: uint256
                - limit: uint256 (min amount out)
                - deadline: uint256
        """
        # This is a simplified version - full implementation would need proper struct encoding
        # swap(SingleSwap,FundManagement,uint256,uint256)
        sig = Web3.keccak(text="swap((bytes32,uint8,address,address,uint256,bytes),(address,bool,address,bool),uint256,uint256)")[:4]
        
        # For now, return self without adding the call
        # Full implementation would require proper Balancer ABI encoding
        print("Note: Balancer swap encoding requires full ABI - use contract interface instead")
        return self
    
    def add_swapr_swap(self, router: str, swap_params: Dict[str, Any]) -> "MulticallV2Builder":
        """
        Add Swapr exactInputSingle call.
        
        Args:
            router: Swapr Router address
            swap_params: Dictionary with swap parameters:
                - token_in: address
                - token_out: address
                - amount_in: uint256
                - amount_out_minimum: uint256
                - deadline: uint256
                - recipient: address (defaults to executor)
                - sqrt_price_limit: uint160 (optional, defaults to 0)
        """
        # exactInputSingle((address,address,address,uint256,uint256,uint256,uint160))
        sig = Web3.keccak(text="exactInputSingle((address,address,address,uint256,uint256,uint256,uint160))")[:4]
        
        # Encode the struct as a tuple
        recipient = swap_params.get('recipient', self.executor_address)
        sqrt_price_limit = swap_params.get('sqrt_price_limit', 0)
        
        struct_data = encode(
            ['address', 'address', 'address', 'uint256', 'uint256', 'uint256', 'uint160'],
            [
                Web3.to_checksum_address(swap_params['token_in']),
                Web3.to_checksum_address(swap_params['token_out']),
                Web3.to_checksum_address(recipient),
                swap_params['deadline'],
                swap_params['amount_in'],
                swap_params['amount_out_minimum'],
                sqrt_price_limit
            ]
        )
        
        data = sig + encode(['bytes'], [struct_data])
        return self.add_call(router, data)
    
    def build(self) -> List[Tuple[str, bytes]]:
        """Build and return the calls array."""
        return self.calls.copy()
    
    def clear(self) -> "MulticallV2Builder":
        """Clear all calls."""
        self.calls = []
        return self
    
    def estimate_gas(self, from_address: str, value: int = 0) -> int:
        """
        Estimate gas for the multicall.
        
        Args:
            from_address: Address that will send the transaction
            value: ETH value to send (default 0)
            
        Returns:
            Estimated gas needed
        """
        # This would require the contract ABI to be loaded
        # For now, return a reasonable estimate
        base_gas = 50000
        per_call_gas = 100000
        return base_gas + (len(self.calls) * per_call_gas)


def build_buy_conditional_arbitrage_v2(
    executor_address: str,
    w3: Web3,
    amount_sdai: int,
    addresses: Dict[str, str]
) -> List[Tuple[str, bytes]]:
    """
    Build multicall for buy conditional arbitrage using V2 pattern.
    
    This assumes the executor contract already has sDAI balance.
    
    Args:
        executor_address: Executor contract address
        w3: Web3 instance
        amount_sdai: Amount of sDAI to use (in wei)
        addresses: Dictionary with required addresses
        
    Returns:
        List of (target, calldata) tuples for multicall
    """
    builder = MulticallV2Builder(executor_address, w3)
    
    # 1. Approve FutarchyRouter to spend sDAI
    builder.add_token_approval(
        addresses['sdai_token'],
        addresses['futarchy_router'],
        amount_sdai
    )
    
    # 2. Split sDAI into YES/NO tokens
    builder.add_futarchy_split(
        addresses['futarchy_router'],
        addresses['proposal'],
        addresses['sdai_token'],
        amount_sdai
    )
    
    # 3. Approve Swapr router for YES tokens
    builder.add_token_approval(
        addresses['sdai_yes_token'],
        addresses['swapr_router'],
        2**256 - 1  # Max approval
    )
    
    # 4. Swap YES sDAI for YES Company tokens
    import time
    builder.add_swapr_swap(
        addresses['swapr_router'],
        {
            'token_in': addresses['sdai_yes_token'],
            'token_out': addresses['company_yes_token'],
            'amount_in': amount_sdai,
            'amount_out_minimum': 0,  # Should calculate based on price
            'deadline': int(time.time()) + 300,
            'recipient': executor_address
        }
    )
    
    # 5. Approve Swapr router for NO tokens
    builder.add_token_approval(
        addresses['sdai_no_token'],
        addresses['swapr_router'],
        2**256 - 1  # Max approval
    )
    
    # 6. Swap NO sDAI for NO Company tokens
    builder.add_swapr_swap(
        addresses['swapr_router'],
        {
            'token_in': addresses['sdai_no_token'],
            'token_out': addresses['company_no_token'],
            'amount_in': amount_sdai,
            'amount_out_minimum': 0,  # Should calculate based on price
            'deadline': int(time.time()) + 300,
            'recipient': executor_address
        }
    )
    
    # 7. Approve FutarchyRouter for Company tokens (for merge)
    builder.add_token_approval(
        addresses['company_yes_token'],
        addresses['futarchy_router'],
        2**256 - 1
    )
    
    builder.add_token_approval(
        addresses['company_no_token'],
        addresses['futarchy_router'],
        2**256 - 1
    )
    
    # Note: Merge amount would need to be calculated based on swap results
    # This is a limitation of the static multicall approach
    
    return builder.build()


def build_sell_conditional_arbitrage_v2(
    executor_address: str,
    w3: Web3,
    amount_company: int,
    addresses: Dict[str, str]
) -> List[Tuple[str, bytes]]:
    """
    Build multicall for sell conditional arbitrage using V2 pattern.
    
    This assumes the executor contract already has Company token balance.
    
    Args:
        executor_address: Executor contract address
        w3: Web3 instance
        amount_company: Amount of Company tokens to use (in wei)
        addresses: Dictionary with required addresses
        
    Returns:
        List of (target, calldata) tuples for multicall
    """
    builder = MulticallV2Builder(executor_address, w3)
    
    # For sell conditional, we would:
    # 1. Swap Company tokens for sDAI on Balancer
    # 2. Return sDAI to owner
    
    # This is simplified - full implementation would need Balancer swap encoding
    
    return builder.build()
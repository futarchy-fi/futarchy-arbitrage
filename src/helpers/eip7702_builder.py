"""
EIP-7702 Transaction Builder for Futarchy Arbitrage Bot
======================================================

This module provides utilities for building EIP-7702 transactions that allow
EOAs to temporarily act as smart contracts and execute batched operations.
"""

from typing import List, Dict, Any, Optional, Union
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from eth_abi import encode
from eth_utils import keccak
import logging

logger = logging.getLogger(__name__)


class EIP7702TransactionBuilder:
    """Builder for EIP-7702 transactions with batched operations."""
    
    def __init__(self, w3: Web3, implementation_address: str):
        """
        Initialize the EIP-7702 transaction builder.
        
        Args:
            w3: Web3 instance
            implementation_address: Address of the FutarchyBatchExecutor contract
        """
        self.w3 = w3
        self.implementation_address = Web3.to_checksum_address(implementation_address)
        self.calls: List[Dict[str, Any]] = []
        
    def add_call(self, target: str, value: int, data: Union[str, bytes]) -> "EIP7702TransactionBuilder":
        """
        Add a call to the batch.
        
        Args:
            target: Target contract address
            value: ETH value to send (in wei)
            data: Calldata as hex string or bytes
        """
        if isinstance(data, str):
            data = bytes.fromhex(data.replace('0x', ''))
        
        self.calls.append({
            'target': Web3.to_checksum_address(target),
            'value': value,
            'data': data
        })
        return self
    
    def add_approval(self, token: str, spender: str, amount: int) -> "EIP7702TransactionBuilder":
        """
        Add an ERC20 approval call.
        
        Args:
            token: Token contract address
            spender: Address to approve
            amount: Amount to approve (use 2**256-1 for max)
        """
        # approve(address,uint256)
        function_selector = keccak(text="approve(address,uint256)")[:4]
        encoded_params = encode(['address', 'uint256'], [Web3.to_checksum_address(spender), amount])
        data = function_selector + encoded_params
        
        return self.add_call(token, 0, data)
    
    def add_futarchy_split(self, router: str, proposal: str, collateral: str, amount: int) -> "EIP7702TransactionBuilder":
        """
        Add FutarchyRouter splitPosition call.
        
        Args:
            router: FutarchyRouter address
            proposal: Proposal address
            collateral: Collateral token address (e.g., sDAI)
            amount: Amount to split (in wei)
        """
        # splitPosition(address,address,uint256)
        function_selector = keccak(text="splitPosition(address,address,uint256)")[:4]
        encoded_params = encode(
            ['address', 'address', 'uint256'],
            [Web3.to_checksum_address(proposal), Web3.to_checksum_address(collateral), amount]
        )
        data = function_selector + encoded_params
        
        return self.add_call(router, 0, data)
    
    def add_futarchy_merge(self, router: str, proposal: str, collateral: str, amount: int) -> "EIP7702TransactionBuilder":
        """
        Add FutarchyRouter mergePositions call.
        
        Args:
            router: FutarchyRouter address
            proposal: Proposal address
            collateral: Collateral token address (e.g., Company token)
            amount: Amount to merge (in wei)
        """
        # mergePositions(address,address,uint256)
        function_selector = keccak(text="mergePositions(address,address,uint256)")[:4]
        encoded_params = encode(
            ['address', 'address', 'uint256'],
            [Web3.to_checksum_address(proposal), Web3.to_checksum_address(collateral), amount]
        )
        data = function_selector + encoded_params
        
        return self.add_call(router, 0, data)
    
    def add_swapr_exact_in(self, router: str, token_in: str, token_out: str, 
                          amount_in: int, amount_out_min: int, recipient: str,
                          deadline: int, sqrt_price_limit: int = 0) -> "EIP7702TransactionBuilder":
        """
        Add Swapr exactInputSingle call.
        
        Args:
            router: Swapr router address
            token_in: Input token address
            token_out: Output token address
            amount_in: Amount of input token (in wei)
            amount_out_min: Minimum amount of output token (in wei)
            recipient: Recipient address
            deadline: Unix timestamp deadline
            sqrt_price_limit: Square root price limit (0 for no limit)
        """
        # exactInputSingle((address,address,address,uint256,uint256,uint256,uint160))
        function_selector = keccak(text="exactInputSingle((address,address,address,uint256,uint256,uint256,uint160))")[:4]
        
        # Encode the struct as a tuple
        struct_data = encode(
            ['address', 'address', 'address', 'uint256', 'uint256', 'uint256', 'uint160'],
            [
                Web3.to_checksum_address(token_in),
                Web3.to_checksum_address(token_out),
                Web3.to_checksum_address(recipient),
                deadline,
                amount_in,
                amount_out_min,
                sqrt_price_limit
            ]
        )
        
        # Encode the entire function call
        data = function_selector + encode(['bytes'], [struct_data])
        
        return self.add_call(router, 0, data)
    
    def build_authorization(self, account: Account, nonce: Optional[int] = None) -> Dict[str, Any]:
        """
        Build and sign the EIP-7702 authorization.
        
        Args:
            account: Account instance to sign with
            nonce: Optional nonce (defaults to current account nonce)
            
        Returns:
            Signed authorization dictionary
        """
        if nonce is None:
            nonce = self.w3.eth.get_transaction_count(account.address)
            
        auth = {
            "chainId": self.w3.eth.chain_id,
            "address": self.implementation_address,
            "nonce": nonce
        }
        
        # Sign the authorization
        signed_auth = account.sign_authorization(auth)
        logger.debug(f"Created authorization for implementation {self.implementation_address}")
        
        # Convert SignedSetCodeAuthorization to dict format for transaction
        # The signed authorization object has the required fields as attributes
        auth_dict = {
            'chainId': signed_auth.chain_id,
            'address': signed_auth.address,
            'nonce': signed_auth.nonce,
            'yParity': signed_auth.y_parity,
            'r': signed_auth.r,
            's': signed_auth.s
        }
        
        return auth_dict
    
    def build_batch_call_data(self) -> bytes:
        """
        Build the calldata for execute(Call[] calldata calls).
        
        Returns:
            Encoded calldata for the batch execution
        """
        # execute(Call[])
        function_selector = keccak(text="execute((address,uint256,bytes)[])")[:4]
        
        # Encode array of structs
        calls_data = []
        for call in self.calls:
            calls_data.append((call['target'], call['value'], call['data']))
        
        encoded_calls = encode(['(address,uint256,bytes)[]'], [calls_data])
        
        return function_selector + encoded_calls
    
    def build_transaction(self, account: Account, gas_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Build the complete EIP-7702 transaction.
        
        Args:
            account: Account to send from
            gas_params: Optional gas parameters (gas, maxFeePerGas, maxPriorityFeePerGas)
            
        Returns:
            Complete transaction dictionary ready for signing
        """
        # Get current nonce
        nonce = self.w3.eth.get_transaction_count(account.address)
        
        # Build authorization
        signed_auth = self.build_authorization(account, nonce)
        
        # Build batch call data
        call_data = self.build_batch_call_data()
        
        # Default gas parameters
        if gas_params is None:
            latest_block = self.w3.eth.get_block('latest')
            base_fee = latest_block.get('baseFeePerGas', self.w3.eth.gas_price)
            priority_fee = self.w3.to_wei(2, 'gwei')
            
            gas_params = {
                'gas': 2000000,  # Conservative estimate for complex operations
                'maxFeePerGas': base_fee + priority_fee * 2,
                'maxPriorityFeePerGas': priority_fee
            }
        
        # Build transaction
        tx = {
            'type': 4,  # EIP-7702 transaction type
            'chainId': self.w3.eth.chain_id,
            'nonce': nonce,
            'to': account.address,  # Send to self
            'value': 0,
            'data': call_data,
            'authorizationList': [signed_auth],
            **gas_params
        }
        
        logger.info(f"Built EIP-7702 transaction with {len(self.calls)} calls")
        
        return tx
    
    def clear(self) -> "EIP7702TransactionBuilder":
        """Clear all pending calls."""
        self.calls = []
        return self
    
    def estimate_gas(self, account: Account) -> int:
        """
        Estimate gas for the transaction.
        
        Args:
            account: Account that will send the transaction
            
        Returns:
            Estimated gas amount
        """
        tx = self.build_transaction(account)
        # Remove gas fields for estimation
        tx.pop('gas', None)
        tx.pop('maxFeePerGas', None)
        tx.pop('maxPriorityFeePerGas', None)
        
        try:
            return self.w3.eth.estimate_gas(tx)
        except Exception as e:
            logger.warning(f"Gas estimation failed: {e}, using default")
            return 2000000  # Default fallback


def create_test_transaction(w3: Web3, implementation_address: str, account: Account) -> Dict[str, Any]:
    """
    Create a simple test transaction for EIP-7702.
    
    Args:
        w3: Web3 instance
        implementation_address: FutarchyBatchExecutor address
        account: Account to use
        
    Returns:
        Transaction dictionary
    """
    builder = EIP7702TransactionBuilder(w3, implementation_address)
    
    # Add a simple approval as test
    # This would approve the router to spend max uint256 of a token
    test_token = "0x0000000000000000000000000000000000000001"  # Dummy address
    test_spender = "0x0000000000000000000000000000000000000002"  # Dummy address
    
    builder.add_approval(test_token, test_spender, 2**256 - 1)
    
    return builder.build_transaction(account)
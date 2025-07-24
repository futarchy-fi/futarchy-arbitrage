# EIP-7702 Integration Design for Complex Bot

## Overview
This document outlines the design for integrating EIP-7702 (Pectra bundled transactions) into the futarchy arbitrage complex bot. Instead of sending multiple sequential transactions, all operations will be bundled into a single atomic EIP-7702 transaction.

## Architecture

### 1. Implementation Contract
We need an implementation contract that the EOA will delegate to. This contract will contain the batching logic.

```solidity
// FutarchyBatchExecutor.sol
contract FutarchyBatchExecutor {
    struct Call {
        address target;
        uint256 value;
        bytes data;
    }
    
    function execute(Call[] calldata calls) external payable {
        require(msg.sender == address(this), "Only self-execution allowed");
        
        for (uint256 i = 0; i < calls.length; i++) {
            (bool success, bytes memory result) = calls[i].target.call{value: calls[i].value}(calls[i].data);
            require(success, string(result));
        }
    }
}
```

### 2. Python Implementation Structure

#### a. EIP-7702 Transaction Builder (`src/helpers/eip7702_builder.py`)
```python
from typing import List, Dict, Any
from web3 import Web3
from eth_account import Account
from eth_abi import encode

class EIP7702TransactionBuilder:
    def __init__(self, w3: Web3, implementation_address: str):
        self.w3 = w3
        self.implementation_address = implementation_address
        self.calls = []
    
    def add_call(self, target: str, value: int, data: bytes):
        """Add a call to the batch."""
        self.calls.append({
            'target': Web3.to_checksum_address(target),
            'value': value,
            'data': data
        })
    
    def build_authorization(self, account: Account, nonce: int) -> Dict[str, Any]:
        """Build and sign the EIP-7702 authorization."""
        auth = {
            "chainId": self.w3.eth.chain_id,
            "address": self.implementation_address,
            "nonce": nonce
        }
        return account.sign_authorization(auth)
    
    def build_transaction(self, account: Account, gas_price_params: Dict) -> Dict[str, Any]:
        """Build the complete EIP-7702 transaction."""
        # Encode the batch execution call
        calls_data = self._encode_batch_call()
        
        # Get current nonce
        nonce = self.w3.eth.get_transaction_count(account.address)
        
        # Sign authorization
        signed_auth = self.build_authorization(account, nonce)
        
        # Build transaction
        tx = {
            "type": 4,  # EIP-7702 transaction type
            "chainId": self.w3.eth.chain_id,
            "nonce": nonce,
            "to": account.address,  # Send to self
            "value": 0,
            "data": calls_data,
            "authorizationList": [signed_auth],
            **gas_price_params
        }
        
        return tx
    
    def _encode_batch_call(self) -> bytes:
        """Encode the execute(Call[]) function call."""
        # This would encode the function selector and parameters
        # Implementation depends on the exact contract interface
        pass
```

#### b. Modified Buy Conditional Function (`src/arbitrage_commands/buy_cond_eip7702.py`)
```python
def build_buy_bundle_eip7702(
    amount: float,
    gno_amount: float = None,
    liquidate_conditional_sdai_amount: float = None
) -> List[Dict[str, Any]]:
    """Build all calls for buy operation to be bundled in EIP-7702 transaction."""
    
    split_amount_in_wei = w3.to_wei(Decimal(amount), "ether")
    calls = []
    
    # 1. Split sDAI → YES/NO conditional sDAI
    split_data = encode_function_call(
        "splitPosition",
        ["address", "address", "uint256"],
        [proposal_addr, collateral_addr, split_amount_in_wei]
    )
    calls.append({
        'target': router_addr,
        'value': 0,
        'data': split_data
    })
    
    # 2. Swap conditional sDAI → conditional Company tokens (YES)
    yes_swap_data = encode_swapr_exact_in(
        token_yes_in, token_yes_out, split_amount_in_wei, 0
    )
    calls.append({
        'target': swapr_router,
        'value': 0,
        'data': yes_swap_data
    })
    
    # 3. Swap conditional sDAI → conditional Company tokens (NO)
    no_swap_data = encode_swapr_exact_in(
        token_no_in, token_no_out, split_amount_in_wei, 0
    )
    calls.append({
        'target': swapr_router,
        'value': 0,
        'data': no_swap_data
    })
    
    # 4. Merge conditional Company → regular Company token
    if gno_amount:
        merge_data = encode_function_call(
            "mergePositions",
            ["address", "address", "uint256"],
            [proposal_addr, company_collateral_addr, gno_amount_in_wei]
        )
        calls.append({
            'target': router_addr,
            'value': 0,
            'data': merge_data
        })
    
    # 5. Liquidate excess conditional sDAI if needed
    if liquidate_conditional_sdai_amount:
        # Add liquidation calls
        pass
    
    # 6. Sell Company token → sDAI on Balancer
    balancer_swap_data = encode_balancer_swap(
        gno_amount_in_wei, min_sdai_out
    )
    calls.append({
        'target': balancer_vault,
        'value': 0,
        'data': balancer_swap_data
    })
    
    return calls
```

#### c. Modified Complex Bot (`src/arbitrage_commands/complex_bot_eip7702.py`)
```python
def execute_buy_with_eip7702(amount: float, tolerance: float):
    """Execute buy operation using EIP-7702 bundled transaction."""
    
    # 1. Build the bundle of calls
    calls = build_buy_bundle_eip7702(amount)
    
    # 2. Create EIP-7702 transaction builder
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_CONTRACT_ADDRESS)
    
    # 3. Add all calls to builder
    for call in calls:
        builder.add_call(call['target'], call['value'], call['data'])
    
    # 4. Build transaction with gas parameters
    gas_params = {
        'gas': 1000000,  # Estimate properly
        'maxFeePerGas': w3.to_wei('30', 'gwei'),
        'maxPriorityFeePerGas': w3.to_wei('2', 'gwei')
    }
    
    tx = builder.build_transaction(acct, gas_params)
    
    # 5. Sign and send
    signed_tx = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    # 6. Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    return {
        'tx_hash': tx_hash.hex(),
        'status': receipt.status,
        'gas_used': receipt.gasUsed
    }
```

### 3. Integration Points

#### Modified `complex_bot.py`
```python
def run_once(amount: float, tolerance: float, broadcast: bool, use_eip7702: bool = False) -> None:
    # ... existing price discovery code ...
    
    if amount > 0:
        if bal_price_val > ideal_bal_price:
            print("→ Buying conditional GNO")
            if use_eip7702:
                # Use EIP-7702 bundled transaction
                result = execute_buy_with_eip7702(amount, tolerance)
            else:
                # Use existing sequential transactions
                result = buy_gno_yes_and_no_amounts_with_sdai(amount, broadcast=broadcast)
```

### 4. Deployment Steps

1. **Deploy Implementation Contract**
   - Deploy `FutarchyBatchExecutor` on Gnosis Chain
   - Verify the contract
   - Store address in configuration

2. **Update Dependencies**
   - Ensure eth-account >= 0.11.3 (already satisfied)
   - Ensure web3.py supports type 4 transactions

3. **Add Configuration**
   ```python
   # src/config/eip7702.py
   EIP7702_CONFIG = {
       'implementation_contract': '0x...',  # FutarchyBatchExecutor address
       'enabled': True,
       'gas_buffer': 1.2  # 20% buffer for bundled operations
   }
   ```

4. **Testing Strategy**
   - Test authorization signing
   - Test transaction building
   - Test on testnet first
   - Compare gas usage vs sequential transactions

### 5. Benefits

1. **Atomicity**: All operations succeed or fail together
2. **Gas Efficiency**: Single transaction overhead
3. **MEV Protection**: Harder to sandwich partial execution
4. **Simplified Error Handling**: One transaction to monitor

### 6. Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| Dynamic amounts (e.g., swap outputs) | Use minimum amounts or implement callback pattern |
| Gas estimation | Add buffer for complex bundled operations |
| Debugging failures | Add detailed logging for each operation |
| Backward compatibility | Keep flag to use sequential transactions |

### 7. Future Enhancements

1. **Gas Sponsorship**: Allow third parties to pay gas fees
2. **Conditional Execution**: Skip operations based on conditions
3. **Multi-signature Support**: Enable multiple signers for added security
4. **Cross-chain Operations**: Leverage EIP-7702 for cross-chain arbitrage

## Implementation Timeline

1. **Phase 1**: Core EIP-7702 utilities (1-2 days)
2. **Phase 2**: Implementation contract development (2-3 days)
3. **Phase 3**: Integration with buy/sell functions (2-3 days)
4. **Phase 4**: Testing and optimization (3-4 days)
5. **Phase 5**: Documentation and deployment (1-2 days)

## Questions for Implementation

1. Should we deploy our own implementation contract or use an existing one?
2. How should we handle token approvals within the bundled transaction?
3. Should we implement a fallback mechanism if EIP-7702 fails?
4. What's the maximum gas limit we should consider for bundled operations?
5. How do we handle partial success scenarios (if the implementation allows)?
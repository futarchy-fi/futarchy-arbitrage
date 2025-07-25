# Pectra Bundled Transactions Task

## Overview
Transform the futarchy arbitrage bot to use EIP-7702 bundled transactions instead of sequential transactions. This leverages Pectra's EIP-7702 feature to execute all arbitrage operations atomically in a single transaction.

## Background
Currently, the arbitrage bot (`complex_bot.py`) executes multiple transactions sequentially:
- Approvals for tokens
- Splitting sDAI into conditional tokens
- Swapping on Swapr pools
- Merging conditional tokens
- Final arbitrage swap

This approach has several limitations:
- MEV risk between transactions
- Higher gas costs due to multiple transaction overheads
- Risk of partial execution if one transaction fails
- Slower execution time

## Objective
Modify `pectra_bot.py` to bundle all operations into a single EIP-7702 transaction using the `FutarchyBatchExecutor` contract.

## Technical Approach

### 1. EIP-7702 Integration
- Use `EIP7702TransactionBuilder` from `src/helpers/eip7702_builder.py`
- Deploy or use existing `FutarchyBatchExecutor` implementation contract
- Create authorization for EOA to act as smart contract temporarily

### 2. Buy Conditional Flow
Bundle these operations:
1. Approve FutarchyRouter for sDAI
2. Split sDAI → YES/NO conditional sDAI
3. Approve Swapr for YES conditional sDAI
4. Swap YES sDAI → YES Company token
5. Approve Swapr for NO conditional sDAI
6. Swap NO sDAI → NO Company token
7. Approve FutarchyRouter for Company tokens
8. Merge YES/NO Company → Company token
9. Approve Balancer for Company token
10. Swap Company → sDAI on Balancer

### 3. Sell Conditional Flow
Bundle these operations:
1. Approve Balancer for sDAI
2. Swap sDAI → Company on Balancer
3. Approve FutarchyRouter for Company token
4. Split Company → YES/NO conditional Company
5. Approve Swapr for YES Company token
6. Swap YES Company → YES sDAI
7. Approve Swapr for NO Company token
8. Swap NO Company → NO sDAI
9. Approve FutarchyRouter for conditional sDAI
10. Merge YES/NO sDAI → sDAI

### 4. Implementation Details

#### Key Functions to Add:
```python
def build_buy_bundle(builder, addresses, amount):
    """Build bundled transaction for buy conditional flow"""
    
def build_sell_bundle(builder, addresses, amount):
    """Build bundled transaction for sell conditional flow"""
    
def simulate_bundle(w3, account, tx):
    """Simulate EIP-7702 transaction and return expected results"""
    
def execute_bundle(w3, account, tx):
    """Sign and send EIP-7702 transaction"""
```

#### Environment Variables Required:
- `IMPLEMENTATION_ADDRESS` - FutarchyBatchExecutor contract address
- All existing addresses (tokens, pools, routers)
- `PRIVATE_KEY` - For signing EIP-7702 transactions

### 5. Benefits
- **Atomicity**: All operations succeed or fail together
- **Gas Savings**: ~15% reduction from avoiding transaction overheads
- **MEV Protection**: No intermediate states exploitable by MEV bots
- **Speed**: Single transaction vs multiple sequential ones

### 6. Testing Strategy
1. Test with small amounts on testnet first
2. Verify gas estimation accuracy
3. Compare profitability vs sequential approach
4. Monitor for EIP-7702 specific issues

## Implementation Steps

1. **Update Imports** ✓
   - Add EIP7702TransactionBuilder
   - Import eth_account for signing
   - Add required contract ABIs

2. **Deployment Check**
   - Check if FutarchyBatchExecutor exists
   - Deploy if needed using deployment script

3. **Refactor Buy Flow**
   - Create `build_buy_conditional_bundle` function
   - Map all operations to builder calls
   - Handle dynamic amount calculations

4. **Refactor Sell Flow**
   - Create `build_sell_conditional_bundle` function
   - Map all operations to builder calls

5. **Simulation Logic**
   - Implement bundle simulation
   - Calculate expected outcomes
   - Verify profitability before execution

6. **Execution Logic**
   - Sign transaction with authorization
   - Send bundled transaction
   - Handle receipts and logging

7. **CLI Updates**
   - Add `--implementation` flag
   - Keep backward compatibility
   - Add bundle-specific options

8. **Error Handling**
   - EIP-7702 authorization errors
   - Bundle execution failures
   - Gas estimation issues

## Success Criteria
- Successfully execute arbitrage in single transaction
- Achieve gas savings vs sequential approach
- Maintain or improve profitability
- No loss of functionality from original bot

## References
- EIP-7702: https://eips.ethereum.org/EIPS/eip-7702
- FutarchyBatchExecutor: contracts/FutarchyBatchExecutor.sol
- EIP7702TransactionBuilder: src/helpers/eip7702_builder.py
- Test implementation: tests/test_eip7702_arbitrage.py
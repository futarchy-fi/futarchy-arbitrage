# FutarchyBatchExecutor Implementation Contract Plan

## Overview
The FutarchyBatchExecutor is designed to enable EIP-7702 batched transactions for futarchy arbitrage operations. When an EOA delegates to this contract via EIP-7702, it can execute multiple operations atomically.

## Key Design Decisions

### 1. Generic vs Specialized Functions
The contract provides both:
- **Generic batch execution** (`execute`, `executeWithResults`) for flexibility
- **Specialized functions** (`executeBuyConditional`, `executeSellConditional`) for optimized paths

### 2. Return Value Handling
- `execute()`: Simple batch execution, reverts on failure
- `executeWithResults()`: Returns array of results for dynamic decision making
- This allows handling cases where swap outputs affect subsequent operations

### 3. Approval Management
- `setApprovals()`: Batch approval setter to minimize overhead
- Internal `_approve()` with proper error handling and return value checking

### 4. Error Handling
- Custom errors for gas efficiency
- Detailed revert information including which call failed
- Events for all operations to aid debugging

## Operations Flow

### Buy Conditional Flow
1. **Approve** FutarchyRouter to spend sDAI
2. **Split** sDAI → YES/NO conditional sDAI tokens
3. **Approve** Swapr router for YES/NO conditional sDAI
4. **Swap** YES conditional sDAI → YES Company token
5. **Swap** NO conditional sDAI → NO Company token
6. **Approve** FutarchyRouter for Company tokens
7. **Merge** YES/NO Company tokens → Company token
8. **Approve** Balancer for Company token
9. **Swap** Company token → sDAI on Balancer
10. **Handle** any excess conditional tokens

### Sell Conditional Flow
1. **Approve** Balancer to spend sDAI
2. **Swap** sDAI → Company token on Balancer
3. **Approve** FutarchyRouter for Company token
4. **Split** Company token → YES/NO conditional Company tokens
5. **Approve** Swapr for conditional Company tokens
6. **Swap** YES Company → YES sDAI
7. **Swap** NO Company → NO sDAI
8. **Approve** FutarchyRouter for conditional sDAI
9. **Merge** YES/NO sDAI → sDAI
10. **Handle** any imbalances

## Advanced Features

### 1. Dynamic Amount Calculation
For operations where output amounts affect subsequent calls:
```solidity
function executeWithDynamicAmounts(
    Call[] calldata staticCalls,
    DynamicCall[] calldata dynamicCalls
) external returns (bytes[] memory)
```

Where `DynamicCall` includes:
- Target address
- Function selector
- Parameter indices to replace
- Source call index for the replacement value

### 2. Conditional Execution
Skip operations based on conditions:
```solidity
struct ConditionalCall {
    Call call;
    bytes32 condition; // e.g., SKIP_IF_ZERO, SKIP_IF_LESS_THAN
    uint256 compareValue;
    uint256 sourceIndex; // Which previous call's result to check
}
```

### 3. Gas Optimization
- Use assembly for low-level calls where beneficial
- Pack structs efficiently
- Minimize storage operations (all logic in memory/calldata)

## Security Considerations

1. **Self-execution only**: `require(msg.sender == address(this))`
2. **No storage**: Stateless design prevents reentrancy issues
3. **Balance checks**: Verify ETH balance before value transfers
4. **Return value validation**: Check success and decode returns properly

## Integration with Python

The Python code will:
1. Encode all operation calldata
2. Build the Call array
3. Sign EIP-7702 authorization
4. Submit transaction to EOA address

Example encoding:
```python
# Split position
split_data = encode_abi(
    ["address", "address", "uint256"],
    [proposal_addr, collateral_addr, amount]
)

calls.append({
    'target': futarchy_router,
    'value': 0,
    'data': "0x" + keccak("splitPosition(address,address,uint256)")[:8] + split_data
})
```

## Testing Strategy

1. **Unit tests**: Each operation in isolation
2. **Integration tests**: Full arbitrage flows
3. **Fork tests**: Against mainnet state
4. **Gas benchmarks**: Compare with sequential transactions

## Future Enhancements

1. **MEV Protection**: Add commit-reveal or flashloan protection
2. **Cross-chain**: Support for cross-chain arbitrage
3. **Gasless**: Integration with relayers for sponsored transactions
4. **Upgradeable**: Proxy pattern for bug fixes (with careful consideration)

## Deployment Checklist

- [ ] Deploy contract on Gnosis testnet
- [ ] Verify contract on explorer
- [ ] Test with small amounts
- [ ] Audit the contract code
- [ ] Deploy on Gnosis mainnet
- [ ] Update bot configuration
- [ ] Monitor initial transactions
- [ ] Document gas savings
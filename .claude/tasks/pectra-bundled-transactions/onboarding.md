# Pectra Bundled Transactions Integration - Onboarding Document

## Task Overview
Modify the complex bot (`src/arbitrage_commands/complex_bot.py`) to submit transactions using Pectra bundled transactions (EIP-7702) instead of sequential individual transactions.

## Current Architecture Understanding

### Complex Bot Flow
1. **Price Discovery**: Fetches prices from Swapr (YES/NO pools) and Balancer pools
2. **Arbitrage Decision**: Calculates ideal price and determines whether to buy or sell conditional tokens
3. **Transaction Execution**: Calls either `buy_gno_yes_and_no_amounts_with_sdai` or `sell_gno_yes_and_no_amounts_to_sdai`

### Current Transaction Submission
Both buy and sell functions use the same pattern:
- Build a bundle of transactions (split, swap, merge, liquidate, etc.)
- Use `_send_bundle_onchain` to send transactions sequentially
- Each transaction is sent with consecutive nonces
- Waits for receipt before sending the next transaction

### Key Files
- **`complex_bot.py`**: Main arbitrage bot logic
- **`buy_cond.py`**: Buy conditional tokens logic
- **`sell_cond.py`**: Sell conditional tokens logic  
- **`blockchain_sender.py`**: Contains `send_tenderly_tx_onchain` for individual transaction sending

## EIP-7702 / Pectra Bundled Transactions Research

### What is EIP-7702?
- New transaction type (type 4) introduced in Ethereum's Pectra upgrade
- Allows Externally Owned Accounts (EOAs) to temporarily function as smart contract accounts
- Enables bundled/batch transactions with a single signature
- Live on mainnet as of May 7, 2025

### Key Features
1. **Batch Transactions**: Multiple operations in a single atomic transaction
2. **No Address Changes**: Works with existing EOAs
3. **Gas Sponsorship**: Third parties can pay gas
4. **Temporary Smart Contract Features**: Only during the transaction

### Technical Implementation
```python
# Basic structure
tx = {
    "type": 4,  # EIP-7702 transaction type
    "chainId": chain_id,
    "nonce": nonce,
    "to": account.address,  # Send to your own EOA
    "data": multicall_data,  # Batched operations
    "authorizationList": [signed_auth],  # Authorization to act as smart contract
}
```

### Authorization Structure
```python
signed_auth = account.sign_authorization({
    "chainId": chain_id,  # or 0 for all chains
    "address": implementation_contract,  # Contract to delegate to
    "nonce": eoa_nonce,
})
```

## Integration Approach

### 1. Implementation Contract Strategy
With EIP-7702, we don't use an external multicall contract. Instead:
- Deploy an implementation contract (like BatchCallAndSponsor) that contains batching logic
- The EOA signs an authorization to delegate to this implementation
- The transaction is sent to the EOA's own address
- The EOA executes batched operations as if it were the implementation contract

Key insight: The EOA itself becomes the executor, maintaining proper `msg.sender` context for approvals and other operations.

### 2. Transaction Bundling Strategy
Current transaction flow for buy operations:
1. Split sDAI → YES/NO conditional sDAI
2. Swap conditional sDAI → conditional Company tokens (2 swaps)
3. Merge conditional Company → regular Company token
4. Liquidate excess conditional sDAI
5. Sell Company token → sDAI on Balancer

All these operations can be bundled into a single EIP-7702 transaction.

### 3. Implementation Plan

#### Phase 1: Infrastructure Setup
- Add EIP-7702 transaction building utilities
- Create authorization signing functions
- Test with simple bundled operations

#### Phase 2: Modify Transaction Builders
- Update `buy_cond.py` and `sell_cond.py` to build multicall data
- Create new `send_bundled_transaction` function
- Maintain backward compatibility with sequential sending

#### Phase 3: Complex Bot Integration
- Add command-line flag for bundled vs sequential execution
- Update simulation logic to handle bundled transactions
- Add proper error handling and logging

### 4. Key Considerations

#### Benefits
- **Atomicity**: All operations succeed or fail together
- **Gas Efficiency**: Single transaction overhead
- **Speed**: No waiting between operations
- **MEV Protection**: Harder to front-run partial execution

#### Challenges
- **Gas Limits**: Bundled transaction may exceed block gas limit
- **Debugging**: Harder to identify which operation failed
- **Simulation**: Need to adapt Tenderly simulation for bundled transactions
- **Multicall Contract**: Need reliable multicall implementation

#### Security Considerations
- Authorization must be carefully scoped
- Multicall contract must be audited
- Need to handle reverts within the bundle

## Next Steps

1. Research existing multicall contracts on Gnosis Chain
2. Design the bundled transaction data structure
3. Implement authorization signing utilities
4. Create bundled transaction builder functions
5. Integrate with complex bot logic
6. Add comprehensive testing
7. Update documentation

## Questions for Clarification

1. **Multicall Contract**: Should we use an existing multicall contract or deploy a custom one?
2. **Backward Compatibility**: Should we maintain the option to use sequential transactions?
3. **Error Handling**: How should we handle partial failures within a bundle?
4. **Testing Strategy**: Do we have access to a testnet with Pectra support?
5. **Gas Optimization**: Are there specific gas constraints we need to consider?

## Resources

- [EIP-7702 Specification](https://eips.ethereum.org/EIPS/eip-7702)
- [web3.py EIP-7702 Patterns](https://snakecharmers.ethereum.org/7702/)
- [Ethereum Pectra Upgrade Documentation](https://ethereum.org/en/roadmap/pectra/)
- [eth-account Authorization Signing](https://eth-account.readthedocs.io/)
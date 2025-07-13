# Multicall Bot Implementation Guide

## Overview

This document describes the multicall-based arbitrage bot implementation for Gnosis Chain futarchy markets. The bot uses a flexible multicall pattern instead of hardcoded arbitrage logic, allowing for dynamic execution of complex arbitrage strategies.

## Architecture Changes

### From Hardcoded to Multicall Pattern

The original FutarchyArbitrageExecutor contract had specific functions for each arbitrage operation. We redesigned it to use a generic multicall pattern that:

1. Accepts an array of arbitrary contract calls as `Call` structs
2. Executes them atomically in sequence
3. Tracks success/failure of each call
4. Calculates profit after all operations

### Key Components

#### 1. FutarchyArbitrageExecutor Contract (`contracts/FutarchyArbitrageExecutor.sol`)

**Core Functions:**
- `multicall(Call[] calldata calls)` - Execute multiple calls, continue on failure
- `multicallStrict(Call[] calldata calls)` - Execute multiple calls, revert on any failure
- `executeArbitrage(calls, profitToken, minProfit)` - Execute arbitrage with profit tracking
- `pullToken/pushToken` - Move tokens between owner and contract
- `batchApprove` - Approve multiple tokens to multiple spenders

**Deployment:**
- Address: `0xf276e5d62978F0E79089a4B7867A2AD97E3c9be5`
- Owner: `0x91c612a37b8365C2db937388d7b424fe03D62850`
- Network: Gnosis Chain

#### 2. Multicall Builder (`multicall_builder.py`)

Helper class to encode complex arbitrage operations:

```python
class MulticallBuilder:
    def add_futarchy_split(self, router_address, proposal, collateral_token, amount)
    def add_swapr_exact_input(self, router_address, params)
    def add_balancer_swap(self, vault_address, pool_id, token_in, token_out, amount_in, min_amount_out)
    def build() -> List[Tuple[str, bytes]]
```

#### 3. Test Scripts

- `test_multicall_simple.py` - Basic multicall functionality testing
- `test_split_and_swap.py` - Complex arbitrage operations testing

## Arbitrage Flow Using Multicall

### Example: Buy Conditional Company Tokens

1. **Pull sDAI from owner to executor**
   ```python
   executor.pullToken(sdai_token, amount)
   ```

2. **Build multicall for arbitrage:**
   ```python
   calls = [
       # Approve FutarchyRouter to spend sDAI
       (sdai_token, approve_data),
       
       # Split sDAI into YES/NO conditional sDAI
       (futarchy_router, split_position_data),
       
       # Approve Swapr router for YES tokens
       (sdai_yes, approve_swapr_data),
       
       # Swap YES sDAI for YES Company tokens
       (swapr_router, swap_yes_data),
       
       # Similar for NO tokens...
   ]
   ```

3. **Execute multicall:**
   ```python
   executor.multicall(calls)
   ```

4. **Push profits back to owner:**
   ```python
   executor.pushToken(company_token, MAX_UINT)
   ```

## Environment Configuration

Required environment variables in `.env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF`:

```bash
# Arbitrage Executor
ARBITRAGE_EXECUTOR_ADDRESS=0xf276e5d62978F0E79089a4B7867A2AD97E3c9be5

# Token Addresses
SDAI_TOKEN_ADDRESS=0xaf204776c7245bF4147c2612BF6e5972Ee483701
COMPANY_TOKEN_ADDRESS=0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb

# Conditional Tokens
SWAPR_SDAI_YES_ADDRESS=0x78d2c7da671fd4275836932a3b213b01177c6628
SWAPR_SDAI_NO_ADDRESS=0x4d67f9302cde3c4640a99f0908fdf6f32d3ddfb6
SWAPR_GNO_YES_ADDRESS=0x718be32688b615c2eb24560371ef332b892f69d8
SWAPR_GNO_NO_ADDRESS=0x72c185710775f307c9da20424910a1d3d27b8be0

# Router Addresses
FUTARCHY_ROUTER_ADDRESS=0x7495a583ba85875d59407781b4958ED6e0E1228f
SWAPR_ROUTER_ADDRESS=0xfFB643E73f280B97809A8b41f7232AB401a04ee1
BALANCER_ROUTER_ADDRESS=0xe2fa4e1d17725e72dcdAfe943Ecf45dF4B9E285b

# Pool Addresses
SWAPR_POOL_YES_ADDRESS=0x4fF34E270CA54944955b2F595CeC4CF53BDc9e0c
SWAPR_POOL_NO_ADDRESS=0x817b01261f9d356922f6Ec18dd342a0cB83e3CD7
BALANCER_POOL_ADDRESS=0xd1d7fa8871d84d0e77020fc28b7cd5718c446522

# Futarchy Proposal
FUTARCHY_PROPOSAL_ADDRESS=0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF
```

## Testing Results

### Successful Operations Tested:

1. **Basic Multicall (test_multicall_simple.py)**
   - Pull 0.001 sDAI from owner
   - Approve FutarchyRouter via multicall
   - Push tokens back to owner

2. **Complex Arbitrage (test_split_and_swap.py)**
   - Pull 0.01 sDAI from owner
   - Split into YES/NO conditional sDAI tokens
   - Swap YES sDAI for 0.000100893043060749 YES Company tokens
   - Successfully executed 4 operations atomically

## Integration with Existing Bots

The multicall executor can be integrated with existing arbitrage strategies:

1. **simple_bot.py** - Monitor price discrepancies and execute trades
2. **complex_bot.py** - Price discovery and side determination
3. **buy_cond.py/sell_cond.py** - Conditional token trading logic

Instead of executing transactions directly, these bots can:
1. Build multicall data using MulticallBuilder
2. Submit to the executor contract
3. Handle results and profit calculation

## Advantages of Multicall Pattern

1. **Atomicity** - All operations succeed or fail together
2. **Gas Efficiency** - Single transaction for complex operations
3. **Flexibility** - Any combination of operations without contract updates
4. **Simulation** - Test entire sequences before execution
5. **Profit Tracking** - Built-in profit calculation and minimum profit enforcement

## Security Considerations

1. **Owner-only** - All functions restricted to contract owner
2. **Pull/Push Pattern** - Explicit token movement for safety
3. **Approval Management** - Reset approvals when needed
4. **Emergency Functions** - rescueToken/rescueETH for stuck funds
5. **Simulation First** - Test operations before execution

## Future Enhancements

1. **MEV Protection** - Use flashloan callbacks or commit-reveal
2. **Multi-token Profit** - Track profit in multiple tokens
3. **Gas Optimization** - Batch similar operations
4. **Event Monitoring** - React to specific on-chain events
5. **Strategy Templates** - Pre-built multicall sequences

## Deployment and Verification

Contract deployed and verified on Gnosisscan:
- Transaction: `0xbbe728f023fc60252801dda910fd793e9cb6f9c80c76bedbb62e20effc972631`
- Block: 41045624
- Verification: Pending (use `verify_contract.py` with constructor args)

## Usage Example

```python
# Initialize
from multicall_builder import MulticallBuilder
from web3 import Web3

w3 = Web3(Web3.HTTPProvider(RPC_URL))
builder = MulticallBuilder()

# Build arbitrage sequence
builder.add_futarchy_split(futarchy_router, proposal, sdai_token, amount)
builder.add_swapr_exact_input(swapr_router, swap_params)
calls = builder.build()

# Execute via contract
executor.functions.executeArbitrage(calls, sdai_token, min_profit).transact()
```

This multicall pattern provides maximum flexibility for executing complex arbitrage strategies while maintaining atomicity and safety.
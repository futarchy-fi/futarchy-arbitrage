# Multicall Bot Implementation Guide

## Overview

This document describes the multicall-based arbitrage bot implementation for Gnosis Chain futarchy markets. The bot uses a simplified multicall pattern with profit verification, designed for maximum safety and efficiency.

## Architecture - V2 Design

### Simplified Multicall Pattern

The FutarchyArbitrageExecutorV2 contract provides a clean, owner-only multicall interface:

1. Accepts an array of arbitrary contract calls as `Call` structs
2. Executes them atomically in sequence
3. Automatically calculates and verifies profit
4. Transfers all profits to the owner

### Key Components

#### 1. FutarchyArbitrageExecutorV2 Contract (`contracts/FutarchyArbitrageExecutorV2.sol`)

**Core Functions:**
- `multicall(Call[] calldata calls)` - Execute multiple calls with failure handling
- `executeArbitrage(calls, profitToken, minProfit)` - Execute arbitrage with profit verification
- `withdrawToken(token, amount)` - Withdraw tokens from contract
- `approveToken(token, spender, amount)` - Approve token spending

**Current Deployment:**
- Address: `0x474024acDA78D7827a94817d3b6C9794F3716AF2`
- Owner: `0x91c612a37b8365C2db937388d7b424fe03D62850`
- Network: Gnosis Chain
- Verified: ✅ [View on Gnosisscan](https://gnosisscan.io/address/0x474024acDA78D7827a94817d3b6C9794F3716AF2#code)

#### 2. Multicall V2 Builder (`src/commands/multicall_v2.py`)

Simplified builder class for V2 contract:

```python
class MulticallV2Builder:
    def add_call(self, target: str, function_name: str, args: List[Any])
    def add_approve(self, token: str, spender: str, amount: int)
    def add_futarchy_split(self, router: str, proposal: str, collateral: str, amount: int)
    def add_swapr_swap(self, router: str, token_in: str, token_out: str, amount_in: int, min_out: int)
    def build() -> List[Tuple[str, bytes]]
```

#### 3. Deployment & Testing Scripts (in `scripts/`)

- `deploy_and_verify_v2.py` - Unified deployment and verification
- `test_deployed_v2.py` - Contract functionality testing
- `verify_only_v2.py` - Standalone verification script

## Arbitrage Flow Using V2 Multicall

### Example: Buy Conditional Company Tokens

1. **Send sDAI to executor contract** (manual transfer)

2. **Build multicall for arbitrage:**
   ```python
   from src.commands.multicall_v2 import MulticallV2Builder
   
   builder = MulticallV2Builder(executor_address, w3)
   
   # Build the sequence
   builder.add_approve(sdai_token, futarchy_router, amount)
   builder.add_futarchy_split(futarchy_router, proposal, sdai_token, amount)
   builder.add_approve(sdai_yes_token, swapr_router, amount_yes)
   builder.add_swapr_swap(swapr_router, sdai_yes_token, company_yes_token, amount_yes, min_out)
   # Similar for NO tokens...
   
   calls = builder.build()
   ```

3. **Execute arbitrage with profit verification:**
   ```python
   executor.functions.executeArbitrage(
       calls, 
       company_token,  # profit token
       min_profit      # minimum required profit
   ).transact()
   ```

4. **Profits automatically sent to owner** ✅

## Environment Configuration

Required environment variables in `.env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF`:

```bash
# Arbitrage Executor V2
ARBITRAGE_EXECUTOR_V2_ADDRESS=0x474024acDA78D7827a94817d3b6C9794F3716AF2

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

### V2 Contract Testing (scripts/test_deployed_v2.py):

1. **Ownership Verification** ✅
   - Contract owner matches deployer
   - Owner-only functions properly restricted

2. **Token Operations** ✅
   - Token approval via executor
   - Balance checking functionality

3. **Multicall Execution** ✅
   - Multiple view calls executed atomically
   - Gas efficiency: ~34k gas for 2 operations

## Integration with Existing Bots

The V2 multicall executor integrates seamlessly with existing arbitrage strategies:

1. **src/arbitrage_commands/simple_bot.py** - Monitor price discrepancies 
2. **src/arbitrage_commands/complex_bot.py** - Price discovery and side determination
3. **src/arbitrage_commands/buy_cond.py** - Conditional token trading logic

**Integration Pattern:**
1. Build multicall data using `MulticallV2Builder`
2. Submit to executor with `executeArbitrage()` 
3. Automatic profit verification and transfer

## Advantages of V2 Multicall Pattern

1. **Simplified Security** - Owner-only, no complex token management
2. **Automatic Profit Handling** - Built-in profit calculation and transfer
3. **Gas Efficiency** - Single transaction for complex operations
4. **Atomicity** - All operations succeed or fail together
5. **Flexibility** - Any combination of operations without contract updates

## Security Considerations

1. **Owner-only Access** - All functions restricted to contract owner
2. **Automatic Profit Transfer** - Prevents funds from getting stuck
3. **Minimal Attack Surface** - Simplified contract with fewer functions
4. **Emergency Withdrawals** - `withdrawToken()` and `withdrawETH()` for stuck funds
5. **No Reentrancy Risk** - Simple call pattern without complex state

## Future Enhancements

1. **MEV Protection** - Use flashloan callbacks or commit-reveal
2. **Multi-token Profit** - Track profit in multiple tokens
3. **Gas Optimization** - Batch similar operations
4. **Event Monitoring** - React to specific on-chain events
5. **Strategy Templates** - Pre-built multicall sequences

## Deployment Information

**V2 Contract Successfully Deployed & Verified:**
- **Address:** `0x474024acDA78D7827a94817d3b6C9794F3716AF2`
- **Transaction:** `0xda2c83d9df4a163369ecbd7aa68fe0539c8d2007fc7faa332d8f007c2d7fc67e`
- **Block:** 41088232
- **Verification:** ✅ Verified on Gnosisscan
- **Deployment Script:** `scripts/deploy_and_verify_v2.py`

## Usage Example

```python
# Initialize V2 Builder
from src.commands.multicall_v2 import MulticallV2Builder
from web3 import Web3

w3 = Web3(Web3.HTTPProvider(RPC_URL))
executor_address = "0x474024acDA78D7827a94817d3b6C9794F3716AF2"
builder = MulticallV2Builder(executor_address, w3)

# Build arbitrage sequence
builder.add_approve(sdai_token, futarchy_router, amount)
builder.add_futarchy_split(futarchy_router, proposal, sdai_token, amount)
builder.add_swapr_swap(swapr_router, sdai_yes, company_yes, amount_yes, min_out)
calls = builder.build()

# Execute with profit verification
executor.functions.executeArbitrage(
    calls, 
    company_token,  # profit token
    min_profit      # minimum required profit
).transact()
```

## File Organization

**Clean root structure after V1 cleanup:**
- `contracts/` - V2 contract only
- `scripts/` - Deployment, verification, and testing scripts  
- `src/commands/multicall_v2.py` - V2 multicall builder
- `src/arbitrage_commands/` - Trading strategy bots
- `deployment_info_v2.json` - Current deployment metadata

The V2 multicall pattern provides maximum safety and efficiency for executing complex arbitrage strategies.
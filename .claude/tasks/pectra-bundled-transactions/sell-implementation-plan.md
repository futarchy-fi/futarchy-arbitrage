# Sell Conditional Bundle Implementation Plan (Subtask 3)

## Overview
Implement `sell_cond_eip7702.py` to execute the sell conditional flow using EIP-7702 bundled transactions. This reverses the buy flow: starting with sDAI, acquiring Company tokens via Balancer, splitting them, swapping to conditional sDAI on Swapr, and merging back to regular sDAI.

## Current Sell Flow Analysis (from sell_cond_onchain.py)

### Operation Sequence:
1. **Buy Company with sDAI** via Balancer (sDAI → Company)
2. **Split Company** into YES/NO conditional Company tokens  
3. **Swap YES Company → YES sDAI** on Swapr
4. **Swap NO Company → NO sDAI** on Swapr
5. **Merge YES/NO sDAI** back to regular sDAI

### Key Differences from Buy Flow:
- **Direction**: Sell starts with Balancer, buy ends with Balancer
- **Tokens**: Sell merges sDAI (not Company tokens)
- **Purpose**: Converting Company exposure back to stable sDAI
- **Arbitrage**: Exploits when Swapr prices > Balancer price

## Implementation Strategy

### 1. Operation Count Challenge
**Problem**: Full flow requires 11 operations (exceeds 10-call limit)

```
1. Approve sDAI for Balancer
2. Swap sDAI → Company on Balancer  
3. Approve Company for FutarchyRouter
4. Split Company into YES/NO
5. Approve YES Company for Swapr
6. Swap YES Company → YES sDAI
7. Approve NO Company for Swapr
8. Swap NO Company → NO sDAI
9. Approve YES sDAI for FutarchyRouter
10. Approve NO sDAI for FutarchyRouter
11. Merge sDAI tokens
```

### 2. Optimization Strategies

#### Option A: Pre-set Infinite Approvals (Recommended)
- Pre-approve tokens with MAX_UINT256 in separate transaction
- Reduces bundle to 5 core operations:
  1. Swap on Balancer
  2. Split Company
  3. Swap YES on Swapr
  4. Swap NO on Swapr  
  5. Merge sDAI
- Similar to how buy_cond handles Company token approvals

#### Option B: Skip Approval Redundancy
- Combine YES/NO sDAI approvals into single MAX approval
- Use conservative merge amount to fit within 10 ops
- Bundle becomes:
  1. Approve sDAI for Balancer
  2. Swap sDAI → Company
  3. Approve Company for split
  4. Split Company
  5. Approve YES Company
  6. Swap YES Company
  7. Approve NO Company
  8. Swap NO Company
  9. Approve both conditional sDAI (single MAX approval)
  10. Merge sDAI

#### Option C: Skip Final Merge
- Execute swaps but don't merge conditional sDAI
- User can merge manually later
- Reduces to 8 operations (fits easily)

### 3. Implementation Details

#### Core Functions to Implement:

```python
def build_balancer_buy_company_call(
    amount_sdai: int,
    min_company_out: int,
    recipient: str
) -> Dict[str, Any]:
    """
    Build Balancer swap call for buying Company with sDAI.
    Uses swapExactIn with two-hop path through buffer pool.
    """
    
def build_sell_conditional_bundle(
    amount_sdai: Decimal,
    skip_merge: bool = False,
    use_existing_approvals: bool = False
) -> List[Dict[str, Any]]:
    """
    Build bundled transaction for sell conditional flow.
    
    Operations:
    1. Buy Company with sDAI on Balancer
    2. Split Company into conditional tokens
    3. Swap conditional Company to conditional sDAI
    4. (Optional) Merge conditional sDAI
    """
    
def sell_conditional_simple(
    amount_sdai: Decimal,
    skip_merge: bool = False
) -> Dict[str, Any]:
    """
    Execute sell conditional flow using proven EIP-7702.
    Simple mode without complex simulation.
    """
    
def check_and_set_approvals() -> Dict[str, bool]:
    """
    Check current approvals and return status.
    Can be used to determine if pre-approvals needed.
    """
```

#### Encoding Compatibility:
- Reuse `build_working_swapr_call()` from buy_cond_eip7702
- Import `swapr_router` for encode_abi() calls
- Use proven patterns from successful buy implementation
- Copy successful encoding patterns

#### Balancer Integration:
Based on sell_cond_onchain.py, the Balancer swap uses:
- Two-hop path: sDAI → buffer pool → Company
- swapExactIn function
- Buffer pool at 0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644
- Final pool at 0xd1d7fa8871d84d0e77020fc28b7cd5718c446522

### 4. File Structure

```python
# src/arbitrage_commands/sell_cond_eip7702.py

import os
import sys
import time
from typing import Dict, List, Any
from decimal import Decimal
from web3 import Web3
from eth_account import Account

from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.swapr_swap import router as swapr_router
from src.helpers.bundle_helpers import (
    encode_approval_call,
    encode_split_position_call,
    encode_merge_positions_call,
    calculate_bundle_gas_params,
    get_token_balance
)

# Constants from environment
IMPLEMENTATION_ADDRESS = "0x65eb5a03635c627a0f254707712812B234753F31"

# Balancer specific constants
BUFFER_POOL = "0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644"
FINAL_POOL = "0xd1d7fa8871d84d0e77020fc28b7cd5718c446522"
MAX_DEADLINE = 9007199254740991

def build_working_swapr_call(...):
    # Copy from buy_cond_eip7702.py
    
def build_balancer_buy_company_call(...):
    # New implementation for Balancer swap
    
def build_sell_conditional_bundle(...):
    # Main bundle builder
    
def sell_conditional_simple(...):
    # Simple execution function
    
def main():
    # CLI interface
```

### 5. Testing Strategy

#### Phase 1: Component Testing
```bash
# Test Balancer buy swap
python -m src.arbitrage_commands.sell_cond_eip7702 0.001 --test-balancer

# Test split operation
python -m src.arbitrage_commands.sell_cond_eip7702 0.001 --test-split

# Test Swapr swaps
python -m src.arbitrage_commands.sell_cond_eip7702 0.001 --test-swaps

# Test merge operation
python -m src.arbitrage_commands.sell_cond_eip7702 0.001 --test-merge
```

#### Phase 2: Bundle Testing
```bash
# Test without merge (8 operations)
python -m src.arbitrage_commands.sell_cond_eip7702 0.001 --skip-merge

# Test with optimized approvals (10 operations)
python -m src.arbitrage_commands.sell_cond_eip7702 0.001 --simple

# Test with pre-set approvals (5 operations)
python -m src.arbitrage_commands.sell_cond_eip7702 0.001 --use-approvals
```

### 6. Implementation Steps

1. **Copy base structure** from buy_cond_eip7702.py
2. **Implement Balancer encoding** using sell_cond_onchain pattern
3. **Build sell bundle** with proper operation ordering
4. **Handle 10-call limit** with optimization strategies
5. **Test each component** individually
6. **Test complete bundle** on Gnosis Chain
7. **Add CLI options** for different modes
8. **Document usage** and limitations

### 7. Expected Challenges & Solutions

#### Challenge: 11 operations exceed limit
**Solution**: 
- Combine conditional sDAI approvals
- Offer --skip-merge option
- Implement pre-approval system

#### Challenge: Balancer encoding complexity
**Solution**:
- Use exact encoding from sell_cond_onchain.py
- Test Balancer swap separately first
- Verify with eth_call simulation

#### Challenge: Amount calculations
**Solution**:
- Use conservative estimates (95% efficiency)
- Let Swapr swaps use exact-in mode
- Merge uses minimum of YES/NO outputs

### 8. Success Criteria
- [x] Compatible with existing infrastructure
- [x] Uses proven encoding methods
- [ ] Executes 10 operations atomically
- [ ] Handles Balancer two-hop swap
- [ ] Gas usage < 2M
- [ ] Clear CLI interface
- [ ] Successful on-chain execution

### 9. Timeline
- Base implementation: 1-2 hours
- Balancer integration: 1 hour
- Testing & debugging: 1-2 hours
- Documentation: 30 minutes
- **Total: 3-5 hours**

### 10. Example Usage

```bash
# Simple mode (10 operations)
python -m src.arbitrage_commands.sell_cond_eip7702 0.01 --simple

# Skip merge to reduce operations (8 ops)
python -m src.arbitrage_commands.sell_cond_eip7702 0.01 --skip-merge

# With pre-set approvals (5 ops only)
python -m src.arbitrage_commands.sell_cond_eip7702 0.01 --use-approvals

# Test individual components
python -m src.arbitrage_commands.sell_cond_eip7702 0.001 --test-balancer
```

## Next Steps After Implementation
1. Test with various amounts
2. Optimize gas usage
3. Add to pectra_bot.py
4. Create comprehensive test suite
5. Performance benchmarking against sequential execution
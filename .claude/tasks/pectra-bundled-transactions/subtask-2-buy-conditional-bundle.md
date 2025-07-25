# Subtask 2: Buy Conditional Flow Bundle Implementation

## Overview
This subtask implements the bundled transaction logic for the buy conditional flow, transforming the current sequential transaction approach into a single atomic EIP-7702 bundle. This includes building the transaction bundle, calculating dynamic parameters, and handling the complex state transitions.

## Objectives
1. Implement `build_buy_conditional_bundle` function with all 10 operations
2. Create dynamic amount calculation for intermediate steps
3. Develop state tracking for bundle simulation
4. Optimize gas usage across bundled operations
5. Ensure atomicity and MEV resistance

## Technical Requirements

### Bundle Composition
The buy conditional flow requires bundling these operations:
1. sDAI approval to FutarchyRouter
2. Split sDAI into YES/NO conditional sDAI
3. YES conditional sDAI approval to Swapr
4. Swap YES conditional sDAI to YES Company token
5. NO conditional sDAI approval to Swapr
6. Swap NO conditional sDAI to NO Company token
7. Company token approvals to FutarchyRouter
8. Merge YES/NO Company tokens to Company token
9. Company token approval to Balancer
10. Swap Company token to sDAI on Balancer

### Dynamic Calculations
- Split amounts must equal input sDAI amount
- Swap amounts depend on pool liquidity and slippage
- Merge amounts must be balanced (min of YES/NO received)
- Final swap amount depends on merged Company tokens

## Implementation Steps

### 1. Bundle Builder Function (Day 1-2)
```python
# src/arbitrage_commands/pectra_bot.py
def build_buy_conditional_bundle(
    builder: EIP7702TransactionBuilder,
    addresses: Dict[str, str],
    amount_sdai: Decimal,
    prices: Dict[str, Decimal],
    slippage: Decimal = Decimal("0.01")
) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Build bundled transaction for buy conditional flow.
    
    Returns:
        - List of transaction dictionaries for the bundle
        - Metadata dict with expected outputs and gas estimates
    """
    bundle = []
    metadata = {
        "expected_outputs": {},
        "gas_estimates": {},
        "intermediate_amounts": {}
    }
    
    # 1. Approve sDAI to FutarchyRouter
    approve_amount = amount_sdai * (1 + slippage)  # Buffer for safety
    bundle.append(build_approval_tx(
        token=addresses["SDAI_TOKEN"],
        spender=addresses["FUTARCHY_ROUTER"],
        amount=approve_amount
    ))
    
    # 2. Split sDAI into conditional tokens
    split_tx, split_output = build_split_tx(
        router=addresses["FUTARCHY_ROUTER"],
        token=addresses["SDAI_TOKEN"],
        amount=amount_sdai
    )
    bundle.append(split_tx)
    metadata["intermediate_amounts"]["split_yes"] = amount_sdai
    metadata["intermediate_amounts"]["split_no"] = amount_sdai
    
    # Continue building remaining operations...
```

### 2. Dynamic Amount Calculation (Day 2-3)
```python
# src/helpers/bundle_calculations.py
class BundleCalculator:
    def calculate_swap_amounts(
        self,
        pool_address: str,
        token_in: str,
        token_out: str,
        amount_in: Decimal,
        reserves: Tuple[int, int]
    ) -> Dict[str, Decimal]:
        """Calculate expected swap outputs with slippage"""
        # 1. Get current pool state
        # 2. Calculate expected output
        # 3. Apply slippage tolerance
        # 4. Return min acceptable amount
        
    def calculate_merge_amounts(
        self,
        yes_amount: Decimal,
        no_amount: Decimal
    ) -> Tuple[Decimal, Decimal, Decimal]:
        """Calculate merge amounts and remainders"""
        merge_amount = min(yes_amount, no_amount)
        yes_remainder = yes_amount - merge_amount
        no_remainder = no_amount - merge_amount
        return merge_amount, yes_remainder, no_remainder
```

### 3. State Tracking System (Day 3-4)
```python
# src/helpers/bundle_state_tracker.py
class BundleStateTracker:
    def __init__(self):
        self.token_balances = {}
        self.approvals = {}
        self.pool_states = {}
    
    def apply_operation(self, operation: Dict) -> Dict:
        """Apply operation to tracked state and return changes"""
        if operation["type"] == "approval":
            return self._apply_approval(operation)
        elif operation["type"] == "split":
            return self._apply_split(operation)
        elif operation["type"] == "swap":
            return self._apply_swap(operation)
        elif operation["type"] == "merge":
            return self._apply_merge(operation)
    
    def validate_final_state(self) -> bool:
        """Ensure bundle achieves desired outcome"""
        # Check final sDAI > initial sDAI (profitable)
        # Verify all intermediate balances cleared
        # Validate no hanging approvals
```

### 4. Gas Optimization (Day 4)
```python
# src/helpers/gas_optimizer.py
class BundleGasOptimizer:
    def optimize_approval_amounts(self, operations: List[Dict]) -> List[Dict]:
        """Optimize approval amounts to avoid redundant approvals"""
        # 1. Track cumulative token usage
        # 2. Set approvals to exact amounts needed
        # 3. Reuse existing approvals where possible
        
    def optimize_operation_order(self, operations: List[Dict]) -> List[Dict]:
        """Reorder operations for optimal gas usage"""
        # 1. Group similar operations (all approvals first)
        # 2. Minimize storage slot changes
        # 3. Batch reads where possible
```

### 5. Bundle Execution Handler (Day 5)
```python
# src/arbitrage_commands/pectra_bot.py
def execute_buy_conditional_bundle(
    w3: Web3,
    account: Account,
    bundle: List[Dict],
    metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute the buy conditional bundle atomically"""
    try:
        # 1. Build EIP-7702 transaction
        tx = builder.build_transaction(
            implementation=IMPLEMENTATION_ADDRESS,
            calls=bundle,
            sender=account.address
        )
        
        # 2. Simulate to verify profitability
        simulation = simulate_bundle(w3, account, tx)
        if not is_profitable(simulation, metadata):
            return {"status": "skipped", "reason": "unprofitable"}
        
        # 3. Sign with authorization
        signed_tx = account.sign_transaction(tx)
        
        # 4. Send and wait for receipt
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        # 5. Parse results and return
        return parse_bundle_receipt(receipt, metadata)
        
    except Exception as e:
        logger.error(f"Bundle execution failed: {e}")
        return {"status": "failed", "error": str(e)}
```

## Testing Approach

### Unit Tests
```python
# tests/test_buy_bundle.py
def test_build_buy_bundle():
    """Test bundle construction with various amounts"""
    
def test_dynamic_calculations():
    """Test amount calculations through the flow"""
    
def test_state_tracking():
    """Verify state changes match expectations"""
    
def test_gas_optimization():
    """Ensure gas optimizations work correctly"""
```

### Integration Tests
1. **Fork Testing**: Test against forked mainnet state
2. **Simulation Testing**: Verify Tenderly simulations match execution
3. **End-to-End Testing**: Complete buy flow on testnet
4. **Stress Testing**: Large amounts and edge cases

### Bundle Validation Tests
```python
def test_bundle_atomicity():
    """Ensure partial execution is impossible"""
    
def test_bundle_determinism():
    """Verify same inputs produce same outputs"""
    
def test_mev_resistance():
    """Confirm no extractable value between operations"""
```

## Success Criteria

### Functional Requirements
- [ ] All 10 operations bundled successfully
- [ ] Dynamic calculations accurate within 0.1%
- [ ] State tracking matches on-chain results
- [ ] Bundle executes atomically

### Performance Requirements
- [ ] Gas savings > 15% vs sequential approach
- [ ] Bundle construction < 100ms
- [ ] Simulation time < 500ms
- [ ] Total execution time < 5 seconds

### Reliability Requirements
- [ ] 99% success rate for profitable opportunities
- [ ] Proper handling of all failure modes
- [ ] Accurate profitability predictions
- [ ] No funds lost due to calculation errors

## Risk Mitigation

### Technical Risks
1. **Calculation Errors**
   - Mitigation: Extensive unit testing of calculations
   - Cross-validation with different methods
   - Conservative slippage buffers

2. **State Synchronization**
   - Mitigation: Fresh state queries before bundle construction
   - Timestamp validation for stale data
   - Retry logic for transient failures

3. **Gas Estimation Failures**
   - Mitigation: Historical gas usage tracking
   - Dynamic gas buffer adjustment
   - Fallback to sequential execution

### Operational Risks
1. **Pool Liquidity Changes**
   - Mitigation: Slippage tolerance parameters
   - Real-time liquidity monitoring
   - Adaptive amount sizing

2. **Network Congestion**
   - Mitigation: Priority fee management
   - Bundle size optimization
   - Off-peak execution strategies

## Dependencies
- Working FutarchyBatchExecutor contract (Subtask 1)
- EIP7702TransactionBuilder functionality
- Pool state reading capabilities
- Gas estimation infrastructure

## Deliverables
1. Complete `build_buy_conditional_bundle` implementation
2. Dynamic calculation utilities
3. State tracking system
4. Gas optimization framework
5. Comprehensive test suite
6. Performance benchmarks documentation
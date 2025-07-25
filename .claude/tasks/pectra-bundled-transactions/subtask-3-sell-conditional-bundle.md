# Subtask 3: Sell Conditional Flow Bundle Implementation

## Overview
This subtask implements the bundled transaction logic for the sell conditional flow, which reverses the buy flow by starting with sDAI on Balancer and ending with sDAI through conditional token operations. This flow requires careful coordination of amounts and handling of potential imbalances.

## Objectives
1. Implement `build_sell_conditional_bundle` function with all 10 operations
2. Handle conditional token imbalances and liquidation strategies
3. Optimize for maximum sDAI output considering all paths
4. Ensure MEV resistance in the reverse flow
5. Implement comprehensive error recovery

## Technical Requirements

### Bundle Composition
The sell conditional flow requires bundling these operations:
1. sDAI approval to Balancer
2. Swap sDAI to Company token on Balancer
3. Company token approval to FutarchyRouter
4. Split Company token into YES/NO conditional Company
5. YES Company approval to Swapr
6. Swap YES Company to YES conditional sDAI
7. NO Company approval to Swapr
8. Swap NO Company to NO conditional sDAI
9. Conditional sDAI approvals to FutarchyRouter
10. Merge YES/NO conditional sDAI to sDAI

### Imbalance Handling
- YES/NO swap outputs may differ due to price disparities
- Excess conditional tokens need liquidation
- Liquidation path optimization for maximum recovery

## Implementation Steps

### 1. Bundle Builder Function (Day 1-2)
```python
# src/arbitrage_commands/pectra_bot.py
def build_sell_conditional_bundle(
    builder: EIP7702TransactionBuilder,
    addresses: Dict[str, str],
    amount_sdai: Decimal,
    prices: Dict[str, Decimal],
    slippage: Decimal = Decimal("0.01")
) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Build bundled transaction for sell conditional flow.
    
    Key differences from buy flow:
    - Starts with Balancer swap
    - Must handle conditional token imbalances
    - Includes liquidation operations
    """
    bundle = []
    metadata = {
        "expected_outputs": {},
        "gas_estimates": {},
        "intermediate_amounts": {},
        "liquidation_strategy": None
    }
    
    # 1. Calculate expected Company tokens from Balancer
    expected_company = calculate_balancer_output(
        pool=addresses["BALANCER_POOL"],
        amount_in=amount_sdai,
        token_in=addresses["SDAI_TOKEN"],
        token_out=addresses["COMPANY_TOKEN"]
    )
    
    # 2-4. Balancer swap and split operations
    bundle.extend(build_balancer_and_split_ops(
        addresses, amount_sdai, expected_company
    ))
    
    # 5-8. Conditional swaps with imbalance prediction
    swap_ops, imbalance_data = build_conditional_swap_ops(
        addresses, expected_company, prices
    )
    bundle.extend(swap_ops)
    
    # 9-10. Merge and liquidation operations
    merge_ops = build_merge_and_liquidation_ops(
        addresses, imbalance_data
    )
    bundle.extend(merge_ops)
    
    return bundle, metadata
```

### 2. Imbalance Detection and Strategy (Day 2-3)
```python
# src/helpers/imbalance_handler.py
class ConditionalImbalanceHandler:
    def predict_imbalance(
        self,
        yes_price: Decimal,
        no_price: Decimal,
        amount: Decimal
    ) -> Dict[str, Any]:
        """Predict post-swap imbalances based on prices"""
        # Higher priced token will yield less conditional sDAI
        yes_output = self.calculate_swap_output("YES", amount, yes_price)
        no_output = self.calculate_swap_output("NO", amount, no_price)
        
        imbalance = abs(yes_output - no_output)
        excess_token = "YES" if yes_output > no_output else "NO"
        
        return {
            "yes_output": yes_output,
            "no_output": no_output,
            "imbalance_amount": imbalance,
            "excess_token": excess_token,
            "merge_amount": min(yes_output, no_output)
        }
    
    def build_liquidation_strategy(
        self,
        imbalance_data: Dict,
        prices: Dict[str, Decimal]
    ) -> List[Dict]:
        """Build optimal liquidation path for excess tokens"""
        if imbalance_data["excess_token"] == "YES":
            # Direct swap YES conditional sDAI -> sDAI
            return self._build_direct_liquidation(
                token=addresses["SWAPR_SDAI_YES"],
                amount=imbalance_data["imbalance_amount"]
            )
        else:
            # Complex path: Buy YES with sDAI, then merge
            return self._build_indirect_liquidation(
                imbalance_data["imbalance_amount"],
                prices
            )
```

### 3. Liquidation Path Optimization (Day 3-4)
```python
# src/helpers/liquidation_optimizer.py
class LiquidationOptimizer:
    def optimize_liquidation_path(
        self,
        excess_token: str,
        amount: Decimal,
        pool_states: Dict
    ) -> Dict[str, Any]:
        """Find optimal path to convert excess conditional tokens"""
        
        paths = []
        
        # Path 1: Direct swap to sDAI if available
        if self.has_direct_liquidity(excess_token, "sDAI"):
            paths.append(self.calculate_direct_path(excess_token, amount))
        
        # Path 2: Buy complementary token and merge
        complement = "NO" if excess_token == "YES" else "YES"
        paths.append(self.calculate_complement_path(
            excess_token, complement, amount
        ))
        
        # Path 3: Multi-hop through liquid pairs
        paths.extend(self.find_multihop_paths(excess_token, amount))
        
        # Return path with maximum sDAI output
        return max(paths, key=lambda p: p["output_amount"])
    
    def build_liquidation_operations(
        self,
        optimal_path: Dict
    ) -> List[Dict]:
        """Convert optimal path to transaction operations"""
        operations = []
        
        for step in optimal_path["steps"]:
            # Add approval if needed
            if step["requires_approval"]:
                operations.append(build_approval_tx(
                    token=step["token_in"],
                    spender=step["target"],
                    amount=step["amount"]
                ))
            
            # Add swap operation
            operations.append(build_swap_tx(
                target=step["target"],
                token_in=step["token_in"],
                token_out=step["token_out"],
                amount_in=step["amount"],
                min_out=step["min_output"]
            ))
        
        return operations
```

### 4. Advanced Bundle Construction (Day 4)
```python
# src/arbitrage_commands/pectra_bot.py
def build_conditional_swap_ops(
    addresses: Dict,
    company_amount: Decimal,
    prices: Dict
) -> Tuple[List[Dict], Dict]:
    """Build swap operations with imbalance handling"""
    
    operations = []
    
    # Calculate expected outputs for both swaps
    imbalance_handler = ConditionalImbalanceHandler()
    imbalance_data = imbalance_handler.predict_imbalance(
        prices["yes_price"],
        prices["no_price"],
        company_amount
    )
    
    # Build YES swap
    operations.extend([
        build_approval_tx(
            addresses["SWAPR_GNO_YES"],
            addresses["SWAPR_POOL_YES"],
            company_amount
        ),
        build_swap_tx(
            pool=addresses["SWAPR_POOL_YES"],
            token_in=addresses["SWAPR_GNO_YES"],
            token_out=addresses["SWAPR_SDAI_YES"],
            amount=company_amount,
            min_out=imbalance_data["yes_output"] * 0.99
        )
    ])
    
    # Build NO swap
    operations.extend([
        build_approval_tx(
            addresses["SWAPR_GNO_NO"],
            addresses["SWAPR_POOL_NO"],
            company_amount
        ),
        build_swap_tx(
            pool=addresses["SWAPR_POOL_NO"],
            token_in=addresses["SWAPR_GNO_NO"],
            token_out=addresses["SWAPR_SDAI_NO"],
            amount=company_amount,
            min_out=imbalance_data["no_output"] * 0.99
        )
    ])
    
    return operations, imbalance_data
```

### 5. Error Recovery and Fallbacks (Day 5)
```python
# src/helpers/bundle_recovery.py
class BundleRecoveryHandler:
    def add_recovery_operations(
        self,
        bundle: List[Dict],
        critical_points: List[int]
    ) -> List[Dict]:
        """Add conditional recovery operations at critical points"""
        
        enhanced_bundle = []
        
        for i, operation in enumerate(bundle):
            enhanced_bundle.append(operation)
            
            if i in critical_points:
                # Add balance check
                enhanced_bundle.append(
                    self.build_balance_check(operation)
                )
                
                # Add conditional revert if needed
                enhanced_bundle.append(
                    self.build_conditional_revert(operation)
                )
        
        return enhanced_bundle
    
    def build_fallback_bundle(
        self,
        original_bundle: List[Dict],
        failure_point: int
    ) -> List[Dict]:
        """Build recovery bundle from partial execution"""
        
        # Analyze state at failure point
        partial_state = self.analyze_partial_state(
            original_bundle[:failure_point]
        )
        
        # Build operations to recover funds
        recovery_ops = []
        
        # Recover trapped tokens
        for token, amount in partial_state["trapped_tokens"].items():
            recovery_ops.extend(
                self.build_token_recovery(token, amount)
            )
        
        return recovery_ops
```

## Testing Approach

### Unit Tests
```python
# tests/test_sell_bundle.py
def test_imbalance_prediction():
    """Test accurate prediction of swap imbalances"""
    
def test_liquidation_strategies():
    """Test all liquidation path calculations"""
    
def test_bundle_construction():
    """Test complete sell bundle generation"""
    
def test_error_recovery():
    """Test recovery from partial executions"""
```

### Integration Tests
1. **Imbalance Scenarios**: Test with various price disparities
2. **Liquidation Paths**: Verify optimal path selection
3. **Full Cycle Testing**: Complete sell flow with liquidation
4. **Failure Recovery**: Test partial execution recovery

### Edge Case Testing
```python
def test_extreme_imbalances():
    """Test with 50%+ price disparities"""
    
def test_zero_liquidity_paths():
    """Test when direct liquidation unavailable"""
    
def test_multi_hop_liquidation():
    """Test complex liquidation paths"""
```

## Success Criteria

### Functional Requirements
- [ ] All 10+ operations (including liquidation) bundled
- [ ] Imbalance predictions within 1% accuracy
- [ ] Optimal liquidation path selection
- [ ] Complete fund recovery on any failure

### Performance Requirements
- [ ] Gas usage < 1.2x buy flow (due to liquidation)
- [ ] Bundle construction < 150ms
- [ ] Path optimization < 50ms
- [ ] 95% value recovery on liquidations

### Reliability Requirements
- [ ] Handle all imbalance scenarios
- [ ] No trapped funds in any failure mode
- [ ] Accurate profitability calculations
- [ ] Robust against price movements

## Risk Mitigation

### Technical Risks
1. **Imbalance Miscalculation**
   - Mitigation: Conservative estimates with buffers
   - Real-time validation before execution
   - Multiple calculation methods

2. **Liquidation Failures**
   - Mitigation: Multiple path options
   - Fallback to manual recovery
   - Partial liquidation strategies

3. **Complex State Management**
   - Mitigation: Comprehensive state tracking
   - Checkpoint-based recovery
   - Atomic sub-bundles

### Market Risks
1. **Price Movement During Execution**
   - Mitigation: Tight slippage controls
   - Fast execution paths
   - Dynamic recalculation

2. **Liquidity Exhaustion**
   - Mitigation: Pre-execution liquidity checks
   - Adaptive amount sizing
   - Multiple pool routing

## Dependencies
- Working buy conditional bundle (Subtask 2)
- Liquidation path infrastructure
- Advanced state tracking system
- Price feed reliability

## Deliverables
1. Complete `build_sell_conditional_bundle` implementation
2. Imbalance prediction and handling system
3. Liquidation path optimizer
4. Recovery mechanism framework
5. Comprehensive test coverage
6. Performance comparison documentation
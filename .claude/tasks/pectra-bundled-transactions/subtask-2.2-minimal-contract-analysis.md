# Analysis: Adapting Pectra Buy Conditional Flow for FutarchyBatchExecutorMinimal

## Executive Summary

The deployed FutarchyBatchExecutorMinimal contract (0x65eb5a03635c627a0f254707712812B234753F31) uses a fundamentally different interface than the original FutarchyBatchExecutor. This analysis details the required changes to make the buy conditional flow work with the new minimal contract.

## Key Interface Differences

### Original FutarchyBatchExecutor
```solidity
// Dynamic arrays approach
function execute(Call[] calldata calls) external payable
function executeWithResults(Call[] calldata calls) external payable returns (bytes[] memory results)

struct Call {
    address target;
    uint256 value;
    bytes data;
}
```

### New FutarchyBatchExecutorMinimal
```solidity
// Fixed-size arrays approach (max 10 calls)
function execute10(
    address[10] calldata targets,
    bytes[10] calldata calldatas,
    uint256 count
) external payable

// Single call execution
function executeOne(
    address target,
    bytes calldata data
) external payable returns (bytes memory)
```

## Required Changes

### 1. EIP7702TransactionBuilder Updates

The builder needs to construct calls for `execute10` instead of `execute`:

**Current approach:**
```python
# Build Call structs array
function_selector = keccak(text="execute((address,uint256,bytes)[])")[:4]
calls_data = [(call['target'], call['value'], call['data']) for call in self.calls]
encoded_calls = encode(['(address,uint256,bytes)[]'], [calls_data])
```

**New approach:**
```python
# Build fixed-size arrays for execute10
function_selector = keccak(text="execute10(address[10],bytes[10],uint256)")[:4]

# Pad arrays to size 10
targets = [call['target'] for call in self.calls[:10]]
targets += [ZERO_ADDRESS] * (10 - len(targets))

calldatas = [call['data'] for call in self.calls[:10]]
calldatas += [b''] * (10 - len(calldatas))

count = min(len(self.calls), 10)
encoded_params = encode(['address[10]', 'bytes[10]', 'uint256'], [targets, calldatas, count])
```

### 2. Value Handling Issue

**Critical Problem:** The minimal contract's `execute10` doesn't support per-call value transfers. The original implementation had `uint256 value` per call, but the minimal version only has:
- `execute10`: No value parameter per call
- `executeOne`: Supports `msg.value` but only for single calls

**Impact:** Any calls requiring ETH value (unlikely in our arbitrage flow) would need special handling.

**Solution:** Verify that none of our arbitrage operations require ETH value transfers. If they do, we'd need to:
1. Use `executeOne` for value-bearing calls
2. Or deploy a new minimal contract with value support

### 3. Result Tracking Loss

**Problem:** No `executeWithResults` equivalent in the minimal contract. The `execute10` function doesn't return any data.

**Impact:** Cannot extract intermediate swap amounts needed for the 3-step simulation approach:
1. Discovery simulation (find YES/NO outputs)
2. Balanced simulation (use min amount)
3. Final simulation with liquidation

**Solutions:**

#### Option A: State-Based Simulation (Recommended)
Use `eth_call` with state overrides to simulate the bundle execution and read token balances:

```python
def simulate_with_state_tracking(w3, account, bundle_calls):
    """Simulate bundle and track state changes via balance queries"""
    
    # Initial balances
    initial_balances = {
        'yes_company': get_token_balance(COMPANY_YES, account.address),
        'no_company': get_token_balance(COMPANY_NO, account.address),
        'sdai': get_token_balance(SDAI_TOKEN, account.address),
    }
    
    # Execute simulation with state overrides
    state_overrides = {
        account.address: {
            'code': w3.eth.get_code(IMPLEMENTATION_ADDRESS)
        }
    }
    
    # Build execute10 transaction
    tx_data = build_execute10_data(bundle_calls)
    
    # Simulate
    w3.eth.call({
        'from': account.address,
        'to': account.address,
        'data': tx_data
    }, 'latest', state_overrides)
    
    # Check final balances in the same call context
    final_balances = {
        'yes_company': get_token_balance(COMPANY_YES, account.address),
        'no_company': get_token_balance(COMPANY_NO, account.address),
        'sdai': get_token_balance(SDAI_TOKEN, account.address),
    }
    
    # Calculate outputs
    yes_output = final_balances['yes_company'] - initial_balances['yes_company']
    no_output = final_balances['no_company'] - initial_balances['no_company']
    
    return yes_output, no_output
```

#### Option B: Event Log Parsing
Parse Transfer events from the simulation to track token movements:

```python
def extract_outputs_from_logs(tx_receipt):
    """Extract swap outputs from transaction logs"""
    yes_output = 0
    no_output = 0
    
    for log in tx_receipt.logs:
        if log.topics[0] == TRANSFER_EVENT_TOPIC:
            # Decode Transfer(from, to, value)
            if log.address == COMPANY_YES:
                # Track YES token transfers
                if log.topics[2] == account.address:  # to us
                    yes_output += decode_uint256(log.data)
            elif log.address == COMPANY_NO:
                # Track NO token transfers
                if log.topics[2] == account.address:  # to us
                    no_output += decode_uint256(log.data)
    
    return yes_output, no_output
```

### 4. Bundle Size Limitations

**Constraint:** Maximum 10 calls per bundle.

**Current buy conditional flow needs:**
1. Approve sDAI → FutarchyRouter
2. Split sDAI → YES/NO
3. Approve YES sDAI → Swapr
4. Swap YES sDAI → YES Company
5. Approve NO sDAI → Swapr
6. Swap NO sDAI → NO Company
7. Approve YES Company → FutarchyRouter
8. Approve NO Company → FutarchyRouter
9. Merge YES/NO Company → Company
10. Approve Company → Balancer
11. Swap Company → sDAI on Balancer

**That's 11 calls!** Plus potential liquidation calls.

**Solutions:**

1. **Optimize Approvals:** Use infinite approvals set once outside the bundle
2. **Split Bundles:** Execute in two transactions (breaks atomicity)
3. **Bundle Optimization:** 
   - Pre-set infinite approvals for frequently used pairs
   - Combine operations where possible
   - Remove redundant approvals

### 5. Modified Bundle Construction

```python
def build_buy_conditional_bundle_minimal(
    amount_sdai: Decimal,
    simulation_results: Optional[Dict] = None,
    skip_approvals: bool = False
) -> List[Dict[str, Any]]:
    """Build bundle for FutarchyBatchExecutorMinimal (max 10 calls)"""
    
    calls = []
    amount_wei = w3.to_wei(amount_sdai, 'ether')
    
    # Check if we need approvals (can be pre-set)
    if not skip_approvals:
        # Critical approvals only
        calls.append(encode_approval_call(SDAI_TOKEN, FUTARCHY_ROUTER, amount_wei))
    
    # Core operations (must fit in remaining slots)
    calls.append(encode_split_position_call(
        FUTARCHY_ROUTER, FUTARCHY_PROPOSAL, SDAI_TOKEN, amount_wei
    ))
    
    # ... continue with swaps and merge ...
    
    # Ensure we don't exceed 10 calls
    if len(calls) > 10:
        raise ValueError(f"Bundle has {len(calls)} calls, max is 10")
    
    return calls
```

## Testing Strategy for Production

### 1. Pre-Production Verification

```python
def verify_pectra_setup():
    """Comprehensive pre-production checks"""
    
    # 1. Contract verification
    assert verify_no_ef_opcodes(IMPLEMENTATION_ADDRESS)
    assert get_code_size(IMPLEMENTATION_ADDRESS) > 0
    
    # 2. Approval status check
    approvals_needed = check_approval_status()
    if approvals_needed:
        print(f"Need to set {len(approvals_needed)} approvals")
        
    # 3. Simulate small test trade
    test_amount = Decimal("0.01")  # 0.01 sDAI
    test_result = simulate_buy_conditional(test_amount)
    
    # 4. Verify bundle construction
    bundle = build_buy_conditional_bundle_minimal(test_amount)
    assert len(bundle) <= 10, f"Bundle too large: {len(bundle)} calls"
    
    return True
```

### 2. Progressive Production Testing

```python
def production_test_sequence():
    """Gradual production testing approach"""
    
    # Phase 1: Tiny amounts with monitoring
    amounts = [0.01, 0.1, 1.0, 10.0]  # sDAI
    
    for amount in amounts:
        print(f"\n=== Testing with {amount} sDAI ===")
        
        # Dry run first
        sim_result = buy_conditional_bundled(amount, broadcast=False)
        print(f"Simulation: {sim_result}")
        
        if sim_result['sdai_net'] > 0:
            # Profitable - execute if in test mode
            if confirm_execution(amount, sim_result):
                live_result = buy_conditional_bundled(amount, broadcast=True)
                print(f"Execution: {live_result}")
                
                # Verify on-chain
                verify_execution(live_result['tx_hash'])
                
                # Wait before next test
                time.sleep(30)
```

### 3. Production Monitoring

```python
class PectraMonitor:
    """Monitor Pectra bundled transactions in production"""
    
    def __init__(self):
        self.metrics = {
            'bundles_sent': 0,
            'bundles_succeeded': 0,
            'bundles_failed': 0,
            'total_profit': Decimal('0'),
            'gas_saved': 0
        }
    
    def track_bundle(self, tx_hash, expected_profit):
        """Track bundle execution and results"""
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt.status == 1:
            self.metrics['bundles_succeeded'] += 1
            actual_profit = self.calculate_actual_profit(receipt)
            self.metrics['total_profit'] += actual_profit
            
            # Compare with sequential gas usage
            sequential_gas = self.estimate_sequential_gas()
            gas_saved = sequential_gas - receipt.gasUsed
            self.metrics['gas_saved'] += gas_saved
            
            print(f"✅ Bundle successful")
            print(f"   Expected profit: {expected_profit}")
            print(f"   Actual profit: {actual_profit}")
            print(f"   Gas saved: {gas_saved}")
        else:
            self.metrics['bundles_failed'] += 1
            print(f"❌ Bundle failed: {tx_hash}")
            self.analyze_failure(receipt)
```

### 4. Failure Recovery

```python
def execute_with_fallback(amount: Decimal, tolerance: Decimal):
    """Execute with fallback to sequential if bundle fails"""
    
    try:
        # Try bundled execution first
        result = buy_conditional_bundled(amount, broadcast=True)
        if result['status'] == 'success':
            return result
    except Exception as e:
        print(f"Bundle failed: {e}")
        
    # Fallback to sequential
    print("Falling back to sequential execution...")
    
    # Import original sequential implementation
    from src.arbitrage_commands.buy_cond import buy_conditional
    
    return buy_conditional(
        amount=amount,
        yes_scalar=1.0,  # Use discovered scalars
        no_scalar=1.0,
        tolerance=tolerance,
        send=True
    )
```

## Implementation Priority

### Phase 1: Core Functionality (Immediate)
1. Update `EIP7702TransactionBuilder.build_batch_call_data()` for `execute10`
2. Modify `buy_cond_eip7702.py` to handle fixed-size arrays
3. Implement state-based simulation approach
4. Add bundle size validation (≤10 calls)

### Phase 2: Optimization (Next)
1. Pre-approval management system
2. Bundle size optimization
3. Gas estimation improvements
4. Event log parsing for better tracking

### Phase 3: Production Readiness (Final)
1. Comprehensive test suite
2. Monitoring and alerting
3. Fallback mechanisms
4. Performance benchmarking

## Risk Assessment

### High Priority Risks
1. **Bundle Size Limit**: Buy conditional barely fits in 10 calls
   - Mitigation: Pre-set approvals, optimize call ordering
   
2. **No Return Data**: Cannot track intermediate amounts
   - Mitigation: State-based simulation with balance checks

3. **Value Transfer Limitation**: No ETH value support
   - Mitigation: Verify no value transfers needed

### Medium Priority Risks
1. **Simulation Accuracy**: State tracking may be less precise
   - Mitigation: Conservative slippage tolerances
   
2. **Gas Estimation**: Harder without specialized tools
   - Mitigation: Historical data + safety margins

### Low Priority Risks
1. **Contract Upgrades**: May need new features later
   - Mitigation: Modular design for easy swapping

## Conclusion

The FutarchyBatchExecutorMinimal contract can support the buy conditional flow with modifications:

1. **Required Changes**:
   - Update transaction builder for `execute10` interface
   - Implement state-based simulation
   - Optimize bundle to fit 10-call limit
   - Handle lack of return data

2. **Testing Approach**:
   - Comprehensive pre-production verification
   - Progressive amount scaling
   - Real-time monitoring
   - Fallback mechanisms

3. **Production Readiness**:
   - Can proceed with implementation
   - Start with small amounts
   - Monitor closely
   - Keep sequential fallback ready

The minimal contract's limitations are manageable for our use case, and the implementation can proceed with appropriate safeguards.
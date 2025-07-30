# Production Testing Plan for Pectra Bundled Transactions

## Overview

This document outlines a comprehensive testing strategy for deploying Pectra bundled transactions to production on Gnosis Chain. The plan emphasizes safety, gradual rollout, and continuous monitoring.

## Pre-Production Checklist

### 1. Infrastructure Verification
```bash
# Run comprehensive verification
python -m src.setup.pectra_verifier

# Expected output:
✅ Implementation contract deployed at: 0x65eb5a03635c627a0f254707712812B234753F31
✅ No 0xEF opcodes found in bytecode
✅ Contract size: 1379 bytes
✅ EIP-7702 transaction type supported
✅ All infrastructure ready
```

### 2. Approval Status Audit
```python
# Check all required approvals
python -m src.setup.check_approvals

# Pre-set infinite approvals for frequently used pairs:
- sDAI → FutarchyRouter
- YES/NO conditional sDAI → Swapr Router
- YES/NO Company tokens → FutarchyRouter
- Company token → Balancer Vault
```

### 3. Environment Configuration
```bash
# .env file must include:
export IMPLEMENTATION_ADDRESS=0x65eb5a03635c627a0f254707712812B234753F31
export FUTARCHY_BATCH_EXECUTOR_ADDRESS=0x65eb5a03635c627a0f254707712812B234753F31
export PECTRA_ENABLED=true
export PECTRA_TEST_MODE=true  # Enable test mode initially
```

## Testing Phases

### Phase 1: Isolated Component Testing (Day 1)

#### 1.1 Contract Interaction Test
```python
# Test basic execute10 functionality
python -m tests.test_minimal_executor

# Tests:
- Single call execution
- Multi-call execution (2-3 calls)
- Max capacity test (10 calls)
- Error handling (>10 calls)
```

#### 1.2 Bundle Construction Test
```python
# Test bundle building without execution
python -m tests.test_bundle_construction

# Verify:
- Correct encoding for execute10
- Proper array padding
- Call count validation
- Gas parameter calculation
```

#### 1.3 Simulation Accuracy Test
```python
# Compare simulation vs actual execution
python -m tests.test_simulation_accuracy --amount 0.01

# Metrics to track:
- Predicted vs actual swap outputs
- Gas estimation accuracy
- Profit calculation accuracy
- State tracking reliability
```

### Phase 2: Testnet Mirror Testing (Day 2-3)

#### 2.1 Fork Testing
```python
# Run against forked mainnet state
python -m src.testing.fork_test --fork-url $RPC_URL

# Test scenarios:
1. Normal market conditions
2. High volatility
3. Low liquidity
4. Large trades
```

#### 2.2 End-to-End Flow Test
```python
# Full arbitrage cycle with small amounts
python -m src.arbitrage_commands.buy_cond_eip7702 0.01 --test-mode

# Verify each step:
1. Price discovery works
2. Bundle construction succeeds
3. Simulation returns valid results
4. Execution (if profitable) succeeds
```

### Phase 3: Production Canary Testing (Day 4-7)

#### 3.1 Micro Trades
```python
# Start with dust amounts
AMOUNTS = [0.001, 0.005, 0.01, 0.05, 0.1]  # sDAI

for amount in AMOUNTS:
    python -m src.arbitrage_commands.pectra_bot \
        --amount $amount \
        --interval 300 \
        --tolerance 0.001 \
        --use-bundle \
        --canary-mode
```

#### 3.2 Monitoring Setup
```python
# Real-time monitoring dashboard
python -m src.monitoring.pectra_monitor

# Track:
- Bundle success rate
- Gas usage vs sequential
- Profit margins
- Error frequency
- Revert reasons
```

#### 3.3 A/B Testing
```python
# Run parallel sequential and bundled strategies
python -m src.testing.ab_test \
    --sequential-amount 1.0 \
    --bundled-amount 1.0 \
    --duration 3600  # 1 hour

# Compare:
- Profitability
- Success rate  
- Gas efficiency
- Execution speed
```

### Phase 4: Gradual Production Rollout (Week 2)

#### 4.1 Progressive Amount Increase
```python
# Gradually increase trade sizes
DAY_1_AMOUNT = 1.0    # $1
DAY_2_AMOUNT = 10.0   # $10
DAY_3_AMOUNT = 100.0  # $100
DAY_4_AMOUNT = 1000.0 # $1000

# With safety checks
if daily_profit > 0 and error_rate < 0.05:
    increase_amount()
else:
    maintain_or_reduce_amount()
```

#### 4.2 Feature Flags
```python
# Progressive feature enablement
FEATURE_FLAGS = {
    'bundle_enabled': True,
    'max_bundle_amount': 100.0,
    'fallback_enabled': True,
    'aggressive_mode': False,
    'liquidation_enabled': False  # Enable after core flow stable
}
```

## Production Monitoring

### 1. Real-Time Metrics
```python
# Metrics collection
class PectraMetrics:
    def __init__(self):
        self.prometheus_client = PrometheusClient()
        
    def track_bundle(self, result):
        self.prometheus_client.increment('pectra_bundles_total')
        
        if result['status'] == 'success':
            self.prometheus_client.increment('pectra_bundles_success')
            self.prometheus_client.observe('pectra_profit_sdai', result['profit'])
            self.prometheus_client.observe('pectra_gas_used', result['gas_used'])
        else:
            self.prometheus_client.increment('pectra_bundles_failed')
            self.prometheus_client.increment(f'pectra_error_{result["error_type"]}')
```

### 2. Alerting Rules
```yaml
# Prometheus alerting rules
groups:
  - name: pectra_alerts
    rules:
      - alert: HighBundleFailureRate
        expr: rate(pectra_bundles_failed[5m]) > 0.1
        annotations:
          summary: "Bundle failure rate >10% in last 5 minutes"
          
      - alert: NegativeProfit
        expr: sum(pectra_profit_sdai[1h]) < 0
        annotations:
          summary: "Negative profit in last hour"
          
      - alert: GasSpikePectra
        expr: pectra_gas_used > 3000000
        annotations:
          summary: "Bundle gas usage exceeds 3M"
```

### 3. Automated Response
```python
# Circuit breaker implementation
class PectraCircuitBreaker:
    def __init__(self):
        self.failure_count = 0
        self.success_count = 0
        self.is_open = False
        
    def record_result(self, success: bool):
        if success:
            self.success_count += 1
            self.failure_count = 0
        else:
            self.failure_count += 1
            
        # Open circuit if 3 consecutive failures
        if self.failure_count >= 3:
            self.is_open = True
            notify_operators("Pectra circuit breaker opened")
            
        # Close circuit after 10 consecutive successes
        if self.success_count >= 10 and self.is_open:
            self.is_open = False
            notify_operators("Pectra circuit breaker closed")
```

## Rollback Plan

### 1. Immediate Rollback Triggers
- Bundle failure rate > 20%
- Any fund loss incident
- Gas costs exceed 2x sequential
- Unexpected contract behavior

### 2. Rollback Procedure
```bash
# 1. Disable Pectra mode immediately
export PECTRA_ENABLED=false

# 2. Switch to sequential execution
python -m src.arbitrage_commands.simple_bot \
    --amount $SAFE_AMOUNT \
    --interval 120 \
    --tolerance 0.05

# 3. Investigate issues
python -m src.diagnostics.analyze_pectra_failures

# 4. Document lessons learned
```

## Success Criteria

### Week 1 Goals
- [ ] 95%+ bundle success rate
- [ ] 15%+ gas savings vs sequential
- [ ] Zero fund loss incidents
- [ ] <5% error rate

### Week 2 Goals
- [ ] Handle 50% of arbitrage volume via bundles
- [ ] Maintain profitability metrics
- [ ] Successfully execute complex bundles (with liquidation)
- [ ] Stable operation at $1000+ trade sizes

### Month 1 Goals
- [ ] 100% migration to bundled transactions
- [ ] 20%+ improvement in overall profitability
- [ ] Reduced MEV exposure
- [ ] Operational confidence for large trades

## Risk Mitigation

### 1. Technical Risks
- **Contract bugs**: Extensive testing + small initial amounts
- **Gas estimation errors**: Conservative buffers + monitoring
- **State sync issues**: Fresh state queries + retry logic

### 2. Market Risks
- **Price volatility**: Tighter slippage tolerances initially
- **Liquidity crunches**: Dynamic amount sizing
- **MEV competition**: Monitor for frontrunning

### 3. Operational Risks
- **Monitoring blind spots**: Comprehensive logging
- **Alert fatigue**: Tuned thresholds
- **Operator errors**: Automated safeguards

## Testing Commands Reference

```bash
# Pre-production verification
python -m src.setup.pectra_verifier

# Simulation test
python -m src.arbitrage_commands.buy_cond_eip7702 0.01

# Live test with small amount
python -m src.arbitrage_commands.buy_cond_eip7702 0.01 --send

# Canary mode bot
python -m src.arbitrage_commands.pectra_bot \
    --amount 0.1 \
    --interval 300 \
    --tolerance 0.001 \
    --use-bundle \
    --canary-mode

# Production bot
python -m src.arbitrage_commands.pectra_bot \
    --amount 100 \
    --interval 120 \
    --tolerance 0.05 \
    --use-bundle \
    --send

# Monitoring dashboard
python -m src.monitoring.pectra_dashboard

# Emergency rollback
export PECTRA_ENABLED=false && python -m src.arbitrage_commands.simple_bot --amount 10 --interval 120
```

## Conclusion

This production testing plan ensures a safe, gradual rollout of Pectra bundled transactions. By following these phases and maintaining strict success criteria, we can confidently migrate to the more efficient bundled execution model while minimizing risk to funds and operations.
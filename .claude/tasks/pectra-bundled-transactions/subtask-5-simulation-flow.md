# Subtask 5: Three-Stage Simulation Flow for EIP-7702

## Problem Statement
The sell conditional flow is failing because we can't accurately predict how much Company we'll receive from Balancer. The actual amount received (~0.000042 Company for 0.001 sDAI) is much less than expected based on spot price, due to slippage and swap mechanics.

## Solution: Three-Stage Simulation
Implement a simulation flow similar to `complex_bot.py` that discovers actual amounts before execution.

## Implementation Plan

### Stage 1: Discover Company Amount
```python
def simulate_balancer_swap(amount_sdai: Decimal) -> Dict[str, Any]:
    """
    Simulate just the Balancer swap to discover actual Company output.
    
    Returns:
        Dict with:
        - company_out: Actual Company tokens we'll receive
        - effective_price: Actual price paid
    """
    # Build single-operation bundle with just Balancer swap
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    
    # Add approval and swap
    builder.add_call(encode_approval_call(SDAI_TOKEN, BALANCER_ROUTER, amount_wei))
    builder.add_call(build_balancer_buy_company_call(amount_wei, 1, account.address))
    
    # Simulate with eth_call
    result = simulate_bundle(builder)
    
    # Parse Company output from events/return data
    company_out = parse_balancer_output(result)
    
    return {
        'company_out': company_out,
        'effective_price': amount_sdai / company_out
    }
```

### Stage 2: Simulate Split and Swaps
```python
def simulate_swapr_operations(company_amount: int) -> Dict[str, Any]:
    """
    Simulate split and Swapr swaps with known Company amount.
    
    Returns:
        Dict with:
        - yes_sdai_out: Amount of YES sDAI received
        - no_sdai_out: Amount of NO sDAI received
    """
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    
    # Add all operations with exact Company amount
    builder.add_call(encode_approval_call(COMPANY_TOKEN, FUTARCHY_ROUTER, company_amount))
    builder.add_call(encode_split_position_call(FUTARCHY_ROUTER, PROPOSAL, COMPANY_TOKEN, company_amount))
    
    # Add Swapr operations
    builder.add_call(encode_approval_call(COMPANY_YES, SWAPR_ROUTER, company_amount))
    builder.add_call(build_swapr_swap(COMPANY_YES, SDAI_YES, company_amount))
    
    builder.add_call(encode_approval_call(COMPANY_NO, SWAPR_ROUTER, company_amount))
    builder.add_call(build_swapr_swap(COMPANY_NO, SDAI_NO, company_amount))
    
    # Simulate
    result = simulate_bundle(builder)
    
    return {
        'yes_sdai_out': parse_swapr_output(result, 'YES'),
        'no_sdai_out': parse_swapr_output(result, 'NO')
    }
```

### Stage 3: Execute Final Bundle
```python
def execute_sell_conditional_with_simulation(amount_sdai: Decimal) -> Dict[str, Any]:
    """
    Execute sell conditional with 3-stage simulation flow.
    """
    print("=== Stage 1: Discovering Company amount ===")
    stage1 = simulate_balancer_swap(amount_sdai)
    company_amount = stage1['company_out']
    print(f"Will receive {w3.from_wei(company_amount, 'ether')} Company")
    
    print("\n=== Stage 2: Simulating Swapr operations ===")
    stage2 = simulate_swapr_operations(company_amount)
    yes_sdai = stage2['yes_sdai_out']
    no_sdai = stage2['no_sdai_out']
    print(f"Will receive {w3.from_wei(yes_sdai, 'ether')} YES sDAI")
    print(f"Will receive {w3.from_wei(no_sdai, 'ether')} NO sDAI")
    
    # Calculate profit
    total_sdai_out = min(yes_sdai, no_sdai)  # Amount we can merge
    profit = total_sdai_out - amount_sdai
    print(f"Expected profit: {w3.from_wei(profit, 'ether')} sDAI")
    
    if profit <= 0:
        print("No profit, skipping execution")
        return {'status': 'skipped', 'reason': 'no_profit'}
    
    print("\n=== Stage 3: Executing bundle ===")
    # Build final bundle with exact amounts
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    
    # All operations with discovered amounts
    builder.add_call(encode_approval_call(SDAI_TOKEN, BALANCER_ROUTER, amount_wei))
    builder.add_call(build_balancer_buy_company_call(amount_wei, int(company_amount * 0.95), account.address))
    builder.add_call(encode_approval_call(COMPANY_TOKEN, FUTARCHY_ROUTER, company_amount))
    builder.add_call(encode_split_position_call(FUTARCHY_ROUTER, PROPOSAL, COMPANY_TOKEN, company_amount))
    builder.add_call(encode_approval_call(COMPANY_YES, SWAPR_ROUTER, company_amount))
    builder.add_call(build_swapr_swap(COMPANY_YES, SDAI_YES, company_amount))
    builder.add_call(encode_approval_call(COMPANY_NO, SWAPR_ROUTER, company_amount))
    builder.add_call(build_swapr_swap(COMPANY_NO, SDAI_NO, company_amount))
    
    # Execute
    tx = builder.build_transaction(account, gas_params)
    signed_tx = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    print(f"Transaction sent: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    return {
        'status': 'success' if receipt.status == 1 else 'failed',
        'tx_hash': tx_hash.hex(),
        'profit': w3.from_wei(profit, 'ether')
    }
```

## Key Improvements

1. **Accurate Amount Discovery**: No more guessing - we know exactly what we'll get
2. **Profit Validation**: Can check profitability before execution
3. **Risk Mitigation**: Only execute if profitable
4. **Better UX**: Clear stage-by-stage feedback

## Files to Create/Modify

1. **New file**: `src/arbitrage_commands/sell_cond_eip7702_simulated.py`
   - Implement 3-stage flow
   - Use eth_call for simulation
   - Parse results accurately

2. **New file**: `src/helpers/eip7702_simulator.py`
   - Helper functions for bundle simulation
   - Result parsing utilities
   - State override helpers

3. **Update**: `src/arbitrage_commands/eip7702_bot.py`
   - Use new simulated sell flow
   - Add flag for simulation mode

## Testing Strategy

1. Test each stage independently
2. Verify amount parsing is accurate
3. Test with small amounts first
4. Compare with sequential execution results

## Success Criteria

- Sell flow executes successfully with correct amounts
- No more "insufficient balance" errors
- Profit calculation is accurate
- Bot can make informed decisions
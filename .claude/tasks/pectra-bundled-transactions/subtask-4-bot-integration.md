# Subtask 4: Bot Integration with EIP-7702 Flows

## Overview
Integrate the proven EIP-7702 buy and sell conditional flows into a monitoring bot that watches for arbitrage opportunities and executes bundled transactions atomically.

## Reference Implementation
Based on `src/arbitrage_commands/light_bot.py` which:
- Monitors Swapr and Balancer pool prices continuously
- Calculates ideal price from prediction markets
- Executes trades when profitable opportunities arise
- Runs in a loop with configurable intervals

## Implementation Plan

### 1. Create `eip7702_bot.py`

#### Core Components

##### Price Monitoring (from light_bot.py)
```python
# Fetch prices from Swapr pools
yes_price = fetch_swapr(SWAPR_POOL_YES_ADDRESS)
pred_yes_price = fetch_swapr(SWAPR_POOL_PRED_YES_ADDRESS) 
no_price = fetch_swapr(SWAPR_POOL_NO_ADDRESS)

# Calculate ideal price
ideal_price = pred_yes_price * yes_price + (1 - pred_yes_price) * no_price

# Get actual Balancer price
balancer_price = fetch_balancer(BALANCER_POOL_ADDRESS)
```

##### Decision Logic
```python
def determine_action(balancer_price, ideal_price, tolerance):
    """
    Determine whether to buy or sell based on price discrepancy.
    
    Returns:
        'buy': If Balancer price > ideal price (buy conditional)
        'sell': If Balancer price < ideal price (sell conditional)
        None: If within tolerance
    """
    diff = abs(balancer_price - ideal_price) / ideal_price
    
    if diff < tolerance:
        return None  # No profitable opportunity
    
    if balancer_price > ideal_price:
        return 'buy'  # Company expensive on Balancer, buy conditional
    else:
        return 'sell'  # Company cheap on Balancer, sell conditional
```

##### Integration with EIP-7702 Flows
```python
from src.arbitrage_commands.buy_cond_eip7702 import buy_conditional_simple
from src.arbitrage_commands.sell_cond_eip7702 import sell_conditional_simple

def execute_arbitrage(action, amount, dry_run=False):
    """
    Execute arbitrage using EIP-7702 bundled transactions.
    
    Args:
        action: 'buy' or 'sell'
        amount: Amount in sDAI
        dry_run: If True, simulate only
    
    Returns:
        Transaction result dictionary
    """
    if action == 'buy':
        # Buy conditional tokens and sell Company on Balancer
        result = buy_conditional_simple(
            amount_sdai=amount,
            skip_balancer=False  # Include Balancer swap
        )
    elif action == 'sell':
        # Buy Company on Balancer and sell conditional tokens
        result = sell_conditional_simple(
            amount_sdai=amount,
            skip_merge=False  # Include merge operation
        )
    else:
        raise ValueError(f"Unknown action: {action}")
    
    return result
```

### 2. Bot Architecture

#### Main Loop Structure
```python
def run_bot(amount, interval, tolerance, max_iterations=None):
    """
    Main bot loop that monitors and executes arbitrage.
    
    Args:
        amount: Trade amount in sDAI
        interval: Seconds between checks
        tolerance: Minimum profit threshold (as percentage)
        max_iterations: Stop after N iterations (None = infinite)
    """
    iteration = 0
    
    while max_iterations is None or iteration < max_iterations:
        try:
            # Fetch current prices
            prices = fetch_all_prices()
            
            # Calculate opportunity
            action = determine_action(
                prices['balancer'],
                prices['ideal'],
                tolerance
            )
            
            if action:
                print(f"Opportunity detected: {action}")
                print(f"Balancer: {prices['balancer']}, Ideal: {prices['ideal']}")
                
                # Execute arbitrage
                result = execute_arbitrage(action, amount)
                
                if result['status'] == 'success':
                    print(f"✅ Arbitrage successful: {result['tx_hash']}")
                    print(f"Gas used: {result['gas_used']}")
                else:
                    print(f"❌ Arbitrage failed: {result.get('error')}")
            else:
                print(f"No opportunity (diff < {tolerance}%)")
            
            iteration += 1
            if max_iterations is None or iteration < max_iterations:
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\nBot stopped by user")
            break
        except Exception as e:
            print(f"Error in bot loop: {e}")
            time.sleep(interval)
```

### 3. Safety Features

#### Balance Checks
```python
def check_balances():
    """
    Verify sufficient balances before trading.
    
    Returns:
        Dict with balance status
    """
    sdai_balance = get_token_balance(SDAI_TOKEN, account.address)
    company_balance = get_token_balance(COMPANY_TOKEN, account.address)
    eth_balance = w3.eth.get_balance(account.address)
    
    return {
        'sdai': w3.from_wei(sdai_balance, 'ether'),
        'company': w3.from_wei(company_balance, 'ether'),
        'eth': w3.from_wei(eth_balance, 'ether'),
        'sufficient': sdai_balance >= MIN_SDAI_BALANCE and eth_balance >= MIN_ETH_BALANCE
    }
```

#### Profit Validation
```python
def estimate_profit(action, amount, prices):
    """
    Estimate expected profit before execution.
    
    Returns:
        Expected profit in sDAI (negative = loss)
    """
    if action == 'buy':
        # Buy conditional at ideal, sell Company at Balancer
        company_out = amount / prices['ideal']
        sdai_back = company_out * prices['balancer']
        return sdai_back - amount
    else:
        # Buy Company at Balancer, sell conditional at ideal
        company_in = amount / prices['balancer']
        sdai_back = company_in * prices['ideal']
        return sdai_back - amount
```

### 4. CLI Interface

```python
def main():
    parser = argparse.ArgumentParser(
        description='EIP-7702 Arbitrage Bot for Futarchy Markets'
    )
    parser.add_argument(
        '--amount', 
        type=float, 
        required=True,
        help='Trade amount in sDAI'
    )
    parser.add_argument(
        '--interval', 
        type=int, 
        default=120,
        help='Check interval in seconds (default: 120)'
    )
    parser.add_argument(
        '--tolerance', 
        type=float, 
        default=0.02,
        help='Minimum profit threshold (default: 0.02 = 2%)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate trades without execution'
    )
    parser.add_argument(
        '--max-iterations',
        type=int,
        help='Stop after N iterations'
    )
    
    args = parser.parse_args()
    
    # Verify environment
    verify_environment()
    
    # Check initial balances
    balances = check_balances()
    print(f"Initial balances:")
    print(f"  sDAI: {balances['sdai']}")
    print(f"  Company: {balances['company']}")
    print(f"  ETH: {balances['eth']}")
    
    if not balances['sufficient']:
        print("❌ Insufficient balances to start bot")
        return
    
    # Start bot
    print(f"\nStarting EIP-7702 arbitrage bot...")
    print(f"Amount: {args.amount} sDAI")
    print(f"Interval: {args.interval}s")
    print(f"Tolerance: {args.tolerance * 100}%")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()
    
    run_bot(
        amount=args.amount,
        interval=args.interval,
        tolerance=args.tolerance,
        max_iterations=args.max_iterations
    )
```

### 5. Testing Strategy

#### Unit Tests
- Price fetching functions
- Decision logic with various price scenarios
- Profit estimation accuracy

#### Integration Tests
- Full cycle with test amounts (0.001 sDAI)
- Verify atomic execution of bundles
- Test failure recovery

#### Monitoring Tests
```bash
# Test with small amount and high frequency
python -m src.arbitrage_commands.eip7702_bot \
    --amount 0.001 \
    --interval 30 \
    --tolerance 0.01 \
    --max-iterations 5 \
    --dry-run

# Production test with real execution
python -m src.arbitrage_commands.eip7702_bot \
    --amount 0.1 \
    --interval 120 \
    --tolerance 0.02 \
    --max-iterations 1
```

## Key Differences from light_bot.py

1. **Atomic Execution**: All operations in single transaction
2. **No Tenderly**: Direct on-chain execution with EIP-7702
3. **Complete Arbitrage**: Includes Balancer swaps (unlike light_bot)
4. **Gas Efficiency**: Single transaction vs multiple sequential
5. **Simplified Logic**: No complex simulation/parsing

## Success Metrics

- Bot successfully detects arbitrage opportunities
- Executes complete buy/sell flows atomically
- Handles errors gracefully without stopping
- Maintains profitability after gas costs
- Provides clear logging and monitoring

## Next Steps

1. Implement `eip7702_bot.py` with core functionality
2. Add comprehensive logging and metrics
3. Test with small amounts on mainnet
4. Add performance optimizations (parallel price fetching)
5. Implement profit tracking and reporting
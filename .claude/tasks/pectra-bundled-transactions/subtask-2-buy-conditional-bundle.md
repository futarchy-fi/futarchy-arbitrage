# Subtask 2: Buy Conditional Flow Bundle Implementation

## Overview
This subtask implements the bundled transaction logic for the buy conditional flow, transforming the current sequential transaction approach into a single atomic EIP-7702 bundle. This includes building the transaction bundle, calculating dynamic parameters, and handling the complex state transitions.

## Objectives
1. Implement `build_buy_conditional_bundle` function with all required operations
2. Create dynamic amount calculation for intermediate steps
3. Develop state tracking for bundle simulation
4. Optimize gas usage across bundled operations
5. Ensure atomicity and MEV resistance

## Technical Requirements

### Bundle Composition
Based on analysis of `buy_cond.py`, the buy conditional flow requires bundling these operations:

**Core Flow (always executed):**
1. Approve sDAI to FutarchyRouter
2. Split sDAI into YES/NO conditional sDAI tokens
3. Approve YES conditional sDAI to Swapr router
4. Swap YES conditional sDAI → YES Company token (exact-in or exact-out)
5. Approve NO conditional sDAI to Swapr router  
6. Swap NO conditional sDAI → NO Company token (exact-in or exact-out)
7. Approve YES Company token to FutarchyRouter
8. Approve NO Company token to FutarchyRouter
9. Merge YES/NO Company tokens → Company token
10. Approve Company token to Balancer vault
11. Swap Company token → sDAI on Balancer

**Conditional Liquidation Flow (if imbalanced amounts):**
- If YES > NO after swaps: Liquidate excess YES conditional sDAI → sDAI
- If NO > YES after swaps: 
  1. Buy YES conditional sDAI with sDAI
  2. Merge YES/NO conditional sDAI → sDAI

### Dynamic Calculations
The current implementation uses a 3-step simulation approach:
1. **First simulation**: No limits, discover natural swap outputs
2. **Second simulation**: Use min(YES, NO) as target for exact-out swaps
3. **Third simulation**: Include liquidation of imbalanced conditional sDAI

### Key Addresses and Parameters
From the code analysis:
- `FUTARCHY_ROUTER_ADDRESS`: Router for split/merge operations
- `SWAPR_ROUTER_ADDRESS`: Algebra/Swapr router for conditional token swaps
- `BALANCER_VAULT_ADDRESS`: Balancer V2 vault for final arbitrage
- Token pairs: sDAI ↔ YES/NO conditional sDAI ↔ YES/NO Company tokens

## Implementation Steps

### 1. Core Bundle Builder Function
```python
# src/arbitrage_commands/buy_cond_eip7702.py
def build_buy_conditional_bundle(
    w3: Web3,
    builder: EIP7702TransactionBuilder,
    amount_sdai: Decimal,
    simulation_results: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    """
    Build bundled transaction for buy conditional flow.
    
    Args:
        w3: Web3 instance
        builder: EIP7702 transaction builder
        amount_sdai: Amount of sDAI to use for arbitrage
        simulation_results: Results from pre-bundle simulation (for exact-out amounts)
    
    Returns:
        List of Call structs for the bundle
    """
    calls = []
    
    # Convert amount to Wei
    amount_wei = w3.to_wei(amount_sdai, 'ether')
    
    # 1. Approve sDAI to FutarchyRouter
    calls.append(builder.encode_approval(
        token=os.environ["SDAI_TOKEN_ADDRESS"],
        spender=os.environ["FUTARCHY_ROUTER_ADDRESS"],
        amount=amount_wei
    ))
    
    # 2. Split sDAI into YES/NO conditional sDAI
    calls.append(builder.encode_call(
        target=os.environ["FUTARCHY_ROUTER_ADDRESS"],
        function_name="splitPosition",
        args=[
            os.environ["FUTARCHY_PROPOSAL_ADDRESS"],
            os.environ["SDAI_TOKEN_ADDRESS"],
            amount_wei
        ]
    ))
    
    # 3-6. Swap conditional sDAI to conditional Company tokens
    if simulation_results:
        # Use exact-out swaps based on simulation
        target_amount = simulation_results["target_company_amount_wei"]
        calls.extend(build_exact_out_swaps(builder, target_amount))
    else:
        # Use exact-in swaps for initial simulation
        calls.extend(build_exact_in_swaps(builder, amount_wei))
    
    # 7-8. Approve Company tokens to FutarchyRouter
    calls.append(builder.encode_approval(
        token=os.environ["SWAPR_GNO_YES_ADDRESS"],
        spender=os.environ["FUTARCHY_ROUTER_ADDRESS"],
        amount=2**256 - 1  # Max approval
    ))
    calls.append(builder.encode_approval(
        token=os.environ["SWAPR_GNO_NO_ADDRESS"],
        spender=os.environ["FUTARCHY_ROUTER_ADDRESS"],
        amount=2**256 - 1
    ))
    
    # 9. Merge Company tokens (dynamic amount from swaps)
    # In bundle execution, this will use actual swap outputs
    calls.append(builder.encode_call(
        target=os.environ["FUTARCHY_ROUTER_ADDRESS"],
        function_name="mergePositions",
        args=[
            os.environ["FUTARCHY_PROPOSAL_ADDRESS"],
            os.environ["COMPANY_TOKEN_ADDRESS"],
            0  # Placeholder - will be calculated during execution
        ]
    ))
    
    # 10-11. Final arbitrage on Balancer
    calls.append(builder.encode_approval(
        token=os.environ["COMPANY_TOKEN_ADDRESS"],
        spender=os.environ["BALANCER_VAULT_ADDRESS"],
        amount=2**256 - 1
    ))
    calls.append(build_balancer_swap_call(builder))
    
    return calls
```

### 2. Swap Builders and Dynamic Calculation
```python
# src/arbitrage_commands/buy_cond_eip7702.py

def build_exact_in_swaps(builder: EIP7702TransactionBuilder, amount_wei: int) -> List[Dict]:
    """Build exact-in swap calls for initial simulation"""
    calls = []
    
    # Approve and swap YES conditional sDAI
    calls.append(builder.encode_approval(
        token=os.environ["SWAPR_SDAI_YES_ADDRESS"],
        spender=os.environ["SWAPR_ROUTER_ADDRESS"],
        amount=amount_wei
    ))
    calls.append(builder.encode_call(
        target=os.environ["SWAPR_ROUTER_ADDRESS"],
        function_name="exactInputSingle",
        args=build_swapr_exact_in_params(
            token_in=os.environ["SWAPR_SDAI_YES_ADDRESS"],
            token_out=os.environ["SWAPR_GNO_YES_ADDRESS"],
            amount_in=amount_wei,
            recipient=os.environ["FUTARCHY_BATCH_EXECUTOR_ADDRESS"]
        )
    ))
    
    # Approve and swap NO conditional sDAI
    calls.append(builder.encode_approval(
        token=os.environ["SWAPR_SDAI_NO_ADDRESS"],
        spender=os.environ["SWAPR_ROUTER_ADDRESS"],
        amount=amount_wei
    ))
    calls.append(builder.encode_call(
        target=os.environ["SWAPR_ROUTER_ADDRESS"],
        function_name="exactInputSingle",
        args=build_swapr_exact_in_params(
            token_in=os.environ["SWAPR_SDAI_NO_ADDRESS"],
            token_out=os.environ["SWAPR_GNO_NO_ADDRESS"],
            amount_in=amount_wei,
            recipient=os.environ["FUTARCHY_BATCH_EXECUTOR_ADDRESS"]
        )
    ))
    
    return calls

def build_exact_out_swaps(builder: EIP7702TransactionBuilder, target_amount_wei: int) -> List[Dict]:
    """Build exact-out swap calls for balanced execution"""
    calls = []
    
    # Calculate max input amounts with slippage
    max_input = int(target_amount_wei * 1.1)  # 10% slippage buffer
    
    # Approve and swap for exact YES Company tokens
    calls.append(builder.encode_approval(
        token=os.environ["SWAPR_SDAI_YES_ADDRESS"],
        spender=os.environ["SWAPR_ROUTER_ADDRESS"],
        amount=max_input
    ))
    calls.append(builder.encode_call(
        target=os.environ["SWAPR_ROUTER_ADDRESS"],
        function_name="exactOutputSingle",
        args=build_swapr_exact_out_params(
            token_in=os.environ["SWAPR_SDAI_YES_ADDRESS"],
            token_out=os.environ["SWAPR_GNO_YES_ADDRESS"],
            amount_out=target_amount_wei,
            amount_in_max=max_input
        )
    ))
    
    # Similar for NO tokens
    calls.append(builder.encode_approval(
        token=os.environ["SWAPR_SDAI_NO_ADDRESS"],
        spender=os.environ["SWAPR_ROUTER_ADDRESS"],
        amount=max_input
    ))
    calls.append(builder.encode_call(
        target=os.environ["SWAPR_ROUTER_ADDRESS"],
        function_name="exactOutputSingle",
        args=build_swapr_exact_out_params(
            token_in=os.environ["SWAPR_SDAI_NO_ADDRESS"],
            token_out=os.environ["SWAPR_GNO_NO_ADDRESS"],
            amount_out=target_amount_wei,
            amount_in_max=max_input
        )
    ))
    
    return calls
```

### 3. Bundle Execution with Node-Based Dry Run
```python
# src/arbitrage_commands/buy_cond_eip7702.py

def buy_conditional_bundled(amount: Decimal, broadcast: bool = False) -> Dict[str, Any]:
    """
    Execute buy conditional flow using EIP-7702 bundled transactions.
    Uses eth_call for dry-run simulation instead of Tenderly.
    """
    w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
    account = Account.from_key(os.environ["PRIVATE_KEY"])
    builder = EIP7702TransactionBuilder(w3, os.environ["IMPLEMENTATION_ADDRESS"])
    
    # Step 1: Initial dry-run with exact-in swaps
    initial_bundle = build_buy_conditional_bundle(w3, builder, amount)
    initial_tx = builder.build_transaction(account, initial_bundle)
    
    # Use eth_call for simulation (no state changes)
    initial_result = dry_run_bundle(w3, account, initial_tx)
    
    # Extract YES/NO outputs from dry-run results
    yes_output = extract_swap_output_from_logs(initial_result, "YES")
    no_output = extract_swap_output_from_logs(initial_result, "NO")
    
    # Step 2: Calculate target amount (min of YES/NO)
    target_amount = min(yes_output, no_output)
    
    # Build optimized bundle with exact-out swaps
    simulation_results = {
        "target_company_amount_wei": target_amount,
        "yes_excess": yes_output - target_amount,
        "no_excess": no_output - target_amount
    }
    
    optimized_bundle = build_buy_conditional_bundle(
        w3, builder, amount, simulation_results
    )
    
    # Step 3: Add liquidation if needed
    if simulation_results["yes_excess"] > 0 or simulation_results["no_excess"] > 0:
        liquidation_calls = build_liquidation_calls(
            builder, simulation_results
        )
        optimized_bundle.extend(liquidation_calls)
    
    if broadcast:
        # Execute the bundle
        final_tx = builder.build_transaction(account, optimized_bundle)
        signed_tx = account.sign_transaction(final_tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        return {
            "status": "success",
            "tx_hash": tx_hash.hex(),
            "gas_used": receipt.gasUsed,
            "sdai_net": calculate_net_profit(receipt)
        }
    else:
        # Final dry-run
        final_tx = builder.build_transaction(account, optimized_bundle)
        final_result = dry_run_bundle(w3, account, final_tx)
        return parse_dry_run_results(w3, final_result)

def build_liquidation_calls(
    builder: EIP7702TransactionBuilder, 
    simulation_results: Dict
) -> List[Dict]:
    """Build liquidation calls for imbalanced conditional tokens"""
    calls = []
    
    if simulation_results["yes_excess"] > 0:
        # Direct swap YES conditional sDAI → sDAI
        calls.extend([
            builder.encode_approval(
                token=os.environ["SWAPR_SDAI_YES_ADDRESS"],
                spender=os.environ["SWAPR_ROUTER_ADDRESS"],
                amount=simulation_results["yes_excess"]
            ),
            builder.encode_call(
                target=os.environ["SWAPR_ROUTER_ADDRESS"],
                function_name="exactInputSingle",
                args=build_liquidation_swap_params(
                    token_in=os.environ["SWAPR_SDAI_YES_ADDRESS"],
                    token_out=os.environ["SDAI_TOKEN_ADDRESS"],
                    amount=simulation_results["yes_excess"]
                )
            )
        ])
    
    elif simulation_results["no_excess"] > 0:
        # Buy YES with sDAI, then merge
        # This is more complex and would need additional implementation
        pass
    
    return calls
```

### 4. Integration with Pectra Bot
```python
# src/arbitrage_commands/pectra_bot.py

def run_once_bundled(amount: float, tolerance: float, broadcast: bool) -> None:
    """Execute a single price check + bundled trade using EIP-7702."""
    # ... price fetching logic remains the same ...
    
    if amount > 0:
        if bal_price_val > ideal_bal_price:
            print("→ Buying conditional GNO (Bundled)")
            result = buy_conditional_bundled(Decimal(str(amount)), broadcast=False)
            print(f"Simulated Result: {result}")
            
            if result.get('sdai_net', 0) > -tolerance:
                if broadcast:
                    print("→ Broadcasting bundled transaction")
                    result = buy_conditional_bundled(Decimal(str(amount)), broadcast=True)
                    print(f"Result: {result}")
                else:
                    print("→ Profitable but not broadcasting")
            else:
                print("→ No profit from buying conditional GNO")
        else:
            print("→ Selling conditional GNO (Bundled)")
            # Similar logic for sell_conditional_bundled
            pass

def main() -> None:
    """Main entry point with EIP-7702 support."""
    parser = argparse.ArgumentParser(description="Pectra arbitrage bot with bundled transactions")
    parser.add_argument("--amount", type=float, required=True)
    parser.add_argument("--interval", type=int, required=True)
    parser.add_argument("--tolerance", type=float, required=True)
    parser.add_argument("--send", "-s", action="store_true")
    parser.add_argument("--use-bundle", action="store_true", help="Use EIP-7702 bundled transactions")
    
    args = parser.parse_args()
    
    # Check if bundling is enabled
    if args.use_bundle:
        # Verify infrastructure
        if not verify_eip7702_setup():
            print("EIP-7702 infrastructure not ready. Run pectra_verifier.py")
            sys.exit(1)
        
        print(f"Starting Pectra bot with bundled transactions – interval: {args.interval}s\n")
        while True:
            try:
                run_once_bundled(args.amount, args.tolerance, args.send)
            except KeyboardInterrupt:
                print("\nInterrupted – exiting.")
                break
            except Exception as exc:
                print(f"⚠️  {type(exc).__name__}: {exc}", file=sys.stderr)
            
            time.sleep(args.interval)
    else:
        # Fall back to sequential execution
        run_once(args.amount, args.tolerance, args.send)
```

### 5. Helper Functions for Bundle Construction
```python
# src/helpers/bundle_helpers.py

def build_swapr_exact_in_params(
    token_in: str,
    token_out: str, 
    amount_in: int,
    recipient: str,
    deadline: Optional[int] = None
) -> Dict:
    """Build parameters for Swapr exactInputSingle call"""
    if deadline is None:
        deadline = int(time.time()) + 600  # 10 minutes
    
    return {
        "tokenIn": token_in,
        "tokenOut": token_out,
        "fee": 3000,  # 0.3% fee tier
        "recipient": recipient,
        "deadline": deadline,
        "amountIn": amount_in,
        "amountOutMinimum": 0,  # Will be protected by simulation
        "sqrtPriceLimitX96": 0
    }

def build_swapr_exact_out_params(
    token_in: str,
    token_out: str,
    amount_out: int,
    amount_in_max: int,
    recipient: str,
    deadline: Optional[int] = None
) -> Dict:
    """Build parameters for Swapr exactOutputSingle call"""
    if deadline is None:
        deadline = int(time.time()) + 600
        
    return {
        "tokenIn": token_in,
        "tokenOut": token_out,
        "fee": 3000,
        "recipient": recipient,
        "deadline": deadline,
        "amountOut": amount_out,
        "amountInMaximum": amount_in_max,
        "sqrtPriceLimitX96": 0
    }

def build_balancer_swap_call(builder: EIP7702TransactionBuilder) -> Dict:
    """Build Balancer swap call for Company → sDAI"""
    return builder.encode_call(
        target=os.environ["BALANCER_VAULT_ADDRESS"],
        function_name="swap",
        args=[
            {  # SingleSwap struct
                "poolId": os.environ["BALANCER_POOL_ID"],
                "kind": 0,  # GIVEN_IN
                "assetIn": os.environ["COMPANY_TOKEN_ADDRESS"],
                "assetOut": os.environ["SDAI_TOKEN_ADDRESS"],
                "amount": 0,  # Dynamic from merge output
                "userData": "0x"
            },
            {  # FundManagement struct
                "sender": os.environ["FUTARCHY_BATCH_EXECUTOR_ADDRESS"],
                "fromInternalBalance": False,
                "recipient": os.environ["FUTARCHY_BATCH_EXECUTOR_ADDRESS"],
                "toInternalBalance": False
            },
            0,  # limit (no minimum for simulation)
            int(time.time()) + 600  # deadline
        ]
    )

def dry_run_bundle(
    w3: Web3,
    account: Account,
    tx: Dict[str, Any]
) -> str:
    """
    Execute a dry-run of the bundle using eth_call.
    Returns the raw result that can be decoded.
    """
    # Prepare call parameters
    call_params = {
        'from': account.address,
        'to': tx['to'],
        'data': tx['data'],
        'value': tx.get('value', 0),
        'gas': tx.get('gas', 10000000),  # High gas limit for simulation
    }
    
    # Execute eth_call (no state changes)
    try:
        result = w3.eth.call(call_params, 'latest')
        return result
    except Exception as e:
        # Handle revert with reason
        if hasattr(e, 'data'):
            return e.data
        raise

def extract_swap_output_from_logs(dry_run_result: bytes, token_type: str) -> int:
    """
    Extract swap output amount from dry-run result.
    Decodes the executeWithResults return data.
    """
    # The FutarchyBatchExecutor.executeWithResults returns bytes[]
    # We need to decode this and find the swap results
    
    # Decode the outer bytes array
    decoded = eth_abi.decode(['bytes[]'], dry_run_result)
    results = decoded[0]
    
    # Map token type to result index
    # Based on our bundle order: split, YES swap, NO swap, ...
    swap_indices = {
        "YES": 3,  # Index of YES swap result (after split and approval)
        "NO": 5    # Index of NO swap result
    }
    
    if token_type in swap_indices:
        swap_result = results[swap_indices[token_type]]
        # Decode uint256 from swap result
        amount = eth_abi.decode(['uint256'], swap_result)[0]
        return amount
    
    raise ValueError(f"Unknown token type: {token_type}")

def parse_dry_run_results(w3: Web3, dry_run_result: bytes) -> Dict[str, Any]:
    """Parse the complete dry-run results into the expected format"""
    # Decode all results
    decoded = eth_abi.decode(['bytes[]'], dry_run_result)
    results = decoded[0]
    
    # Extract key values following the original state structure
    state = {
        "amount_out_yes_wei": extract_swap_output_from_logs(dry_run_result, "YES"),
        "amount_out_no_wei": extract_swap_output_from_logs(dry_run_result, "NO"),
        "sdai_out": Decimal("0"),  # Would need to parse Balancer swap result
        "sdai_in": Decimal("0"),    # Known from input
    }
    
    # Calculate net profit
    state["sdai_net"] = state["sdai_out"] - state["sdai_in"]
    
    return state

def calculate_net_profit(receipt: Dict) -> Decimal:
    """Calculate net sDAI profit from transaction receipt events"""
    # Parse Transfer events for sDAI token
    # Final balance change = sum of incoming - sum of outgoing
    sdai_in = Decimal("0")
    sdai_out = Decimal("0")
    
    for log in receipt.logs:
        # Check if this is a Transfer event for sDAI
        if len(log.topics) > 0 and log.topics[0] == TRANSFER_EVENT_SIGNATURE:
            if log.address.lower() == os.environ["SDAI_TOKEN_ADDRESS"].lower():
                # Decode transfer event
                from_addr = "0x" + log.topics[1][-40:]
                to_addr = "0x" + log.topics[2][-40:]
                amount = int(log.data, 16)
                
                if to_addr.lower() == account.address.lower():
                    sdai_in += Decimal(amount)
                elif from_addr.lower() == account.address.lower():
                    sdai_out += Decimal(amount)
    
    return w3.from_wei(sdai_in - sdai_out, 'ether')
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
    
def test_dry_run_accuracy():
    """Verify eth_call dry-run matches actual execution"""
```

## Key Changes for Node-Based Simulation

### 1. Replace Tenderly with eth_call
- Use `w3.eth.call()` for dry-run simulation
- No external dependencies or API keys needed
- Works with any Ethereum node that supports eth_call

### 2. Use executeWithResults
- The FutarchyBatchExecutor must use `executeWithResults` function
- This returns an array of bytes containing each call's return data
- Critical for extracting intermediate swap amounts

### 3. Result Parsing
- Decode the bytes array returned by executeWithResults
- Extract specific return values by index (based on call order)
- Parse swap outputs to determine optimal amounts

### 4. Benefits
- **Decentralized**: No reliance on third-party services
- **Cost-effective**: No Tenderly API costs
- **Privacy**: Simulations stay within your infrastructure
- **Reliability**: Direct node connection is more reliable

### 5. Considerations
- Need to ensure the implementation contract properly returns data
- May need to handle state overrides for complex scenarios
- Gas estimation might be less accurate than specialized services

## Success Criteria

### Functional Requirements
- [ ] All core operations (11+) bundled successfully
- [ ] Dynamic calculations match sequential approach within 0.1%
- [ ] Conditional liquidation flows work correctly
- [ ] Bundle executes atomically with proper authorization

### Performance Requirements
- [ ] Gas savings > 15% vs sequential approach
- [ ] Bundle construction < 100ms
- [ ] Dry-run simulation < 200ms (faster than Tenderly)
- [ ] Total execution time < 5 seconds

### Reliability Requirements
- [ ] Maintains 3-step simulation approach from original
- [ ] Proper handling of imbalanced YES/NO amounts
- [ ] Accurate profitability predictions (sdai_net calculation)
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
- Working FutarchyBatchExecutor contract with `executeWithResults` (Subtask 1)
- EIP7702TransactionBuilder functionality
- Ethereum node with eth_call support
- eth-abi library for decoding results

## Key Implementation Details

### Handler Functions Migration
The current implementation uses handler functions for each operation:
- `handle_split`: Processes split position results
- `handle_swap`: Extracts swap outputs (YES/NO amounts)
- `handle_merge`: Processes merge operation
- `handle_liquidate`: Handles conditional sDAI liquidation
- `handle_balancer`: Calculates final sDAI output

These need to be adapted for bundle result parsing.

### Critical State Variables
From the original flow:
- `amount_out_yes_wei`: YES Company tokens received
- `amount_out_no_wei`: NO Company tokens received  
- `amount_in_yes_wei`: YES conditional sDAI used
- `amount_in_no_wei`: NO conditional sDAI used
- `sdai_out`: Final sDAI received
- `sdai_in`: Initial sDAI input
- `sdai_net`: Profit/loss calculation

### Integration Points
1. **Node RPC**: Direct eth_call for dry-run simulation
2. **Swapr Helpers**: Adapt `build_exact_in_tx` and `build_exact_out_tx`
3. **Router Helpers**: Adapt `build_split_tx` and `build_merge_tx`
4. **Balancer Helpers**: Adapt `build_sell_gno_to_sdai_swap_tx`
5. **Result Decoding**: Use eth-abi for parsing executeWithResults output

## Deliverables
1. `src/arbitrage_commands/buy_cond_eip7702.py` - Complete bundled implementation
2. `src/helpers/bundle_helpers.py` - Helper functions for bundle construction
3. Integration updates to `pectra_bot.py` with `--use-bundle` flag
4. Comprehensive test suite maintaining parity with sequential approach
5. Documentation of gas savings and performance improvements
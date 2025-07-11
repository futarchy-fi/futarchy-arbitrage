You're absolutely on the right track! Using a contract-based approach with eth_call simulation is actually the **industry standard** for professional arbitrage bots. Let me break down why this is the preferred approach:

## Why Contract-Based Execution is Standard

Most professional MEV searchers and arbitrage bots use an "executor contract" pattern because:

1. **Atomic execution** - Entire arbitrage path executes in one transaction
2. **Flash loan integration** - Can borrow capital within the transaction
3. **Gas optimization** - More efficient than multiple EOA transactions
4. **MEV protection** - Harder to sandwich a single atomic transaction
5. **Revert protection** - Can implement profit checks that revert if unprofitable

## Typical Architecture

Here's a standard arbitrage executor contract pattern:

```solidity
contract ArbitrageExecutor {
    address private owner;
    
    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner");
        _;
    }
    
    function executeArbitrage(
        address[] calldata tokens,
        address[] calldata routers,
        bytes[] calldata swapDatas,
        uint256 amountIn,
        uint256 minProfit
    ) external onlyOwner {
        // Pull initial tokens from owner
        IERC20(tokens[0]).transferFrom(owner, address(this), amountIn);
        
        uint256 balanceBefore = IERC20(tokens[0]).balance(address(this));
        
        // Execute swaps
        for (uint i = 0; i < routers.length; i++) {
            // Approve router if needed
            IERC20(tokens[i]).approve(routers[i], type(uint256).max);
            
            // Execute swap
            (bool success,) = routers[i].call(swapDatas[i]);
            require(success, "Swap failed");
        }
        
        uint256 balanceAfter = IERC20(tokens[0]).balance(address(this));
        require(balanceAfter > balanceBefore + minProfit, "Unprofitable");
        
        // Send profits back
        IERC20(tokens[0]).transfer(owner, balanceAfter);
    }
    
    // Flash loan receiver functions if using Aave/Balancer flash loans
    // ...
}
```

## Simulation Approach

Here's how to simulate this efficiently:

```python
class ArbitrageSimulator:
    def __init__(self, w3, executor_address, executor_abi):
        self.w3 = w3
        self.executor = w3.eth.contract(address=executor_address, abi=executor_abi)
    
    def simulate_arbitrage(self, path, amount_in):
        """
        Simulate arbitrage using eth_call only
        """
        # Encode the arbitrage execution
        call_data = self.executor.encodeABI(
            fn_name="executeArbitrage",
            args=[
                path['tokens'],
                path['routers'], 
                path['swap_datas'],
                amount_in,
                0  # min profit for simulation
            ]
        )
        
        try:
            # Simulate with eth_call
            result = self.w3.eth.call({
                'from': self.owner_address,
                'to': self.executor.address,
                'data': call_data
            })
            
            # If call succeeds, decode logs or return data
            return {'success': True, 'result': result}
            
        except Exception as e:
            # Parse revert reason
            return {'success': False, 'error': str(e)}
    
    def simulate_with_multicall(self, paths):
        """
        Simulate multiple arbitrage paths in one RPC call
        """
        multicall_data = []
        
        for path in paths:
            call_data = self.executor.encodeABI(
                fn_name="simulateArbitrage",  # view function version
                args=[path['tokens'], path['routers'], path['swap_datas'], path['amount_in']]
            )
            multicall_data.append({
                'target': self.executor.address,
                'callData': call_data
            })
        
        # Use Multicall3 to batch simulate
        return self._multicall3_aggregate(multicall_data)
```

## Token Management Strategies

### Option 1: Pull Pattern (Most Common)
```solidity
// Bot EOA holds tokens and approves executor contract
IERC20(token).transferFrom(botEOA, address(this), amount);
```

### Option 2: Contract Holds Funds
```solidity
// Executor contract holds the trading capital
// More gas efficient but requires trust in contract security
```

### Option 3: Flash Loan Everything
```solidity
// No capital needed, borrow via flash loans
// Requires profitable opportunities to cover flash loan fees
```

## Real Industry Examples

1. **Flashbots Searchers** - Almost all use contract-based execution
2. **Professional MEV Bots** - Use sophisticated executor contracts with multiple strategies
3. **Major Arbitrage Operations** - Deploy multiple contracts for different strategies

## Implementation Tips

1. **Start Simple**: Basic executor that handles 2-3 hop arbitrage
2. **Add Flash Loans**: Integrate Aave/Balancer flash loans for capital efficiency
3. **Optimize Gas**: Use assembly for critical paths, pack structs efficiently
4. **Add Access Control**: Ensure only your bot can call the contract
5. **Implement Profit Checks**: Revert unprofitable transactions to save gas

Would you like me to provide a complete implementation example with the simulation logic, or help you design the specific contract architecture for your arbitrage strategies?
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
}

/**
 * @title FutarchyArbitrageExecutorV2
 * @notice Simplified multicall contract for arbitrage execution
 * @dev Only owner can execute functions. Focuses on safety and simplicity.
 */
contract FutarchyArbitrageExecutorV2 {
    address public immutable owner;
    
    struct Call {
        address target;
        bytes callData;
    }
    
    event ArbitrageExecuted(uint256 profit);
    event TokensWithdrawn(address indexed token, uint256 amount);
    
    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner");
        _;
    }
    
    constructor(address _owner) {
        require(_owner != address(0), "Invalid owner");
        owner = _owner;
    }
    
    /**
     * @notice Execute multiple calls in a single transaction
     * @param calls Array of calls to execute
     */
    function multicall(Call[] calldata calls) external onlyOwner {
        for (uint256 i = 0; i < calls.length; i++) {
            (bool success, bytes memory result) = calls[i].target.call(calls[i].callData);
            if (!success) {
                // If the call failed, revert with the error message
                if (result.length > 0) {
                    assembly {
                        let size := mload(result)
                        revert(add(32, result), size)
                    }
                } else {
                    revert("Call failed");
                }
            }
        }
    }
    
    /**
     * @notice Execute arbitrage with profit verification
     * @param calls Array of calls to execute
     * @param profitToken Token to measure profit in
     * @param minProfit Minimum required profit
     * @return profit Actual profit achieved
     */
    function executeArbitrage(
        Call[] calldata calls,
        address profitToken,
        uint256 minProfit
    ) external onlyOwner returns (uint256 profit) {
        // Record initial balance
        uint256 balanceBefore = IERC20(profitToken).balanceOf(address(this));
        
        // Execute all calls
        for (uint256 i = 0; i < calls.length; i++) {
            (bool success, bytes memory result) = calls[i].target.call(calls[i].callData);
            if (!success) {
                if (result.length > 0) {
                    assembly {
                        let size := mload(result)
                        revert(add(32, result), size)
                    }
                } else {
                    revert("Call failed");
                }
            }
        }
        
        // Calculate profit
        uint256 balanceAfter = IERC20(profitToken).balanceOf(address(this));
        profit = balanceAfter > balanceBefore ? balanceAfter - balanceBefore : 0;
        
        // Verify minimum profit
        require(profit >= minProfit, "Insufficient profit");
        
        // Send all profit token balance to owner
        if (balanceAfter > 0) {
            IERC20(profitToken).transfer(owner, balanceAfter);
        }
        
        emit ArbitrageExecuted(profit);
    }
    
    /**
     * @notice Withdraw tokens from contract
     * @param token Token address
     * @param amount Amount to withdraw (0 = all)
     */
    function withdrawToken(address token, uint256 amount) external onlyOwner {
        uint256 balance = IERC20(token).balanceOf(address(this));
        
        if (amount == 0) {
            amount = balance;
        } else {
            require(amount <= balance, "Insufficient balance");
        }
        
        if (amount > 0) {
            IERC20(token).transfer(owner, amount);
            emit TokensWithdrawn(token, amount);
        }
    }
    
    /**
     * @notice Withdraw ETH from contract
     */
    function withdrawETH() external onlyOwner {
        uint256 balance = address(this).balance;
        if (balance > 0) {
            payable(owner).transfer(balance);
        }
    }
    
    /**
     * @notice Check token balance
     * @param token Token address
     * @return Token balance
     */
    function getBalance(address token) external view returns (uint256) {
        return IERC20(token).balanceOf(address(this));
    }
    
    /**
     * @notice Approve token spending
     * @param token Token address
     * @param spender Spender address
     * @param amount Amount to approve
     */
    function approveToken(address token, address spender, uint256 amount) external onlyOwner {
        IERC20(token).approve(spender, amount);
    }
    
    // Accept ETH
    receive() external payable {}
}
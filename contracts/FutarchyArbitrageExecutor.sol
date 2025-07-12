// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
}

contract FutarchyArbitrageExecutor {
    address public immutable owner;
    
    uint256 private constant MAX_UINT = type(uint256).max;
    
    struct Call {
        address target;
        bytes callData;
    }
    
    struct Result {
        bool success;
        bytes returnData;
    }
    
    event MulticallExecuted(
        uint256 callsCount,
        uint256 successCount
    );
    
    event ArbitrageProfit(
        address indexed token,
        uint256 profit
    );
    
    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can execute");
        _;
    }
    
    constructor(address _owner) {
        require(_owner != address(0), "Invalid owner");
        owner = _owner;
    }
    
    /**
     * @notice Execute multiple calls in a single transaction
     * @param calls Array of Call structs containing target addresses and calldata
     * @return returnData Array of Result structs containing success status and return data
     */
    function multicall(Call[] calldata calls) external onlyOwner returns (Result[] memory returnData) {
        uint256 length = calls.length;
        returnData = new Result[](length);
        uint256 successCount = 0;
        
        for (uint256 i = 0; i < length; i++) {
            (bool success, bytes memory ret) = calls[i].target.call(calls[i].callData);
            returnData[i] = Result(success, ret);
            if (success) successCount++;
        }
        
        emit MulticallExecuted(length, successCount);
    }
    
    /**
     * @notice Execute multiple calls, reverting if any fail
     * @param calls Array of Call structs containing target addresses and calldata
     * @return returnData Array of return data from each call
     */
    function multicallStrict(Call[] calldata calls) external onlyOwner returns (bytes[] memory returnData) {
        uint256 length = calls.length;
        returnData = new bytes[](length);
        
        for (uint256 i = 0; i < length; i++) {
            (bool success, bytes memory ret) = calls[i].target.call(calls[i].callData);
            require(success, string(abi.encodePacked("Call ", _toString(i), " failed")));
            returnData[i] = ret;
        }
        
        emit MulticallExecuted(length, length);
    }
    
    /**
     * @notice Execute arbitrage operations and calculate profit
     * @param calls Array of Call structs for the arbitrage operations
     * @param profitToken The token to measure profit in
     * @param minProfit Minimum profit required (transaction reverts if not met)
     */
    function executeArbitrage(
        Call[] calldata calls,
        address profitToken,
        uint256 minProfit
    ) external onlyOwner returns (uint256 profit) {
        // Record initial balance
        uint256 initialBalance = IERC20(profitToken).balanceOf(address(this));
        
        // Execute all calls
        uint256 length = calls.length;
        for (uint256 i = 0; i < length; i++) {
            (bool success, bytes memory ret) = calls[i].target.call(calls[i].callData);
            require(success, string(abi.encodePacked("Arbitrage call ", _toString(i), " failed: ", _getRevertMsg(ret))));
        }
        
        // Calculate profit
        uint256 finalBalance = IERC20(profitToken).balanceOf(address(this));
        profit = finalBalance > initialBalance ? finalBalance - initialBalance : 0;
        
        require(profit >= minProfit, "Insufficient profit");
        
        // Transfer profit to owner
        if (profit > 0) {
            IERC20(profitToken).transfer(owner, profit);
            emit ArbitrageProfit(profitToken, profit);
        }
        
        // Transfer any remaining balance
        uint256 remainingBalance = IERC20(profitToken).balanceOf(address(this));
        if (remainingBalance > 0) {
            IERC20(profitToken).transfer(owner, remainingBalance);
        }
    }
    
    /**
     * @notice Approve tokens for multiple spenders
     * @param tokens Array of token addresses
     * @param spenders Array of spender addresses
     * @param amounts Array of amounts to approve (use MAX_UINT for unlimited)
     */
    function batchApprove(
        address[] calldata tokens,
        address[] calldata spenders,
        uint256[] calldata amounts
    ) external onlyOwner {
        require(tokens.length == spenders.length && tokens.length == amounts.length, "Array length mismatch");
        
        for (uint256 i = 0; i < tokens.length; i++) {
            _approveIfNeeded(tokens[i], spenders[i], amounts[i]);
        }
    }
    
    /**
     * @notice Transfer tokens from owner to contract
     * @param token Token address
     * @param amount Amount to transfer
     */
    function pullToken(address token, uint256 amount) external onlyOwner {
        IERC20(token).transferFrom(owner, address(this), amount);
    }
    
    /**
     * @notice Transfer tokens from contract to owner
     * @param token Token address
     * @param amount Amount to transfer (use MAX_UINT for entire balance)
     */
    function pushToken(address token, uint256 amount) external onlyOwner {
        if (amount == MAX_UINT) {
            amount = IERC20(token).balanceOf(address(this));
        }
        IERC20(token).transfer(owner, amount);
    }
    
    /**
     * @notice Get token balance of this contract
     * @param token Token address
     * @return balance Token balance
     */
    function getBalance(address token) external view returns (uint256) {
        return IERC20(token).balanceOf(address(this));
    }
    
    /**
     * @notice Simulate multicall execution
     * @param calls Array of Call structs
     * @return results Array of Result structs with success status and return data
     */
    function simulateMulticall(Call[] calldata calls) external returns (Result[] memory results) {
        uint256 length = calls.length;
        results = new Result[](length);
        
        for (uint256 i = 0; i < length; i++) {
            try this.simulateCall(calls[i].target, calls[i].callData) returns (bytes memory ret) {
                results[i] = Result(true, ret);
            } catch (bytes memory reason) {
                results[i] = Result(false, reason);
            }
        }
    }
    
    /**
     * @notice Helper function for simulation
     */
    function simulateCall(address target, bytes calldata data) external returns (bytes memory) {
        (bool success, bytes memory ret) = target.call(data);
        if (!success) {
            assembly {
                revert(add(ret, 32), mload(ret))
            }
        }
        return ret;
    }
    
    // Internal functions
    function _approveIfNeeded(address token, address spender, uint256 amount) private {
        uint256 currentAllowance = IERC20(token).allowance(address(this), spender);
        if (currentAllowance < amount) {
            // Reset approval to 0 first for tokens that require it
            if (currentAllowance > 0) {
                IERC20(token).approve(spender, 0);
            }
            IERC20(token).approve(spender, amount == MAX_UINT ? MAX_UINT : amount);
        }
    }
    
    function _getRevertMsg(bytes memory returnData) private pure returns (string memory) {
        if (returnData.length < 68) return "Transaction reverted silently";
        
        assembly {
            returnData := add(returnData, 0x04)
        }
        return abi.decode(returnData, (string));
    }
    
    function _toString(uint256 value) private pure returns (string memory) {
        if (value == 0) {
            return "0";
        }
        uint256 temp = value;
        uint256 digits;
        while (temp != 0) {
            digits++;
            temp /= 10;
        }
        bytes memory buffer = new bytes(digits);
        while (value != 0) {
            digits -= 1;
            buffer[digits] = bytes1(uint8(48 + uint256(value % 10)));
            value /= 10;
        }
        return string(buffer);
    }
    
    // Emergency functions
    function rescueToken(address token, uint256 amount) external onlyOwner {
        if (amount == MAX_UINT) {
            amount = IERC20(token).balanceOf(address(this));
        }
        IERC20(token).transfer(owner, amount);
    }
    
    function rescueETH() external onlyOwner {
        payable(owner).transfer(address(this).balance);
    }
    
    // Receive ETH
    receive() external payable {}
}
// SPDX-License-Identifier: MIT
pragma solidity 0.8.17;

/**
 * @title FutarchyBatchExecutorV2
 * @notice Implementation contract for EIP-7702 batched futarchy arbitrage operations
 * @dev Redesigned to avoid dynamic arrays which generate 0xEF opcodes
 * 
 * This version uses a hybrid approach:
 * - Fixed-size arrays for common operations (up to 20 calls)
 * - Specialized functions for futarchy-specific operations
 */
contract FutarchyBatchExecutorV2 {
    // Events
    event CallExecuted(uint256 index, address target, bool success);
    event BatchExecuted(uint256 callsExecuted);
    event ApprovalSet(address indexed token, address indexed spender, uint256 amount);

    // Errors
    error OnlySelf();
    error CallFailed(uint256 index);
    error InvalidCount();

    modifier onlySelf() {
        if (msg.sender != address(this)) revert OnlySelf();
        _;
    }

    /**
     * @notice Execute up to 20 calls in a batch
     * @dev Uses fixed-size arrays to avoid 0xEF generation
     * @param count Number of calls to execute (max 20)
     * @param targets Array of 20 target addresses (use address(0) for unused slots)
     * @param values Array of 20 ETH values
     * @param calldatas Array of 20 calldata
     */
    function execute20(
        uint256 count,
        address[20] calldata targets,
        uint256[20] calldata values,
        bytes[20] calldata calldatas
    ) external payable onlySelf {
        if (count > 20) revert InvalidCount();
        
        for (uint256 i = 0; i < count; i++) {
            if (targets[i] != address(0)) {
                (bool success,) = targets[i].call{value: values[i]}(calldatas[i]);
                if (!success) revert CallFailed(i);
                emit CallExecuted(i, targets[i], success);
            }
        }
        
        emit BatchExecuted(count);
    }

    /**
     * @notice Execute up to 20 calls and return results
     * @param count Number of calls to execute
     * @param targets Array of 20 target addresses
     * @param values Array of 20 ETH values
     * @param calldatas Array of 20 calldata
     * @return success Array of success flags
     * @return results Array of return data (only valid entries up to count)
     */
    function execute20WithResults(
        uint256 count,
        address[20] calldata targets,
        uint256[20] calldata values,
        bytes[20] calldata calldatas
    ) external payable onlySelf returns (
        bool[20] memory success,
        bytes[20] memory results
    ) {
        if (count > 20) revert InvalidCount();
        
        for (uint256 i = 0; i < count; i++) {
            if (targets[i] != address(0)) {
                (success[i], results[i]) = targets[i].call{value: values[i]}(calldatas[i]);
                emit CallExecuted(i, targets[i], success[i]);
            }
        }
        
        emit BatchExecuted(count);
    }

    /**
     * @notice Specialized function for buy conditional flow (11 operations)
     * @dev Optimized for the specific sequence of operations in buy flow
     */
    function executeBuyConditional(
        address[11] calldata targets,
        uint256[11] calldata values,
        bytes[11] calldata calldatas
    ) external payable onlySelf returns (bytes[11] memory results) {
        // Execute all 11 operations for buy conditional flow
        for (uint256 i = 0; i < 11; i++) {
            (bool success, bytes memory result) = targets[i].call{value: values[i]}(calldatas[i]);
            if (!success) revert CallFailed(i);
            results[i] = result;
            emit CallExecuted(i, targets[i], success);
        }
        
        emit BatchExecuted(11);
    }

    /**
     * @notice Set multiple token approvals
     * @param tokens Array of token addresses
     * @param spenders Array of spender addresses
     * @param amounts Array of amounts to approve
     */
    function setApprovals(
        address[5] calldata tokens,
        address[5] calldata spenders,
        uint256[5] calldata amounts,
        uint256 count
    ) external onlySelf {
        if (count > 5) revert InvalidCount();
        
        for (uint256 i = 0; i < count; i++) {
            if (tokens[i] != address(0)) {
                _approve(tokens[i], spenders[i], amounts[i]);
            }
        }
    }

    /**
     * @notice Internal function to handle token approvals
     */
    function _approve(address token, address spender, uint256 amount) internal {
        (bool success, bytes memory data) = token.call(
            abi.encodeWithSignature("approve(address,uint256)", spender, amount)
        );
        
        if (!success) revert CallFailed(0);
        
        // Check return value if present
        if (data.length > 0) {
            bool approved = abi.decode(data, (bool));
            if (!approved) revert CallFailed(0);
        }
        
        emit ApprovalSet(token, spender, amount);
    }

    /**
     * @notice Execute a single call (for simple operations)
     */
    function executeOne(
        address target,
        uint256 value,
        bytes calldata data
    ) external payable onlySelf returns (bytes memory) {
        (bool success, bytes memory result) = target.call{value: value}(data);
        if (!success) revert CallFailed(0);
        emit CallExecuted(0, target, success);
        return result;
    }

    /**
     * @notice Receive ETH
     */
    receive() external payable {}
}
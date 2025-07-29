// SPDX-License-Identifier: MIT
pragma solidity 0.8.17;

/**
 * @title FutarchyBatchExecutorSimple
 * @notice Simplified implementation contract for EIP-7702 batched futarchy arbitrage operations
 * @dev This is a minimal version that avoids features that generate 0xEF opcodes
 */
contract FutarchyBatchExecutorSimple {
    // Events
    event CallExecuted(uint256 index, bool success);
    event BatchExecuted(uint256 callsExecuted);

    /**
     * @notice Execute a batch of calls using separate arrays
     * @dev Avoiding struct arrays which may trigger 0xEF generation
     * @param targets Array of target addresses
     * @param values Array of ETH values
     * @param calldatas Array of calldata
     */
    function execute(
        address[] calldata targets,
        uint256[] calldata values,
        bytes[] calldata calldatas
    ) external payable {
        // Ensure the caller is the contract itself (EIP-7702 self-execution)
        require(msg.sender == address(this), "Only self");
        
        // Ensure arrays have same length
        require(targets.length == values.length, "Length mismatch");
        require(targets.length == calldatas.length, "Length mismatch");
        
        // Execute all calls
        for (uint256 i = 0; i < targets.length; i++) {
            (bool success,) = targets[i].call{value: values[i]}(calldatas[i]);
            require(success, "Call failed");
            emit CallExecuted(i, success);
        }
        
        emit BatchExecuted(targets.length);
    }

    /**
     * @notice Execute a batch of calls with results (simplified)
     * @param targets Array of target addresses
     * @param values Array of ETH values
     * @param calldatas Array of calldata
     * @return results Array of return data
     */
    function executeWithResults(
        address[] calldata targets,
        uint256[] calldata values,
        bytes[] calldata calldatas
    ) external payable returns (bytes[] memory results) {
        require(msg.sender == address(this), "Only self");
        require(targets.length == values.length, "Length mismatch");
        require(targets.length == calldatas.length, "Length mismatch");
        
        results = new bytes[](targets.length);
        
        for (uint256 i = 0; i < targets.length; i++) {
            (bool success, bytes memory result) = targets[i].call{value: values[i]}(calldatas[i]);
            require(success, "Call failed");
            results[i] = result;
            emit CallExecuted(i, success);
        }
        
        emit BatchExecuted(targets.length);
    }

    /**
     * @notice Simple receive function
     */
    receive() external payable {}
}
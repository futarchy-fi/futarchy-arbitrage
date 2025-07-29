// SPDX-License-Identifier: MIT
pragma solidity 0.8.17;

/**
 * @title FutarchyBatchExecutorMinimal
 * @notice Ultra-minimal implementation for EIP-7702 testing
 * @dev Avoids all complex features that might generate 0xEF
 */
contract FutarchyBatchExecutorMinimal {
    
    /**
     * @notice Execute up to 10 calls in a batch
     * @dev Fixed-size approach to avoid dynamic array issues
     */
    function execute10(
        address[10] calldata targets,
        bytes[10] calldata calldatas,
        uint256 count
    ) external payable {
        require(msg.sender == address(this), "Only self");
        require(count <= 10, "Too many calls");
        
        for (uint256 i = 0; i < count; i++) {
            if (targets[i] != address(0)) {
                (bool success,) = targets[i].call(calldatas[i]);
                require(success, "Failed");
            }
        }
    }
    
    /**
     * @notice Execute a single call (most minimal)
     */
    function executeOne(
        address target,
        bytes calldata data
    ) external payable returns (bytes memory) {
        require(msg.sender == address(this), "Only self");
        (bool success, bytes memory result) = target.call{value: msg.value}(data);
        require(success, "Failed");
        return result;
    }
    
    receive() external payable {}
}
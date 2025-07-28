// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title SimpleEIP7702Test
 * @notice Minimal implementation contract for testing EIP-7702
 */
contract SimpleEIP7702Test {
    event TestExecuted(address caller, uint256 value);
    
    /**
     * @notice Simple test function
     */
    function test() external payable {
        emit TestExecuted(msg.sender, msg.value);
    }
    
    /**
     * @notice Execute a single call
     */
    function execute(address target, uint256 value, bytes calldata data) external payable returns (bytes memory) {
        require(msg.sender == address(this), "Only self");
        (bool success, bytes memory result) = target.call{value: value}(data);
        require(success, "Call failed");
        return result;
    }
}
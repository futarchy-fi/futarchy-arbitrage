// SPDX-License-Identifier: MIT
pragma solidity ^0.8.17;

/**
 * @title PectraWrapper
 * @notice Wrapper contract to execute batched calls without EIP-7702
 * @dev This contract allows bundled execution of arbitrage operations
 */
contract PectraWrapper {
    // Events
    event CallExecuted(address indexed target, bytes data, bool success);
    event BatchExecuted(uint256 callsExecuted);

    // Owner who can execute batches
    address public immutable owner;

    // Custom errors
    error OnlyOwner();
    error CallFailed(uint256 index, bytes returnData);

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert OnlyOwner();
        _;
    }

    /**
     * @notice Execute up to 10 calls in a batch
     * @dev Similar interface to FutarchyBatchExecutorMinimal but callable by owner
     */
    function execute10(
        address[10] calldata targets,
        bytes[10] calldata calldatas,
        uint256 count
    ) external payable onlyOwner {
        require(count <= 10, "Too many calls");
        
        for (uint256 i = 0; i < count; i++) {
            if (targets[i] != address(0)) {
                (bool success, bytes memory returnData) = targets[i].call(calldatas[i]);
                if (!success) {
                    revert CallFailed(i, returnData);
                }
                emit CallExecuted(targets[i], calldatas[i], success);
            }
        }
        
        emit BatchExecuted(count);
    }

    /**
     * @notice Execute a single call
     */
    function executeOne(
        address target,
        bytes calldata data
    ) external payable onlyOwner returns (bytes memory) {
        (bool success, bytes memory result) = target.call{value: msg.value}(data);
        require(success, "Call failed");
        emit CallExecuted(target, data, success);
        return result;
    }

    /**
     * @notice Rescue stuck tokens
     */
    function rescueToken(address token, uint256 amount) external onlyOwner {
        if (token == address(0)) {
            payable(owner).transfer(amount);
        } else {
            // Use low-level call to handle non-standard tokens
            (bool success, ) = token.call(
                abi.encodeWithSignature("transfer(address,uint256)", owner, amount)
            );
            require(success, "Transfer failed");
        }
    }

    receive() external payable {}
}
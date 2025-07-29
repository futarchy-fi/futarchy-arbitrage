// SPDX-License-Identifier: MIT
pragma solidity 0.8.17;

/**
 * @title FutarchyBatchExecutorUltra
 * @notice Ultra-simple implementation that avoids all 0xEF triggers
 * @dev No arrays, no loops, just sequential execution
 */
contract FutarchyBatchExecutorUltra {
    
    event Executed(address target);
    
    modifier onlySelf() {
        require(msg.sender == address(this), "Only self");
        _;
    }
    
    /**
     * @notice Execute 2 calls
     */
    function execute2(
        address target1, bytes calldata data1,
        address target2, bytes calldata data2
    ) external payable onlySelf {
        (bool s1,) = target1.call(data1);
        require(s1, "Call 1 failed");
        emit Executed(target1);
        
        (bool s2,) = target2.call(data2);
        require(s2, "Call 2 failed");
        emit Executed(target2);
    }
    
    /**
     * @notice Execute 3 calls
     */
    function execute3(
        address target1, bytes calldata data1,
        address target2, bytes calldata data2,
        address target3, bytes calldata data3
    ) external payable onlySelf {
        (bool s1,) = target1.call(data1);
        require(s1, "Call 1 failed");
        
        (bool s2,) = target2.call(data2);
        require(s2, "Call 2 failed");
        
        (bool s3,) = target3.call(data3);
        require(s3, "Call 3 failed");
    }
    
    /**
     * @notice Execute 5 calls (no loops)
     */
    function execute5(
        address t1, bytes calldata d1,
        address t2, bytes calldata d2,
        address t3, bytes calldata d3,
        address t4, bytes calldata d4,
        address t5, bytes calldata d5
    ) external payable onlySelf {
        (bool s,) = t1.call(d1);
        require(s, "1");
        
        (s,) = t2.call(d2);
        require(s, "2");
        
        (s,) = t3.call(d3);
        require(s, "3");
        
        (s,) = t4.call(d4);
        require(s, "4");
        
        (s,) = t5.call(d5);
        require(s, "5");
    }
    
    /**
     * @notice Execute 11 calls for buy conditional flow
     */
    function executeBuy11(
        address t1, bytes calldata d1,
        address t2, bytes calldata d2,
        address t3, bytes calldata d3,
        address t4, bytes calldata d4,
        address t5, bytes calldata d5,
        address t6, bytes calldata d6,
        address t7, bytes calldata d7,
        address t8, bytes calldata d8,
        address t9, bytes calldata d9,
        address t10, bytes calldata d10,
        address t11, bytes calldata d11
    ) external payable onlySelf returns (
        bytes memory r1, bytes memory r2, bytes memory r3,
        bytes memory r4, bytes memory r5, bytes memory r6
    ) {
        bool s;
        (s, r1) = t1.call(d1);
        require(s, "1");
        
        (s,) = t2.call(d2);
        require(s, "2");
        
        (s,) = t3.call(d3);
        require(s, "3");
        
        (s, r2) = t4.call(d4);
        require(s, "4");
        
        (s,) = t5.call(d5);
        require(s, "5");
        
        (s, r3) = t6.call(d6);
        require(s, "6");
        
        (s,) = t7.call(d7);
        require(s, "7");
        
        (s,) = t8.call(d8);
        require(s, "8");
        
        (s, r4) = t9.call(d9);
        require(s, "9");
        
        (s,) = t10.call(d10);
        require(s, "10");
        
        (s, r5) = t11.call(d11);
        require(s, "11");
        
        r6 = r5; // Just to use the variable
    }
    
    receive() external payable {}
}
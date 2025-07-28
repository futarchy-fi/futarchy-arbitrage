# Subtask 2.1: Debug and Fix Invalid Opcode Issue

## Problem Statement

During on-chain testing of EIP-7702 bundled transactions, execution is failing with the error:
```
"opcode 0xef not defined"
```

## Root Cause Analysis

### 1. Contract Bytecode Analysis
The deployed FutarchyBatchExecutor contract at `0x2552eafcE4e4D0863388Fb03519065a2e5866135` contains:
- Total bytecode size: 5147 bytes
- 6 occurrences of "ef" hex sequence
- 2 actual `0xEF` opcodes at byte positions 1336 and 2082

### 2. EIP-3541 Restriction
- EIP-3541 (part of London upgrade) reserves the `0xEF` byte for EOF (Ethereum Object Format)
- Contracts containing `0xEF` as an opcode are considered invalid
- This restriction prevents deployment of new contracts starting with `0xEF`

### 3. EIP-7702 Execution Flow
When using EIP-7702:
1. EOA temporarily delegates to implementation contract
2. EOA's code is replaced with implementation contract's code
3. EVM executes the delegated code
4. If code contains invalid opcodes like `0xEF`, execution fails

## Test Transactions

| Transaction Hash | Authorization Status | Result |
|-----------------|---------------------|---------|
| 0xcac5bb6993f3d028d0f66063d181863ca12835497788ea74e10b6d379c8bdca5 | Invalid (nonce=2266) | Low gas usage (85,230) |
| 0x7c9a2f0c876e1d4c9802b5b9c05aaf2f44b87df027dbb08277e08be126ce1cf0 | Invalid (nonce=0) | Low gas usage (85,230) |
| 0xdc8a038eeb4e0647a4061ca2201ea0373f57f8ea7b7c7e4df9bc7ed206ab984a | Valid (nonce=2269) | Failed with high gas (474,257) |

The third transaction confirms that:
- ✅ EIP-7702 authorization works correctly with `nonce = account.nonce + 1`
- ✅ Gnosis Chain supports EIP-7702 (Pectra upgrade live since May 7, 2025)
- ❌ Implementation contract execution fails due to invalid opcodes

## Solution Approaches

### Option 1: Recompile with Different Settings (Recommended)
1. **Change Solidity Version**
   - Current: `pragma solidity ^0.8.20;`
   - Recommended: `pragma solidity 0.8.19;` or earlier
   - Some Solidity versions generate different bytecode patterns

2. **Adjust Optimizer Settings**
   ```json
   {
     "optimizer": {
       "enabled": true,
       "runs": 200,
       "details": {
         "yul": false,
         "yulDetails": {
           "stackAllocation": false
         }
       }
     }
   }
   ```

3. **Verification Process**
   - Compile contract
   - Check bytecode for `0xEF` bytes: `bytecode.includes('ef')`
   - Ensure no `0xEF` at even positions (opcode positions)
   - Deploy only if clean

### Option 2: Minimal Test Contract First
Deploy `SimpleEIP7702Test.sol` to verify EIP-7702 functionality:
```solidity
contract SimpleEIP7702Test {
    event TestExecuted(address caller, uint256 value);
    
    function test() external payable {
        emit TestExecuted(msg.sender, msg.value);
    }
    
    function execute(address target, uint256 value, bytes calldata data) external payable returns (bytes memory) {
        require(msg.sender == address(this), "Only self");
        (bool success, bytes memory result) = target.call{value: value}(data);
        require(success, "Call failed");
        return result;
    }
}
```

### Option 3: Bytecode Modification
- Manually identify and replace `0xEF` opcodes with equivalent instructions
- High risk, not recommended

## Implementation Steps

1. **Setup Compilation Environment**
   ```bash
   npm install --save-dev solc@0.8.19
   ```

2. **Create Verification Script**
   ```javascript
   const bytecode = compiledContract.evm.bytecode.object;
   const efPositions = [];
   for (let i = 0; i < bytecode.length; i += 2) {
     if (bytecode.substr(i, 2) === 'ef') {
       efPositions.push(i / 2);
     }
   }
   console.log(`Found ${efPositions.length} potential 0xEF opcodes at positions:`, efPositions);
   ```

3. **Deploy Clean Contract**
   - Compile with verified settings
   - Deploy to Gnosis Chain
   - Update environment variables

4. **Test EIP-7702 Execution**
   - Start with simple test transaction
   - Verify authorization works
   - Test full arbitrage bundle

## Environment Updates Required

After deploying clean contract:
```bash
export IMPLEMENTATION_ADDRESS=<new_contract_address>
export FUTARCHY_BATCH_EXECUTOR_ADDRESS=<new_contract_address>
```

## Success Criteria

1. Contract bytecode contains no `0xEF` opcodes
2. EIP-7702 authorization validates successfully
3. Simple test transaction executes without opcode errors
4. Full arbitrage bundle executes atomically

## References

- [EIP-3541: Reject new contracts starting with 0xEF](https://eips.ethereum.org/EIPS/eip-3541)
- [EIP-7702: Set EOA account code](https://eips.ethereum.org/EIPS/eip-7702)
- [Solidity Compiler Optimizer Settings](https://docs.soliditylang.org/en/latest/using-the-compiler.html#optimizer-options)
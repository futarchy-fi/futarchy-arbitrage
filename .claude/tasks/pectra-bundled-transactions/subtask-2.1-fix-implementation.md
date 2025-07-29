# Implementation Plan: Fixing the 0xEF Opcode Issue

## Status: Ready for Implementation

### Problem Summary
The deployed FutarchyBatchExecutor contract (0x2552eafcE4e4D0863388Fb03519065a2e5866135) contains invalid 0xEF opcodes that prevent EIP-7702 execution. This is due to Solidity 0.8.20+ occasionally emitting the reserved 0xEF byte.

### Solution Overview
1. Downgrade to Solidity 0.8.19
2. Disable Yul optimizer
3. Add bytecode verification
4. Redeploy clean contract

## Step-by-Step Implementation

### Step 1: Update Solidity Version in Contract
**File**: `contracts/FutarchyBatchExecutor.sol`
```diff
-pragma solidity ^0.8.20;
+pragma solidity 0.8.19;
```

### Step 2: Update Compiler Configuration
**File**: `hardhat.config.ts` or `foundry.toml`

For Hardhat:
```javascript
solidity: {
  version: "0.8.19",
  settings: {
    optimizer: {
      enabled: true,
      runs: 200,
      details: {
        yul: false  // Critical: prevents 0xEF emission
      }
    }
  }
}
```

For Foundry:
```toml
[profile.default]
solc_version = "0.8.19"
optimizer = true
optimizer_runs = 200
via_ir = false  # Avoid IR pipeline which may introduce 0xEF
```

### Step 3: Update Deployment Script
**File**: `src/setup/deploy_batch_executor.py`

Add bytecode verification before deployment:
```python
def verify_bytecode(bytecode: str) -> bool:
    """Check if bytecode contains 0xEF opcodes."""
    # Remove 0x prefix if present
    bytecode = bytecode.replace('0x', '')
    
    # Check for 0xEF at even positions (opcode positions)
    ef_positions = []
    for i in range(0, len(bytecode), 2):
        if bytecode[i:i+2].lower() == 'ef':
            ef_positions.append(i // 2)
    
    if ef_positions:
        print(f"❌ Found 0xEF opcodes at byte positions: {ef_positions}")
        return False
    
    print("✅ Bytecode is clean - no 0xEF opcodes found")
    return True

# In deploy function:
if not verify_bytecode(compiled_contract['evm']['bytecode']['object']):
    raise RuntimeError("Cannot deploy contract with 0xEF opcodes")
```

### Step 4: Update Verifier
**File**: `src/helpers/pectra_verifier.py`

Add runtime bytecode check:
```python
def check_implementation_bytecode(self, address: str) -> bool:
    """Verify deployed contract has no 0xEF opcodes."""
    code = self.w3.eth.get_code(address)
    
    # Check for 0xEF bytes
    if b'\xef' in code:
        ef_count = code.count(b'\xef')
        self.add_error(f"Implementation contains {ef_count} 0xEF bytes - must redeploy")
        return False
    
    self.add_success("Implementation bytecode is clean")
    return True
```

### Step 5: Create Test Contract
**File**: `contracts/SimpleEIP7702Test.sol`
```solidity
// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;

contract SimpleEIP7702Test {
    event TestExecuted(address caller, uint256 value);
    event CallExecuted(address target, bool success, bytes result);
    
    function test() external payable {
        emit TestExecuted(msg.sender, msg.value);
    }
    
    function execute(address target, uint256 value, bytes calldata data) 
        external 
        payable 
        returns (bytes memory) 
    {
        require(msg.sender == address(this), "Only self");
        (bool success, bytes memory result) = target.call{value: value}(data);
        emit CallExecuted(target, success, result);
        require(success, "Call failed");
        return result;
    }
}
```

## Deployment Procedure

### 1. Clean Build
```bash
# Remove old artifacts
rm -rf artifacts cache out

# Compile with new settings
npx hardhat compile
# or
forge build
```

### 2. Deploy Contract
```bash
# Activate environment
source futarchy_env/bin/activate
source .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF

# Deploy (will auto-verify bytecode)
python -m src.setup.deploy_batch_executor
```

### 3. Update Environment
```bash
# Add to .env file
export IMPLEMENTATION_ADDRESS=<new_deployed_address>
export FUTARCHY_BATCH_EXECUTOR_ADDRESS=<new_deployed_address>

# Verify deployment
python -m src.helpers.pectra_verifier
```

### 4. Test Minimal Transaction
```bash
# Test with simple approval
python -c "
from src.helpers.eip7702_builder import create_test_transaction
from web3 import Web3
from eth_account import Account
import os

w3 = Web3(Web3.HTTPProvider(os.environ['RPC_URL']))
account = Account.from_key(os.environ['PRIVATE_KEY'])
impl_addr = os.environ['IMPLEMENTATION_ADDRESS']

tx = create_test_transaction(w3, impl_addr, account)
print(f'Test transaction built successfully')
"
```

### 5. Test Buy Bundle
```bash
# Dry run
python -m src.arbitrage_commands.buy_cond_eip7702 0.001

# If successful, test with broadcast
python -m src.arbitrage_commands.buy_cond_eip7702 0.001 --send
```

## Verification Checklist

- [ ] Contract compiles with Solidity 0.8.19
- [ ] Bytecode verification passes (no 0xEF)
- [ ] Contract deploys successfully
- [ ] pectra_verifier.py shows all green
- [ ] Simple test transaction executes
- [ ] Buy bundle simulation works
- [ ] Buy bundle broadcast succeeds

## Rollback Plan

If issues persist:
1. Keep old implementation address in `IMPLEMENTATION_ADDRESS_OLD`
2. Test with different optimizer settings
3. Try Solidity 0.8.18 or 0.8.17 if needed
4. Consider manual bytecode patching as last resort

## Expected Outcomes

- No more "opcode 0xef not defined" errors
- Successful EIP-7702 transaction execution
- Gas usage similar to previous estimates
- All arbitrage operations working atomically
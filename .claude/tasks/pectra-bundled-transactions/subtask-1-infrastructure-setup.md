# Subtask 1: Contract Deployment and Infrastructure Setup

## Overview
This subtask focuses on establishing the foundational infrastructure for EIP-7702 bundled transactions, including deploying the FutarchyBatchExecutor contract, setting up deployment scripts, and configuring the environment for Pectra compatibility.

## Objectives
1. Deploy FutarchyBatchExecutor implementation contract on Gnosis Chain
2. Create deployment and verification scripts for reproducibility
3. Configure environment variables for EIP-7702 operations
4. Establish contract upgrade patterns for future improvements
5. Set up monitoring infrastructure for bundled transactions

## Technical Requirements

### Smart Contract Infrastructure
- FutarchyBatchExecutor contract with multicall capabilities
- Support for arbitrary call data execution
- Gas-efficient implementation with minimal storage operations
- Compatibility with existing FutarchyRouter and pool interfaces

### Deployment Requirements
- Deterministic deployment addresses using CREATE2
- Contract verification on Gnosisscan
- Deployment across multiple environments (testnet, mainnet)
- Gas optimization for deployment costs

## Implementation Steps

### 1. Contract Development (Day 1-2)
```solidity
// contracts/FutarchyBatchExecutor.sol
contract FutarchyBatchExecutor {
    struct Call {
        address target;
        uint256 value;
        bytes data;
    }
    
    function executeBatch(Call[] calldata calls) external payable returns (bytes[] memory results);
    function simulateBatch(Call[] calldata calls) external view returns (bytes[] memory results, bool[] memory success);
}
```

**Key Features:**
- Reentrancy protection
- Gas accounting per call
- Result aggregation
- Revert reason propagation

### 2. Deployment Script Creation (Day 2-3)
```python
# src/setup/deploy_batch_executor.py
def deploy_batch_executor():
    """Deploy FutarchyBatchExecutor with CREATE2 for deterministic addresses"""
    # 1. Compile contract
    # 2. Calculate CREATE2 address
    # 3. Deploy via factory
    # 4. Verify on Gnosisscan
    # 5. Update environment files
```

**Deployment Strategy:**
- Use factory pattern for CREATE2 deployment
- Implement deployment replay protection
- Generate deployment reports with addresses and gas costs

### 3. Environment Configuration (Day 3)
```bash
# .env.pectra additions
IMPLEMENTATION_ADDRESS=0x...  # FutarchyBatchExecutor address
PECTRA_ENABLED=true
EIP7702_GAS_BUFFER=20000  # Additional gas for authorization
BUNDLE_SIMULATION_ENDPOINT=http://...  # Tenderly/local fork
```

**Configuration Management:**
- Create pectra-specific environment template
- Document all required environment variables
- Implement configuration validation on startup

### 4. Infrastructure Verification (Day 4)
```python
# src/helpers/pectra_verifier.py
def verify_infrastructure():
    """Verify all Pectra infrastructure is properly deployed"""
    # 1. Check implementation contract exists
    # 2. Verify contract bytecode matches expected
    # 3. Test basic multicall functionality
    # 4. Validate gas estimation accuracy
```



## Success Criteria

### Deployment Success
- [x] FutarchyBatchExecutor contract developed and ready for deployment
- [ ] Contract verified on Gnosisscan (pending deployment)
- [x] Deployment script created (`deploy_batch_executor.py`)
- [x] Gas optimization implemented in contract

### Infrastructure Readiness
- [x] All environment variables documented in `pectra_verifier.py`
- [x] Deployment scripts created and versioned
- [x] EIP-7702 transaction builder implemented
- [x] Infrastructure verification tool created
- [x] Contract ABI generated and stored
- [x] Comprehensive test suite implemented

## Risk Mitigation

### Operational Risks
1. **Network Congestion**
   - Mitigation: Priority fee management
   - Off-peak deployment windows

2. **Configuration Errors**
   - Mitigation: Automated validation
   - Configuration testing framework

## Dependencies
- Solidity 0.8.19+ for Pectra compatibility
- web3.py with EIP-7702 support
- Gnosis Chain RPC with Pectra activation
- Contract verification API access

## Deliverables
1. ✅ FutarchyBatchExecutor contract (ready for deployment)
2. ✅ Deployment and verification scripts (`deploy_batch_executor.py`)
3. ✅ Environment configuration documentation in `pectra_verifier.py`
4. ✅ Infrastructure documentation (design docs and implementation plan)
5. ✅ Verification and testing tools
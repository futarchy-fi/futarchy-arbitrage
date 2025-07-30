# Pool Addresses and Contract Details

## Core Contracts

### PNK Token
- **Network**: Gnosis Chain
- **Address**: `[TO BE DETERMINED]`
- **Decimals**: 18
- **Symbol**: PNK

### WETH (Wrapped Ether on Gnosis)
- **Network**: Gnosis Chain
- **Address**: `[TO BE DETERMINED FROM CONFIG]`
- **Decimals**: 18
- **Symbol**: WETH

### WXDAI (Wrapped xDAI)
- **Network**: Gnosis Chain
- **Address**: `[DERIVED FROM POOL]`
- **Decimals**: 18
- **Symbol**: WXDAI

### sDAI (Savings DAI)
- **Network**: Gnosis Chain
- **Address**: `0x89C80A4540A00b5270347E02e2E144c71da2EceD`
- **Decimals**: 18
- **Symbol**: sDAI
- **Type**: ERC-4626 Vault Token

## Liquidity Pools

### PNK/WETH Pool
- **Address**: `0x2613Cb099C12CECb1bd290Fd0eF6833949374165`
- **Type**: Uniswap V2 Compatible
- **Token0**: `[TO BE DETERMINED]`
- **Token1**: `[TO BE DETERMINED]`
- **Fee**: 0.3%

### WETH/WXDAI Pool
- **Address**: `0x1865d5445010e0baf8be2eb410d3eae4a68683c2`
- **Type**: Uniswap V2 Compatible
- **Token0**: `[TO BE DETERMINED]`
- **Token1**: `[TO BE DETERMINED]`
- **Fee**: 0.3%

## Required ABI Methods

### For Uniswap V2 Pools
```solidity
// Get current reserves
function getReserves() external view returns (
    uint112 reserve0,
    uint112 reserve1,
    uint32 blockTimestampLast
);

// Get token0 address
function token0() external view returns (address);

// Get token1 address
function token1() external view returns (address);
```

### For sDAI Contract
```solidity
// Get current sDAI to DAI conversion rate
function convertToAssets(uint256 shares) external view returns (uint256 assets);

// Alternative method
function previewRedeem(uint256 shares) external view returns (uint256 assets);
```

## Configuration Requirements

### Environment Variables
```bash
# Token Addresses
PNK_TOKEN_ADDRESS=
WETH_ADDRESS=

# Pool Addresses
PNK_WETH_POOL=0x2613Cb099C12CECb1bd290Fd0eF6833949374165
WETH_WXDAI_POOL=0x1865d5445010e0baf8be2eb410d3eae4a68683c2

# Contract Addresses
SDAI_CONTRACT=0x89C80A4540A00b5270347E02e2E144c71da2EceD

# RPC Configuration
RPC_URL=https://rpc.gnosischain.com
```

### Python Configuration Structure
```python
PNK_CONFIG = {
    "pools": {
        "pnk_weth": {
            "address": "0x2613Cb099C12CECb1bd290Fd0eF6833949374165",
            "token0": None,  # To be determined on init
            "token1": None,  # To be determined on init
            "decimals0": 18,
            "decimals1": 18
        },
        "weth_wxdai": {
            "address": "0x1865d5445010e0baf8be2eb410d3eae4a68683c2",
            "token0": None,  # To be determined on init
            "token1": None,  # To be determined on init
            "decimals0": 18,
            "decimals1": 18
        }
    },
    "tokens": {
        "PNK": {
            "address": None,  # From env
            "decimals": 18,
            "symbol": "PNK"
        },
        "WETH": {
            "address": None,  # From env
            "decimals": 18,
            "symbol": "WETH"
        },
        "sDAI": {
            "address": "0x89C80A4540A00b5270347E02e2E144c71da2EceD",
            "decimals": 18,
            "symbol": "sDAI"
        }
    }
}
```

## Notes

1. **Token Order**: Must dynamically determine token0/token1 positions in pools
2. **Decimal Handling**: All calculations must account for 18 decimal precision
3. **Gas Optimization**: Batch RPC calls where possible to reduce latency
4. **Error Handling**: Implement fallback mechanisms for RPC failures
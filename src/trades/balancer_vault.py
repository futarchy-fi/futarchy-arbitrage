"""
Balancer trades for FutarchyArbExecutorV4 using the **Batch Router**.

Responsibilities:
- Encode Router.swapExactIn for a 2-hop sDAI -> WXDAI -> GNO path.
- Quote output via Router.querySwapExactIn for slippage bounds.
- Build an Execute10Batch payload for V4.runTrade.

Uses the entrypoint address for swaps (matching successful traces).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Tuple, List

from web3 import Web3
from eth_abi import encode as abi_encode
from src.config.abis.balancer import BALANCER_BATCH_ROUTER_ABI

PATCH_NONE = 255  # type(uint8).max in Solidity

# Router addresses on Gnosis
ROUTER_ENTRYPOINT = "0xe2fa4e1d17725e72dcdafe943ecf45df4b9e285b"  # the address in your working trace
ROUTER_IMPL       = "0xba1333333333a1ba1108e8412f11850a5c319ba9"  # module (keep for quoting)

@dataclass
class VaultConfig:
    vault: str                   # Balancer Vault
    pool_sdai_aave_gno: str      # Pool 1: sDAI/Aave GNO pool address
    token_sdai: str
    token_aave_gno: str          # Aave GNO token (0x7c16...)
    router_entrypoint: str = ROUTER_ENTRYPOINT
    router_impl: str = ROUTER_IMPL


def _router_entrypoint(w3: Web3, cfg: VaultConfig):
    return w3.eth.contract(address=w3.to_checksum_address(cfg.router_entrypoint),
                           abi=BALANCER_BATCH_ROUTER_ABI)

def _router_impl(w3: Web3, cfg: VaultConfig):
    return w3.eth.contract(address=w3.to_checksum_address(cfg.router_impl),
                           abi=BALANCER_BATCH_ROUTER_ABI)


def encode_query_swap_exact_in_lowlevel(
    w3: Web3,
    cfg: VaultConfig,
    amount_in: int,
    sender: str,
) -> bytes:
    """
    Low-level encoding of querySwapExactIn to avoid Web3 nested tuple issues.
    Returns raw calldata for eth_call.
    """
    # Function selector for querySwapExactIn - 0x07b1d5ac
    selector = bytes.fromhex("07b1d5ac")
    
    # Build the paths array with explicit encoding
    # Path struct: (tokenIn, steps[], exactAmountIn, minAmountOut)
    # Step struct: (pool, tokenOut, isBuffer)
    
    # Encode the nested structs manually
    paths_encoded = abi_encode(
        ["(address,(address,address,bool)[],uint256,uint256)[]"],
        [[
            (
                w3.to_checksum_address(cfg.token_sdai),  # tokenIn
                [
                    (w3.to_checksum_address(cfg.pool_sdai_wxdai), w3.to_checksum_address(cfg.token_wxdai), False),
                    (w3.to_checksum_address(cfg.pool_wxdai_comp), w3.to_checksum_address(cfg.token_comp), False),
                ],  # steps
                int(amount_in),  # exactAmountIn
                0  # minAmountOut (0 for query)
            )
        ]]
    )
    
    # Encode the full call
    calldata = selector + abi_encode(
        ["bytes", "address", "bytes"],
        [paths_encoded, w3.to_checksum_address(sender), b""]
    )
    
    return calldata


def _build_path_structs(w3: Web3, cfg: VaultConfig, amount_in: int, min_out: int):
    """
    Build the 'paths' arg for Router.swapExactIn / querySwapExactIn:
      paths: IBatchRouter.SwapPathExactAmountIn[]
        - tokenIn: sDAI
        - steps: [(pool: sDAI/Aave GNO, tokenOut: Aave GNO)]
        - exactAmountIn: amount_in
        - minAmountOut: min_out
    """
    steps = [
        (
            w3.to_checksum_address(cfg.pool_sdai_aave_gno),  # pool
            w3.to_checksum_address(cfg.token_aave_gno),      # tokenOut
            False                                             # isBuffer
        ),
    ]
    path = (
        w3.to_checksum_address(cfg.token_sdai),  # tokenIn
        steps,                                    # steps
        int(amount_in),                           # exactAmountIn
        int(min_out)                              # minAmountOut
    )
    return [path]


def encode_router_swap_exact_in(
    w3: Web3,
    cfg: VaultConfig,
    amount_in: int,
    min_out: int,
    deadline_secs: int = 1800,
) -> Tuple[str, bytes]:
    """Encode BatchRouter.swapExactIn(paths, deadline, wethIsEth=false, userData='')."""
    router = _router_entrypoint(w3, cfg)  # <<< entrypoint, matches working trace
    deadline = int(time.time()) + int(deadline_secs)
    paths = _build_path_structs(w3, cfg, amount_in=amount_in, min_out=min_out)
    calldata = router.functions.swapExactIn(
        paths,
        deadline,
        False,   # wethIsEth
        b""      # userData
    )._encode_transaction_data()
    return cfg.router_entrypoint, calldata


def get_pool_spot_price(w3: Web3, cfg: VaultConfig) -> float:
    """
    Get spot price from the sDAI/Aave GNO pool.
    Returns aave_gno_per_sdai ratio.
    """
    # Get balances directly from the pool
    pool_addr = cfg.pool_sdai_aave_gno
    
    try:
        # Use getCurrentLiveBalances() which we know works
        selector = w3.keccak(text="getCurrentLiveBalances()")[:4]
        result = w3.eth.call({
            'to': w3.to_checksum_address(pool_addr),
            'data': '0x' + selector.hex()
        })
        
        if len(result) >= 128:
            # From our testing:
            # Token 0 (Aave GNO): offset 64-96
            # Token 1 (sDAI): offset 96-128
            aave_gno_balance = int.from_bytes(result[64:96], 'big')
            sdai_balance = int.from_bytes(result[96:128], 'big')
            
            # Price = aave_gno_balance / sdai_balance
            aave_gno_per_sdai = aave_gno_balance / sdai_balance if sdai_balance > 0 else 0.007454
            
            print(f"  Pool (sDAI/Aave GNO): 1 sDAI = {aave_gno_per_sdai:.6f} Aave GNO")
            print(f"    Aave GNO balance: {w3.from_wei(aave_gno_balance, 'ether'):.2f}")
            print(f"    sDAI balance: {w3.from_wei(sdai_balance, 'ether'):.2f}")
            
            return aave_gno_per_sdai
            
    except Exception as e:
        print(f"  Warning: Could not fetch pool price: {e}")
        # Return the last known price
        return 0.007454  # ~1 sDAI = 0.007454 Aave GNO


def quote_aave_gno_out(
    w3: Web3,
    cfg: VaultConfig,
    amount_in: int,
    slippage_bps: int,
    executor_address: str,
) -> Tuple[int, int]:
    """
    Quote based on actual pool spot price with slippage.
    Returns (quote_out, min_out) in wei.
    """
    print(f"  Fetching current pool price...")
    
    # Get spot price from pool
    aave_gno_per_sdai = get_pool_spot_price(w3, cfg)
    
    # Calculate expected output
    quote_out = int(amount_in * aave_gno_per_sdai)
    
    print(f"  Rate: 1 sDAI = {aave_gno_per_sdai:.6f} Aave GNO")
    print(f"  Expected output: {w3.from_wei(quote_out, 'ether'):.6f} Aave GNO")
    
    # Apply slippage
    min_out = (quote_out * (10_000 - int(slippage_bps))) // 10_000
    if min_out == 0:
        min_out = 1
        
    print(f"  Min output with {slippage_bps/100:.1f}% slippage: {w3.from_wei(min_out, 'ether'):.6f} Aave GNO")
    
    return quote_out, min_out


def build_execute10_buy_aave_gno(
    w3: Web3,
    cfg: VaultConfig,
    amount_in: int,
    min_out: int,
    executor_address: str,
):
    """
    Return Execute10Batch for V4.runTrade that calls **Batch Router**.
    spender = 0 to skip approve (Balancer uses Permit2 instead).
    """
    target, data = encode_router_swap_exact_in(
        w3, cfg, amount_in=amount_in, min_out=min_out
    )

    targets = [w3.to_checksum_address(target)] + [Web3.to_checksum_address("0x" + "00"*20)] * 9
    calldatas = [data] + [b""] * 9

    batch = (
        targets,
        calldatas,
        1,  # count
        w3.to_checksum_address(cfg.token_sdai),      # tokenIn
        w3.to_checksum_address(cfg.token_aave_gno),  # tokenOut (Aave GNO)
        Web3.to_checksum_address("0x" + "00"*20),   # spender = 0 to skip approve
        int(amount_in),
        int(min_out),
        PATCH_NONE,                                   # no runtime patching
        0,
        (1 << 256) - 1,                               # type(uint256).max
        0
    )
    return batch
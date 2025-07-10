import os, time
from typing import List, Tuple
from eth_account import Account
from web3 import Web3

# --------------------------------------------------------------------------- #
# 0️⃣  Setup web3 & signing middleware                                        #
# --------------------------------------------------------------------------- #
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))   # chain-id 100
acct = Account.from_key(os.environ["PRIVATE_KEY"])
w3.eth.default_account = acct.address

# --------------------------------------------------------------------------- #
# 1️⃣  Minimal ERC-20 ABI (approve only)                                      #
# --------------------------------------------------------------------------- #
ERC20_ABI = [
    {
        "name":  "approve",
        "type":  "function",
        "stateMutability": "nonpayable",
        "inputs":  [
            {"name": "spender", "type": "address"},
            {"name": "amount",  "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "allowance",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    }
]

# --------------------------------------------------------------------------- #
# 2️⃣  Tuple list with (token, spender, amount)                               #
#     - amounts are raw uint256 (already in token-decimals)                   #
# --------------------------------------------------------------------------- #
MAX_UINT256 = (1 << 256) - 1         # 2**256 − 1

# Build allowances list dynamically, skipping missing env vars
ALLOWANCES: List[Tuple[str, str, int]] = []

# Helper function to safely add allowance
def add_allowance(token_env: str, spender_env: str, amount: int, comment: str = "") -> None:
    if token_env in os.environ and spender_env in os.environ:
        ALLOWANCES.append((os.environ[token_env], os.environ[spender_env], amount))
    else:
        missing_vars = []
        if token_env not in os.environ:
            missing_vars.append(token_env)
        if spender_env not in os.environ:
            missing_vars.append(spender_env)
        print(f"⚠️  Skipping allowance {comment}: missing {', '.join(missing_vars)}")

# SwapR router – swaps that use a token *as input*
add_allowance("SDAI_TOKEN_ADDRESS", "SWAPR_ROUTER_ADDRESS", MAX_UINT256, "sDAI → SwapR Router")
add_allowance("SWAPR_SDAI_YES_ADDRESS", "SWAPR_ROUTER_ADDRESS", MAX_UINT256, "sDAI-YES → SwapR Router")
add_allowance("SWAPR_SDAI_NO_ADDRESS", "SWAPR_ROUTER_ADDRESS", MAX_UINT256, "sDAI-NO → SwapR Router")
add_allowance("SWAPR_GNO_YES_ADDRESS", "SWAPR_ROUTER_ADDRESS", MAX_UINT256, "GNO-YES → SwapR Router")
add_allowance("SWAPR_GNO_NO_ADDRESS", "SWAPR_ROUTER_ADDRESS", MAX_UINT256, "GNO-NO → SwapR Router")

# Futarchy router – splitting collateral and later merging positions
add_allowance("SDAI_TOKEN_ADDRESS", "FUTARCHY_ROUTER_ADDRESS", MAX_UINT256, "sDAI → Futarchy Router")
add_allowance("COMPANY_TOKEN_ADDRESS", "FUTARCHY_ROUTER_ADDRESS", MAX_UINT256, "Company token → Futarchy Router")
add_allowance("SWAPR_GNO_YES_ADDRESS", "FUTARCHY_ROUTER_ADDRESS", MAX_UINT256, "GNO-YES → Futarchy Router")
add_allowance("SWAPR_GNO_NO_ADDRESS", "FUTARCHY_ROUTER_ADDRESS", MAX_UINT256, "GNO-NO → Futarchy Router")
add_allowance("SWAPR_SDAI_YES_ADDRESS", "FUTARCHY_ROUTER_ADDRESS", MAX_UINT256, "sDAI-YES → Futarchy Router")
add_allowance("SWAPR_SDAI_NO_ADDRESS", "FUTARCHY_ROUTER_ADDRESS", MAX_UINT256, "sDAI-NO → Futarchy Router")

# Balancer router – selling plain Company token for sDAI
add_allowance("COMPANY_TOKEN_ADDRESS", "BALANCER_ROUTER_ADDRESS", MAX_UINT256, "Company token → Balancer Router")

# Balancer router – buying Company token with sDAI
add_allowance("SDAI_TOKEN_ADDRESS", "BALANCER_ROUTER_ADDRESS", MAX_UINT256, "sDAI → Balancer Router")

# CowSwap GPv2 Settlement – sells & buys any token
add_allowance("SDAI_TOKEN_ADDRESS", "GPV2_SETTLEMENT_ADDRESS", MAX_UINT256, "sDAI → CowSwap")
add_allowance("COMPANY_TOKEN_ADDRESS", "GPV2_SETTLEMENT_ADDRESS", MAX_UINT256, "Company token → CowSwap")

# Add PNK token directly since it's not in env vars
PNK_TOKEN_ADDRESS = "0x37b60f4E9A31A64cCc0024dce7D0fD07eAA0F7B3"  # PNK on Gnosis Chain
if "GPV2_SETTLEMENT_ADDRESS" in os.environ:
    ALLOWANCES.append((PNK_TOKEN_ADDRESS, os.environ["GPV2_SETTLEMENT_ADDRESS"], MAX_UINT256))
else:
    print("⚠️  Skipping allowance PNK → CowSwap: missing GPV2_SETTLEMENT_ADDRESS")

# --------------------------------------------------------------------------- #
# 3️⃣  Push on-chain approvals                                                #
# --------------------------------------------------------------------------- #
def send_allowances() -> None:
    nonce = w3.eth.get_transaction_count(acct.address)
    for token, spender, amount in ALLOWANCES:
        token   = w3.to_checksum_address(token)
        spender = w3.to_checksum_address(spender)

        # Obtain an ERC20 contract instance (Web3 v6+ requires keyword args)
        token_contract = w3.eth.contract(address=token, abi=ERC20_ABI)

        # Check current allowance
        current_allowance = token_contract.functions.allowance(acct.address, spender).call()
        
        # Skip if already has max allowance
        if current_allowance == MAX_UINT256:
            print(f"✓ {spender[:6]}… already has max allowance for {token[:6]}… (skipping)")
            continue

        tx = token_contract.functions.approve(
            spender, amount
        ).build_transaction(
            {
                "from":  acct.address,
                "nonce": nonce,
                "gas":   100_000,                       # ≈10 k margin
                "maxFeePerGas":        w3.to_wei("2", "gwei"),
                "maxPriorityFeePerGas": w3.to_wei("1", "gwei"),
                "chainId": 100,
            }
        )

        # sign transaction manually for web3.py 6.x compatibility
        signed_tx = acct.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"→ approve {spender[:6]}… for {amount} on {token[:6]}… "
              f"[{tx_hash.hex()}]")

        # wait (optional—but helpful to stop on revert)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise RuntimeError("Approval reverted")

        nonce += 1  # manual nonce tracking to avoid race conditions


if __name__ == "__main__":
    send_allowances()

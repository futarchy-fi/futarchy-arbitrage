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
    }
]

# --------------------------------------------------------------------------- #
# 2️⃣  Tuple list with (token, spender, amount)                               #
#     - amounts are raw uint256 (already in token-decimals)                   #
# --------------------------------------------------------------------------- #
MAX_UINT256 = (1 << 256) - 1         # 2**256 − 1

ALLOWANCES: List[Tuple[str, str, int]] = [
    # (token                      , spender                       , amount_wei)
    # ----------------------------------------------------------------------- #
    # SwapR router – swaps that use a token *as input*                        #
    (os.environ["SDAI_TOKEN_ADDRESS"],  # sDAI
     os.environ["SWAPR_ROUTER_ADDRESS"],  # SwapR Router
     MAX_UINT256),
    (os.environ["SWAPR_SDAI_YES_ADDRESS"],  # sDAI-YES
     os.environ["SWAPR_ROUTER_ADDRESS"],
     MAX_UINT256),
    (os.environ["SWAPR_SDAI_NO_ADDRESS"],  # sDAI-NO
     os.environ["SWAPR_ROUTER_ADDRESS"],
     MAX_UINT256),
    (os.environ["SWAPR_GNO_YES_ADDRESS"],  # GNO-YES
     os.environ["SWAPR_ROUTER_ADDRESS"],
     MAX_UINT256),
    (os.environ["SWAPR_GNO_NO_ADDRESS"],  # GNO-NO
     os.environ["SWAPR_ROUTER_ADDRESS"],
     MAX_UINT256),

    # Futarchy router – splitting collateral and later merging positions      #
    (os.environ["SDAI_TOKEN_ADDRESS"],  # sDAI (collateral)
     os.environ["FUTARCHY_ROUTER_ADDRESS"],  # Futarchy Router
     MAX_UINT256),
    (os.environ["SWAPR_GNO_YES_ADDRESS"],  # GNO-YES
     os.environ["FUTARCHY_ROUTER_ADDRESS"],
     MAX_UINT256),
    (os.environ["SWAPR_GNO_NO_ADDRESS"],  # GNO-NO
     os.environ["FUTARCHY_ROUTER_ADDRESS"],
     MAX_UINT256),
    (os.environ["SWAPR_SDAI_YES_ADDRESS"],  # sDAI-YES
     os.environ["FUTARCHY_ROUTER_ADDRESS"],
     MAX_UINT256),
    (os.environ["SWAPR_SDAI_NO_ADDRESS"],  # sDAI-NO
     os.environ["FUTARCHY_ROUTER_ADDRESS"],
     MAX_UINT256),

    # Balancer router – selling plain GNO for sDAI                             #
    (os.environ["GNO_TOKEN_ADDRESS"],  # GNO
     os.environ["BALANCER_ROUTER_ADDRESS"],  # Balancer Router
     MAX_UINT256),
]

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

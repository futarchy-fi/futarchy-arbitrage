import os, time
from eth_account import Account
from web3 import Web3
from web3.middleware import construct_sign_and_send_raw_middleware

# --------------------------------------------------------------------------- #
# 0️⃣  Setup web3 & signing middleware                                        #
# --------------------------------------------------------------------------- #
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))   # chain-id 100
acct = Account.from_key(os.environ["PRIVATE_KEY"])
w3.middleware_onion.add(construct_sign_and_send_raw_middleware(acct))
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

ALLOWANCES: list[tuple[str, str, int]] = [
    # (token                      , spender                       , amount_wei)
    # ----------------------------------------------------------------------- #
    # SwapR router – swaps that use a token *as input*                        #
    ("0xaf204776c7245bF4147c2612BF6e5972Ee483701",  # sDAI
     "0xfFB643E73f280B97809A8b41f7232AB401a04ee1",  # SwapR Router
     MAX_UINT256),
    ("0x839454be590E3F6F593Ebb38179388d19f2e9cB0",  # sDAI-YES
     "0xfFB643E73f280B97809A8b41f7232AB401a04ee1",
     MAX_UINT256),
    ("0xBA345931638963C60Df3aba8D2f07E14334B81ed",  # sDAI-NO
     "0xfFB643E73f280B97809A8b41f7232AB401a04ee1",
     MAX_UINT256),
    ("0x4daC7974823a41407e9b8D041585158C09433322",  # GNO-YES
     "0xfFB643E73f280B97809A8b41f7232AB401a04ee1",
     MAX_UINT256),
    ("0xD0a8A12DB9c2764e8087e5D4Bf42e9c7a074d335",  # GNO-NO
     "0xfFB643E73f280B97809A8b41f7232AB401a04ee1",
     MAX_UINT256),

    # Futarchy router – splitting collateral and later merging positions      #
    ("0xaf204776c7245bF4147c2612BF6e5972Ee483701",  # sDAI (collateral)
     "0x7495a583ba85875d59407781b4958ED6e0E1228f",  # Futarchy Router
     MAX_UINT256),
    ("0x4daC7974823a41407e9b8D041585158C09433322",  # GNO-YES
     "0x7495a583ba85875d59407781b4958ED6e0E1228f",
     MAX_UINT256),
    ("0xD0a8A12DB9c2764e8087e5D4Bf42e9c7a074d335",  # GNO-NO
     "0x7495a583ba85875d59407781b4958ED6e0E1228f",
     MAX_UINT256),
    ("0x839454be590E3F6F593Ebb38179388d19f2e9cB0",  # sDAI-YES
     "0x7495a583ba85875d59407781b4958ED6e0E1228f",
     MAX_UINT256),
    ("0xBA345931638963C60Df3aba8D2f07E14334B81ed",  # sDAI-NO
     "0x7495a583ba85875d59407781b4958ED6e0E1228f",
     MAX_UINT256),

    # Balancer router – selling plain GNO for sDAI                             #
    ("0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb",  # GNO
     "0xe2fa4e1d17725e72dcdAfe943Ecf45dF4B9E285b",  # Balancer Router
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

        # sign-and-send via middleware; returns hash bytes
        tx_hash = w3.eth.send_transaction(tx)
        print(f"→ approve {spender[:6]}… for {amount} on {token[:6]}… "
              f"[{tx_hash.hex()}]")

        # wait (optional—but helpful to stop on revert)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise RuntimeError("Approval reverted")

        nonce += 1  # manual nonce tracking to avoid race conditions


if __name__ == "__main__":
    send_allowances()

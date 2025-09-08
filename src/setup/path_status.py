#!/usr/bin/env python3
from __future__ import annotations

"""
Path Status Checker

For a given HD derivation path, this tool:
- Resolves the main wallet (EOA) address for that path (via mnemonic or index.json)
- Prints its native xDAI balance
- Looks up a deployed FutarchyArbExecutorV5 contract for that path (if any) and
  prints the contract's sDAI (or provided ERC20) token balance

Usage examples:
  python -m src.setup.path_status --path "m/44'/60'/0'/0/5" --env .env
  python -m src.setup.path_status --path "m/44'/60'/0'/0/5" --mnemonic-env MNEMONIC
  python -m src.setup.path_status --path "m/44'/60'/0'/0/5" --token 0xTokenAddr

Environment:
  - RPC_URL or GNOSIS_RPC_URL should be set (or pass via --env)
  - SDAI_TOKEN_ADDRESS is used as default token if --token not provided (falls back to Gnosis sDAI)
  - Automatically loads .env.seed first (if present), then any --env files, and finally .env if no --env given
"""

import argparse
import os
from pathlib import Path
import json
from typing import Optional, Tuple

from web3 import Web3
from eth_utils import to_checksum_address

try:
    from dotenv import load_dotenv
except Exception:  # lightweight fallback
    def load_dotenv(path: Optional[str] = None, override: bool = False):
        if not path:
            return False
        try:
            with open(path, "r") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    if s.startswith("export "):
                        s = s[7:]
                    if "=" in s:
                        k, v = s.split("=", 1)
                        v = v.strip().strip('"').strip("'")
                        if override or (k not in os.environ):
                            os.environ[k] = v
            return True
        except Exception:
            return False

# Reuse helpers from setup modules
from .wallet_manager import load_index
from .keystore import derive_privkey_from_mnemonic
from .deployment_links import find_by_path as find_deploy_link_by_path


SDAI_GNOSIS_DEFAULT = "0xaf204776c7245bF4147c2612BF6e5972Ee483701"

ERC20_MIN_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]


def _build_w3() -> Web3:
    rpc = os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL")
    if not rpc:
        raise SystemExit("RPC_URL (or GNOSIS_RPC_URL) is required; pass --env or set in environment")
    w3 = Web3(Web3.HTTPProvider(rpc))
    try:
        from web3.middleware import geth_poa_middleware

        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        try:
            from web3.middleware import ExtraDataToPOAMiddleware

            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception:
            pass
    if hasattr(w3, "is_connected") and callable(getattr(w3, "is_connected")):
        if not w3.is_connected():
            raise SystemExit("Failed to connect to RPC_URL")
    return w3


def _resolve_address_for_path(path: str, *, mnemonic: Optional[str], index_path: Path) -> str:
    # Prefer mnemonic if provided
    if mnemonic:
        _, addr = derive_privkey_from_mnemonic(mnemonic, path)
        return to_checksum_address(addr)

    # Else, try index.json for a record with this path
    records = load_index(index_path)
    match = next((r for r in records if r.get("path") == path and r.get("address")), None)
    if not match:
        raise SystemExit("Path not found in index.json and no mnemonic provided. Provide --mnemonic/--mnemonic-env or ensure index contains this path.")
    return to_checksum_address(match["address"])  # type: ignore[index]


def _get_token_balance(w3: Web3, token: str, holder: str) -> int:
    erc = w3.eth.contract(address=to_checksum_address(token), abi=ERC20_MIN_ABI)
    return int(erc.functions.balanceOf(to_checksum_address(holder)).call())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check wallet xDAI balance and deployed executor token balance for a given HD path")
    p.add_argument("--path", required=True, help="HD derivation path (e.g., m/44'/60'/0'/0/5)")
    p.add_argument(
        "--env",
        dest="env_files",
        action="append",
        help=".env file(s) to load (can be passed multiple times). .env.seed is always loaded first if present."
    )
    p.add_argument("--mnemonic", help="BIP-39 mnemonic to derive the address (preferred)")
    p.add_argument("--mnemonic-env", help="Env var name that holds the mnemonic")
    p.add_argument("--index", help="Wallet index file (default build/wallets/index.json)")
    p.add_argument("--token", help="ERC20 token address for contract balance (default $SDAI_TOKEN_ADDRESS or Gnosis sDAI)")
    p.add_argument("--json", action="store_true", help="Print result as JSON to stdout")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Load env files with precedence:
    # 1) .env.seed (if present), 2) any --env files in order, else 3) .env fallback
    try:
        seed_env = Path(".env.seed")
        if seed_env.exists():
            load_dotenv(str(seed_env), override=False)
    except Exception:
        pass

    if getattr(args, "env_files", None):
        for env_path in args.env_files:
            try:
                load_dotenv(env_path, override=False)
            except Exception:
                pass
    else:
        # Fallback to .env if no explicit files provided
        try:
            load_dotenv(".env", override=False)
        except Exception:
            pass

    # Resolve token address
    token_addr = args.token or os.getenv("SDAI_TOKEN_ADDRESS") or SDAI_GNOSIS_DEFAULT

    # Resolve mnemonic if provided via env name
    mnemonic: Optional[str] = args.mnemonic
    if not mnemonic and args.mnemonic_env:
        mnemonic = os.getenv(args.mnemonic_env)
    if not mnemonic:
        # fallback to MNEMONIC
        mnemonic = os.getenv("MNEMONIC")

    # Index path
    index_path = Path(args.index or "build/wallets/index.json")

    # Web3
    w3 = _build_w3()

    # Resolve EOA address for path
    address = _resolve_address_for_path(args.path, mnemonic=mnemonic, index_path=index_path)

    # Wallet xDAI balance
    bal_wei = int(w3.eth.get_balance(address))
    bal_eth = w3.from_wei(bal_wei, "ether")

    result = {
        "wallet": {
            "path": args.path,
            "address": address,
            "xdai": str(bal_eth),
            "xdai_wei": str(bal_wei),
        }
    }
    if not args.json:
        print("Wallet")
        print(f"  Path:      {args.path}")
        print(f"  Address:   {address}")
        print(f"  xDAI:      {bal_eth} (wei={bal_wei})")

    # Deployment lookup by path
    link = find_deploy_link_by_path(args.path)
    if not link:
        if args.json:
            result["deployment"] = {"found": False}
            print(json.dumps(result))
            return 0
        print("\nDeployment")
        print("  No deployment found for this path (no address in build/wallets/deploy_v5_*.json)")
        return 0

    exec_addr = to_checksum_address(link.address)
    token_bal_wei = _get_token_balance(w3, token_addr, exec_addr)
    token_bal = w3.from_wei(token_bal_wei, "ether")

    result["deployment"] = {
        "found": True,
        "executor": exec_addr,
        "token": to_checksum_address(token_addr),
        "balance": str(token_bal),
        "balance_wei": str(token_bal_wei),
        "tx": link.tx,
        "log": link.log_file,
    }
    if args.json:
        print(json.dumps(result))
        return 0
    print("\nDeployment")
    print(f"  Executor:  {exec_addr}")
    print(f"  Token:     {to_checksum_address(token_addr)}")
    print(f"  Balance:   {token_bal} (wei={token_bal_wei})")
    if link.tx:
        print(f"  Tx:        {link.tx}")
    if link.log_file:
        print(f"  Log:       {link.log_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils import to_checksum_address
from web3 import Web3
from web3.types import TxParams

from .wallet_manager import load_index, scan_keystores, save_index, upsert_record, record_for
from .keystore import encrypt_private_key, write_keystore, derive_privkey_from_mnemonic, resolve_password


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_env(path: Optional[str]) -> None:
    if not path:
        return
    try:
        from dotenv import load_dotenv as _ld

        _ld(path)
    except Exception:
        # Minimal loader
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[7:]
                    if "=" in line:
                        k, v = line.split("=", 1)
                        v = v.strip().strip('"').strip("'")
                        os.environ.setdefault(k.strip(), v)
        except Exception:
            pass


def _build_w3(rpc_url: Optional[str] = None) -> Web3:
    url = rpc_url or os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL")
    if not url:
        raise EnvironmentError("Set --rpc-url or RPC_URL/GNOSIS_RPC_URL in env")
    w3 = Web3(Web3.HTTPProvider(url))
    # Inject POA middleware (Gnosis)
    try:
        from web3.middleware import geth_poa_middleware

        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass
    return w3


def _parse_amount_eth(amount_str: str) -> Decimal:
    try:
        v = Decimal(str(amount_str))
        if v <= 0:
            raise ValueError
        return v
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid --amount: {amount_str}")


def _to_wei(w3: Web3, value: Any, unit: str) -> int:
    try:
        # web3.py v6 style
        to_wei = getattr(w3, "to_wei", None)
        if callable(to_wei):
            return int(to_wei(value, unit))
        # fallback to class method (v5)
        return int(Web3.toWei(value, unit))
    except Exception:
        return int(Web3.toWei(value, unit))


def _to_wei_eth(w3: Web3, amount_eth: Decimal) -> int:
    return _to_wei(w3, str(amount_eth), "ether")


def _default_log_path(base_dir: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return base_dir / f"funding_{ts}.json"


def _filter_addresses(records: List[Dict[str, Any]], only: Optional[str]) -> List[str]:
    addrs = [to_checksum_address(r.get("address")) for r in records if r.get("address")]
    if not only:
        return addrs
    only = only.strip()
    if not only:
        return addrs
    patterns = [p.strip() for p in only.split(",") if p.strip()]
    # If any pattern contains glob wildcard, fnmatch against addresses; else treat all as literal addresses
    import fnmatch

    if any("*" in p or "?" in p for p in patterns):
        selected: List[str] = []
        for a in addrs:
            if any(fnmatch.fnmatch(a, p) for p in patterns):
                selected.append(a)
        return selected
    # Else, treat CSV as explicit addresses (case-insensitive)
    wanted = {to_checksum_address(x) for x in patterns}
    return [a for a in addrs if a in wanted]


def _filter_records_by_path(records: List[Dict[str, Any]], only_path: Optional[str]) -> List[Dict[str, Any]]:
    if not only_path:
        return records
    pat = only_path.strip()
    if not pat:
        return records
    import fnmatch

    patterns = [p.strip() for p in pat.split(",") if p.strip()]
    selected: List[Dict[str, Any]] = []
    for r in records:
        path = r.get("path")
        if not path:
            continue
        if any(fnmatch.fnmatch(path, p) for p in patterns):
            selected.append(r)
    return selected


def _is_eip1559_supported(w3: Web3) -> bool:
    try:
        blk = w3.eth.get_block("latest")
        return "baseFeePerGas" in blk
    except Exception:
        return False


@dataclass
class GasConfig:
    type: str  # "eip1559" or "legacy"
    gas_limit: int
    max_fee_gwei: Optional[Decimal] = None
    prio_fee_gwei: Optional[Decimal] = None
    gas_price_gwei: Optional[Decimal] = None

    def as_tx_fields(self, w3: Web3) -> Dict[str, int]:
        if self.type == "eip1559":
            assert self.max_fee_gwei is not None and self.prio_fee_gwei is not None
            return {
                "maxFeePerGas": _to_wei(w3, str(self.max_fee_gwei), "gwei"),
                "maxPriorityFeePerGas": _to_wei(w3, str(self.prio_fee_gwei), "gwei"),
                "gas": int(self.gas_limit),
            }
        else:
            assert self.gas_price_gwei is not None
            return {
                "gasPrice": _to_wei(w3, str(self.gas_price_gwei), "gwei"),
                "gas": int(self.gas_limit),
            }

    def max_gas_cost_wei(self, w3: Web3, tx_count: int) -> int:
        if tx_count <= 0:
            return 0
        if self.type == "eip1559":
            assert self.max_fee_gwei is not None
            return _to_wei(w3, str(self.max_fee_gwei), "gwei") * int(self.gas_limit) * tx_count
        else:
            assert self.gas_price_gwei is not None
            return _to_wei(w3, str(self.gas_price_gwei), "gwei") * int(self.gas_limit) * tx_count


def _load_recipients(out_dir: Path, index_path: Optional[Path]) -> List[Dict[str, Any]]:
    if index_path and index_path.exists():
        return load_index(index_path)
    # Fallback to scanning keystore dir
    return scan_keystores(out_dir)


def fund_xdai(
    *,
    out_dir: Path,
    index_path: Optional[Path],
    amount_eth: str,
    from_env: str,
    env_file: Optional[str] = None,
    rpc_url: Optional[str] = None,
    chain_id: int = 100,
    only: Optional[str] = None,
    only_path: Optional[str] = None,
    ensure_paths: Optional[str] = None,
    ensure_mnemonic: Optional[str] = None,
    ensure_mnemonic_env: Optional[str] = None,
    keystore_pass: Optional[str] = None,
    keystore_pass_env: Optional[str] = None,
    always_send: bool = False,
    gas: Optional[GasConfig] = None,
    timeout: int = 120,
    dry_run: bool = False,
    log_path: Optional[Path] = None,
    require_confirm: bool = False,
) -> int:
    _load_env(env_file)

    # Resolve funder account
    pk = os.getenv(from_env) or os.getenv("PRIVATE_KEY")
    if not pk:
        raise EnvironmentError(f"Set {from_env} or PRIVATE_KEY in env (use --env-file if needed)")
    if not pk.startswith("0x"):
        pk = "0x" + pk
    acct: LocalAccount = Account.from_key(pk)
    funder = to_checksum_address(acct.address)

    # Connect web3
    w3 = _build_w3(rpc_url)
    # Connectivity check
    try:
        if hasattr(w3, "is_connected") and callable(getattr(w3, "is_connected")):
            if not w3.is_connected():
                raise EnvironmentError("Web3 provider not connected (check RPC URL)")
    except Exception:
        # Proceed; next calls will raise with clearer errors
        pass

    actual_chain_id = w3.eth.chain_id
    if chain_id and actual_chain_id != chain_id:
        raise SystemExit(f"Unexpected chainId {actual_chain_id}; expected {chain_id}. Use --chain-id to override.")

    # Resolve gas config
    gas = gas or GasConfig(type="eip1559", gas_limit=21000, max_fee_gwei=Decimal("2"), prio_fee_gwei=Decimal("1"))
    # Gas sanity checks and EIP-1559 support
    if gas.gas_limit < 21000:
        raise SystemExit("gas-limit must be >= 21000 for native transfers")
    if gas.type == "eip1559" and not _is_eip1559_supported(w3):
        raise SystemExit("RPC appears to not support EIP-1559 (no baseFeePerGas). Use --legacy or different RPC.")

    # Optionally ensure specific HD paths exist and are indexed
    ensured_records: List[Dict[str, Any]] = []
    if ensure_paths:
        if index_path is None:
            index_path = out_dir / "index.json"
        existing = load_index(index_path)
        # Map existing by path
        existing_by_path = {r.get("path"): r for r in existing if r.get("path")}
        paths = [p.strip() for p in str(ensure_paths).split(",") if p.strip()]
        # Determine which are missing
        missing = [p for p in paths if p not in existing_by_path]
        if missing:
            mnemonic = ensure_mnemonic or (os.getenv(ensure_mnemonic_env) if ensure_mnemonic_env else None) or os.getenv("MNEMONIC")
            if not mnemonic:
                raise SystemExit("--ensure-path requires --mnemonic/--mnemonic-env or MNEMONIC in env when creating missing paths")
            password = resolve_password(keystore_pass, keystore_pass_env, "PRIVATE_KEY")
        updated = existing
        for path in paths:
            rec = existing_by_path.get(path)
            if rec is None:
                priv_hex, address = derive_privkey_from_mnemonic(mnemonic, path)  # type: ignore[arg-type]
                ks, _ = encrypt_private_key(priv_hex, password)  # type: ignore[arg-type]
                ks_path = write_keystore(out_dir, address, ks)
                rec = record_for(address, ks_path, source="hd", derivation_path=path, tags=None)
                updated = upsert_record(updated, rec)
            ensured_records.append(rec)
        if updated is not existing:
            save_index(index_path, updated)

    # Load recipients
    records = _load_recipients(out_dir, index_path)
    # Apply path filter first (only available when using index records)
    records = _filter_records_by_path(records, only_path)
    if ensure_paths and not only and not only_path:
        # Narrow to ensured paths only when no explicit filters provided
        ensured_set = {to_checksum_address(r.get("address")) for r in ensured_records}
        records = [r for r in records if to_checksum_address(r.get("address")) in ensured_set]
    if not records:
        print("No wallets found (index missing and keystore dir empty) or no matches for --only-path")
        return 1
    recipients = _filter_addresses(records, only)
    if not recipients:
        print("No matching recipients after --only filtering")
        return 1

    # Convert amount and gather balances
    target_eth = _parse_amount_eth(amount_eth)
    target_wei = _to_wei_eth(w3, target_eth)

    before_bal: Dict[str, int] = {}
    deltas: Dict[str, int] = {}
    needs: List[str] = []
    for addr in recipients:
        bal = int(w3.eth.get_balance(addr))
        before_bal[addr] = bal
        delta = target_wei if always_send else max(0, target_wei - bal)
        if delta > 0:
            deltas[addr] = delta
            needs.append(addr)

    tx_count = len(needs)
    total_value = sum(deltas.values())
    gas_budget = gas.max_gas_cost_wei(w3, tx_count)
    funder_bal = int(w3.eth.get_balance(funder))
    sufficient = funder_bal >= total_value + gas_budget

    # Build summary
    summary: Dict[str, Any] = {
        "chain_id": actual_chain_id,
        "rpc_url": rpc_url or os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL"),
        "funder": funder,
        "target_per_wallet_wei": target_wei,
        "always": bool(always_send),
        "tx_count": tx_count,
        "total_value_wei": total_value,
        "gas_budget_wei": gas_budget,
        "funder_balance_wei": funder_bal,
        "sufficient_funds": sufficient,
        "dry_run": bool(dry_run),
        "generated_at": _utc_now_iso(),
        "gas": {
            "type": gas.type,
            "gas_limit": gas.gas_limit,
            "max_fee_gwei": str(gas.max_fee_gwei) if gas.max_fee_gwei is not None else None,
            "priority_fee_gwei": str(gas.prio_fee_gwei) if gas.prio_fee_gwei is not None else None,
            "gas_price_gwei": str(gas.gas_price_gwei) if gas.gas_price_gwei is not None else None,
        },
    }

    # Prepare results list
    results: List[Dict[str, Any]] = []
    for addr in recipients:
        results.append(
            {
                "address": addr,
                "before_wei": before_bal.get(addr, 0),
                "delta_wei": deltas.get(addr, 0),
                "tx_hash": None,
                "status": "skip" if deltas.get(addr, 0) == 0 else ("planned" if dry_run else "pending"),
            }
        )

    # Write dry-run or require confirm
    log_dir = out_dir if out_dir else Path("build/wallets")
    log_path = log_path or _default_log_path(log_dir)

    if dry_run or require_confirm:
        payload = {"summary": summary, "results": results}
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"Prepared funding plan: {log_path}")
        if require_confirm and not dry_run:
            print("Pass --confirm to execute this plan.")
            return 2
        if dry_run:
            return 0

    if not sufficient:
        print("Insufficient funder balance for value + gas. Aborting.")
        payload = {"summary": summary, "results": results}
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(payload, f, indent=2)
        return 2

    # Execute transfers sequentially with nonce management
    nonce = w3.eth.get_transaction_count(funder, "pending")
    gas_fields = gas.as_tx_fields(w3)

    for r in results:
        if r["delta_wei"] == 0:
            r["status"] = "skipped"
            r["after_wei"] = r["before_wei"]
            continue
        to_addr = r["address"]
        value = int(r["delta_wei"])
        tx: TxParams = {
            "to": to_addr,
            "value": value,
            "nonce": nonce,
            "chainId": actual_chain_id,
            **gas_fields,
        }
        signed = Account.sign_transaction(tx, private_key=pk)
        try:
            # Support eth-account variants: rawTransaction (v0.5.x) vs raw_transaction (v0.9+)
            raw = getattr(signed, "rawTransaction", None)
            if raw is None:
                raw = getattr(signed, "raw_transaction", None)
            if raw is None:
                raise AttributeError("SignedTransaction missing rawTransaction/raw_transaction")
            tx_hash = w3.eth.send_raw_transaction(raw)
            r["tx_hash"] = tx_hash.hex()
            # Wait for receipt
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
            r["status"] = "success" if int(receipt.get("status", 0)) == 1 else "failed"
        except Exception as e:
            r["status"] = f"error: {e}"  # capture error
        finally:
            # Update nonce even on error to avoid nonce reuse
            nonce += 1
            # Query new balance
            try:
                r["after_wei"] = int(w3.eth.get_balance(to_addr))
            except Exception:
                r["after_wei"] = None

    # Write final log
    payload = {"summary": summary, "results": results}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(payload, f, indent=2)
    # Return 0 if all needed transfers succeeded or were skipped; non-zero on any error/failed
    errors = [r for r in results if r["delta_wei"] > 0 and r.get("status") not in ("success",)]
    if errors:
        print(f"Funding finished with errors: {len(errors)} failed. Log: {log_path}")
        # Print a short error preview to aid debugging
        for e in errors[:5]:
            print(f" - {e['address']} status={e.get('status')} tx={e.get('tx_hash')}")
        return 1
    else:
        print(f"Funding succeeded. Log: {log_path}")
        return 0

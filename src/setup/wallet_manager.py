#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Iterable, Tuple

from eth_account import Account
from eth_utils import to_checksum_address

from .keystore import (
    encrypt_private_key,
    write_keystore,
    write_env_private_key,
    derive_privkey_from_mnemonic,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_addr(addr: str) -> str:
    return to_checksum_address(addr)


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def load_index(index_path: Path) -> List[Dict[str, Any]]:
    if not index_path.exists():
        return []
    try:
        with open(index_path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "wallets" in data:
            return data["wallets"]
    except Exception:
        pass
    return []


def save_index(index_path: Path, records: List[Dict[str, Any]]) -> None:
    ensure_dir(index_path.parent)
    payload = {"wallets": records}
    with open(index_path, "w") as f:
        json.dump(payload, f, indent=2)


def upsert_record(records: List[Dict[str, Any]], rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    addr = _norm_addr(rec["address"])
    replaced = False
    out: List[Dict[str, Any]] = []
    for r in records:
        if _norm_addr(r.get("address", "0x0")) == addr:
            out.append(rec)
            replaced = True
        else:
            out.append(r)
    if not replaced:
        out.append(rec)
    return out


def scan_keystores(keystore_dir: Path) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    if not keystore_dir.exists():
        return results
    for p in sorted(keystore_dir.glob("0x*.json")):
        try:
            addr = to_checksum_address(p.stem)
        except Exception:
            continue
        results.append({
            "address": addr,
            "keystore_path": str(p),
            "created_at": _utc_now_iso(),
            "tags": [],
        })
    return results


def record_for(address: str, ks_path: Path, *, source: str, derivation_path: Optional[str] = None, tags: Optional[List[str]] = None) -> Dict[str, Any]:
    rec = {
        "address": _norm_addr(address),
        "keystore_path": str(ks_path),
        "created_at": _utc_now_iso(),
        "source": source,
        "tags": tags or [],
    }
    if derivation_path:
        rec["path"] = derivation_path
    return rec


def derive_hd_batch(mnemonic: str, path_base: str, start: int, count: int, password: str, out_dir: Path, *, tags: Optional[List[str]] = None, emit_env: bool = False, insecure_plain: bool = False) -> List[Dict[str, Any]]:
    Account.enable_unaudited_hdwallet_features()
    records: List[Dict[str, Any]] = []
    for i in range(start, start + count):
        path = f"{path_base}/{i}"
        priv_hex, address = derive_privkey_from_mnemonic(mnemonic, path)
        ks, _ = encrypt_private_key(priv_hex, password)
        ks_path = write_keystore(out_dir, address, ks)
        if emit_env and insecure_plain:
            write_env_private_key(out_dir, address, priv_hex)
        records.append(record_for(address, ks_path, source="hd", derivation_path=path, tags=tags))
    return records


def create_random_wallets(count: int, password: str, out_dir: Path, *, tags: Optional[List[str]] = None, emit_env: bool = False, insecure_plain: bool = False) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for _ in range(count):
        acct = Account.create()
        priv_hex = "0x" + bytes(acct.key).hex()
        address = to_checksum_address(acct.address)
        ks, _ = encrypt_private_key(priv_hex, password)
        ks_path = write_keystore(out_dir, address, ks)
        if emit_env and insecure_plain:
            write_env_private_key(out_dir, address, priv_hex)
        records.append(record_for(address, ks_path, source="random", tags=tags))
    return records


def import_private_keys(keys: Iterable[str], password: str, out_dir: Path, *, tags: Optional[List[str]] = None, emit_env: bool = False, insecure_plain: bool = False) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for k in keys:
        k = k.strip()
        if not k:
            continue
        if not k.startswith("0x"):
            k = "0x" + k
        ks, address = encrypt_private_key(k, password)
        ks_path = write_keystore(out_dir, address, ks)
        if emit_env and insecure_plain:
            write_env_private_key(out_dir, address, k)
        records.append(record_for(address, ks_path, source="import", tags=tags))
    return records


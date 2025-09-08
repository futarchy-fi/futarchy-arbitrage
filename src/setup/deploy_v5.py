#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils import to_checksum_address
from web3 import Web3

from .keystore import (
    resolve_password,
    derive_privkey_from_mnemonic,
    read_keystore,
)
from .wallet_manager import (
    load_index,
    save_index,
    upsert_record,
    record_for,
)
from .fund_xdai import GasConfig as GasConfig1559, fund_xdai as fund_xdai_topup


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_env(path: Optional[str]) -> None:
    if not path:
        return
    try:
        from dotenv import load_dotenv as _ld

        _ld(path)
    except Exception:
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
                        os.environ.setdefault(k.strip(), v)
        except Exception:
            pass


def _build_w3(rpc_url: Optional[str]) -> Web3:
    url = rpc_url or os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL")
    if not url:
        raise EnvironmentError("Set --rpc-url or RPC_URL/GNOSIS_RPC_URL in env")
    w3 = Web3(Web3.HTTPProvider(url))
    try:
        from web3.middleware import geth_poa_middleware

        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass
    return w3


def _is_eip1559_supported(w3: Web3) -> bool:
    try:
        blk = w3.eth.get_block("latest")
        return "baseFeePerGas" in blk
    except Exception:
        return False


def _default_log_path(base_dir: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return base_dir / f"deploy_v5_{ts}.json"


def _load_artifacts() -> Tuple[str, list]:
    """Load bytecode and ABI from build artifacts (preferred fallback to avoid requiring solc/solcx)."""
    abi_path = Path("build/FutarchyArbExecutorV5.abi")
    bin_path = Path("build/FutarchyArbExecutorV5.bin")
    if not abi_path.exists() or not bin_path.exists():
        raise SystemExit("Missing build artifacts. Run scripts/deploy_executor_v5.py once to generate build/FutarchyArbExecutorV5.abi/bin or install solc/solcx.")
    abi = json.loads(abi_path.read_text())
    bytecode = bin_path.read_text().strip()
    if not bytecode.startswith("0x"):
        bytecode = "0x" + bytecode
    return bytecode, abi


def _ensure_path_and_get_address(
    *,
    path: str,
    out_dir: Path,
    index_path: Path,
    mnemonic: Optional[str],
    keystore_pass: Optional[str],
    keystore_pass_env: Optional[str],
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Ensure the HD path exists in index/keystore if mnemonic is provided; return (address, record_or_None)."""
    existing = load_index(index_path)
    by_path = {r.get("path"): r for r in existing if r.get("path")}
    rec = by_path.get(path)
    if rec is None and mnemonic:
        priv_hex, address = derive_privkey_from_mnemonic(mnemonic, path)
        # Write keystore only if we have a password to avoid secrets in memory later
        try:
            pwd = resolve_password(keystore_pass, keystore_pass_env, "PRIVATE_KEY")
        except Exception:
            pwd = None  # type: ignore[assignment]
        if pwd:
            from .keystore import encrypt_private_key, write_keystore

            ks, _ = encrypt_private_key(priv_hex, pwd)
            ks_path = write_keystore(out_dir, address, ks)
            rec = record_for(address, ks_path, source="hd", derivation_path=path, tags=None)
            updated = upsert_record(existing, rec)
            save_index(index_path, updated)
        else:
            # No password available: do not write keystore; still return address
            address = to_checksum_address(address)
            return address, None
    if rec is None:
        # As a last resort, auto-generate a mnemonic to satisfy "derive if necessary" behavior
        try:
            Account.enable_unaudited_hdwallet_features()
            _, auto_mnemonic = Account.create_with_mnemonic()
            priv_hex, address = derive_privkey_from_mnemonic(auto_mnemonic, path)
            # Try to persist a keystore if we can resolve a password
            try:
                pwd = resolve_password(keystore_pass, keystore_pass_env, "PRIVATE_KEY")
            except Exception:
                pwd = None  # type: ignore[assignment]
            if pwd:
                from .keystore import encrypt_private_key, write_keystore

                ks, _ = encrypt_private_key(priv_hex, pwd)
                ks_path = write_keystore(out_dir, address, ks)
                rec = record_for(address, ks_path, source="hd", derivation_path=path, tags=None)
                updated = upsert_record(existing, rec)
                save_index(index_path, updated)
                return to_checksum_address(address), rec
            # Could not persist; return address without record
            return to_checksum_address(address), None
        except Exception:
            raise SystemExit(
                "HD path not found and unable to auto-derive. Provide MNEMONIC/--mnemonic or ensure keystore exists."
            )
    return to_checksum_address(rec.get("address")), rec


def _derive_private_key_for_path(
    *,
    path: str,
    out_dir: Path,
    index_path: Path,
    mnemonic: Optional[str],
    keystore_pass: Optional[str],
    keystore_pass_env: Optional[str],
) -> Tuple[str, str]:
    """Return (private_key_hex, checksum_address) for the requested HD path.

    Order of resolution:
    - If mnemonic provided (via arg/env), derive directly from mnemonic and path.
    - Else, read index to find keystore_path for this path and decrypt using resolved password.
    """
    if mnemonic:
        priv_hex, address = derive_privkey_from_mnemonic(mnemonic, path)
        return priv_hex, to_checksum_address(address)

    existing = load_index(index_path)
    match = next((r for r in existing if r.get("path") == path), None)
    if not match:
        # Auto-generate mnemonic to satisfy derive-if-necessary behavior
        try:
            Account.enable_unaudited_hdwallet_features()
            _, auto_mnemonic = Account.create_with_mnemonic()
            priv_hex, address = derive_privkey_from_mnemonic(auto_mnemonic, path)
            return priv_hex, to_checksum_address(address)
        except Exception:
            raise SystemExit(
                "Path not found in index.json and unable to auto-derive mnemonic. Provide --mnemonic/--mnemonic-env or create keystore."
            )
    ks_path = match.get("keystore_path")
    if not ks_path or not Path(ks_path).exists():
        raise SystemExit("Keystore file for the path is missing; cannot decrypt. Provide --mnemonic or fix index/keystore.")
    password = resolve_password(keystore_pass, keystore_pass_env, "PRIVATE_KEY")
    ks_json = read_keystore(Path(ks_path))
    from .keystore import decrypt_keystore

    priv_hex = decrypt_keystore(ks_json, password)
    address = to_checksum_address(Account.from_key(priv_hex).address)
    # sanity check: if index has address, ensure it matches
    try:
        indexed_addr = to_checksum_address(match.get("address"))
        if indexed_addr != address:
            raise SystemExit("Decrypted keystore address mismatch for the requested path.")
    except Exception:
        pass
    return priv_hex, address


@dataclass
class DeployGasConfig:
    type: str  # "eip1559" or "legacy"
    gas_limit: int
    max_fee_gwei: Optional[Decimal] = None
    prio_fee_gwei: Optional[Decimal] = None
    gas_price_gwei: Optional[Decimal] = None

    def as_tx_fields(self, w3: Web3) -> Dict[str, int]:
        # Reuse semantics from funding GasConfig
        if self.type == "eip1559":
            assert self.max_fee_gwei is not None and self.prio_fee_gwei is not None
            max_fee = int(w3.to_wei(str(self.max_fee_gwei), "gwei"))
            prio = int(w3.to_wei(str(self.prio_fee_gwei), "gwei"))
            return {"maxFeePerGas": max_fee, "maxPriorityFeePerGas": prio, "gas": int(self.gas_limit)}
        else:
            assert self.gas_price_gwei is not None
            gp = int(w3.to_wei(str(self.gas_price_gwei), "gwei"))
            return {"gasPrice": gp, "gas": int(self.gas_limit)}


def deploy_v5(
    *,
    path: str,
    out_dir: Path,
    index_path: Path,
    ensure_path: bool,
    ensure_mnemonic: Optional[str],
    ensure_mnemonic_env: Optional[str],
    keystore_pass: Optional[str],
    keystore_pass_env: Optional[str],
    env_file: Optional[str],
    rpc_url: Optional[str],
    chain_id: int,
    gas: DeployGasConfig,
    timeout: int,
    dry_run: bool,
    log_path: Optional[Path],
    require_confirm: bool,
    fund_xdai_eth: Optional[str] = None,
    funder_env: str = "FUNDER_PRIVATE_KEY",
) -> int:
    """Deploy FutarchyArbExecutorV5 with the owner set to the EOA derived at --path.

    Ensures the private key used belongs to the specified HD path.
    """
    _load_env(env_file)

    # Resolve mnemonic via args/env; if missing and path not found, auto-generate one
    mnemonic = ensure_mnemonic or (os.getenv(ensure_mnemonic_env) if ensure_mnemonic_env else None) or os.getenv("MNEMONIC")

    out_dir.mkdir(parents=True, exist_ok=True)
    if not index_path:
        index_path = out_dir / "index.json"

    existing_for_check = load_index(index_path)
    has_path = any(r.get("path") == path for r in existing_for_check)
    if not has_path and not mnemonic:
        try:
            Account.enable_unaudited_hdwallet_features()
            _, auto_mnemonic = Account.create_with_mnemonic()
            mnemonic = auto_mnemonic
        except Exception:
            pass

    # Ensure/create the path record opportunistically (even without --ensure-path)
    _addr_tmp, _rec_tmp = _ensure_path_and_get_address(
        path=path,
        out_dir=out_dir,
        index_path=index_path,
        mnemonic=mnemonic,
        keystore_pass=keystore_pass,
        keystore_pass_env=keystore_pass_env,
    )

    # Always derive or decrypt the private key for the path (prefer mnemonic if set)
    priv_hex, deployer = _derive_private_key_for_path(
        path=path,
        out_dir=out_dir,
        index_path=index_path,
        mnemonic=mnemonic,
        keystore_pass=keystore_pass,
        keystore_pass_env=keystore_pass_env,
    )
    acct: LocalAccount = Account.from_key(priv_hex)
    assert to_checksum_address(acct.address) == to_checksum_address(deployer)

    # Web3 connection and chain checks
    w3 = _build_w3(rpc_url)
    try:
        if hasattr(w3, "is_connected") and callable(getattr(w3, "is_connected")):
            if not w3.is_connected():
                raise EnvironmentError("Web3 provider not connected (check RPC URL)")
    except Exception:
        pass
    actual_chain_id = w3.eth.chain_id
    if chain_id and actual_chain_id != chain_id:
        raise SystemExit(f"Unexpected chainId {actual_chain_id}; expected {chain_id}. Use --chain-id to override.")

    if gas.type == "eip1559" and not _is_eip1559_supported(w3):
        raise SystemExit("RPC appears to not support EIP-1559 (no baseFeePerGas). Use --legacy or different RPC.")
    if gas.gas_limit < 500_000:
        raise SystemExit("gas-limit too low for deployment (recommend >= 2,000,000)")

    # Load artifacts
    bytecode, abi = _load_artifacts()

    # Build constructor tx for estimation and keep the constructor builder
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    base_tx = {
        "from": deployer,
        "nonce": w3.eth.get_transaction_count(deployer, "pending"),
        "chainId": actual_chain_id,
    }
    ctor_builder = None
    try:
        ctor_builder = Contract.constructor()
        tx_est = ctor_builder.build_transaction(base_tx)
    except TypeError:
        # Backward-compat: if ABI expects 3 ctor args, use env
        futarchy_router = os.getenv("FUTARCHY_ROUTER_ADDRESS")
        swapr_router = os.getenv("SWAPR_ROUTER_ADDRESS")
        proposal = os.getenv("FUTARCHY_PROPOSAL_ADDRESS")
        if not (futarchy_router and swapr_router and proposal):
            raise SystemExit("Constructor requires FUTARCHY_ROUTER_ADDRESS, SWAPR_ROUTER_ADDRESS, FUTARCHY_PROPOSAL_ADDRESS in env")
        ctor_builder = Contract.constructor(futarchy_router, swapr_router, proposal)
        tx_est = ctor_builder.build_transaction(base_tx)

    # Estimate gas and balances
    try:
        est_gas = int(w3.eth.estimate_gas(tx_est))
    except Exception:
        est_gas = 5_000_000
    gas_limit = max(gas.gas_limit, int(est_gas * 12 // 10))  # at least 20% buffer
    gas_fields = dict(gas.as_tx_fields(w3))
    gas_fields["gas"] = gas_limit
    max_gas_cost = 0
    if gas.type == "eip1559":
        assert gas.max_fee_gwei is not None
        max_gas_cost = int(w3.to_wei(str(gas.max_fee_gwei), "gwei")) * gas_limit
    else:
        assert gas.gas_price_gwei is not None
        max_gas_cost = int(w3.to_wei(str(gas.gas_price_gwei), "gwei")) * gas_limit

    deployer_bal = int(w3.eth.get_balance(deployer))

    # Optional/Automatic pre-fund
    prefund_summary: Optional[Dict[str, Any]] = None
    def _top_up_to_target(target_wei: int) -> None:
        nonlocal deployer_bal
        rc = fund_xdai_topup(
            out_dir=out_dir,
            index_path=index_path,
            amount_eth=str(Web3.from_wei(target_wei, "ether")),
            from_env=funder_env,
            env_file=env_file,
            rpc_url=rpc_url,
            chain_id=chain_id,
            only=None,
            only_path=None,
            ensure_paths=path,
            ensure_mnemonic=mnemonic,
            ensure_mnemonic_env=None,
            keystore_pass=keystore_pass,
            keystore_pass_env=keystore_pass_env,
            always_send=False,
            gas=GasConfig1559(
                type=gas.type,
                gas_limit=21_000,
                max_fee_gwei=gas.max_fee_gwei,
                prio_fee_gwei=gas.prio_fee_gwei,
                gas_price_gwei=gas.gas_price_gwei,
            ),
            timeout=timeout,
            dry_run=False,
            log_path=None,
            require_confirm=False,
        )
        if int(rc) != 0:
            print("Auto-funding xDAI failed; continuing to deployment attempt anyway.")
        try:
            deployer_bal = int(w3.eth.get_balance(deployer))
        except Exception:
            pass

    if fund_xdai_eth is not None:
        target_wei = int(w3.to_wei(str(Decimal(str(fund_xdai_eth))), "ether"))
        if deployer_bal < target_wei:
            _top_up_to_target(target_wei)
        prefund_summary = {"target_wei": target_wei, "after_balance_wei": deployer_bal}
    else:
        if deployer_bal < max_gas_cost:
            # Compute a sensible target: 1.2x gas or +0.01 xDAI minimum buffer
            buffer = int(w3.to_wei("0.01", "ether"))
            target_wei = max(int(max_gas_cost * 12 // 10), max_gas_cost + buffer)
            _top_up_to_target(target_wei)
            prefund_summary = {"target_wei": target_wei, "after_balance_wei": deployer_bal}

    # Prepare plan/summary
    summary: Dict[str, Any] = {
        "chain_id": actual_chain_id,
        "rpc_url": rpc_url or os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL"),
        "deployer": deployer,
        "path": path,
        "gas": {
            "type": gas.type,
            "gas_limit": gas_limit,
            "max_fee_gwei": str(gas.max_fee_gwei) if gas.max_fee_gwei is not None else None,
            "priority_fee_gwei": str(gas.prio_fee_gwei) if gas.prio_fee_gwei is not None else None,
            "gas_price_gwei": str(gas.gas_price_gwei) if gas.gas_price_gwei is not None else None,
        },
        "deployer_balance_wei": deployer_bal,
        "max_gas_cost_wei": max_gas_cost,
        "generated_at": _utc_now_iso(),
        "dry_run": bool(dry_run),
        "prefund": prefund_summary,
    }

    log_dir = out_dir if out_dir else Path("build/wallets")
    log_path = log_path or _default_log_path(log_dir)

    if dry_run or require_confirm:
        payload = {"summary": summary}
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"Prepared deploy plan: {log_path}")
        if require_confirm and not dry_run:
            print("Pass --confirm to execute this plan.")
            return 2
        return 0

    # Execute deployment (reuse the same constructor builder used for estimation)
    assert ctor_builder is not None
    tx = ctor_builder.build_transaction({
        "from": deployer,
        "nonce": w3.eth.get_transaction_count(deployer, "pending"),
        "chainId": actual_chain_id,
        **gas_fields,
    })

    signed = Account.sign_transaction(tx, private_key=priv_hex)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
    tx_hash = w3.eth.send_raw_transaction(raw)
    print(f"Deploy tx: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
    status_ok = int(getattr(receipt, "status", getattr(receipt, "status", 0))) == 1 or int(receipt.get("status", 0)) == 1  # type: ignore[index]
    if not status_ok:
        print("Deployment failed (status != 1)")
        def _jsonify(obj: Any):
            try:
                from hexbytes import HexBytes
            except Exception:
                class HexBytes(bytes):
                    pass  # best-effort fallback

            if isinstance(obj, (bytes, bytearray)):
                return "0x" + bytes(obj).hex()
            try:
                # HexBytes or objects with .hex()
                hx = getattr(obj, "hex", None)
                if callable(hx):
                    val = hx()
                    if isinstance(val, str):
                        return val
            except Exception:
                pass
            if isinstance(obj, dict):
                return {k: _jsonify(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_jsonify(x) for x in obj]
            try:
                json.dumps(obj)
                return obj
            except Exception:
                return str(obj)

        payload = {"summary": summary, "tx": tx_hash.hex(), "receipt": _jsonify(dict(receipt))}
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(payload, f, indent=2)
        return 1

    address = getattr(receipt, "contractAddress", None) or receipt.get("contractAddress")  # type: ignore[index]
    address = to_checksum_address(address)

    # Write deployment record under deployments/
    deployments_dir = Path("deployments")
    deployments_dir.mkdir(parents=True, exist_ok=True)
    dep_file = deployments_dir / f"deployment_executor_v5_{int(datetime.now().timestamp())}.json"
    dep_payload = {
        "address": address,
        "tx_hash": tx_hash.hex(),
        "gas_used": int(getattr(receipt, "gasUsed", getattr(receipt, "gas_used", 0))),
        "block_number": int(getattr(receipt, "blockNumber", getattr(receipt, "block_number", 0))),
        "timestamp": _utc_now_iso(),
        "abi": abi,
        "network": "gnosis",
        "contract": "FutarchyArbExecutorV5",
        # Linkage to HD derivation for easy lookup
        "path": path,
        "deployer": deployer,
    }
    with open(dep_file, "w") as f:
        json.dump(dep_payload, f, indent=2)
    print(f"Saved deployment info to {dep_file}")

    # Final log
    payload = {"summary": summary, "address": address, "tx": tx_hash.hex()}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Deployed FutarchyArbExecutorV5 at: {address}")
    return 0

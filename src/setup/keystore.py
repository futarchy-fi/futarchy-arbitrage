#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils import to_checksum_address


def _normalize_privkey_hex(pk: str) -> str:
    if not isinstance(pk, str):
        raise ValueError("private key must be a hex string")
    pk = pk.strip()
    if pk.startswith("0x"):
        pk = pk[2:]
    if len(pk) != 64:
        raise ValueError("private key hex must be 64 characters (32 bytes)")
    int(pk, 16)  # validate hex
    return "0x" + pk


def resolve_password(cli_pass: Optional[str], pass_env: Optional[str]) -> str:
    """Resolve keystore password from CLI or environment variable name.

    Precedence: cli_pass > env[pass_env] > env["WALLET_KEYSTORE_PASSWORD"].
    Raises ValueError if none found.
    """
    if cli_pass:
        return cli_pass
    env_name = pass_env or "WALLET_KEYSTORE_PASSWORD"
    pwd = os.getenv(env_name) or os.getenv("WALLET_KEYSTORE_PASSWORD")
    if not pwd:
        raise ValueError(
            "Keystore password not provided. Use --keystore-pass or set WALLET_KEYSTORE_PASSWORD (or provide --keystore-pass-env)."
        )
    return pwd


def encrypt_private_key(private_key_hex: str, password: str) -> Tuple[Dict[str, Any], str]:
    """Encrypt a private key into a keystore JSON and return (keystore, checksum address)."""
    priv = _normalize_privkey_hex(private_key_hex)
    acct: LocalAccount = Account.from_key(priv)
    keystore: Dict[str, Any] = Account.encrypt(priv, password)
    address = to_checksum_address(acct.address)
    return keystore, address


def decrypt_keystore(keystore_json: Dict[str, Any], password: str) -> str:
    """Decrypt a keystore JSON and return the 0x-prefixed private key hex string."""
    key_bytes = Account.decrypt(keystore_json, password)
    # Ensure plain bytes before hex() to avoid leading '0x' from HexBytes.hex()
    return "0x" + bytes(key_bytes).hex()


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="keystore_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def keystore_filename(address: str) -> str:
    addr = to_checksum_address(address)
    return f"{addr}.json"


def write_keystore(out_dir: Path, address: str, keystore_json: Dict[str, Any]) -> Path:
    filename = keystore_filename(address)
    dest = out_dir / filename
    write_json_atomic(dest, keystore_json)
    return dest


def read_keystore(path: Path) -> Dict[str, Any]:
    return read_json(path)


def write_env_private_key(out_dir: Path, address: str, private_key_hex: str) -> Path:
    """Write a minimal .env.<address> containing PRIVATE_KEY=... (explicitly insecure)."""
    addr = to_checksum_address(address)
    out_dir.mkdir(parents=True, exist_ok=True)
    env_path = out_dir / f".env.{addr}"
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="envkey_", suffix=".tmp", dir=str(out_dir))
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(f"PRIVATE_KEY={private_key_hex}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, env_path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
    return env_path


def derive_privkey_from_mnemonic(mnemonic: str, path: str) -> Tuple[str, str]:
    """Derive a private key and address from a BIP-32/44 path using a BIP-39 mnemonic.

    Returns (private_key_hex, checksum_address).
    """
    # Enable HD wallet features (eth-account marks as unaudited)
    Account.enable_unaudited_hdwallet_features()
    acct: LocalAccount = Account.from_mnemonic(mnemonic, account_path=path)
    priv_hex = "0x" + bytes(acct.key).hex()
    address = to_checksum_address(acct.address)
    return priv_hex, address

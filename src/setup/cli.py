#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from eth_account import Account
from eth_utils import to_checksum_address
try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(path: Optional[str] = None):
        return False
import secrets
import string

from .keystore import (
    encrypt_private_key,
    decrypt_keystore,
    resolve_password,
    write_keystore,
    read_keystore,
    write_env_private_key,
    derive_privkey_from_mnemonic,
)


def cmd_keystore_create(args: argparse.Namespace) -> int:
    try:
        # Optionally load env file for PRIVATE_KEY / password
        if args.env_file:
            load_dotenv(args.env_file)

        # Determine private key source: --private-key > --private-key-env/env > --random
        priv_hex: Optional[str] = None
        if args.random:
            acct = Account.create()
            priv_hex = "0x" + bytes(acct.key).hex()
        elif args.private_key:
            priv_hex = args.private_key
        else:
            # Try env variable
            env_name = args.private_key_env or "PRIVATE_KEY"
            pk_env = os.getenv(env_name)
            if pk_env:
                priv_hex = pk_env
            else:
                # default to random if neither provided (backward-compatible)
                acct = Account.create()
                priv_hex = "0x" + bytes(acct.key).hex()

        # Resolve password
        password = resolve_password(args.keystore_pass, args.keystore_pass_env)
        keystore, address = encrypt_private_key(priv_hex, password)

        out_dir = Path(args.out or "build/wallets")
        ks_path = write_keystore(out_dir, address, keystore)

        print(f"Created keystore: {ks_path}")
        print(f"Address: {address}")

        if args.emit_env:
            if not args.insecure_plain:
                print("Refusing to write plaintext env without --insecure-plain", file=sys.stderr)
                return 2
            env_path = write_env_private_key(out_dir, address, priv_hex)
            print(f"Wrote plaintext env (insecure): {env_path}")

        if args.show_private_key:
            if not args.insecure_plain:
                print("Refusing to print private key without --insecure-plain", file=sys.stderr)
                return 2
            print(f"Private key: {priv_hex}")

        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_keystore_decrypt(args: argparse.Namespace) -> int:
    try:
        # Optionally load env file for password resolution
        if args.env_file:
            load_dotenv(args.env_file)

        path = Path(args.file)
        if not path.exists():
            print(f"Keystore file not found: {path}", file=sys.stderr)
            return 1
        keystore_json = read_keystore(path)
        password = resolve_password(args.keystore_pass, args.keystore_pass_env)
        priv_hex = decrypt_keystore(keystore_json, password)

        # Derive address
        address = to_checksum_address(Account.from_key(priv_hex).address)
        print(f"Address: {address}")

        if args.show_private_key:
            if not args.insecure_plain:
                print("Refusing to print private key without --insecure-plain", file=sys.stderr)
                return 2
            print(f"Private key: {priv_hex}")
        return 0
    except ValueError as ve:
        print(f"Decryption failed: {ve}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Setup CLI (phase 1: keystore)")
    sub = parser.add_subparsers(dest="cmd")

    # keystore-create
    p_create = sub.add_parser("keystore-create", help="Create an encrypted keystore for a private key")
    src_group = p_create.add_mutually_exclusive_group()
    src_group.add_argument("--private-key", help="0x-hex private key")
    src_group.add_argument("--random", action="store_true", help="Generate a random private key")
    p_create.add_argument("--private-key-env", dest="private_key_env", help="Env var name holding a private key (default PRIVATE_KEY)")
    p_create.add_argument("--keystore-pass", dest="keystore_pass", help="Keystore password (insecure on CLI)")
    p_create.add_argument("--keystore-pass-env", dest="keystore_pass_env", help="Env var name for password (default WALLET_KEYSTORE_PASSWORD)")
    p_create.add_argument("--out", help="Output directory for keystore files (default build/wallets)")
    p_create.add_argument("--env-file", help="Path to .env file to load before resolving env vars")
    p_create.add_argument("--emit-env", action="store_true", help="Also write a plaintext .env.<address> with PRIVATE_KEY (insecure)")
    p_create.add_argument("--show-private-key", action="store_true", help="Print the private key (requires --insecure-plain)")
    p_create.add_argument("--insecure-plain", action="store_true", help="Acknowledge insecurity when writing/printing plaintext keys")
    p_create.set_defaults(func=cmd_keystore_create)

    # keystore-decrypt
    p_decrypt = sub.add_parser("keystore-decrypt", help="Decrypt a keystore and show address (optionally private key)")
    p_decrypt.add_argument("--file", required=True, help="Path to keystore JSON file")
    p_decrypt.add_argument("--keystore-pass", dest="keystore_pass", help="Keystore password")
    p_decrypt.add_argument("--keystore-pass-env", dest="keystore_pass_env", help="Env var name for password (default WALLET_KEYSTORE_PASSWORD)")
    p_decrypt.add_argument("--env-file", help="Path to .env file to load before resolving env vars")
    p_decrypt.add_argument("--show-private-key", action="store_true", help="Print the private key (requires --insecure-plain)")
    p_decrypt.add_argument("--insecure-plain", action="store_true", help="Acknowledge insecurity when printing private key")
    p_decrypt.set_defaults(func=cmd_keystore_decrypt)

    # hd-derive: derive a key from mnemonic + path and create a keystore
    p_hd = sub.add_parser("hd-derive", help="Derive a key from a mnemonic and path, then create a keystore")
    mn_group = p_hd.add_mutually_exclusive_group(required=True)
    mn_group.add_argument("--mnemonic", help="BIP-39 mnemonic phrase (quoted)")
    mn_group.add_argument("--mnemonic-env", help="Env var name holding the mnemonic")
    p_hd.add_argument("--path", default="m/44'/60'/0'/0/0", help="Derivation path (default: m/44'/60'/0'/0/0)")
    p_hd.add_argument("--keystore-pass", dest="keystore_pass", help="Keystore password")
    p_hd.add_argument("--keystore-pass-env", dest="keystore_pass_env", help="Env var name for password (default WALLET_KEYSTORE_PASSWORD)")
    p_hd.add_argument("--out", help="Output directory for keystore files (default build/wallets)")
    p_hd.add_argument("--env-file", help="Path to .env file to load before resolving env vars (for mnemonic/password)")
    p_hd.add_argument("--emit-env", action="store_true", help="Also write a plaintext .env.<address> (insecure)")
    p_hd.add_argument("--show-private-key", action="store_true", help="Print the derived private key (requires --insecure-plain)")
    p_hd.add_argument("--insecure-plain", action="store_true", help="Acknowledge insecurity when writing/printing plaintext keys")
    def _cmd_hd(args: argparse.Namespace) -> int:
        try:
            if args.env_file:
                load_dotenv(args.env_file)
            mnemonic = args.mnemonic or os.getenv(args.mnemonic_env)  # type: ignore[arg-type]
            if not mnemonic:
                print("Mnemonic not provided (use --mnemonic or --mnemonic-env)", file=sys.stderr)
                return 2
            priv_hex, address = derive_privkey_from_mnemonic(mnemonic.strip(), args.path)
            password = resolve_password(args.keystore_pass, args.keystore_pass_env)
            keystore, _ = encrypt_private_key(priv_hex, password)
            out_dir = Path(args.out or "build/wallets")
            ks_path = write_keystore(out_dir, address, keystore)
            print(f"Derived {address} at {args.path}")
            print(f"Created keystore: {ks_path}")
            if args.emit_env:
                if not args.insecure_plain:
                    print("Refusing to write plaintext env without --insecure-plain", file=sys.stderr)
                    return 2
                env_path = write_env_private_key(out_dir, address, priv_hex)
                print(f"Wrote plaintext env (insecure): {env_path}")
            if args.show_private_key:
                if not args.insecure_plain:
                    print("Refusing to print private key without --insecure-plain", file=sys.stderr)
                    return 2
                print(f"Private key: {priv_hex}")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    p_hd.set_defaults(func=_cmd_hd)

    # hd-new: generate a fresh mnemonic + ephemeral password in-memory; derive N accounts and write keystores
    p_new = sub.add_parser("hd-new", help="Generate a new mnemonic and temp password, derive N keys, and create keystores")
    p_new.add_argument("--count", type=int, default=1, help="Number of consecutive accounts to derive (default 1)")
    p_new.add_argument("--path-base", default="m/44'/60'/0'/0", help="Base derivation path (default m/44'/60'/0'/0)")
    p_new.add_argument("--out", help="Output directory for keystore files (default build/wallets)")
    p_new.add_argument("--print-secrets", action="store_true", help="Print the generated mnemonic and password to stdout")
    p_new.add_argument("--keystore-pass", dest="keystore_pass", help="Override with a provided keystore password (avoid printing)")
    def _cmd_hd_new(args: argparse.Namespace) -> int:
        try:
            # Enable HD features and generate mnemonic
            Account.enable_unaudited_hdwallet_features()
            acct, mnemonic = Account.create_with_mnemonic()

            # Resolve password: provided or generate ephemeral
            if args.keystore_pass:
                password = args.keystore_pass
            else:
                # Generate a reasonably strong URL-safe password
                password = secrets.token_urlsafe(24)

            out_dir = Path(args.out or "build/wallets")

            print("Deriving accounts:")
            derived = []
            for i in range(int(args.count)):
                path = f"{args.path_base}/{i}"
                priv_hex, address = derive_privkey_from_mnemonic(mnemonic, path)
                keystore, _ = encrypt_private_key(priv_hex, password)
                ks_path = write_keystore(out_dir, address, keystore)
                derived.append({"index": i, "path": path, "address": address, "keystore": str(ks_path)})
                print(f"  [{i}] {address} @ {path} -> {ks_path}")

            if args.print_secrets or not args.keystore_pass:
                print("\nSECRETS (Handle carefully; not stored anywhere):")
                print(f"Mnemonic: {mnemonic}")
                print(f"Keystore password: {password}")

            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    p_new.set_defaults(func=_cmd_hd_new)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

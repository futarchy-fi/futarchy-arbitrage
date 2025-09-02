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
        """Lightweight .env loader fallback: KEY=VALUE per line, supports optional 'export ' prefix."""
        if not path:
            return False
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[7:]
                    if "=" in line:
                        key, val = line.split("=", 1)
                        val = val.strip().strip('"').strip("'")
                        os.environ.setdefault(key, val)
            return True
        except Exception:
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
from .wallet_manager import (
    load_index,
    save_index,
    scan_keystores,
    derive_hd_batch,
    create_random_wallets,
    import_private_keys,
    upsert_record,
)
from .fund_xdai import fund_xdai as _fund_xdai, GasConfig as _GasConfig


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
        password = resolve_password(args.keystore_pass, args.keystore_pass_env, args.private_key_env or "PRIVATE_KEY")
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
        password = resolve_password(args.keystore_pass, args.keystore_pass_env, args.private_key_env or "PRIVATE_KEY")
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
    p_decrypt.add_argument("--private-key-env", dest="private_key_env", help="Env var name holding a private key (default PRIVATE_KEY) for password fallback")
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
            password = resolve_password(args.keystore_pass, args.keystore_pass_env, "PRIVATE_KEY")
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

    # hd-from-env: read PRIVATE_KEY from --env-file, generate mnemonic, derive batch, and write an .env with MNEMONIC + WALLET_KEYSTORE_PASSWORD
    p_hfe = sub.add_parser("hd-from-env", help="Generate an HD seed from env PRIVATE_KEY, derive N accounts, and write an .env with MNEMONIC + WALLET_KEYSTORE_PASSWORD")
    p_hfe.add_argument("--env-file", required=True, help="Path to .env file that contains PRIVATE_KEY")
    p_hfe.add_argument("--out-env", required=True, help="Path to write the resulting .env with MNEMONIC and WALLET_KEYSTORE_PASSWORD")
    p_hfe.add_argument("--count", type=int, default=1, help="Number of consecutive accounts to derive (default 1)")
    p_hfe.add_argument("--path-base", default="m/44'/60'/0'/0", help="Base derivation path (default m/44'/60'/0'/0)")
    p_hfe.add_argument("--out", help="Output directory for keystore files (default build/wallets)")
    p_hfe.add_argument("--print-secrets", action="store_true", help="Also print the generated mnemonic and password")
    def _cmd_hd_from_env(args: argparse.Namespace) -> int:
        try:
            # Load source env to get PRIVATE_KEY
            load_dotenv(args.env_file)
            pk = os.getenv("PRIVATE_KEY")
            if not pk:
                print("PRIVATE_KEY not found in --env-file", file=sys.stderr)
                return 2
            # Derive keystore password deterministically from PRIVATE_KEY
            password = resolve_password(None, None, "PRIVATE_KEY")

            # Create mnemonic and derive batch
            Account.enable_unaudited_hdwallet_features()
            acct, mnemonic = Account.create_with_mnemonic()

            out_dir = Path(args.out or "build/wallets")
            base = args.path_base
            print("Deriving accounts:")
            for i in range(int(args.count)):
                path = f"{base}/{i}"
                priv_hex, address = derive_privkey_from_mnemonic(mnemonic, path)
                keystore, _ = encrypt_private_key(priv_hex, password)
                ks_path = write_keystore(out_dir, address, keystore)
                print(f"  [{i}] {address} @ {path} -> {ks_path}")

            # Write out .env with MNEMONIC and WALLET_KEYSTORE_PASSWORD for future runs
            out_env = Path(args.out_env)
            out_env.parent.mkdir(parents=True, exist_ok=True)
            with open(out_env, "w") as f:
                f.write(f"MNEMONIC='{mnemonic}'\n")
                f.write(f"WALLET_KEYSTORE_PASSWORD={password}\n")
                f.write(f"HD_PATH_BASE=\"{base}\"\n")
            print(f"Wrote seed env: {out_env}")
            if args.print_secrets:
                print("\nSECRETS (Copied to out-env):")
                print(f"Mnemonic: {mnemonic}")
                print(f"Keystore password: {password}")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    p_hfe.set_defaults(func=_cmd_hd_from_env)

    # generate: batch create wallets (hd|random) and update index
    p_gen = sub.add_parser("generate", help="Generate a batch of wallets (HD or random) and update index")
    p_gen.add_argument("--mode", choices=["hd", "random"], default="hd", help="Generation mode (default hd)")
    p_gen.add_argument("--count", type=int, default=1, help="Number of wallets to generate (default 1)")
    p_gen.add_argument("--start", type=int, default=0, help="Start index for HD derivation (default 0)")
    p_gen.add_argument("--path-base", default="m/44'/60'/0'/0", help="Base path for HD mode (default m/44'/60'/0'/0)")
    p_gen.add_argument("--mnemonic", help="BIP-39 mnemonic (HD mode)")
    p_gen.add_argument("--mnemonic-env", help="Env var name for mnemonic (HD mode)")
    p_gen.add_argument("--keystore-pass", dest="keystore_pass", help="Keystore password")
    p_gen.add_argument("--keystore-pass-env", dest="keystore_pass_env", help="Env var for password (default WALLET_KEYSTORE_PASSWORD)")
    p_gen.add_argument("--out", help="Keystore output directory (default build/wallets)")
    p_gen.add_argument("--index", help="Index file path (default build/wallets/index.json)")
    p_gen.add_argument("--tag", action="append", help="Add tag(s) to records (repeatable)")
    p_gen.add_argument("--emit-env", action="store_true", help="Also write plaintext .env.<address> (insecure)")
    p_gen.add_argument("--insecure-plain", action="store_true", help="Acknowledge insecurity when writing plaintext env files")
    p_gen.add_argument("--env-file", help="Path to .env file for resolving env vars (mnemonic/password)")
    def _cmd_generate(args: argparse.Namespace) -> int:
        try:
            if args.env_file:
                load_dotenv(args.env_file)
            out_dir = Path(args.out or "build/wallets")
            index_path = Path(args.index or (out_dir / "index.json"))
            # Resolve password (fallback to PRIVATE_KEY-derived if no WALLET_KEYSTORE_PASSWORD)
            password = resolve_password(args.keystore_pass, args.keystore_pass_env, "PRIVATE_KEY")
            # Create records
            if args.mode == "hd":
                # Resolve mnemonic from CLI or env (.env provides MNEMONIC)
                mnemonic = args.mnemonic or (os.getenv(args.mnemonic_env) if args.mnemonic_env else None) or os.getenv("MNEMONIC")
                if not mnemonic:
                    print("HD mode requires MNEMONIC in --env-file or via --mnemonic/--mnemonic-env", file=sys.stderr)
                    return 2
                # Resolve base derivation path from env if provided
                path_base = os.getenv("HD_PATH_BASE") or args.path_base
                new_records = derive_hd_batch(mnemonic.strip(), path_base, args.start, args.count, password, out_dir, tags=args.tag or [], emit_env=args.emit_env, insecure_plain=args.insecure_plain)
            else:
                new_records = create_random_wallets(args.count, password, out_dir, tags=args.tag or [], emit_env=args.emit_env, insecure_plain=args.insecure_plain)

            # Update index
            existing = load_index(index_path)
            for rec in new_records:
                existing = upsert_record(existing, rec)
            save_index(index_path, existing)

            print(f"Generated {len(new_records)} wallet(s). Index: {index_path}")
            for r in new_records:
                print(f" - {r['address']} -> {r['keystore_path']}" + (f" @ {r.get('path')}" if r.get('path') else ""))
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    p_gen.set_defaults(func=_cmd_generate)

    # list: show wallets from index or keystore directory
    p_list = sub.add_parser("list", help="List wallets from index or keystore directory")
    p_list.add_argument("--out", help="Keystore directory (default build/wallets)")
    p_list.add_argument("--index", help="Index file (default build/wallets/index.json)")
    p_list.add_argument("--format", choices=["table", "json"], default="table")
    def _cmd_list(args: argparse.Namespace) -> int:
        try:
            out_dir = Path(args.out or "build/wallets")
            index_path = Path(args.index or (out_dir / "index.json"))
            records = load_index(index_path)
            if not records:
                # fallback: scan
                records = scan_keystores(out_dir)
            if args.format == "json":
                print(json.dumps({"wallets": records}, indent=2))
            else:
                for r in records:
                    addr = r.get("address")
                    path = r.get("path", "-")
                    tags = ",".join(r.get("tags", [])) or "-"
                    print(f"{addr} | {path} | {tags} | {r.get('keystore_path')}")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    p_list.set_defaults(func=_cmd_list)

    # import-keys: import from file or repeated --key
    p_imp = sub.add_parser("import-keys", help="Import private keys and write keystores; update index")
    src_group = p_imp.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--file", help="Path to file with one private key per line")
    src_group.add_argument("--key", action="append", help="Private key(s) (repeatable)")
    p_imp.add_argument("--keystore-pass", dest="keystore_pass", help="Keystore password")
    p_imp.add_argument("--keystore-pass-env", dest="keystore_pass_env", help="Env var for password (default WALLET_KEYSTORE_PASSWORD)")
    p_imp.add_argument("--out", help="Keystore directory (default build/wallets)")
    p_imp.add_argument("--index", help="Index file (default build/wallets/index.json)")
    p_imp.add_argument("--tag", action="append", help="Add tag(s) to records (repeatable)")
    p_imp.add_argument("--emit-env", action="store_true", help="Also write plaintext .env.<address> (insecure)")
    p_imp.add_argument("--insecure-plain", action="store_true", help="Acknowledge insecurity when writing plaintext env files")
    p_imp.add_argument("--env-file", help="Path to .env file for resolving env vars (password)")
    def _cmd_import(args: argparse.Namespace) -> int:
        try:
            if args.env_file:
                load_dotenv(args.env_file)
            out_dir = Path(args.out or "build/wallets")
            index_path = Path(args.index or (out_dir / "index.json"))
            password = resolve_password(args.keystore_pass, args.keystore_pass_env)
            keys: List[str] = []
            if args.file:
                with open(args.file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            keys.append(line)
            else:
                keys = args.key or []
            new_records = import_private_keys(keys, password, out_dir, tags=args.tag or [], emit_env=args.emit_env, insecure_plain=args.insecure_plain)
            existing = load_index(index_path)
            # simple merge avoiding duplicates
            seen = {r.get('address') for r in existing}
            for r in new_records:
                if r['address'] not in seen:
                    existing.append(r)
                    seen.add(r['address'])
            save_index(index_path, existing)
            print(f"Imported {len(new_records)} key(s). Index: {index_path}")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    p_imp.set_defaults(func=_cmd_import)

    # fund-xdai: top up native xDAI to a target balance for each wallet in index/keystore dir
    p_fx = sub.add_parser("fund-xdai", help="Top up wallets to a target xDAI balance")
    p_fx.add_argument("--amount", required=True, help="Target xDAI balance per wallet (e.g., 0.01)")
    p_fx.add_argument("--from-env", dest="from_env", default="FUNDER_PRIVATE_KEY", help="Env var holding funder PRIVATE_KEY (default FUNDER_PRIVATE_KEY; fallback PRIVATE_KEY)")
    p_fx.add_argument("--out", help="Keystore directory (default build/wallets)")
    p_fx.add_argument("--index", help="Index file (default <out>/index.json)")
    p_fx.add_argument("--only", help="Filter recipients: CSV of addresses or glob pattern against addresses (e.g., '0xAbc*')")
    p_fx.add_argument("--only-path", dest="only_path", help="Filter by HD derivation path or glob (matches index records' path)")
    p_fx.add_argument("--env-file", help="Path to .env file to load before resolving env and RPC")
    p_fx.add_argument("--rpc-url", help="Override RPC URL (defaults to RPC_URL or GNOSIS_RPC_URL)")
    p_fx.add_argument("--chain-id", type=int, default=100, help="Expected chainId (default 100 for Gnosis)")
    p_fx.add_argument("--gas-limit", type=int, default=21000, help="Gas limit per transfer (default 21000)")
    # Gas price strategy
    gas_mode = p_fx.add_mutually_exclusive_group()
    gas_mode.add_argument("--legacy", action="store_true", help="Use legacy gasPrice instead of EIP-1559")
    p_fx.add_argument("--gas-price-gwei", type=float, default=1.0, help="Legacy gasPrice in gwei (used when --legacy)")
    p_fx.add_argument("--max-fee-gwei", type=float, default=2.0, help="EIP-1559 maxFeePerGas in gwei (default 2)")
    p_fx.add_argument("--priority-fee-gwei", type=float, default=1.0, help="EIP-1559 maxPriorityFeePerGas in gwei (default 1)")
    p_fx.add_argument("--timeout", type=int, default=120, help="Wait timeout (seconds) for each receipt (default 120)")
    p_fx.add_argument("--dry-run", action="store_true", help="Do not send transactions; write plan JSON only")
    p_fx.add_argument("--confirm", action="store_true", help="Confirm execution; without this flag, a plan is written and no txs are sent")
    p_fx.add_argument("--log", help="Path to write JSON log (default build/wallets/funding_<timestamp>.json)")
    def _cmd_fund_xdai(args: argparse.Namespace) -> int:
        try:
            from decimal import Decimal

            out_dir = Path(args.out or "build/wallets")
            index_path = Path(args.index) if args.index else (out_dir / "index.json")
            # Gas config
            if args.legacy:
                gas = _GasConfig(type="legacy", gas_limit=int(args.gas_limit), gas_price_gwei=Decimal(str(args.gas_price_gwei)))
            else:
                gas = _GasConfig(
                    type="eip1559",
                    gas_limit=int(args.gas_limit),
                    max_fee_gwei=Decimal(str(args.max_fee_gwei)),
                    prio_fee_gwei=Decimal(str(args.priority_fee_gwei)),
                )
            log_path = Path(args.log) if args.log else None
            rc = _fund_xdai(
                out_dir=out_dir,
                index_path=index_path if index_path.exists() else None,
                amount_eth=str(args.amount),
                from_env=args.from_env,
                env_file=args.env_file,
                rpc_url=args.rpc_url,
                chain_id=int(args.chain_id),
                only=args.only,
                only_path=args.only_path,
                gas=gas,
                timeout=int(args.timeout),
                dry_run=bool(args.dry_run),
                log_path=log_path,
                require_confirm=not bool(args.confirm),
            )
            return int(rc)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    p_fx.set_defaults(func=_cmd_fund_xdai)

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

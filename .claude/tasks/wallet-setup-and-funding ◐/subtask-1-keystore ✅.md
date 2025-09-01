[# content moved from 01_keystore.md]
# 01 – Keystore

## Goal

Implement secure keystore helpers for encrypting/decrypting private keys, reading/writing keystore files, and basic password sourcing. Provide initial CLI to create/import a single key.

## Deliverables

- `src/setup/keystore.py`:
  - `encrypt_private_key(private_key_hex, password) -> dict`
  - `decrypt_keystore(keystore_json, password) -> str`
  - `write_keystore(path, keystore_json)` / `read_keystore(path)`
  - `resolve_password(cli_pass, pass_env)`
  - `keystore_filename(address)`
  - `derive_privkey_from_mnemonic(mnemonic, path) -> (priv_hex, address)`
- Progressive CLI (phase 1) in `src/setup/cli.py`:
  - `python -m src.setup.cli keystore-create --private-key <hex>|--random --keystore-pass <pass>|--keystore-pass-env WALLET_KEYSTORE_PASSWORD [--out build/wallets] [--emit-env] [--insecure-plain]`
  - `python -m src.setup.cli keystore-create --private-key-env PRIVATE_KEY [--env-file .env] --keystore-pass <pass>|--keystore-pass-env WALLET_KEYSTORE_PASSWORD [--out build/wallets]`
  - `python -m src.setup.cli keystore-decrypt --file build/wallets/<address>.json --keystore-pass <pass>|--keystore-pass-env WALLET_KEYSTORE_PASSWORD [--env-file .env]`
  - `python -m src.setup.cli hd-derive --mnemonic "<words>"|--mnemonic-env MNEMONIC --path "m/44'/60'/0'/0/0" --keystore-pass <pass>|--keystore-pass-env WALLET_KEYSTORE_PASSWORD [--env-file .env] [--out build/wallets] [--emit-env] [--insecure-plain]`

## Implementation Steps

- Use `eth_account.Account.encrypt/decrypt` for keystore ops; normalize 0x-prefixed hex.
- Ensure output directory exists; write files atomically.
- Derive address from encrypted payload (via decrypt or re-derive from private key before encrypting).
- `--emit-env` optionally writes `.env.<address>` with `PRIVATE_KEY=` only when `--insecure-plain` is present.
- Return exit codes: 0 on success, non-zero with clear messages on error.
- HD support: enable `Account.enable_unaudited_hdwallet_features()`; derive via `Account.from_mnemonic(mnemonic, account_path=path)`.

## Validation & Testing

- Round-trip: random key → encrypt → write → read → decrypt → equals original.
- Verify file naming: `build/wallets/0xADDR.json` and permissions (best-effort).
- Password sources precedence: CLI flag > env var; error if missing.

## Risks & Edge Cases

- Wrong password → explicit error without leaking info.
- Disk write interruption → use temp file then rename.
- Never print private key unless `--insecure-plain` is explicitly set.
 - HD note: mnemonic is not stored; it must be provided each time or managed by a higher-level vault in later subtasks.

## Acceptance Criteria

- Can securely create keystore for a random or provided key.
- Can decrypt a keystore via CLI and output address (not key by default).
- No plaintext leaks unless explicitly requested.
 - Can derive a child key from mnemonic + derivation path and create a keystore for that child key.

## Implementation Status

- Implemented `src/setup/keystore.py` with encrypt/decrypt, atomic I/O, password resolution, env writer (insecure opt‑in), and `derive_privkey_from_mnemonic`.
- Implemented `src/setup/cli.py` with commands:
  - `keystore-create`, `keystore-decrypt`, and `hd-derive` (BIP‑44 path supported; default `m/44'/60'/0'/0/0`).

## Verification Commands

Set a password (choose your own):

- `export WALLET_KEYSTORE_PASSWORD=testpass`

Create a random keystore and decrypt it:

- `python -m src.setup.cli keystore-create --random --out build/wallets_test`
- `python -m src.setup.cli keystore-decrypt --file build/wallets_test/<ADDRESS>.json`

HD derive two addresses (paths 0 and 1) and decrypt them:

- `printf "MNEMONIC='word1 word2 ... word12'\nWALLET_KEYSTORE_PASSWORD=testpass\n" > .env.hd`
- `python -m src.setup.cli hd-derive --mnemonic-env MNEMONIC --path "m/44'/60'/0'/0/0" --env-file .env.hd --out build/wallets_hd_test`
- `python -m src.setup.cli hd-derive --mnemonic-env MNEMONIC --path "m/44'/60'/0'/0/1" --env-file .env.hd --out build/wallets_hd_test`
- `for f in build/wallets_hd_test/*.json; do echo "--- $f"; python -m src.setup.cli keystore-decrypt --file "$f" --env-file .env.hd; done`

Optional cross‑check with Python to confirm addresses for given paths (does not write keys):

- `python - << 'PY'
import os
from eth_account import Account
from eth_utils import to_checksum_address
Account.enable_unaudited_hdwallet_features()
mnemonic = os.environ.get('MNEMONIC')
for i in [0,1]:
    path = f"m/44'/60'/0'/0/{i}"
    acct = Account.from_mnemonic(mnemonic, account_path=path)
    print(i, path, to_checksum_address(acct.address))
PY`

Security notes:

- Plaintext outputs require `--insecure-plain` and are not recommended.
- The mnemonic is sensitive; avoid storing it in shell history or logs.

Using PRIVATE_KEY from .env:

- `echo "PRIVATE_KEY=0x..." > .env.local` (or ensure PRIVATE_KEY is exported in your shell)
- `export WALLET_KEYSTORE_PASSWORD=testpass`
- `python -m src.setup.cli keystore-create --private-key-env PRIVATE_KEY --env-file .env.local --out build/wallets_from_env`
- `ls build/wallets_from_env` and decrypt with:
- `python -m src.setup.cli keystore-decrypt --file build/wallets_from_env/<ADDRESS>.json`

Single-shot derivation with in-memory mnemonic + password:

- `python -m src.setup.cli hd-new --count 2 --path-base "m/44'/60'/0'/0" --out build/wallets_hd_new --print-secrets`
- This prints the mnemonic and the keystore password once (not stored). Save them securely if you need to decrypt later.

## PRIVATE_KEY-only minimal flow

The keystore password can be derived deterministically from `PRIVATE_KEY` in `.env` — no `WALLET_KEYSTORE_PASSWORD` required.

1) Create a `.env.pk` containing a fresh `PRIVATE_KEY`:

```bash
python - << 'PY'
from eth_account import Account
acct = Account.create()
open('.env.pk','w').write('PRIVATE_KEY=0x'+bytes(acct.key).hex()+'\n')
print('Wrote .env.pk')
PY
```

2) Create a keystore using only `.env.pk` (no password flags):

```bash
python -m src.setup.cli keystore-create --private-key-env PRIVATE_KEY --env-file .env.pk --out build/env_only_test
```

3) Decrypt the keystore using only `.env.pk` (no password flags):

```bash
FILE=$(ls -t build/env_only_test/*.json | head -n1)
python -m src.setup.cli keystore-decrypt --file "$FILE" --env-file .env.pk --private-key-env PRIVATE_KEY
```

Notes:
- The keystore password is derived from `PRIVATE_KEY` in-memory; do not delete `.env.pk` if you plan to decrypt later.
- You can replace `.env.pk` with any `.env` file that only contains `PRIVATE_KEY=0x...` and the commands still work.

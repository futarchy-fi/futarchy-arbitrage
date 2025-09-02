# 02 – Wallet Manager ◐

## Goal

Implement batch wallet generation (HD and random), keystore indexing, import of existing private keys, and a simple `list` display. Extend the CLI accordingly.

## Deliverables

- `src/setup/wallet_manager.py`:
  - `load_index(index_path)` / `save_index(index_path, records)`
  - `scan_keystores(keystore_dir)`
  - `derive_hd_batch(mnemonic, path_base, start, count, password, out_dir, tags, emit_env, insecure_plain)`
  - `create_random_wallets(count, password, out_dir, tags, emit_env, insecure_plain)`
  - `import_private_keys(keys, password, out_dir, tags, emit_env, insecure_plain)`
- CLI additions in `src/setup/cli.py`:
  - `generate` – batch create wallets (`--mode hd|random`, `--count`, `--start`, `--path-base`, `--mnemonic|--mnemonic-env`, `--keystore-pass|--keystore-pass-env`, `--env-file`, `--out`, `--index`, `--tag`, `--emit-env`, `--insecure-plain`)
  - `list` – show wallets from index (fallback to scanning keystore dir); formats: `table|json`
  - `import-keys` – import from `--file` or repeated `--key`; updates index

## Implementation Status

- Implemented all deliverables above; integrated into CLI.

## Verification Commands

Env-only flows (recommended for reproducibility):

- Create an env file with mnemonic and password:
  - `printf "MNEMONIC='<12-word mnemonic>'\nWALLET_KEYSTORE_PASSWORD=testpass\n" > .env.wm`

HD batch (derive first 5 at base path using .env only):
- `python -m src.setup.cli generate --mode hd --count 5 --start 0 --path-base "m/44'/60'/0'/0" --mnemonic-env MNEMONIC --env-file .env.wm --out build/wm_hd_env`
- `python -m src.setup.cli list --out build/wm_hd_env --format table`

Idempotency check (no duplicates on repeat):
- `python -m src.setup.cli generate --mode hd --count 5 --start 0 --path-base "m/44'/60'/0'/0" --mnemonic-env MNEMONIC --env-file .env.wm --out build/wm_hd_env`
- `python -m src.setup.cli list --out build/wm_hd_env --format json | jq '.wallets | length'` (length remains 5)

Random batch with .env-only password:
- `python -m src.setup.cli generate --mode random --count 2 --env-file .env.wm --out build/wm_rand_env`
- `python -m src.setup.cli list --out build/wm_rand_env --format table`

PRIVATE_KEY-only minimal flow for subtask 2 (no WALLET_KEYSTORE_PASSWORD):

1) Create `.env.wm.pk` with a fresh PRIVATE_KEY:

```bash
python - << 'PY'
from eth_account import Account
acct = Account.create()
open('.env.wm.pk','w').write('PRIVATE_KEY=0x'+bytes(acct.key).hex()+'\n')
print('Wrote .env.wm.pk')
PY
```

2) Generate 3 random wallets using only PRIVATE_KEY-derived password:

```bash
python -m src.setup.cli generate --mode random --count 3 --env-file .env.wm.pk --out build/wm_env_only
```

3) List and decrypt one keystore using only PRIVATE_KEY-derived password:

```bash
python -m src.setup.cli list --out build/wm_env_only --format table
FILE=$(ls -t build/wm_env_only/0x*.json | head -n1)
python -m src.setup.cli keystore-decrypt --file "$FILE" --env-file .env.wm.pk --private-key-env PRIVATE_KEY
```

Continue HD derivation later using only the generated seed env:

4) Create seed env from PRIVATE_KEY and derive 3 addresses; writes `.env.seed` with MNEMONIC, WALLET_KEYSTORE_PASSWORD, and HD_PATH_BASE:

```bash
python -m src.setup.cli hd-from-env --env-file .env.wm.pk --out-env .env.seed --count 3 --out build/wm_hd_seed
```

5) Generate 2 more addresses (indices 3 and 4) using only `.env.seed` (no extra flags needed for mnemonic or path):

```bash
python -m src.setup.cli generate --mode hd --count 2 --start 3 --env-file .env.seed --out build/wm_hd_seed
python -m src.setup.cli list --out build/wm_hd_seed --format table
```

Import keys using .env-only password:
- `printf "0x<key1>\n0x<key2>\n" > keys.txt`
- `python -m src.setup.cli import-keys --file keys.txt --env-file .env.wm --out build/wm_import_env`
- `python -m src.setup.cli list --out build/wm_import_env --format table`

## Notes

- Index path defaults to `<out>/index.json` and is created/updated on generate/import.
- `--emit-env` is insecure and requires `--insecure-plain` on keystore creation commands; avoid in production.
- HD derivation requires a valid BIP‑39 mnemonic; use `hd-new` to generate one safely if needed.
 - All commands that accept `--env-file` will load it before resolving `MNEMONIC` and/or `WALLET_KEYSTORE_PASSWORD` (and other env-based options).

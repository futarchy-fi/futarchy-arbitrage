Below is a practical, end‑to‑end plan to deploy a **working TickLens** contract that’s compatible with **Algebra (Integral) V3 pools** on **Gnosis Chain (mainnet, chainId 100)**. I use Hardhat as the primary toolchain (Foundry notes included). Citations are attached where they matter most.

---

## What TickLens is (and why you deploy it)

* Algebra’s periphery includes a **TickLens** contract (ported from Uniswap v3 periphery) that exposes `getPopulatedTicksInWord(pool, tickBitmapIndex)` for reading populated ticks in a CLAMM pool. Algebra credits Uniswap and keeps the same semantics, so your UI/tools can reuse existing tick logic. ([Algebra Finance][1], [Medium][2])
* Algebra’s **Step-by-step deployment** guide lists **TickLens** among periphery contracts that integrators deploy and then reuse across their frontends/backends. ([Algebra Finance][3])

---

## Gnosis Chain parameters you’ll use

| Item                            | Value                                                          |
| ------------------------------- | -------------------------------------------------------------- |
| Network                         | Gnosis (mainnet)                                               |
| Chain ID                        | 100                                                            |
| Native symbol                   | XDAI                                                           |
| RPC URL                         | [https://rpc.gnosischain.com](https://rpc.gnosischain.com)     |
| Explorer                        | [https://gnosisscan.io](https://gnosisscan.io)                 |
| Explorer API (for verification) | [https://api.gnosisscan.io/api](https://api.gnosisscan.io/api) |

Sources: official Gnosis docs for MetaMask setup (RPC, chainId, explorer) and Gnosis developer docs (Gnosisscan verification). ([Gnosis Chain][4])

> Tip (optional): gateway.fm RPC: `https://rpc.gnosis.gateway.fm`. ([Gnosis Chain][5])

---

## Prerequisites

* Node 18+ and npm.
* A deployer EOA funded with a little **xDAI** on Gnosis.
* A **Gnosisscan API key** (free) for contract verification. ([Gnosis Chain][6])

---

## Project setup (Hardhat)

1. Initialize

```bash
mkdir algebra-ticklens-gnosis && cd $_
npm init -y
npm i -D hardhat @nomicfoundation/hardhat-ethers ethers @nomicfoundation/hardhat-verify dotenv
# Algebra packages (periphery contains TickLens)
npm i @cryptoalgebra/integral-periphery @cryptoalgebra/integral-core
```

NPM package provides Algebra periphery contracts (GPL-2.0-or-later; ported from Uniswap). ([npm][7])

2. Create Hardhat

```bash
npx hardhat init # choose "Create an empty hardhat.config.js"
```

3. Add **.env**

```bash
GNOSIS_RPC_URL=https://rpc.gnosischain.com
PRIVATE_KEY=0xyour_private_key # no quotes
GNOSISSCAN_API_KEY=your_api_key
```

4. Hardhat config (`hardhat.config.js`)

```js
require("dotenv").config();
require("@nomicfoundation/hardhat-ethers");
require("@nomicfoundation/hardhat-verify");

const { GNOSIS_RPC_URL, PRIVATE_KEY, GNOSISSCAN_API_KEY } = process.env;

module.exports = {
  solidity: {
    version: "0.8.20",
    settings: {
      optimizer: { enabled: true, runs: 1_000_000 } // typical for Algebra/Uniswap periphery builds
    }
  },
  networks: {
    gnosis: {
      url: GNOSIS_RPC_URL,
      chainId: 100,
      accounts: PRIVATE_KEY ? [PRIVATE_KEY] : []
    }
  },
  etherscan: {
    // Gnosisscan is Etherscan-compatible; note the '/api' in apiURL
    apiKey: { gnosis: GNOSISSCAN_API_KEY },
    customChains: [
      {
        network: "gnosis",
        chainId: 100,
        urls: {
          apiURL: "https://api.gnosisscan.io/api",
          browserURL: "https://gnosisscan.io"
        }
      }
    ]
  }
};
```

Notes: Gnosisscan verification uses the Etherscan plugin with a **customChains** entry and the API base **including `/api`**. ([Gnosis Chain][6], [npm][8], [GitHub][9])

---

## Contract source

TickLens has **no constructor args** and is **stateless**. You can deploy it as‑is from Algebra’s periphery package.

Create `contracts/TickLensImport.sol`:

```solidity
// SPDX-License-Identifier: GPL-2.0-or-later
pragma solidity =0.8.20;

// One of these import paths will match the package version.
// Check node_modules to confirm the exact folder layout.
//
import "@cryptoalgebra/integral-periphery/contracts/lens/TickLens.sol";
// If your package version nests under periphery/, use:
// import "@cryptoalgebra/integral-periphery/contracts/periphery/lens/TickLens.sol";
```

> Why 0.8.20? Algebra’s public builds of TickLens are compiled with 0.8.20; using that version and high optimizer runs helps produce the expected bytecode/metadata for clean verification. ([explorer-testnet.incentiv.io][10])

---

## Deployment script

Create `scripts/deploy-ticklens.js`:

```js
const hre = require("hardhat");

async function main() {
  const factory = await hre.ethers.getContractFactory("TickLens");
  const tickLens = await factory.deploy();
  await tickLens.waitForDeployment();
  const addr = await tickLens.getAddress();
  console.log("TickLens deployed to:", addr);

  // Optional: wait a few blocks for the explorer indexer, then verify
  // Or run `npx hardhat verify --network gnosis <addr>` separately
}

main().catch((e) => { console.error(e); process.exit(1); });
```

Deploy:

```bash
npx hardhat run scripts/deploy-ticklens.js --network gnosis
```

Verify:

```bash
npx hardhat verify --network gnosis <DEPLOYED_ADDRESS>
```

(You can also verify manually via the Gnosisscan UI if needed.) ([Gnosis Chain Blockchain Explorer][11])

---

## Quick smoke test (reads from a pool)

After deployment, test against **an Algebra pool address on Gnosis** (your own Integral‑based DEX, or a test pool you created). In the Hardhat console:

```bash
npx hardhat console --network gnosis
```

```js
const tickLens = await ethers.getContractAt("TickLens", "<YOUR_TICKLENS_ADDRESS>");
const pool = "<AN_ALGEBRA_POOL_ADDRESS_ON_GNOSIS>";
// Read the first word (index 0) of the pool's tick bitmap:
await tickLens.getPopulatedTicksInWord(pool, 0);
```

TickLens API (same semantics as Uniswap v3): returns an array of populated ticks for the given `tickBitmapIndex`. ([Algebra Finance][1], [Uniswap Docs][12])

---

## (Optional) Chiado testnet first

If you prefer a dry‑run:

* Chain ID: **10200**
* RPC: **[https://rpc.chiadochain.net](https://rpc.chiadochain.net)**
* Configure `networks.chiado` similarly and deploy/verify there first. ([Gnosis Chain][4], [docs.chainstack.com][13])

---

## Operational notes & gotchas

* **License**: TickLens is GPL‑2.0‑or‑later (via Algebra periphery / Uniswap periphery). Keep headers intact when importing. ([Algebra Finance][1], [npm][7])
* **Why not use Uniswap’s TickLens on Gnosis?** It exists (address listed in the Uniswap v3 Gnosis deployment) but is meant for **Uniswap pools**, not Algebra pools. Use the Algebra periphery TickLens for Algebra pools, as per Algebra’s docs and deployment flow. ([Algebra Finance][3])
* **Verification fails with “Unexpected token < … not valid JSON”**: double‑check your **apiURL includes `/api`** in `customChains` and that your compiler settings match (0.8.20 + optimizer). ([GitHub][9])
* **RPC issues**: If the public RPC is flaky, switch to another provider from the Gnosis RPC providers list. ([Gnosis Chain][14])

---

## Foundry alternative (sketch)

1. Install:

```bash
forge init algebra-ticklens-gnosis
cd algebra-ticklens-gnosis
forge install cryptoalgebra/Algebra
```

2. Create `src/TickLensImport.sol` with the same import as above (adjust `remappings.txt` if needed).
3. Deploy:

```bash
forge create --rpc-url https://rpc.gnosischain.com \
  --private-key $PRIVATE_KEY src/TickLensImport.sol:TickLens
```

4. Verify with a Gnosisscan‑compatible verifier (or use manual UI). If using automated tools, make sure the target uses `https://api.gnosisscan.io/api`. ([Gnosis Chain][6], [npm][8])

---

## Deliverables checklist (what you’ll produce)

* **Deployed address** for TickLens on Gnosis.
* **Verified source** on Gnosisscan (publicly readable ABI).
* A one‑liner **smoke test** result proving `getPopulatedTicksInWord()` returns data on a known **Algebra pool** on Gnosis (your own pool if you’re the first to deploy Algebra pools there).

---

## Why this plan works

* Algebra’s own documentation defines TickLens and lists it among the periphery contracts integrators deploy. ([Algebra Finance][1])
* Gnosis mainnet parameters and explorer/verification path are official and stable. ([Gnosis Chain][4])

If you want, I can adapt these steps to your preferred stack (e.g., pure Foundry with CI, or a multisig‑controlled deployment) and include a minimal script to query one of your pools right after deployment.

[1]: https://docs.algebra.finance/algebra-integral-documentation/algebra-v1-technical-reference/contracts/api-reference-v2.0/v2.0-periphery/ticklens?utm_source=chatgpt.com "TickLens | Algebra Integral"
[2]: https://medium.com/%40crypto_algebra/integral-by-algebra-next-gen-dex-infrastructure-vs-balancer-uniswap-traderjoe-ba72d69b3431?utm_source=chatgpt.com "Integral by Algebra: Next-Gen DEX Infrastructure vs. ..."
[3]: https://docs.algebra.finance/algebra-integral-documentation/algebra-integral-technical-reference/integration-process/step-by-step-deployment "Step by Step Deployment | Algebra Integral"
[4]: https://docs.gnosischain.com/tools/wallets/metamask/?utm_source=chatgpt.com "MetaMask | Gnosis Chain"
[5]: https://docs.gnosischain.com/about/networks/mainnet?utm_source=chatgpt.com "Gnosis (Mainnet)"
[6]: https://docs.gnosischain.com/developers/Verify%20Smart%20Contracts/gnosisscan?utm_source=chatgpt.com "Using Gnosisscan - Gnosis Chain"
[7]: https://www.npmjs.com/package/%40cryptoalgebra/integral-periphery?utm_source=chatgpt.com "cryptoalgebra/integral-periphery"
[8]: https://www.npmjs.com/package/%40layerzerolabs/verify-contract?utm_source=chatgpt.com "layerzerolabs/verify-contract"
[9]: https://github.com/NomicFoundation/hardhat/issues/3957?utm_source=chatgpt.com "Contract verification is failing with \"Unexpected token < in ..."
[10]: https://explorer-testnet.incentiv.io/address/0x3bCd0D9F1111dc1300dbc03951Ab7307b8a54f49?tab=contract&utm_source=chatgpt.com "Contract details"
[11]: https://gnosisscan.io/verifyContract?utm_source=chatgpt.com "Verify & Publish Contract Source Code | GnosisScan"
[12]: https://docs.uniswap.org/contracts/v3/reference/periphery/lens/TickLens?utm_source=chatgpt.com "TickLens"
[13]: https://docs.chainstack.com/docs/gnosis-tooling?utm_source=chatgpt.com "Gnosis Chain tooling"
[14]: https://docs.gnosischain.com/tools/RPC%20Providers/?utm_source=chatgpt.com "RPC Providers | Gnosis Chain"

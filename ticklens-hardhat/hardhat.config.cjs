require('dotenv/config');
require('@nomicfoundation/hardhat-ethers');
require('@nomicfoundation/hardhat-verify');

const RPC_FALLBACK = process.env.GNOSIS_RPC_URL || process.env.RPC_URL;
const { PRIVATE_KEY, GNOSISSCAN_API_KEY } = process.env;

function getAccounts() {
  if (!PRIVATE_KEY) return [];
  const key = PRIVATE_KEY.startsWith('0x') ? PRIVATE_KEY : `0x${PRIVATE_KEY}`;
  return [key];
}

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: '0.8.20',
    settings: { optimizer: { enabled: true, runs: 1000000 } }
  },
  networks: {
    gnosis: {
      url: RPC_FALLBACK || 'https://rpc.gnosischain.com',
      chainId: 100,
      accounts: getAccounts(),
    },
  },
  etherscan: {
    apiKey: { gnosis: GNOSISSCAN_API_KEY || '' },
    customChains: [
      {
        network: 'gnosis',
        chainId: 100,
        urls: {
          apiURL: 'https://api.gnosisscan.io/api',
          browserURL: 'https://gnosisscan.io',
        },
      },
    ],
  },
};


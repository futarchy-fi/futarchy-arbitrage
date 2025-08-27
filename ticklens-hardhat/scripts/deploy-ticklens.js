import hardhat from 'hardhat';
const { ethers } = hardhat;
import TickLensArtifact from '@cryptoalgebra/integral-periphery/artifacts/contracts/lens/TickLens.sol/TickLens.json' assert { type: 'json' };

async function main() {
  const factory = await ethers.getContractFactoryFromArtifact(TickLensArtifact);
  const contract = await factory.deploy();
  const receipt = await contract.deploymentTransaction().wait();
  const addr = await contract.getAddress();
  console.log('TickLens deployed to:', addr);
  if (receipt) console.log('Deployed in tx:', receipt.hash);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

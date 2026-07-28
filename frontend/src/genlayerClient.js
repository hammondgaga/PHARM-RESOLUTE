import { createClient, createAccount } from "genlayer-js";
import { studionet, testnetAsimov } from "genlayer-js/chains";

// Set VITE_NETWORK=testnet in your .env to point at Asimov testnet once
// the contract is deployed there. Defaults to GenLayer Studio for local
// development against the simulator.
const NETWORK = import.meta.env.VITE_NETWORK || "studio";
const chain = NETWORK === "testnet" ? testnetAsimov : studionet;

// In production, load the private key from a wallet connection instead of
// generating a throwaway account. createAccount() here is only for local
// development against the Studio simulator.
const account = createAccount();

export const client = createClient({
  chain,
  account,
});

export const CONTRACT_ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS || "";

export async function submitClaim(fields) {
  const {
    shipment_id,
    pharmacy_name,
    carrier_name,
    distributor_name,
    last_known_temp_c,
    delay_narrative,
    packaging_condition,
    gps_deviation_notes,
  } = fields;

  const txHash = await client.writeContract({
    address: CONTRACT_ADDRESS,
    functionName: "submit_claim",
    args: [
      shipment_id,
      pharmacy_name,
      carrier_name,
      distributor_name,
      last_known_temp_c,
      delay_narrative,
      packaging_condition,
      gps_deviation_notes,
    ],
    value: 0,
  });

  return client.waitForTransactionReceipt({ hash: txHash });
}

export async function fundEscrow(shipmentId, amount) {
  const txHash = await client.writeContract({
    address: CONTRACT_ADDRESS,
    functionName: "fund_escrow",
    args: [shipmentId],
    value: amount,
  });
  return client.waitForTransactionReceipt({ hash: txHash });
}

export async function releasePayout(claimId, pharmacyAddress) {
  const txHash = await client.writeContract({
    address: CONTRACT_ADDRESS,
    functionName: "release_payout",
    args: [claimId, pharmacyAddress],
    value: 0,
  });
  return client.waitForTransactionReceipt({ hash: txHash });
}

export async function getAllClaims() {
  return client.readContract({
    address: CONTRACT_ADDRESS,
    functionName: "get_all_claims",
    args: [],
  });
}

export async function getEscrowBalance(shipmentId) {
  return client.readContract({
    address: CONTRACT_ADDRESS,
    functionName: "get_escrow_balance",
    args: [shipmentId],
  });
}

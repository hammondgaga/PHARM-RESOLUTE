import { createClient, createAccount } from "genlayer-js";
import { studionet, testnetAsimov } from "genlayer-js/chains";

// Set VITE_NETWORK=testnet in your .env to point at Asimov testnet once
// the contract is deployed there. Defaults to GenLayer Studio for local
// development against the simulator.
const NETWORK = import.meta.env.VITE_NETWORK || "studio";
const chain = NETWORK === "testnet" ? testnetAsimov : studionet;

// In production, load the account from a connected wallet instead of
// generating a throwaway one. createAccount() here is only for local
// development against the Studio simulator. Note: because roles are now
// bound to specific addresses in the contract (register_shipment), the
// SAME account must be used consistently as "the pharmacy" across a given
// shipment's fund_escrow -> submit_claim -> release_payout flow for the
// demo to work end-to-end from a single browser session.
const account = createAccount();

export const client = createClient({
  chain,
  account,
});

export const CONTRACT_ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS || "";
export const MY_ADDRESS = account.address;

const WAIT_OPTS = { interval: 3000, retries: 40 }; // LLM consensus calls take longer than plain writes

export async function registerShipment(shipmentId, carrierAddress, pharmacyAddress) {
  const txHash = await client.writeContract({
    address: CONTRACT_ADDRESS,
    functionName: "register_shipment",
    args: [shipmentId, carrierAddress, pharmacyAddress],
    value: 0,
  });
  return client.waitForTransactionReceipt({ hash: txHash, ...WAIT_OPTS });
}

export async function fundEscrow(shipmentId, amount) {
  const txHash = await client.writeContract({
    address: CONTRACT_ADDRESS,
    functionName: "fund_escrow",
    args: [shipmentId],
    value: amount,
  });
  return client.waitForTransactionReceipt({ hash: txHash, ...WAIT_OPTS });
}

export async function submitClaim(fields) {
  const {
    shipment_id,
    last_known_temp_c,
    delay_narrative,
    packaging_condition,
    gps_deviation_notes,
    evidence_url,
  } = fields;

  const txHash = await client.writeContract({
    address: CONTRACT_ADDRESS,
    functionName: "submit_claim",
    args: [
      shipment_id,
      last_known_temp_c,
      delay_narrative,
      packaging_condition,
      gps_deviation_notes,
      evidence_url,
    ],
    value: 0,
  });

  return client.waitForTransactionReceipt({ hash: txHash, ...WAIT_OPTS });
}

export async function releasePayout(claimId) {
  const txHash = await client.writeContract({
    address: CONTRACT_ADDRESS,
    functionName: "release_payout",
    args: [claimId],
    value: 0,
  });
  return client.waitForTransactionReceipt({ hash: txHash, ...WAIT_OPTS });
}

export async function getAllClaims() {
  return client.readContract({
    address: CONTRACT_ADDRESS,
    functionName: "get_all_claims",
    args: [],
  });
}

export async function getShipment(shipmentId) {
  return client.readContract({
    address: CONTRACT_ADDRESS,
    functionName: "get_shipment",
    args: [shipmentId],
  });
}

export async function getEscrowBalance(shipmentId) {
  return client.readContract({
    address: CONTRACT_ADDRESS,
    functionName: "get_escrow_balance",
    args: [shipmentId],
  });
}

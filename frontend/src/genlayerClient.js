import { createClient, createAccount } from "genlayer-js";
import { studionet, testnetAsimov } from "genlayer-js/chains";

const NETWORK = import.meta.env.VITE_NETWORK || "studio";
const chain = NETWORK === "testnet" ? testnetAsimov : studionet;

// In production, load the account from a connected wallet instead of
// generating a throwaway one. Because roles are bound to specific
// addresses (register_shipment), the SAME account must be used
// consistently as "the pharmacy" (or "the carrier") across a shipment's
// flow for the demo to work end-to-end from one browser session.
const account = createAccount();

export const client = createClient({ chain, account });
export const CONTRACT_ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS || "";
export const MY_ADDRESS = account.address;

const WAIT_OPTS = { interval: 3000, retries: 40 }; // LLM consensus calls take longer than plain writes

async function write(functionName, args, value = 0) {
  const txHash = await client.writeContract({
    address: CONTRACT_ADDRESS,
    functionName,
    args,
    value,
  });
  return client.waitForTransactionReceipt({ hash: txHash, ...WAIT_OPTS });
}

export const registerShipment = (shipmentId, carrierAddress, pharmacyAddress) =>
  write("register_shipment", [shipmentId, carrierAddress, pharmacyAddress]);

export const fundEscrow = (shipmentId, amount) =>
  write("fund_escrow", [shipmentId], amount);

export const submitClaim = (fields) =>
  write("submit_claim", [
    fields.shipment_id,
    fields.last_known_temp_c,
    fields.delay_narrative,
    fields.packaging_condition,
    fields.gps_deviation_notes,
    fields.evidence_url,
  ]);

export const submitDefense = (claimId, defenseNarrative, defenseEvidenceUrl) =>
  write("submit_defense", [claimId, defenseNarrative, defenseEvidenceUrl]);

export const waiveDefense = (claimId) => write("waive_defense", [claimId]);

export const resolveClaim = (claimId) => write("resolve_claim", [claimId]);

export const settleClaim = (claimId) => write("settle_claim", [claimId]);

export async function getAllClaims() {
  return client.readContract({ address: CONTRACT_ADDRESS, functionName: "get_all_claims", args: [] });
}

export async function getShipment(shipmentId) {
  return client.readContract({ address: CONTRACT_ADDRESS, functionName: "get_shipment", args: [shipmentId] });
}

export async function getEscrowBalance(shipmentId) {
  return client.readContract({ address: CONTRACT_ADDRESS, functionName: "get_escrow_balance", args: [shipmentId] });
}

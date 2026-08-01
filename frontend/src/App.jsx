import React, { useEffect, useState } from "react";
import {
  registerShipment,
  fundEscrow,
  submitClaim,
  submitDefense,
  resolveClaim,
  releasePayout,
  getAllClaims,
  CONTRACT_ADDRESS,
  MY_ADDRESS,
} from "./genlayerClient";

const emptyClaimForm = {
  shipment_id: "",
  last_known_temp_c: "",
  delay_narrative: "",
  packaging_condition: "",
  gps_deviation_notes: "",
  evidence_url: "",
};

const emptyDefenseForm = { claim_id: "", defense_narrative: "", defense_evidence_url: "" };

export default function App() {
  const [shipForm, setShipForm] = useState({ shipment_id: "", carrier_address: "", pharmacy_address: "" });
  const [fundForm, setFundForm] = useState({ shipment_id: "", amount: "" });
  const [claimForm, setClaimForm] = useState(emptyClaimForm);
  const [defenseForm, setDefenseForm] = useState(emptyDefenseForm);
  const [claims, setClaims] = useState({});
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  async function refreshClaims() {
    if (!CONTRACT_ADDRESS) return;
    try {
      setClaims((await getAllClaims()) || {});
    } catch (err) {
      console.error("Failed to load claims", err);
    }
  }

  useEffect(() => {
    refreshClaims();
  }, []);

  async function runAction(fn, successMsg, busyMsg) {
    setStatus(busyMsg);
    setLoading(true);
    try {
      await fn();
      setStatus(successMsg);
      await refreshClaims();
    } catch (err) {
      console.error(err);
      setStatus("Failed: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <header>
        <h1>PHARM RESOLUTE</h1>
        <p className="subtitle">
          A GenLayer Intelligent Contract that arbitrates cold-chain liability disputes for
          temperature-sensitive pharma shipments across Nigerian distribution networks - with
          both the pharmacy's claim and the carrier's defense weighed before a verdict.
        </p>
        {!CONTRACT_ADDRESS && (
          <p className="warning">Set VITE_CONTRACT_ADDRESS in your .env before submitting claims.</p>
        )}
        {MY_ADDRESS && (
          <p className="warning" style={{ background: "#0d2a1a", borderColor: "#1a7a3a", color: "#7affa0" }}>
            Your session account: <code>{MY_ADDRESS}</code>
            <br />
            This one browser session can only act as ONE role per shipment (whichever address
            you register it as - pharmacy or carrier). To see both sides interact, register a
            shipment using this address as the pharmacy for one test, and as the carrier for
            another.
          </p>
        )}
      </header>

      <section className="panel">
        <h2>1. Register a shipment</h2>
        <p className="hint">Binds a carrier and pharmacy address to a shipment_id.</p>
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            runAction(
              () => registerShipment(shipForm.shipment_id, shipForm.carrier_address, shipForm.pharmacy_address),
              `Shipment "${shipForm.shipment_id}" registered.`,
              "Registering shipment..."
            );
          }}
        >
          <label>
            Shipment ID
            <input value={shipForm.shipment_id} onChange={(e) => setShipForm({ ...shipForm, shipment_id: e.target.value })} required />
          </label>
          <label>
            Carrier address
            <input value={shipForm.carrier_address} onChange={(e) => setShipForm({ ...shipForm, carrier_address: e.target.value })} placeholder="0x..." required />
          </label>
          <label className="full-width">
            Pharmacy address
            <input value={shipForm.pharmacy_address} onChange={(e) => setShipForm({ ...shipForm, pharmacy_address: e.target.value })} placeholder="0x..." required />
          </label>
          <button type="submit" disabled={loading}>Register shipment</button>
        </form>
      </section>

      <section className="panel">
        <h2>2. Fund escrow</h2>
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            runAction(
              () => fundEscrow(fundForm.shipment_id, Number(fundForm.amount)),
              `Escrow funded for "${fundForm.shipment_id}".`,
              "Funding escrow..."
            );
          }}
        >
          <label>
            Shipment ID
            <input value={fundForm.shipment_id} onChange={(e) => setFundForm({ ...fundForm, shipment_id: e.target.value })} required />
          </label>
          <label>
            Amount (GEN, in wei)
            <input value={fundForm.amount} onChange={(e) => setFundForm({ ...fundForm, amount: e.target.value })} placeholder="e.g. 10000000000000000000" required />
          </label>
          <button type="submit" disabled={loading}>Fund escrow</button>
        </form>
      </section>

      <section className="panel">
        <h2>3. Pharmacy: submit a claim</h2>
        <p className="hint">Must be sent from the registered pharmacy account. No verdict yet - the carrier gets a chance to respond.</p>
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            runAction(
              async () => {
                await submitClaim(claimForm);
                setClaimForm(emptyClaimForm);
              },
              "Claim filed. Carrier may now submit a defense before it's resolved.",
              "Filing claim..."
            );
          }}
        >
          <label>
            Shipment ID
            <input value={claimForm.shipment_id} onChange={(e) => setClaimForm({ ...claimForm, shipment_id: e.target.value })} required />
          </label>
          <label>
            Last known temperature reading
            <input value={claimForm.last_known_temp_c} onChange={(e) => setClaimForm({ ...claimForm, last_known_temp_c: e.target.value })} placeholder="e.g. 9C recorded at 14:00 WAT" required />
          </label>
          <label className="full-width">
            Delay / transit narrative
            <textarea value={claimForm.delay_narrative} onChange={(e) => setClaimForm({ ...claimForm, delay_narrative: e.target.value })} required />
          </label>
          <label className="full-width">
            Packaging condition on arrival
            <textarea value={claimForm.packaging_condition} onChange={(e) => setClaimForm({ ...claimForm, packaging_condition: e.target.value })} required />
          </label>
          <label className="full-width">
            GPS / route deviation notes
            <textarea value={claimForm.gps_deviation_notes} onChange={(e) => setClaimForm({ ...claimForm, gps_deviation_notes: e.target.value })} required />
          </label>
          <label className="full-width">
            Evidence photo/document URL
            <input value={claimForm.evidence_url} onChange={(e) => setClaimForm({ ...claimForm, evidence_url: e.target.value })} placeholder="Link to a photo - validators fetch and visually verify this" required />
          </label>
          <button type="submit" disabled={loading}>Submit claim</button>
        </form>
      </section>

      <section className="panel">
        <h2>4. Carrier: submit a defense (required before resolution)</h2>
        <p className="hint">Must be sent from the registered carrier account. A claim cannot be resolved until this has been filed.</p>
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            runAction(
              async () => {
                await submitDefense(Number(defenseForm.claim_id), defenseForm.defense_narrative, defenseForm.defense_evidence_url);
                setDefenseForm(emptyDefenseForm);
              },
              "Defense filed.",
              "Filing defense..."
            );
          }}
        >
          <label>
            Claim ID
            <input value={defenseForm.claim_id} onChange={(e) => setDefenseForm({ ...defenseForm, claim_id: e.target.value })} required />
          </label>
          <label className="full-width">
            Defense narrative
            <textarea value={defenseForm.defense_narrative} onChange={(e) => setDefenseForm({ ...defenseForm, defense_narrative: e.target.value })} placeholder="e.g. Package was insulated per protocol; delay was due to a flooded route, not negligence" required />
          </label>
          <label className="full-width">
            Defense evidence URL
            <input value={defenseForm.defense_evidence_url} onChange={(e) => setDefenseForm({ ...defenseForm, defense_evidence_url: e.target.value })} placeholder="Link to photo/document supporting the defense" required />
          </label>
          <button type="submit" disabled={loading}>Submit defense</button>
        </form>
      </section>

      {status && <p className="status">{status}</p>}

      <section className="panel">
        <h2>Claims</h2>
        {Object.keys(claims).length === 0 && <p>No claims yet.</p>}
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Shipment</th>
              <th>Defense filed?</th>
              <th>Liability</th>
              <th>Payout band</th>
              <th>Paid out</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(claims).map(([id, c]) => (
              <tr key={id}>
                <td>{id}</td>
                <td>{c.shipment_id}</td>
                <td>{c.has_defense ? "Yes" : "No"}</td>
                <td>{c.resolved ? c.liability : "pending"}</td>
                <td>{c.resolved ? `${c.payout_band}%` : "-"}</td>
                <td>{c.paid_out ? "Yes" : "No"}</td>
                <td>
                  {!c.resolved && c.has_defense && (
                    <button onClick={() => runAction(() => resolveClaim(id), "Claim resolved.", "Resolving claim...")}>
                      Resolve claim
                    </button>
                  )}
                  {!c.resolved && !c.has_defense && (
                    <span style={{ color: "#9da7b3", fontSize: "0.85rem" }}>
                      Awaiting carrier defense
                    </span>
                  )}
                  {c.resolved && !c.paid_out && (
                    <button onClick={() => runAction(() => releasePayout(id), "Payout released.", "Releasing payout...")}>
                      Release payout
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

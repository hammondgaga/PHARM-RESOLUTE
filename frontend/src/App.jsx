import React, { useEffect, useState } from "react";
import {
  registerShipment,
  fundEscrow,
  submitClaim,
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

export default function App() {
  const [shipForm, setShipForm] = useState({
    shipment_id: "",
    carrier_address: "",
    pharmacy_address: "",
  });
  const [fundForm, setFundForm] = useState({ shipment_id: "", amount: "" });
  const [claimForm, setClaimForm] = useState(emptyClaimForm);
  const [claims, setClaims] = useState({});
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  async function refreshClaims() {
    if (!CONTRACT_ADDRESS) return;
    try {
      const result = await getAllClaims();
      setClaims(result || {});
    } catch (err) {
      console.error("Failed to load claims", err);
    }
  }

  useEffect(() => {
    refreshClaims();
  }, []);

  async function handleRegisterShipment(e) {
    e.preventDefault();
    setStatus("Registering shipment...");
    setLoading(true);
    try {
      await registerShipment(
        shipForm.shipment_id,
        shipForm.carrier_address,
        shipForm.pharmacy_address
      );
      setStatus(`Shipment "${shipForm.shipment_id}" registered.`);
    } catch (err) {
      console.error(err);
      setStatus("Registration failed: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleFundEscrow(e) {
    e.preventDefault();
    setStatus("Funding escrow...");
    setLoading(true);
    try {
      await fundEscrow(fundForm.shipment_id, Number(fundForm.amount));
      setStatus(`Escrow funded for "${fundForm.shipment_id}".`);
    } catch (err) {
      console.error(err);
      setStatus("Funding failed: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmitClaim(e) {
    e.preventDefault();
    setStatus("Submitting claim to validators for consensus...");
    setLoading(true);
    try {
      await submitClaim(claimForm);
      setStatus("Claim resolved. Refreshing list...");
      await refreshClaims();
      setClaimForm(emptyClaimForm);
    } catch (err) {
      console.error(err);
      setStatus("Submission failed: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleRelease(claimId) {
    setStatus(`Releasing payout for claim ${claimId}...`);
    try {
      await releasePayout(claimId);
      setStatus("Payout released to the shipment's registered pharmacy.");
      await refreshClaims();
    } catch (err) {
      console.error(err);
      setStatus("Release failed: " + err.message);
    }
  }

  return (
    <div className="page">
      <header>
        <h1>PHARM RESOLUTE</h1>
        <p className="subtitle">
          A GenLayer Intelligent Contract that arbitrates cold-chain
          liability disputes for temperature-sensitive pharma shipments
          across Nigerian distribution networks.
        </p>
        {!CONTRACT_ADDRESS && (
          <p className="warning">
            Set VITE_CONTRACT_ADDRESS in your .env to a deployed
            ColdChainOracle contract address before submitting claims.
          </p>
        )}
        {MY_ADDRESS && (
          <p className="warning" style={{ background: "#0d2a1a", borderColor: "#1a7a3a", color: "#7affa0" }}>
            Your session account: <code>{MY_ADDRESS}</code>
            <br />
            To test the full flow yourself, register a shipment using this
            exact address as the pharmacy_address below - only this
            account can then submit a claim or receive its payout.
          </p>
        )}
      </header>

      <section className="panel">
        <h2>1. Register a shipment</h2>
        <p className="hint">
          Binds a carrier and pharmacy address to a shipment_id. Only the
          registered pharmacy address may later file a claim or receive
          its payout.
        </p>
        <form onSubmit={handleRegisterShipment} className="form-grid">
          <label>
            Shipment ID
            <input
              value={shipForm.shipment_id}
              onChange={(e) => setShipForm({ ...shipForm, shipment_id: e.target.value })}
              required
            />
          </label>
          <label>
            Carrier address
            <input
              value={shipForm.carrier_address}
              onChange={(e) => setShipForm({ ...shipForm, carrier_address: e.target.value })}
              placeholder="0x..."
              required
            />
          </label>
          <label className="full-width">
            Pharmacy address
            <input
              value={shipForm.pharmacy_address}
              onChange={(e) => setShipForm({ ...shipForm, pharmacy_address: e.target.value })}
              placeholder="0x... (use your session account to test end-to-end)"
              required
            />
          </label>
          <button type="submit" disabled={loading}>
            Register shipment
          </button>
        </form>
      </section>

      <section className="panel">
        <h2>2. Fund escrow</h2>
        <form onSubmit={handleFundEscrow} className="form-grid">
          <label>
            Shipment ID
            <input
              value={fundForm.shipment_id}
              onChange={(e) => setFundForm({ ...fundForm, shipment_id: e.target.value })}
              required
            />
          </label>
          <label>
            Amount (GEN, in wei)
            <input
              value={fundForm.amount}
              onChange={(e) => setFundForm({ ...fundForm, amount: e.target.value })}
              placeholder="e.g. 10000000000000000000"
              required
            />
          </label>
          <button type="submit" disabled={loading}>
            Fund escrow
          </button>
        </form>
      </section>

      <section className="panel">
        <h2>3. Submit a claim</h2>
        <p className="hint">
          Must be sent from the registered pharmacy account for this
          shipment.
        </p>
        <form onSubmit={handleSubmitClaim} className="form-grid">
          <label>
            Shipment ID
            <input
              value={claimForm.shipment_id}
              onChange={(e) => setClaimForm({ ...claimForm, shipment_id: e.target.value })}
              required
            />
          </label>
          <label>
            Last known temperature reading
            <input
              value={claimForm.last_known_temp_c}
              onChange={(e) => setClaimForm({ ...claimForm, last_known_temp_c: e.target.value })}
              placeholder="e.g. 9C recorded at 14:00 WAT, unknown after"
              required
            />
          </label>
          <label className="full-width">
            Delay / transit narrative
            <textarea
              value={claimForm.delay_narrative}
              onChange={(e) => setClaimForm({ ...claimForm, delay_narrative: e.target.value })}
              placeholder="e.g. Vehicle held at checkpoint for 6 hours due to fuel scarcity"
              required
            />
          </label>
          <label className="full-width">
            Packaging condition on arrival
            <textarea
              value={claimForm.packaging_condition}
              onChange={(e) => setClaimForm({ ...claimForm, packaging_condition: e.target.value })}
              placeholder="Pharmacist's note on ice pack state, box integrity"
              required
            />
          </label>
          <label className="full-width">
            GPS / route deviation notes
            <textarea
              value={claimForm.gps_deviation_notes}
              onChange={(e) => setClaimForm({ ...claimForm, gps_deviation_notes: e.target.value })}
              placeholder="Any recorded deviation, or 'no GPS data available'"
              required
            />
          </label>
          <label className="full-width">
            Evidence photo/document URL
            <input
              value={claimForm.evidence_url}
              onChange={(e) => setClaimForm({ ...claimForm, evidence_url: e.target.value })}
              placeholder="Link to a photo of packaging/ice packs, or a page showing sensor logs - validators fetch and visually verify this"
              required
            />
          </label>
          <button type="submit" disabled={loading}>
            {loading ? "Submitting..." : "Submit claim"}
          </button>
        </form>
        {status && <p className="status">{status}</p>}
      </section>

      <section className="panel">
        <h2>Resolved claims</h2>
        {Object.keys(claims).length === 0 && <p>No claims yet.</p>}
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Shipment</th>
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
                <td>{c.liability}</td>
                <td>{c.payout_band}%</td>
                <td>{c.paid_out ? "Yes" : "No"}</td>
                <td>
                  {!c.paid_out && (
                    <button onClick={() => handleRelease(id)}>
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

import React, { useEffect, useState } from "react";
import {
  submitClaim,
  releasePayout,
  getAllClaims,
  CONTRACT_ADDRESS,
} from "./genlayerClient";

const emptyForm = {
  shipment_id: "",
  pharmacy_name: "",
  carrier_name: "",
  distributor_name: "",
  last_known_temp_c: "",
  delay_narrative: "",
  packaging_condition: "",
  gps_deviation_notes: "",
};

export default function App() {
  const [form, setForm] = useState(emptyForm);
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

  function handleChange(e) {
    setForm({ ...form, [e.target.name]: e.target.value });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setStatus("Submitting claim to validators for consensus...");
    setLoading(true);
    try {
      await submitClaim(form);
      setStatus("Claim resolved. Refreshing list...");
      await refreshClaims();
      setForm(emptyForm);
    } catch (err) {
      console.error(err);
      setStatus("Submission failed: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleRelease(claimId) {
    const pharmacyAddress = window.prompt(
      "Pharmacy address to receive payout:"
    );
    if (!pharmacyAddress) return;
    setStatus(`Releasing payout for claim ${claimId}...`);
    try {
      await releasePayout(claimId, pharmacyAddress);
      setStatus("Payout released.");
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
        <p className="tagline">Cold-Chain Integrity Oracle</p>
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
      </header>

      <section className="panel">
        <h2>Submit a claim</h2>
        <form onSubmit={handleSubmit} className="form-grid">
          <label>
            Shipment ID
            <input
              name="shipment_id"
              value={form.shipment_id}
              onChange={handleChange}
              required
            />
          </label>
          <label>
            Pharmacy name
            <input
              name="pharmacy_name"
              value={form.pharmacy_name}
              onChange={handleChange}
              required
            />
          </label>
          <label>
            Carrier name
            <input
              name="carrier_name"
              value={form.carrier_name}
              onChange={handleChange}
              required
            />
          </label>
          <label>
            Distributor name
            <input
              name="distributor_name"
              value={form.distributor_name}
              onChange={handleChange}
              required
            />
          </label>
          <label>
            Last known temperature reading
            <input
              name="last_known_temp_c"
              placeholder="e.g. 9C recorded at 14:00 WAT, unknown after that"
              value={form.last_known_temp_c}
              onChange={handleChange}
              required
            />
          </label>
          <label className="full-width">
            Delay / transit narrative
            <textarea
              name="delay_narrative"
              placeholder="e.g. Vehicle held at checkpoint for 6 hours due to fuel scarcity, no cold pack replacement available"
              value={form.delay_narrative}
              onChange={handleChange}
              required
            />
          </label>
          <label className="full-width">
            Packaging condition on arrival
            <textarea
              name="packaging_condition"
              placeholder="Pharmacist's note on ice pack state, box integrity, insulation condition"
              value={form.packaging_condition}
              onChange={handleChange}
              required
            />
          </label>
          <label className="full-width">
            GPS / route deviation notes
            <textarea
              name="gps_deviation_notes"
              placeholder="Any recorded route deviation, or 'no GPS data available'"
              value={form.gps_deviation_notes}
              onChange={handleChange}
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

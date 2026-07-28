# PHARM RESOLUTE
### Cold-Chain Integrity Oracle

A GenLayer Intelligent Contract that resolves ambiguous cold-chain liability
disputes for temperature-sensitive pharmaceutical shipments (vaccines,
insulin, certain antibiotics) moving through Nigeria's multi-hop
distribution networks: distributor → carrier/dispatch rider → pharmacy.

## The problem

When a pharmacy receives a shipment it suspects was compromised in transit,
there is almost never a clean, complete sensor log. What exists instead is a
mix of:

- a partial temperature reading from before contact was lost
- the carrier's account of what happened (fuel scarcity, checkpoint delays,
  a breakdown, a diversion)
- the receiving pharmacist's professional note on packaging/ice-pack
  condition
- rough or missing GPS/route data

Deciding whether the **carrier**, the **distributor**, or **nobody** (force
majeure) is liable is a judgment call, not a lookup. A traditional smart
contract has no way to reason over that evidence — it can only check
numbers against thresholds it was given in advance, and this kind of
dispute rarely comes with clean numbers.

## Why GenLayer

GenLayer's Intelligent Contracts let a set of validators independently read
the same natural-language evidence and reach consensus on a subjective
verdict, using the Equivalence Principle instead of exact-computation
matching. That's exactly the primitive this use case needs: no oracle
network, no off-chain arbitrator, no manual insurance adjuster — the
liability decision and the resulting payout both happen on-chain, from the
same evidence.

This is deliberately built as a **reusable primitive**, not a single app.
Any pharmacy, distributor, or adjacent perishable-goods supply chain (food,
agro-inputs, vaccines for veterinary use) can call `fund_escrow` →
`submit_claim` → `release_payout` against this same contract without being
built into this frontend at all.

## Architecture

```
contracts/cold_chain_oracle.py   Intelligent Contract (Python, GenLayer)
frontend/                        React claim-submission portal + dashboard
```

**Intelligent Contract — `ColdChainOracle`**

| Method | Type | What it does |
|---|---|---|
| `fund_escrow(shipment_id)` | write, payable | Distributor/carrier locks GEN against a shipment before dispatch |
| `submit_claim(...)` | write, non-deterministic | Validators independently reason over submitted evidence and reach strict consensus on `liability` (`carrier` / `distributor` / `force_majeure` / `no_breach`) and a `payout_band` (0/25/50/75/100%) |
| `release_payout(claim_id, pharmacy_address)` | write, deterministic | Pays out the escrowed pool according to the resolved verdict |
| `get_claim` / `get_all_claims` / `get_escrow_balance` | view | Read state |

The non-deterministic reasoning is isolated inside `submit_claim`, wrapped
in `gl.eq_principle.strict_eq`, per GenLayer's pattern for LLM-backed
methods — validators only need to agree on the structured verdict
(`liability`, `payout_band`), not on free-text wording, which keeps
consensus reliable.

> **Known limitation / future work:** the arbitrator's free-text reasoning
> is intentionally left out of the consensus payload, since exact wording
> varies between validators and would break `strict_eq`. A natural
> next step is to validate the reasoning field with GenLayer's
> non-comparative Equivalence Principle so the dashboard can show
> validator-agreed reasoning, not just the verdict.

**Frontend** — a claim submission form (pharmacy fills in the evidence
fields) and a dashboard of resolved claims with a payout-release action,
built with React + `genlayer-js`.

## Running locally

### Contract

1. Open [GenLayer Studio](https://studio.genlayer.com) and load
   `contracts/cold_chain_oracle.py`.
2. Deploy to the simulator, note the deployed contract address.

### Frontend

```bash
cd frontend
cp .env.example .env
# paste your deployed contract address into VITE_CONTRACT_ADDRESS
npm install
npm run dev
```

To point at Asimov testnet instead of the local simulator, set
`VITE_NETWORK=testnet` in `.env` after deploying there via the GenLayer
CLI (`genlayer deploy`).

## Use case walkthrough

1. A distributor dispatching insulin from Lagos to a pharmacy in Onitsha
   locks GEN into escrow for `shipment_id="SHP-2201"` via `fund_escrow`.
2. The shipment arrives; the receiving pharmacist believes the cold chain
   was broken and submits a claim with what evidence exists: last known
   temperature, the driver's delay account, packaging condition, and
   route notes.
3. Validators independently run the arbitration prompt against that
   evidence and reach consensus: e.g. `liability: "carrier"`,
   `payout_band: 75`.
4. `release_payout` pays 75% of the escrowed pool to the pharmacy's
   address, deterministically, based on the agreed verdict.

## License

MIT

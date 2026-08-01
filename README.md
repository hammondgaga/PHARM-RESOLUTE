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

## Dispute model (two-sided)

An earlier review round flagged that any caller could submit unverified
evidence and redirect an approved payout to an arbitrary address - and
separately, the original design only let the pharmacy speak, with no way
for the carrier to defend themselves. This version addresses both:

1. **`register_shipment`** - the distributor binds a specific carrier and
   pharmacy address to a `shipment_id` before anything else happens.
2. **`fund_escrow`** - distributor or carrier locks GEN against the
   shipment.
3. **`submit_claim`** - only the *registered pharmacy address* may file a
   claim, with a narrative and an `evidence_url` (a photo of packaging/ice
   packs). This does **not** immediately produce a verdict.
4. **`submit_defense`** *(optional, once)* - only the *registered carrier
   address* may respond, with their own narrative and evidence URL (e.g.
   photos showing the shipment was properly insulated).
5. **`resolve_claim`** - callable by anyone once a claim exists. Validators
   independently fetch *both* parties' evidence URLs themselves via
   `gl.nondet.web.render(url, mode="screenshot")` and weigh both images
   against both narratives via `gl.nondet.exec_prompt(images=[...])`,
   then reach strict consensus on `liability` and a `payout_band`. If the
   carrier never filed a defense, the arbitrator is told that explicitly
   rather than silently assuming guilt.
6. **`release_payout`** - pays the resolved verdict's share of escrow to
   the shipment's *registered* pharmacy address. No caller-supplied
   recipient parameter exists anymore - this closes the arbitrary-payout
   vulnerability directly.

Additional protections: a `claimed` flag blocks a second claim on the
same shipment, and both `submit_claim`/`submit_defense` assert
`gl.message.sender_address` matches the registered role - since that
address is the cryptographic signer of the transaction, evidence is
inherently tied to an authenticated account rather than free text anyone
could post.

**Known limitations / future work:**
- There's no on-chain deadline forcing a minimum response window before
  `resolve_claim` can be called - anyone can call it immediately, whether
  or not the carrier has responded. A production version would add a
  block-height-based deadline giving the carrier a guaranteed window.
- Evidence *images* are visually verified, but the contract doesn't
  cryptographically prove a photo was taken at the claimed time/place. A
  natural extension would have shipment sensors or a device sign evidence
  at capture time, with the contract checking that signature.

## Architecture (updated)

```
contracts/cold_chain_oracle.py   Intelligent Contract (Python, GenLayer)
frontend/                        React claim-submission portal + dashboard
```

**Intelligent Contract — `ColdChainOracle`**

| Method | Type | What it does |
|---|---|---|
| `register_shipment(shipment_id, carrier_address, pharmacy_address)` | write | Caller becomes the distributor; binds carrier and pharmacy addresses |
| `fund_escrow(shipment_id)` | write, payable | Distributor or carrier locks GEN against a registered shipment |
| `submit_claim(shipment_id, ..., evidence_url)` | write | Only the registered pharmacy may call this. Files a claim - no verdict yet. |
| `submit_defense(claim_id, defense_narrative, defense_evidence_url)` | write | Only the registered carrier may call this, once, before resolution |
| `resolve_claim(claim_id)` | write, non-deterministic | Callable by anyone. Validators fetch both parties' evidence URLs and reach strict consensus on `liability` and `payout_band`. |
| `release_payout(claim_id)` | write, deterministic | Pays out to the shipment's registered pharmacy address — no caller-supplied recipient |
| `get_shipment` / `get_claim` / `get_all_claims` / `get_escrow_balance` | view | Read state |

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

1. A distributor registers a shipment (`SHP-2201`), binding a specific
   carrier address and pharmacy address to it.
2. The distributor (or carrier) locks GEN into escrow for that shipment.
3. The shipment arrives; the registered pharmacy believes the cold chain
   was broken and files a claim: last known temperature, delay account,
   packaging condition, and a photo of the melted ice packs. No verdict
   yet.
4. The registered carrier has a chance to respond with a defense - e.g.
   a narrative explaining the delay was unavoidable, plus a photo showing
   the shipment was properly insulated at dispatch.
5. Either party (or anyone) calls `resolve_claim`. Validators
   independently fetch both evidence photos and weigh them against both
   narratives, then reach consensus: e.g. `liability: "carrier"`,
   `payout_band: 75` (partial liability, since the carrier's defense
   photo held up better than their narrative claimed).
6. `release_payout` pays 75% of the escrowed pool to the pharmacy's
   registered address, deterministically, based on the agreed verdict.

## License

MIT

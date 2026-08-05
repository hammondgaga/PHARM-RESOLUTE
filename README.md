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

## Dispute model (two-sided, with full settlement and a real deadline)

Staff feedback across two review rounds asked for: role-gated evidence and
payout (closed previously), a complete settlement path that accounts for
every escrow remainder, a deadline (or waiver) so a claim can't be stuck
forever on carrier silence, enforcement of valid liability/payout
combinations, and multi-account contract tests. This version addresses
all of it:

1. **`register_shipment`** - the distributor binds a specific carrier and
   pharmacy address to a `shipment_id`.
2. **`fund_escrow`** - distributor or carrier locks GEN against the
   shipment. Each funder's contribution is tracked individually
   (`funder_contributions`), so it can be refunded precisely later even
   if both the distributor and carrier both funded.
3. **`submit_claim`** - only the registered pharmacy may file a claim,
   with a narrative and an `evidence_url`. No verdict yet. Records a
   `filed_at` timestamp.
4. **`submit_defense`** *(optional)* - the registered carrier responds
   with their own narrative and evidence URL. Unblocks resolution
   immediately.
5. **`waive_defense`** *(optional)* - alternative to `submit_defense`:
   the carrier explicitly declines to respond. Also unblocks resolution
   immediately, before any deadline.
6. **The actual deadline** - if the carrier does *neither* of the above,
   `resolve_claim` becomes callable once `DEFENSE_WINDOW_SECONDS` have
   passed since `filed_at`. This is a genuine deterministic deadline, not
   a waiver-dependent workaround: GenVM pins Python's clock
   (`datetime.now()`, `time.time()`) to the current transaction's
   timestamp, so every validator re-executing `resolve_claim` sees the
   exact same value and agrees on whether the window has elapsed,
   without needing an external time source. A carrier who does *nothing
   at all* - not even a waiver - no longer blocks resolution forever.
   **The contract currently sets `DEFENSE_WINDOW_SECONDS = 120` (2
   minutes)** so the deadline path is actually observable in a normal
   testing session instead of requiring a multi-day wait - raise this to
   something like `172800`-`259200` (2-3 days) before a real deployment,
   since a carrier needs realistic time to respond.
7. **`resolve_claim`** - callable by anyone once a defense/waiver exists
   *or* the deadline has passed. Validators fetch both parties' evidence
   URLs (if any) as images and weigh them against both narratives, then
   reach strict consensus on `liability` and a `payout_band`. The
   verdict is checked against `ALLOWED_COMBINATIONS` before being
   accepted - e.g. `"no_breach"` and `"force_majeure"` can only pair
   with a 0% payout; `"carrier"` and `"distributor"` must pair with
   25/50/75/100%, never 0 (a liability finding with no payout is
   contradictory). An out-of-policy verdict causes the call to revert
   rather than being silently accepted.
8. **`settle_claim`** - pays the pharmacy its `payout_band` share of
   escrow, **and** refunds every remaining unit to whoever actually
   funded escrow, split proportionally to their tracked contributions.
   Escrow is always drained to exactly zero afterward - no verdict, not
   even a 0% one, leaves GEN stranded in the contract.

`get_claim` exposes `filed_at` and `defense_deadline` so a frontend can
show a countdown, and `is_resolvable(claim_id)` is a convenience view
that returns whether `resolve_claim` would currently succeed.

## Multi-account tests

`tests/test_cold_chain_oracle.py` uses GenLayer's `gltest` framework
(package `genlayer-test`, pytest-based) with four distinct signers
(distributor, carrier, pharmacy, and an unrelated stranger) to verify:
role binding, duplicate-claim protection, that resolution is blocked
until a defense/waiver/deadline unlocks it, that a carrier can't both
defend and waive, **the deadline mechanism itself** (resolution rejected
before the window and accepted after it, with zero carrier response, by
simulating time passing via `transaction_context={"genvm_datetime":
...}` rather than waiting 3 real days), full settlement (pharmacy paid +
escrow drained to zero regardless of verdict), double-settlement
protection, and per-funder contribution tracking across multiple
funders.

This suite was written against `gltest`'s actual installed API - verified
by installing `genlayer-test` and reading its source directly (the
account-switching pattern, `contract.connect(account)`, and the
`genvm_datetime` time-simulation parameter were both confirmed this way
rather than guessed) - and all 18 tests collect cleanly under `pytest`.
It has not been executed end-to-end against a live GenLayer node as part
of building this project, since no node was available in the build
environment; running it requires `gltest` installed and a GenLayer
node/localnet available:

```bash
pip install genlayer-test
gltest --network localnet
# or against GenLayer Studio's simulator:
gltest --network studionet
```

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
| `submit_defense(claim_id, defense_narrative, defense_evidence_url)` | write | Only the registered carrier may call this, once. Unblocks `resolve_claim` immediately. |
| `waive_defense(claim_id)` | write | Only the registered carrier may call this, once. Explicitly declines to respond; also unblocks `resolve_claim` immediately. |
| `resolve_claim(claim_id)` | write, non-deterministic | Callable by anyone once a defense/waiver exists, or once `DEFENSE_WINDOW_SECONDS` has elapsed since the claim was filed. Validators fetch both parties' evidence URLs and reach strict consensus on `liability` and `payout_band`, checked against `ALLOWED_COMBINATIONS`. |
| `settle_claim(claim_id)` | write, deterministic | Pays the pharmacy its share and refunds the remainder to whoever funded escrow, proportionally. Drains escrow to exactly zero. |
| `is_resolvable(claim_id)` | view | Whether `resolve_claim` would currently succeed |
| `get_shipment` / `get_claim` / `get_all_claims` / `get_escrow_balance` | view | Read state |

The non-deterministic reasoning is isolated inside `resolve_claim`, wrapped
in `gl.eq_principle.strict_eq`, per GenLayer's pattern for LLM-backed
methods — validators only need to agree on the structured verdict
(`liability`, `payout_band`), not on free-text wording, which keeps
consensus reliable.

**Evidence-fetch robustness.** `resolve_claim` fetches each side's
`evidence_url` as a screenshot before showing it to the arbitrator. A real
bug surfaced during manual testing: a defense evidence field accidentally
held a raw `data:image/...` URI instead of a real link, and
`gl.nondet.web.render` rejected it identically on every validator - which
reached a valid *consensus on the failure*, but since `submit_defense` is
one-shot, that permanently bricked the claim (no way to ever resolve it).
`resolve_claim` now catches this: unfetchable or non-http(s) evidence URLs
are skipped, with the arbitrator explicitly told a given side's evidence
couldn't be retrieved so it can still judge fairly on the narrative alone,
rather than the whole transaction reverting forever. Covered by
`TestEvidenceRobustness` in the test suite.

> **Known limitation / future work:** the arbitrator's free-text reasoning
> is intentionally left out of the consensus payload, since exact wording
> varies between validators and would break `strict_eq`. A natural
> next step is to validate the reasoning field with GenLayer's
> non-comparative Equivalence Principle so the dashboard can show
> validator-agreed reasoning, not just the verdict.

**Frontend** — a multi-step form (register shipment, fund escrow, submit
claim, submit defense/waive) and a claims dashboard with resolve/settle
actions, built with React + `genlayer-js`.

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

# { "Depends": "py-genlayer:test" }
"""
Cold-Chain Integrity Oracle
----------------------------
A GenLayer Intelligent Contract that resolves ambiguous cold-chain liability
disputes for temperature-sensitive pharmaceutical shipments (vaccines,
insulin, some antibiotics) moving through Nigeria's multi-hop distribution
networks (distributor -> carrier/dispatch -> pharmacy).

When a pharmacy receives a shipment it believes was compromised in transit,
there is rarely a clean, complete sensor log. Evidence is a mix of partial
temperature readings, a driver/carrier narrative (fuel scarcity, checkpoint
delays, vehicle breakdown, diversion), the receiving pharmacist's
professional assessment of packaging condition, and route/GPS notes.

Deciding whether the carrier, the distributor, or nobody (force majeure) is
liable is exactly the kind of natural-language judgment call a deterministic
contract cannot make on its own. This contract has GenLayer validators
independently reason over the submitted evidence and reach consensus on a
liability verdict and payout band, then (deterministically) executes payout
against an on-chain escrow pool for the shipment.

This is designed as a reusable primitive: any pharmacy, distributor, or
adjacent perishable-goods supply chain (food, agro-inputs) can call
`fund_escrow` + `submit_claim` + `release_payout` without needing to be
built into this same app.
"""

from genlayer import *
import json


class ColdChainOracle(gl.Contract):
    # claim_id (str) -> claim record (dict)
    claims: dict
    claim_counter: int
    # shipment_id (str) -> escrowed GEN balance for that shipment
    escrow_balance: dict
    owner: str

    def __init__(self):
        self.claims = {}
        self.claim_counter = 0
        self.escrow_balance = {}
        self.owner = gl.message.sender_address

    # ------------------------------------------------------------------
    # Escrow funding (deterministic)
    # ------------------------------------------------------------------
    @gl.public.write.payable
    def fund_escrow(self, shipment_id: str) -> None:
        """
        A distributor or carrier locks GEN value against a shipment_id
        before dispatch. This pool is what a successful claim pays out
        from.
        """
        amount = gl.message.value
        current = self.escrow_balance.get(shipment_id, 0)
        self.escrow_balance[shipment_id] = current + amount

    @gl.public.view
    def get_escrow_balance(self, shipment_id: str) -> int:
        return self.escrow_balance.get(shipment_id, 0)

    # ------------------------------------------------------------------
    # Claim submission and arbitration (non-deterministic, LLM consensus)
    # ------------------------------------------------------------------
    @gl.public.write
    def submit_claim(
        self,
        shipment_id: str,
        pharmacy_name: str,
        carrier_name: str,
        distributor_name: str,
        last_known_temp_c: str,
        delay_narrative: str,
        packaging_condition: str,
        gps_deviation_notes: str,
    ) -> int:
        """
        Submits a cold-chain breach claim with free-text evidence.
        Validators independently evaluate the same prompt and must reach
        strict consensus on the liability category and payout band before
        the claim is recorded as resolved.
        """
        claim_id = self.claim_counter
        self.claim_counter += 1

        prompt = f"""
You are an impartial cold-chain logistics arbitrator for pharmaceutical
shipments distributed across Nigeria.

Review the evidence below for a temperature-sensitive shipment dispute and
decide who bears liability for a possible cold-chain breach.

SHIPMENT ID: {shipment_id}
LAST KNOWN TEMPERATURE READING: {last_known_temp_c}
DELAY / TRANSIT NARRATIVE: {delay_narrative}
PACKAGING CONDITION ON ARRIVAL (pharmacist's note): {packaging_condition}
GPS / ROUTE DEVIATION NOTES: {gps_deviation_notes}

Consider common real-world causes in Nigerian logistics: fuel scarcity,
checkpoint or border delays, vehicle breakdown, route diversion through
high-heat conditions, poor insulated packaging, and genuinely unavoidable
circumstances (flooding, civil unrest, accidents).

Decide exactly:
1. liability: one of "carrier", "distributor", "force_majeure", "no_breach"
2. payout_band: one of 0, 25, 50, 75, 100
   (percentage of the escrowed shipment value owed to the pharmacy)

Respond using ONLY this JSON format, with no other words or characters:
{{"liability": "<carrier|distributor|force_majeure|no_breach>", "payout_band": <0|25|50|75|100>}}
"""

        def nondet():
            res = gl.nondet.exec_prompt(prompt, response_format="json")
            # Only the fields validators must strictly agree on are
            # included here. Free-text reasoning is intentionally excluded
            # from the consensus payload since wording varies between
            # validators; see README for how reasoning transparency could
            # be added via a non-comparative equivalence check.
            return json.dumps(
                {
                    "liability": res["liability"],
                    "payout_band": int(res["payout_band"]),
                },
                sort_keys=True,
            )

        verdict_json = gl.eq_principle.strict_eq(nondet)
        verdict = json.loads(verdict_json)

        self.claims[str(claim_id)] = {
            "shipment_id": shipment_id,
            "pharmacy_name": pharmacy_name,
            "carrier_name": carrier_name,
            "distributor_name": distributor_name,
            "liability": verdict["liability"],
            "payout_band": verdict["payout_band"],
            "resolved": True,
            "paid_out": False,
        }

        return claim_id

    @gl.public.view
    def get_claim(self, claim_id: int) -> dict:
        return self.claims.get(str(claim_id), {})

    @gl.public.view
    def get_all_claims(self) -> dict:
        return self.claims

    # ------------------------------------------------------------------
    # Payout execution (deterministic, gated on a resolved verdict)
    # ------------------------------------------------------------------
    @gl.public.write
    def release_payout(self, claim_id: int, pharmacy_address: str) -> None:
        key = str(claim_id)
        claim = self.claims.get(key)
        assert claim is not None, "claim does not exist"
        assert claim["resolved"], "claim not yet resolved"
        assert not claim["paid_out"], "claim already paid out"

        shipment_id = claim["shipment_id"]
        pool = self.escrow_balance.get(shipment_id, 0)
        payout = (pool * claim["payout_band"]) // 100

        if payout > 0:
            gl.emit_transfer(pharmacy_address, payout)
            self.escrow_balance[shipment_id] = pool - payout

        claim["paid_out"] = True
        self.claims[key] = claim

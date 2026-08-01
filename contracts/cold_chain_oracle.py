# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
PHARM RESOLUTE - Cold-Chain Integrity Oracle
----------------------------------------------
A GenLayer Intelligent Contract that resolves ambiguous cold-chain liability
disputes for temperature-sensitive pharmaceutical shipments (vaccines,
insulin, some antibiotics) moving through Nigeria's multi-hop distribution
networks (distributor -> carrier/dispatch -> pharmacy).

SECURITY MODEL
--------------
A shipment must be registered by its distributor before any claim can be
filed against it. Registration binds three addresses to a shipment_id:
distributor, carrier, and pharmacy. This closes two issues from an earlier
review round:

  1. Unauthenticated evidence: only the address registered as the
     shipment's pharmacy may call submit_claim for that shipment. Since
     gl.message.sender_address reflects the cryptographic signer of the
     transaction, a claim is inherently "signed" by an authenticated,
     pre-registered account rather than free text anyone could post.
  2. Arbitrary payout address: release_payout no longer accepts a
     recipient address as a parameter at all. Funds are always sent to
     the pharmacy address recorded at registration time.

A `claimed` flag on the shipment record also prevents the same shipment
from being claimed more than once.

Evidence verification: submit_claim accepts an evidence_url. Validators
independently fetch that URL themselves via gl.nondet.web.render(...,
mode="screenshot") and visually inspect it alongside the submitter's
written narrative via gl.nondet.exec_prompt(images=[...]), rather than
trusting free text alone. This is genuinely contract-verifiable: the
contract itself retrieves and reasons over the evidence, not the
claimant.
"""

from genlayer import *
from dataclasses import dataclass
import json


@allow_storage
@dataclass
class Shipment:
    distributor: Address
    carrier: Address
    pharmacy: Address
    escrow_balance: bigint
    claimed: bool


@allow_storage
@dataclass
class Claim:
    shipment_id: str
    liability: str
    payout_band: u32
    submitted_by: Address
    evidence_url: str
    resolved: bool
    paid_out: bool


class ColdChainOracle(gl.Contract):
    # shipment_id (str) -> registered shipment record
    shipments: TreeMap[str, Shipment]
    # claim_id (str) -> claim record
    claims: TreeMap[str, Claim]
    claim_counter: u32

    def __init__(self):
        self.claim_counter = 0

    # ------------------------------------------------------------------
    # Shipment registration (binds authenticated roles to a shipment)
    # ------------------------------------------------------------------
    @gl.public.write
    def register_shipment(
        self, shipment_id: str, carrier_address: str, pharmacy_address: str
    ) -> None:
        """
        Registers a shipment before dispatch. The caller becomes the
        distributor of record. carrier_address and pharmacy_address are
        bound to this shipment_id - only the registered pharmacy address
        will be able to file a claim or receive a payout for it.
        """
        assert shipment_id not in self.shipments, "shipment already registered"
        self.shipments[shipment_id] = Shipment(
            distributor=gl.message.sender_address,
            carrier=Address(carrier_address),
            pharmacy=Address(pharmacy_address),
            escrow_balance=0,
            claimed=False,
        )

    @gl.public.view
    def get_shipment(self, shipment_id: str) -> dict:
        s = self.shipments.get(shipment_id)
        if s is None:
            return {}
        return {
            "distributor": s.distributor.as_hex,
            "carrier": s.carrier.as_hex,
            "pharmacy": s.pharmacy.as_hex,
            "escrow_balance": s.escrow_balance,
            "claimed": s.claimed,
        }

    # ------------------------------------------------------------------
    # Escrow funding (deterministic, restricted to distributor or carrier)
    # ------------------------------------------------------------------
    @gl.public.write.payable
    def fund_escrow(self, shipment_id: str) -> None:
        shipment = self.shipments.get(shipment_id)
        assert shipment is not None, "shipment not registered"
        sender = gl.message.sender_address
        assert (
            sender == shipment.distributor or sender == shipment.carrier
        ), "only the distributor or carrier may fund escrow"

        amount = gl.message.value
        self.shipments[shipment_id] = Shipment(
            distributor=shipment.distributor,
            carrier=shipment.carrier,
            pharmacy=shipment.pharmacy,
            escrow_balance=shipment.escrow_balance + amount,
            claimed=shipment.claimed,
        )

    @gl.public.view
    def get_escrow_balance(self, shipment_id: str) -> int:
        s = self.shipments.get(shipment_id)
        return s.escrow_balance if s is not None else 0

    # ------------------------------------------------------------------
    # Claim submission and arbitration (non-deterministic, LLM consensus)
    # ------------------------------------------------------------------
    @gl.public.write
    def submit_claim(
        self,
        shipment_id: str,
        last_known_temp_c: str,
        delay_narrative: str,
        packaging_condition: str,
        gps_deviation_notes: str,
        evidence_url: str,
    ) -> int:
        """
        Submits a cold-chain breach claim. evidence_url should point to a
        photo of the shipment's packaging/ice packs on arrival (or a
        screenshot-able page showing sensor/log data). Validators
        independently fetch this URL themselves via gl.nondet.web.render
        and visually verify it against the submitted narrative, rather
        than trusting the pharmacist's text description alone. Only
        callable by the address registered as this shipment's pharmacy.
        Only one claim may ever be filed per shipment.
        """
        shipment = self.shipments.get(shipment_id)
        assert shipment is not None, "shipment not registered"
        sender = gl.message.sender_address
        assert sender == shipment.pharmacy, "only the registered pharmacy may file a claim"
        assert not shipment.claimed, "a claim has already been filed for this shipment"

        claim_id = self.claim_counter
        self.claim_counter += 1

        prompt = f"""
You are an impartial cold-chain logistics arbitrator for pharmaceutical
shipments distributed across Nigeria.

Review the evidence below for a temperature-sensitive shipment dispute and
decide who bears liability for a possible cold-chain breach. You have
also been given a photo/screenshot of the evidence referenced by the
claimant. Weigh what you can actually observe in the image against the
written narrative below - if the image contradicts the narrative (for
example, packaging looks intact despite a claim of melted ice packs),
factor that into your liability decision.

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
            if evidence_url:
                evidence_image = gl.nondet.web.render(evidence_url, mode="screenshot")
                res = gl.nondet.exec_prompt(
                    prompt,
                    images=[evidence_image],
                    response_format="json",
                )
            else:
                res = gl.nondet.exec_prompt(prompt, response_format="json")
            return json.dumps(
                {
                    "liability": res["liability"],
                    "payout_band": int(res["payout_band"]),
                },
                sort_keys=True,
            )

        verdict_json = gl.eq_principle.strict_eq(nondet)
        verdict = json.loads(verdict_json)

        self.claims[str(claim_id)] = Claim(
            shipment_id=shipment_id,
            liability=verdict["liability"],
            payout_band=verdict["payout_band"],
            submitted_by=sender,
            evidence_url=evidence_url,
            resolved=True,
            paid_out=False,
        )

        # Lock the shipment so it cannot be claimed again.
        self.shipments[shipment_id] = Shipment(
            distributor=shipment.distributor,
            carrier=shipment.carrier,
            pharmacy=shipment.pharmacy,
            escrow_balance=shipment.escrow_balance,
            claimed=True,
        )

        return claim_id

    def _claim_to_dict(self, c: Claim) -> dict:
        return {
            "shipment_id": c.shipment_id,
            "liability": c.liability,
            "payout_band": c.payout_band,
            "submitted_by": c.submitted_by.as_hex,
            "evidence_url": c.evidence_url,
            "resolved": c.resolved,
            "paid_out": c.paid_out,
        }

    @gl.public.view
    def get_claim(self, claim_id: int) -> dict:
        c = self.claims.get(str(claim_id))
        if c is None:
            return {}
        return self._claim_to_dict(c)

    @gl.public.view
    def get_all_claims(self) -> dict:
        result = {}
        for key, c in self.claims.items():
            result[key] = self._claim_to_dict(c)
        return result

    # ------------------------------------------------------------------
    # Payout execution (deterministic; recipient is always the shipment's
    # registered pharmacy address, never a caller-supplied one)
    # ------------------------------------------------------------------
    @gl.public.write
    def release_payout(self, claim_id: int) -> None:
        key = str(claim_id)
        claim = self.claims.get(key)
        assert claim is not None, "claim does not exist"
        assert claim.resolved, "claim not yet resolved"
        assert not claim.paid_out, "claim already paid out"

        shipment = self.shipments.get(claim.shipment_id)
        assert shipment is not None, "shipment not found"

        pool = shipment.escrow_balance
        payout = (pool * claim.payout_band) // 100

        if payout > 0:
            recipient = gl.get_contract_at(shipment.pharmacy)
            recipient.emit_transfer(value=payout)

            self.shipments[claim.shipment_id] = Shipment(
                distributor=shipment.distributor,
                carrier=shipment.carrier,
                pharmacy=shipment.pharmacy,
                escrow_balance=pool - payout,
                claimed=shipment.claimed,
            )

        self.claims[key] = Claim(
            shipment_id=claim.shipment_id,
            liability=claim.liability,
            payout_band=claim.payout_band,
            submitted_by=claim.submitted_by,
            evidence_url=claim.evidence_url,
            resolved=claim.resolved,
            paid_out=True,
        )

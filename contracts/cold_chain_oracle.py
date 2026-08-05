# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
PHARM RESOLUTE - Cold-Chain Integrity Oracle
----------------------------------------------
A GenLayer Intelligent Contract that resolves ambiguous cold-chain liability
disputes for temperature-sensitive pharmaceutical shipments (vaccines,
insulin, some antibiotics) moving through Nigeria's multi-hop distribution
networks (distributor -> carrier/dispatch -> pharmacy).

DISPUTE MODEL (two-sided, with settlement)
-------------------------------------------
  1. register_shipment - distributor binds a carrier and pharmacy address
     to a shipment_id.
  2. fund_escrow - distributor or carrier locks GEN against the shipment.
     Each funder's contribution is tracked individually so it can be
     refunded later.
  3. submit_claim - only the registered pharmacy may file a claim, with a
     narrative and an evidence_url (a photo of packaging/ice packs). No
     verdict yet. Records a filed_at timestamp.
  4. submit_defense OR waive_defense - the registered carrier may respond
     with a narrative and evidence_url, or explicitly decline. Either
     unblocks resolution immediately, before any deadline.
  5. resolve_claim - callable by anyone once EITHER a defense/waiver
     exists OR DEFENSE_WINDOW_SECONDS has elapsed since filed_at (a real,
     deterministic deadline - see below). Validators independently fetch
     both parties' evidence URLs (if any) as images and weigh them
     against both narratives via gl.nondet.exec_prompt, then reach strict
     consensus on liability and a payout_band, checked against an
     explicit allow-list before being accepted.
  6. settle_claim - pays the resolved payout_band's share of escrow to
     the shipment's registered pharmacy address, AND refunds whatever
     remains to whoever actually funded escrow (distributor and/or
     carrier), split proportionally to their contributions. Every GEN in
     escrow is accounted for regardless of verdict - none is ever left
     stranded in the contract.

DETERMINISTIC TIME (the actual deadline mechanism)
----------------------------------------------------
GenVM pins Python's clock (datetime.now(), time.time()) to the current
transaction's timestamp - every validator re-executing the transaction
sees the exact same value, so it's safe to use for storage and
comparisons without breaking consensus (this is different from fetching
"now" from an external source, which would need a non-deterministic
block). submit_claim records filed_at using this clock; resolve_claim
compares it against DEFENSE_WINDOW_SECONDS to decide whether enough time
has passed to proceed even without any carrier response at all. This
closes the gap a waiver-only design has: a carrier who does nothing -
not even an explicit waiver - no longer blocks resolution forever.

SECURITY MODEL
--------------
- Role binding: only the registered pharmacy can file a claim or receive
  a payout; only the registered carrier can defend, waive, or receive a
  refund. This closes an earlier issue where any caller could submit
  unverified evidence and redirect payout to an arbitrary address.
- One claim per shipment: a `claimed` flag blocks resubmission.
- Contract-verified evidence: validators fetch evidence URLs themselves
  and visually inspect them, rather than trusting free text.
- Enforced liability/payout combinations: resolve_claim rejects any
  validator verdict that doesn't match a fixed allow-list, so e.g.
  "no_breach" can never be paired with a nonzero payout by mistake or
  manipulation.
"""

from genlayer import *
from dataclasses import dataclass
from datetime import datetime, timezone
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
    # pharmacy's side
    last_known_temp_c: str
    delay_narrative: str
    packaging_condition: str
    gps_deviation_notes: str
    evidence_url: str
    submitted_by: Address
    filed_at: u32  # unix seconds, deterministic transaction timestamp
    # carrier's side (defense, waiver, or deadline unlocks resolution)
    has_defense: bool
    defense_narrative: str
    defense_evidence_url: str
    # verdict
    resolved: bool
    liability: str
    payout_band: u32
    settled: bool


# How long the carrier has to defend or waive before resolve_claim may
# proceed without any response at all. Backed by GenVM's deterministic
# transaction timestamp (see module docstring), not external wall-clock
# time, so all validators agree on whether the window has elapsed.
#
# Set short here so the deadline path is actually observable in a normal
# testing session (submit a claim, wait ~2 minutes, resolve without any
# defense). Raise this substantially - e.g. 172800-259200 (2-3 days) -
# before a real deployment; a carrier needs realistic time to respond.
DEFENSE_WINDOW_SECONDS = 120  # 2 minutes - TESTING VALUE, raise for production

# Allowed (liability -> valid payout_band values) combinations. Enforced
# deterministically after validators reach consensus on a verdict.
ALLOWED_COMBINATIONS = {
    "no_breach": (0,),
    "force_majeure": (0,),
    "carrier": (25, 50, 75, 100),
    "distributor": (25, 50, 75, 100),
}


class ColdChainOracle(gl.Contract):
    shipments: TreeMap[str, Shipment]
    claims: TreeMap[str, Claim]
    claim_counter: u32
    # f"{shipment_id}:{funder_address_hex}" -> amount that funder contributed
    funder_contributions: TreeMap[str, bigint]

    def __init__(self):
        self.claim_counter = 0

    # ------------------------------------------------------------------
    # Shipment registration
    # ------------------------------------------------------------------
    @gl.public.write
    def register_shipment(
        self, shipment_id: str, carrier_address: str, pharmacy_address: str
    ) -> None:
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
    # Escrow funding - contributions tracked per funder for later refund
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

        contrib_key = f"{shipment_id}:{sender.as_hex}"
        current = self.funder_contributions.get(contrib_key, 0)
        self.funder_contributions[contrib_key] = current + amount

    @gl.public.view
    def get_escrow_balance(self, shipment_id: str) -> int:
        s = self.shipments.get(shipment_id)
        return s.escrow_balance if s is not None else 0

    # ------------------------------------------------------------------
    # Step 1 of the claim: pharmacy files (no verdict yet)
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
        shipment = self.shipments.get(shipment_id)
        assert shipment is not None, "shipment not registered"
        sender = gl.message.sender_address
        assert sender == shipment.pharmacy, "only the registered pharmacy may file a claim"
        assert not shipment.claimed, "a claim has already been filed for this shipment"

        claim_id = self.claim_counter
        self.claim_counter += 1
        now = u32(int(datetime.now(timezone.utc).timestamp()))

        self.claims[str(claim_id)] = Claim(
            shipment_id=shipment_id,
            last_known_temp_c=last_known_temp_c,
            delay_narrative=delay_narrative,
            packaging_condition=packaging_condition,
            gps_deviation_notes=gps_deviation_notes,
            evidence_url=evidence_url,
            submitted_by=sender,
            filed_at=now,
            has_defense=False,
            defense_narrative="",
            defense_evidence_url="",
            resolved=False,
            liability="",
            payout_band=0,
            settled=False,
        )

        self.shipments[shipment_id] = Shipment(
            distributor=shipment.distributor,
            carrier=shipment.carrier,
            pharmacy=shipment.pharmacy,
            escrow_balance=shipment.escrow_balance,
            claimed=True,
        )

        return claim_id

    def _require_carrier_and_open_claim(self, claim_id: int):
        key = str(claim_id)
        claim = self.claims.get(key)
        assert claim is not None, "claim does not exist"
        assert not claim.resolved, "claim already resolved"
        assert not claim.has_defense, "a defense/waiver has already been filed for this claim"

        shipment = self.shipments.get(claim.shipment_id)
        assert shipment is not None, "shipment not found"
        assert gl.message.sender_address == shipment.carrier, (
            "only the registered carrier may respond to this claim"
        )
        return key, claim

    # ------------------------------------------------------------------
    # Step 2a: carrier defends with their own evidence
    # ------------------------------------------------------------------
    @gl.public.write
    def submit_defense(
        self, claim_id: int, defense_narrative: str, defense_evidence_url: str
    ) -> None:
        key, claim = self._require_carrier_and_open_claim(claim_id)
        self.claims[key] = Claim(
            shipment_id=claim.shipment_id,
            last_known_temp_c=claim.last_known_temp_c,
            delay_narrative=claim.delay_narrative,
            packaging_condition=claim.packaging_condition,
            gps_deviation_notes=claim.gps_deviation_notes,
            evidence_url=claim.evidence_url,
            submitted_by=claim.submitted_by,
            filed_at=claim.filed_at,
            has_defense=True,
            defense_narrative=defense_narrative,
            defense_evidence_url=defense_evidence_url,
            resolved=claim.resolved,
            liability=claim.liability,
            payout_band=claim.payout_band,
            settled=claim.settled,
        )

    # ------------------------------------------------------------------
    # Step 2b: carrier explicitly waives their right to respond
    # ------------------------------------------------------------------
    @gl.public.write
    def waive_defense(self, claim_id: int) -> None:
        key, claim = self._require_carrier_and_open_claim(claim_id)
        self.claims[key] = Claim(
            shipment_id=claim.shipment_id,
            last_known_temp_c=claim.last_known_temp_c,
            delay_narrative=claim.delay_narrative,
            packaging_condition=claim.packaging_condition,
            gps_deviation_notes=claim.gps_deviation_notes,
            evidence_url=claim.evidence_url,
            submitted_by=claim.submitted_by,
            filed_at=claim.filed_at,
            has_defense=True,
            defense_narrative="(The carrier was given the opportunity to respond and explicitly waived their right to submit a defense.)",
            defense_evidence_url="",
            resolved=claim.resolved,
            liability=claim.liability,
            payout_band=claim.payout_band,
            settled=claim.settled,
        )

    # ------------------------------------------------------------------
    # Step 3: resolve - validators weigh both sides and their evidence
    # ------------------------------------------------------------------
    @gl.public.write
    def resolve_claim(self, claim_id: int) -> None:
        key = str(claim_id)
        claim = self.claims.get(key)
        assert claim is not None, "claim does not exist"
        assert not claim.resolved, "claim already resolved"

        now = int(datetime.now(timezone.utc).timestamp())
        deadline_passed = now >= int(claim.filed_at) + DEFENSE_WINDOW_SECONDS
        assert claim.has_defense or deadline_passed, (
            f"cannot resolve: carrier has not responded and the "
            f"{DEFENSE_WINDOW_SECONDS}s response window has not elapsed yet"
        )

        if claim.has_defense:
            carrier_section = f"CARRIER'S RESPONSE: {claim.defense_narrative}"
        else:
            carrier_section = (
                "CARRIER'S RESPONSE: The carrier did not respond at all "
                f"within the {DEFENSE_WINDOW_SECONDS}-second response window, "
                "and that window has now passed. Do not automatically assume "
                "fault because of this silence, but the pharmacy's evidence "
                "stands entirely unrebutted."
            )

        prompt = f"""
You are an impartial cold-chain logistics arbitrator for pharmaceutical
shipments distributed across Nigeria. This is a two-sided dispute - weigh
both the pharmacy's claim and the carrier's response (if any) fairly
before deciding liability.

SHIPMENT ID: {claim.shipment_id}

PHARMACY'S CLAIM:
LAST KNOWN TEMPERATURE READING: {claim.last_known_temp_c}
DELAY / TRANSIT NARRATIVE: {claim.delay_narrative}
PACKAGING CONDITION ON ARRIVAL (pharmacist's note): {claim.packaging_condition}
GPS / ROUTE DEVIATION NOTES: {claim.gps_deviation_notes}

{carrier_section}

You have been given photo/screenshot evidence for whichever side(s)
submitted an evidence_url. Weigh what you can actually observe in each
image against the corresponding written narrative - if an image
contradicts its narrative, factor that into your decision.

Consider common real-world causes in Nigerian logistics: fuel scarcity,
checkpoint or border delays, vehicle breakdown, route diversion through
high-heat conditions, poor insulated packaging, and genuinely unavoidable
circumstances (flooding, civil unrest, accidents).

Decide exactly:
1. liability: one of "carrier", "distributor", "force_majeure", "no_breach"
2. payout_band: one of 0, 25, 50, 75, 100 (percentage of escrowed value
   owed to the pharmacy). IMPORTANT: "no_breach" and "force_majeure" must
   use payout_band 0. "carrier" and "distributor" must use 25, 50, 75, or
   100 - never 0, since finding a party liable with a 0% payout is
   contradictory.

Respond using ONLY this JSON format, with no other words or characters:
{{"liability": "<carrier|distributor|force_majeure|no_breach>", "payout_band": <0|25|50|75|100>}}
"""

        pharmacy_evidence_url = claim.evidence_url
        carrier_evidence_url = claim.defense_evidence_url

        def nondet():
            images = []
            if pharmacy_evidence_url:
                images.append(gl.nondet.web.render(pharmacy_evidence_url, mode="screenshot"))
            if carrier_evidence_url:
                images.append(gl.nondet.web.render(carrier_evidence_url, mode="screenshot"))

            if images:
                res = gl.nondet.exec_prompt(prompt, images=images, response_format="json")
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

        liability = verdict["liability"]
        payout_band = verdict["payout_band"]
        allowed_bands = ALLOWED_COMBINATIONS.get(liability)
        assert allowed_bands is not None, "validators returned an unrecognized liability value"
        assert payout_band in allowed_bands, (
            f"validators returned an invalid combination: {liability} with payout_band {payout_band}"
        )

        self.claims[key] = Claim(
            shipment_id=claim.shipment_id,
            last_known_temp_c=claim.last_known_temp_c,
            delay_narrative=claim.delay_narrative,
            packaging_condition=claim.packaging_condition,
            gps_deviation_notes=claim.gps_deviation_notes,
            evidence_url=claim.evidence_url,
            submitted_by=claim.submitted_by,
            filed_at=claim.filed_at,
            has_defense=claim.has_defense,
            defense_narrative=claim.defense_narrative,
            defense_evidence_url=claim.defense_evidence_url,
            resolved=True,
            liability=liability,
            payout_band=payout_band,
            settled=False,
        )

    def _claim_to_dict(self, c: Claim) -> dict:
        return {
            "shipment_id": c.shipment_id,
            "delay_narrative": c.delay_narrative,
            "packaging_condition": c.packaging_condition,
            "evidence_url": c.evidence_url,
            "filed_at": c.filed_at,
            "defense_deadline": int(c.filed_at) + DEFENSE_WINDOW_SECONDS,
            "has_defense": c.has_defense,
            "defense_narrative": c.defense_narrative,
            "defense_evidence_url": c.defense_evidence_url,
            "resolved": c.resolved,
            "liability": c.liability,
            "payout_band": c.payout_band,
            "settled": c.settled,
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

    @gl.public.view
    def is_resolvable(self, claim_id: int) -> bool:
        """True once resolve_claim would succeed: either a defense/waiver
        has been filed, or the response deadline has passed."""
        c = self.claims.get(str(claim_id))
        if c is None or c.resolved:
            return False
        if c.has_defense:
            return True
        now = int(datetime.now(timezone.utc).timestamp())
        return now >= int(c.filed_at) + DEFENSE_WINDOW_SECONDS

    @gl.public.view
    def get_funder_contribution(self, shipment_id: str, funder_address: str) -> int:
        return self.funder_contributions.get(f"{shipment_id}:{funder_address}", 0)

    # ------------------------------------------------------------------
    # Step 4: full settlement - pays pharmacy's share AND refunds every
    # remaining unit of escrow back to whoever funded it. No verdict ever
    # leaves GEN stranded in the contract.
    # ------------------------------------------------------------------
    @gl.public.write
    def settle_claim(self, claim_id: int) -> None:
        key = str(claim_id)
        claim = self.claims.get(key)
        assert claim is not None, "claim does not exist"
        assert claim.resolved, "claim not yet resolved"
        assert not claim.settled, "claim already settled"

        shipment = self.shipments.get(claim.shipment_id)
        assert shipment is not None, "shipment not found"

        pool = shipment.escrow_balance
        payout = (pool * claim.payout_band) // 100
        remainder = pool - payout

        if payout > 0:
            gl.get_contract_at(shipment.pharmacy).emit_transfer(value=payout)

        if remainder > 0:
            distributor_key = f"{claim.shipment_id}:{shipment.distributor.as_hex}"
            carrier_key = f"{claim.shipment_id}:{shipment.carrier.as_hex}"
            distributor_contribution = self.funder_contributions.get(distributor_key, 0)
            carrier_contribution = self.funder_contributions.get(carrier_key, 0)
            total_contribution = distributor_contribution + carrier_contribution

            if total_contribution > 0:
                distributor_refund = (remainder * distributor_contribution) // total_contribution
                carrier_refund = remainder - distributor_refund  # remainder always fully allocated

                if distributor_refund > 0:
                    gl.get_contract_at(shipment.distributor).emit_transfer(value=distributor_refund)
                if carrier_refund > 0:
                    gl.get_contract_at(shipment.carrier).emit_transfer(value=carrier_refund)

        self.shipments[claim.shipment_id] = Shipment(
            distributor=shipment.distributor,
            carrier=shipment.carrier,
            pharmacy=shipment.pharmacy,
            escrow_balance=0,
            claimed=shipment.claimed,
        )

        self.claims[key] = Claim(
            shipment_id=claim.shipment_id,
            last_known_temp_c=claim.last_known_temp_c,
            delay_narrative=claim.delay_narrative,
            packaging_condition=claim.packaging_condition,
            gps_deviation_notes=claim.gps_deviation_notes,
            evidence_url=claim.evidence_url,
            submitted_by=claim.submitted_by,
            filed_at=claim.filed_at,
            has_defense=claim.has_defense,
            defense_narrative=claim.defense_narrative,
            defense_evidence_url=claim.defense_evidence_url,
            resolved=claim.resolved,
            liability=claim.liability,
            payout_band=claim.payout_band,
            settled=True,
        )

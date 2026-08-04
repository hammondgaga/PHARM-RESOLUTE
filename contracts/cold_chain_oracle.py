# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
PHARM RESOLUTE - Cold-Chain Integrity Oracle
----------------------------------------------
A GenLayer Intelligent Contract that resolves ambiguous cold-chain liability
disputes for temperature-sensitive pharmaceutical shipments (vaccines,
insulin, some antibiotics) moving through Nigeria's multi-hop distribution
networks (distributor -> carrier/dispatch -> pharmacy).

DISPUTE MODEL (two-sided, with a deadline)
-------------------------------------------
A claim is not a one-sided accusation. The flow is:

  1. register_shipment - distributor binds a carrier and pharmacy address
     to a shipment_id.
  2. fund_escrow - distributor or carrier locks GEN against the shipment.
  3. submit_claim - only the registered pharmacy may file a claim, with
     its evidence (narrative + an evidence_url pointing to a photo of
     packaging/ice packs). This does NOT immediately produce a verdict.
     The claim's timestamp is recorded (deterministic - see below).
  4. submit_defense - only the registered carrier may respond, once, with
     their own narrative and evidence_url (e.g. photos showing the
     shipment was properly packed, or an insulated-box certificate).
  5. resolve_claim - callable by anyone once EITHER:
       a) the carrier has filed a defense, OR
       b) DEFENSE_WINDOW_SECONDS has elapsed since the claim was filed
          and the carrier still has not responded.
     Validators independently review both sides' narratives (and both
     evidence URLs, when present) and reach consensus on liability and a
     payout band. If the carrier defaulted by silence, the arbitrator is
     told this explicitly, so it can weigh it as a factor rather than
     treat it as automatic full liability.
  6. release_payout - pays the resolved verdict's share of escrow to the
     shipment's registered pharmacy address. No caller-supplied recipient.

DEADLINE MECHANISM
-------------------
Earlier versions of this contract required a defense unconditionally,
which meant a carrier who never responded could lock a pharmacy's escrow
forever. This version closes that gap using GenLayer's Transaction
Context: `datetime.now(timezone.utc)` (and `time.time()`) inside a
contract method return the enclosing transaction's timestamp, which is
pinned and identical across all validators - it is deterministic, not a
non-deterministic web fetch. That makes it safe to use directly in
assertions without gl.eq_principle.

This means silence has a cost (the claim eventually resolves without the
carrier's side being heard) but not an unbounded one (the pharmacy is
never permanently blocked from a verdict).

SECURITY MODEL
--------------
- Role binding: only the registered pharmacy can file a claim or receive
  a payout; only the registered carrier can file a defense.
- One claim per shipment: a `claimed` flag blocks resubmission.
- Contract-verified evidence: validators fetch evidence URLs themselves
  and visually inspect them, rather than trusting free text.
- Deadline-gated resolution: resolution can never be blocked forever by
  carrier silence, but also never proceeds early - only once a defense
  exists or the response window has genuinely elapsed.
"""

from genlayer import *
from dataclasses import dataclass
from datetime import datetime, timezone
import json

# How long the carrier has to respond with a defense before a claim can
# be resolved without one. 172800 seconds = 48 hours.
DEFENSE_WINDOW_SECONDS: u32 = 172800


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
    claim_timestamp: u32
    # carrier's side (optional)
    has_defense: bool
    defense_narrative: str
    defense_evidence_url: str
    # verdict
    resolved: bool
    liability: str
    payout_band: u32
    paid_out: bool


class ColdChainOracle(gl.Contract):
    shipments: TreeMap[str, Shipment]
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
        """
        Files a cold-chain breach claim. Only callable by the shipment's
        registered pharmacy. Does not produce a verdict - the carrier
        gets DEFENSE_WINDOW_SECONDS to submit_defense before anyone can
        call resolve_claim without one.
        """
        shipment = self.shipments.get(shipment_id)
        assert shipment is not None, "shipment not registered"
        sender = gl.message.sender_address
        assert sender == shipment.pharmacy, "only the registered pharmacy may file a claim"
        assert not shipment.claimed, "a claim has already been filed for this shipment"

        claim_id = self.claim_counter
        self.claim_counter += 1

        now_ts = int(datetime.now(timezone.utc).timestamp())

        self.claims[str(claim_id)] = Claim(
            shipment_id=shipment_id,
            last_known_temp_c=last_known_temp_c,
            delay_narrative=delay_narrative,
            packaging_condition=packaging_condition,
            gps_deviation_notes=gps_deviation_notes,
            evidence_url=evidence_url,
            submitted_by=sender,
            claim_timestamp=now_ts,
            has_defense=False,
            defense_narrative="",
            defense_evidence_url="",
            resolved=False,
            liability="",
            payout_band=0,
            paid_out=False,
        )

        self.shipments[shipment_id] = Shipment(
            distributor=shipment.distributor,
            carrier=shipment.carrier,
            pharmacy=shipment.pharmacy,
            escrow_balance=shipment.escrow_balance,
            claimed=True,
        )

        return claim_id

    # ------------------------------------------------------------------
    # Step 2 of the claim: carrier may defend (optional, once, in window)
    # ------------------------------------------------------------------
    @gl.public.write
    def submit_defense(
        self, claim_id: int, defense_narrative: str, defense_evidence_url: str
    ) -> None:
        """
        Lets the shipment's registered carrier respond to a claim with
        their own narrative and evidence (e.g. a photo proving the
        package was properly insulated) before resolve_claim is called.
        Only callable once per claim, only before it is resolved, and
        only within the defense window - after that, resolve_claim may
        proceed without a defense and this method will reject late
        submissions to avoid a defense landing after (or racing) a
        resolution.
        """
        key = str(claim_id)
        claim = self.claims.get(key)
        assert claim is not None, "claim does not exist"
        assert not claim.resolved, "claim already resolved"
        assert not claim.has_defense, "a defense has already been filed for this claim"

        now_ts = int(datetime.now(timezone.utc).timestamp())
        assert (
            now_ts - claim.claim_timestamp < DEFENSE_WINDOW_SECONDS
        ), "the defense window for this claim has already elapsed"

        shipment = self.shipments.get(claim.shipment_id)
        assert shipment is not None, "shipment not found"
        assert gl.message.sender_address == shipment.carrier, (
            "only the registered carrier may file a defense"
        )

        self.claims[key] = Claim(
            shipment_id=claim.shipment_id,
            last_known_temp_c=claim.last_known_temp_c,
            delay_narrative=claim.delay_narrative,
            packaging_condition=claim.packaging_condition,
            gps_deviation_notes=claim.gps_deviation_notes,
            evidence_url=claim.evidence_url,
            submitted_by=claim.submitted_by,
            claim_timestamp=claim.claim_timestamp,
            has_defense=True,
            defense_narrative=defense_narrative,
            defense_evidence_url=defense_evidence_url,
            resolved=claim.resolved,
            liability=claim.liability,
            payout_band=claim.payout_band,
            paid_out=claim.paid_out,
        )

    # ------------------------------------------------------------------
    # Step 3: resolve - validators weigh both sides and their evidence
    # ------------------------------------------------------------------
    @gl.public.write
    def resolve_claim(self, claim_id: int) -> None:
        """
        Callable by anyone once EITHER a defense has been filed OR the
        defense window has elapsed. Validators independently fetch both
        parties' evidence URLs (if provided) as images and weigh them
        against both narratives, then reach strict consensus on
        liability and a payout band. If the carrier never filed a
        defense, the arbitrator is told explicitly whether that was
        because the window is still open (should not happen here, since
        this is asserted against) or because the window elapsed without
        a response.
        """
        key = str(claim_id)
        claim = self.claims.get(key)
        assert claim is not None, "claim does not exist"
        assert not claim.resolved, "claim already resolved"

        now_ts = int(datetime.now(timezone.utc).timestamp())
        window_elapsed = (now_ts - claim.claim_timestamp) >= DEFENSE_WINDOW_SECONDS

        assert claim.has_defense or window_elapsed, (
            "cannot resolve: no defense has been filed and the "
            f"{DEFENSE_WINDOW_SECONDS}s response window has not yet elapsed"
        )

        if claim.has_defense:
            defense_section = f"""
CARRIER'S DEFENSE: {claim.defense_narrative}
(The carrier has also submitted their own evidence photo/document, shown
to you separately from the pharmacy's evidence.)
"""
        else:
            defense_section = """
CARRIER'S DEFENSE: none. The carrier did not respond within the response
window. Silence alone is not proof of fault - weigh the pharmacy's
evidence on its own merits, but you may note the absence of a rebuttal
as a factor, not as automatic full liability.
"""

        prompt = f"""
You are an impartial cold-chain logistics arbitrator for pharmaceutical
shipments distributed across Nigeria. This is a two-sided dispute -
weigh both the pharmacy's claim and the carrier's defense (if any) fairly
before deciding liability.

SHIPMENT ID: {claim.shipment_id}

PHARMACY'S CLAIM:
LAST KNOWN TEMPERATURE READING: {claim.last_known_temp_c}
DELAY / TRANSIT NARRATIVE: {claim.delay_narrative}
PACKAGING CONDITION ON ARRIVAL (pharmacist's note): {claim.packaging_condition}
GPS / ROUTE DEVIATION NOTES: {claim.gps_deviation_notes}
{defense_section}

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
2. payout_band: one of 0, 25, 50, 75, 100
   (percentage of the escrowed shipment value owed to the pharmacy)

Respond using ONLY this JSON format, with no other words or characters:
{{"liability": "<carrier|distributor|force_majeure|no_breach>", "payout_band": <0|25|50|75|100>}}
"""

        pharmacy_evidence_url = claim.evidence_url
        carrier_evidence_url = claim.defense_evidence_url if claim.has_defense else ""

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

        self.claims[key] = Claim(
            shipment_id=claim.shipment_id,
            last_known_temp_c=claim.last_known_temp_c,
            delay_narrative=claim.delay_narrative,
            packaging_condition=claim.packaging_condition,
            gps_deviation_notes=claim.gps_deviation_notes,
            evidence_url=claim.evidence_url,
            submitted_by=claim.submitted_by,
            claim_timestamp=claim.claim_timestamp,
            has_defense=claim.has_defense,
            defense_narrative=claim.defense_narrative,
            defense_evidence_url=claim.defense_evidence_url,
            resolved=True,
            liability=verdict["liability"],
            payout_band=verdict["payout_band"],
            paid_out=False,
        )

    def _claim_to_dict(self, c: Claim) -> dict:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        deadline_ts = c.claim_timestamp + DEFENSE_WINDOW_SECONDS
        return {
            "shipment_id": c.shipment_id,
            "delay_narrative": c.delay_narrative,
            "packaging_condition": c.packaging_condition,
            "evidence_url": c.evidence_url,
            "claim_timestamp": c.claim_timestamp,
            "defense_deadline": deadline_ts,
            "defense_window_expired": now_ts >= deadline_ts,
            "has_defense": c.has_defense,
            "defense_narrative": c.defense_narrative,
            "defense_evidence_url": c.defense_evidence_url,
            "resolved": c.resolved,
            "liability": c.liability,
            "payout_band": c.payout_band,
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
            last_known_temp_c=claim.last_known_temp_c,
            delay_narrative=claim.delay_narrative,
            packaging_condition=claim.packaging_condition,
            gps_deviation_notes=claim.gps_deviation_notes,
            evidence_url=claim.evidence_url,
            submitted_by=claim.submitted_by,
            claim_timestamp=claim.claim_timestamp,
            has_defense=claim.has_defense,
            defense_narrative=claim.defense_narrative,
            defense_evidence_url=claim.defense_evidence_url,
            resolved=claim.resolved,
            liability=claim.liability,
            payout_band=claim.payout_band,
            paid_out=True,
        )
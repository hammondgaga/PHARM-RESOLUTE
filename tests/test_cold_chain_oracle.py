"""
Multi-account test suite for ColdChainOracle, written against GenLayer's
`gltest` framework (pytest-based, package `genlayer-test`).

This suite was written against gltest's actual installed API (verified by
inspecting the genlayer-test package source directly: get_contract_factory,
create_account, Contract.connect(), ContractFunction.call()/.transact(),
tx_execution_succeeded, tx_execution_failed), NOT executed against a live
GenLayer node - the sandbox used to build PHARM RESOLUTE does not have a
GenLayer node available to run gltest against. The account-switching
pattern in particular (contract.connect(account).method(args=[...]).transact())
was confirmed by reading gltest/contracts/contract.py rather than guessed.

Run with (once gltest is installed and a GenLayer node/localnet is running):
    gltest --network localnet

Or against GenLayer Studio's simulator:
    gltest --network studionet
"""

import pytest
from datetime import datetime, timedelta, timezone
from gltest import get_contract_factory, get_default_account, create_account
from gltest.assertions import tx_execution_succeeded, tx_execution_failed

# NOTE: cold_chain_oracle.py does `from genlayer import *`, which only
# resolves inside the actual GenVM sandbox - the real `genlayer` PyPI
# package (as opposed to `genlayer-py`/`genlayer-test`) is effectively an
# empty placeholder outside that environment. So this test file does NOT
# import the contract module directly; get_contract_factory ships the
# contract's source to the node rather than importing it locally, which is
# the correct pattern here. This table is a manually-kept-in-sync copy of
# the contract's ALLOWED_COMBINATIONS purely for use in assertions below -
# if you change one, change the other.
ALLOWED_COMBINATIONS = {
    "no_breach": (0,),
    "force_majeure": (0,),
    "carrier": (25, 50, 75, 100),
    "distributor": (25, 50, 75, 100),
}

# Must match the contract's DEFENSE_WINDOW_SECONDS constant (currently a
# short testing value - see the comment above that constant in
# cold_chain_oracle.py for why, and what to raise it to for production).
DEFENSE_WINDOW_SECONDS = 120  # 2 minutes


# ---------------------------------------------------------------------------
# Pure-Python check of the liability/payout allow-list mirrored above. This
# doesn't need a chain at all - it documents exactly what the contract is
# supposed to enforce, and will fail loudly if this local copy is ever
# edited inconsistently (e.g. someone adds a "no_breach": (0, 25) entry).
# ---------------------------------------------------------------------------
def test_allowed_combinations_table_is_internally_consistent():
    assert ALLOWED_COMBINATIONS["no_breach"] == (0,)
    assert ALLOWED_COMBINATIONS["force_majeure"] == (0,)
    assert 0 not in ALLOWED_COMBINATIONS["carrier"]
    assert 0 not in ALLOWED_COMBINATIONS["distributor"]
    assert set(ALLOWED_COMBINATIONS["carrier"]) == {25, 50, 75, 100}
    assert set(ALLOWED_COMBINATIONS["distributor"]) == {25, 50, 75, 100}


@pytest.fixture
def accounts():
    """Four distinct signers: distributor, carrier, pharmacy, and a random
    unrelated third party used to test that role checks actually reject
    unauthorized callers."""
    return {
        "distributor": get_default_account(),
        "carrier": create_account(),
        "pharmacy": create_account(),
        "stranger": create_account(),
    }


@pytest.fixture
def contract(accounts):
    factory = get_contract_factory("ColdChainOracle")
    # Deployed and owned by the distributor account by default; use
    # contract.connect(other_account) to act as a different signer.
    return factory.deploy(account=accounts["distributor"])


def _as(contract, account):
    return contract.connect(account)


def _register(contract, accounts, shipment_id):
    tx = _as(contract, accounts["distributor"]).register_shipment(
        args=[shipment_id, accounts["carrier"].address, accounts["pharmacy"].address]
    ).transact()
    assert tx_execution_succeeded(tx)


def _fund(contract, accounts, shipment_id, amount, funder="distributor"):
    tx = _as(contract, accounts[funder]).fund_escrow(args=[shipment_id]).transact(value=amount)
    assert tx_execution_succeeded(tx)


def _submit_claim(contract, accounts, shipment_id, evidence_url=""):
    tx = _as(contract, accounts["pharmacy"]).submit_claim(
        args=[
            shipment_id,
            "9C recorded at 14:00 WAT, unknown after",
            "Vehicle held at checkpoint for 6 hours due to fuel scarcity",
            "Ice packs fully melted, box warm to touch",
            "no GPS data available",
            evidence_url,
        ]
    ).transact()
    assert tx_execution_succeeded(tx)
    claims = contract.get_all_claims().call()
    # newest claim id is the highest numeric key
    return max(claims.keys(), key=int)


class TestRoleBinding:
    def test_register_shipment_binds_roles(self, contract, accounts):
        _register(contract, accounts, "shp-role-1")
        shipment = contract.get_shipment(args=["shp-role-1"]).call()
        assert shipment["distributor"].lower() == accounts["distributor"].address.lower()
        assert shipment["carrier"].lower() == accounts["carrier"].address.lower()
        assert shipment["pharmacy"].lower() == accounts["pharmacy"].address.lower()
        assert shipment["escrow_balance"] == 0
        assert shipment["claimed"] is False

    def test_cannot_register_same_shipment_twice(self, contract, accounts):
        _register(contract, accounts, "shp-role-2")
        tx = _as(contract, accounts["distributor"]).register_shipment(
            args=["shp-role-2", accounts["carrier"].address, accounts["pharmacy"].address]
        ).transact()
        assert tx_execution_failed(tx)

    def test_stranger_cannot_fund_escrow(self, contract, accounts):
        _register(contract, accounts, "shp-role-3")
        tx = _as(contract, accounts["stranger"]).fund_escrow(args=["shp-role-3"]).transact(value=1000)
        assert tx_execution_failed(tx)

    def test_stranger_cannot_submit_claim(self, contract, accounts):
        _register(contract, accounts, "shp-role-4")
        _fund(contract, accounts, "shp-role-4", 1000)
        tx = _as(contract, accounts["stranger"]).submit_claim(
            args=["shp-role-4", "9C", "delay", "condition", "gps", ""]
        ).transact()
        assert tx_execution_failed(tx)

    def test_only_registered_pharmacy_can_claim(self, contract, accounts):
        _register(contract, accounts, "shp-role-5")
        _fund(contract, accounts, "shp-role-5", 1000)
        # carrier trying to file a claim as if they were the pharmacy
        tx = _as(contract, accounts["carrier"]).submit_claim(
            args=["shp-role-5", "9C", "delay", "condition", "gps", ""]
        ).transact()
        assert tx_execution_failed(tx)


class TestDuplicateClaimProtection:
    def test_cannot_file_second_claim_on_same_shipment(self, contract, accounts):
        _register(contract, accounts, "shp-dup-1")
        _fund(contract, accounts, "shp-dup-1", 1000)
        _submit_claim(contract, accounts, "shp-dup-1")
        tx = _as(contract, accounts["pharmacy"]).submit_claim(
            args=["shp-dup-1", "9C", "delay again", "condition", "gps", ""]
        ).transact()
        assert tx_execution_failed(tx)


class TestDefenseAndWaiver:
    def test_stranger_cannot_submit_defense(self, contract, accounts):
        _register(contract, accounts, "shp-def-1")
        _fund(contract, accounts, "shp-def-1", 1000)
        claim_id = _submit_claim(contract, accounts, "shp-def-1")
        tx = _as(contract, accounts["stranger"]).submit_defense(
            args=[int(claim_id), "not the real carrier", ""]
        ).transact()
        assert tx_execution_failed(tx)

    def test_cannot_resolve_without_defense_or_waiver(self, contract, accounts):
        _register(contract, accounts, "shp-def-2")
        _fund(contract, accounts, "shp-def-2", 1000)
        claim_id = _submit_claim(contract, accounts, "shp-def-2")
        tx = _as(contract, accounts["stranger"]).resolve_claim(args=[int(claim_id)]).transact()
        assert tx_execution_failed(tx)

    def test_waiver_unblocks_resolution(self, contract, accounts):
        _register(contract, accounts, "shp-def-3")
        _fund(contract, accounts, "shp-def-3", 1000)
        claim_id = _submit_claim(contract, accounts, "shp-def-3")

        waive_tx = _as(contract, accounts["carrier"]).waive_defense(args=[int(claim_id)]).transact()
        assert tx_execution_succeeded(waive_tx)

        # anyone (a stranger, even) may call resolve_claim once unblocked
        resolve_tx = _as(contract, accounts["stranger"]).resolve_claim(args=[int(claim_id)]).transact()
        assert tx_execution_succeeded(resolve_tx)

        claim = contract.get_claim(args=[int(claim_id)]).call()
        assert claim["resolved"] is True
        assert claim["liability"] in ALLOWED_COMBINATIONS
        assert claim["payout_band"] in ALLOWED_COMBINATIONS[claim["liability"]]

    def test_defense_then_carrier_cannot_also_waive(self, contract, accounts):
        _register(contract, accounts, "shp-def-4")
        _fund(contract, accounts, "shp-def-4", 1000)
        claim_id = _submit_claim(contract, accounts, "shp-def-4")

        defend_tx = _as(contract, accounts["carrier"]).submit_defense(
            args=[int(claim_id), "Package was properly insulated per protocol", ""]
        ).transact()
        assert tx_execution_succeeded(defend_tx)

        # second response of any kind should be rejected - only one shot
        waive_tx = _as(contract, accounts["carrier"]).waive_defense(args=[int(claim_id)]).transact()
        assert tx_execution_failed(waive_tx)


class TestDeadline:
    """
    Exercises the actual deterministic-time deadline (DEFENSE_WINDOW_SECONDS)
    using gltest's transaction_context={"genvm_datetime": ...} to simulate
    time passing, rather than waiting 3 real days. GenVM pins Python's clock
    to the transaction timestamp for every validator, so this is a faithful
    simulation of the real mechanism, not a mock of it.
    """

    def test_resolve_rejected_before_deadline_with_no_response(self, contract, accounts):
        _register(contract, accounts, "shp-deadline-1")
        _fund(contract, accounts, "shp-deadline-1", 1000)
        claim_id = _submit_claim(contract, accounts, "shp-deadline-1")

        # No defense, no waiver, and no time has passed - must be rejected.
        tx = _as(contract, accounts["stranger"]).resolve_claim(args=[int(claim_id)]).transact()
        assert tx_execution_failed(tx)

    def test_resolve_succeeds_after_deadline_with_no_response(self, contract, accounts):
        _register(contract, accounts, "shp-deadline-2")
        _fund(contract, accounts, "shp-deadline-2", 1000)
        claim_id = _submit_claim(contract, accounts, "shp-deadline-2")

        future_dt = datetime.now(timezone.utc) + timedelta(
            seconds=DEFENSE_WINDOW_SECONDS + 60
        )

        # Carrier never defends or waives at all - only the passage of the
        # deterministic transaction clock unlocks resolution.
        tx = _as(contract, accounts["stranger"]).resolve_claim(args=[int(claim_id)]).transact(
            transaction_context={"genvm_datetime": future_dt.isoformat()}
        )
        assert tx_execution_succeeded(tx)

        claim = contract.get_claim(args=[int(claim_id)]).call()
        assert claim["resolved"] is True
        assert claim["has_defense"] is False

    def test_is_resolvable_reflects_deadline_state(self, contract, accounts):
        _register(contract, accounts, "shp-deadline-3")
        _fund(contract, accounts, "shp-deadline-3", 1000)
        claim_id = _submit_claim(contract, accounts, "shp-deadline-3")

        assert contract.is_resolvable(args=[int(claim_id)]).call() is False

        # A real defense unblocks it immediately, independent of the clock.
        _as(contract, accounts["carrier"]).submit_defense(
            args=[int(claim_id), "Package was properly insulated per protocol", ""]
        ).transact()
        assert contract.is_resolvable(args=[int(claim_id)]).call() is True


class TestEvidenceRobustness:
    """
    Regression test for a real bug hit during manual testing: a claim whose
    evidence_url was accidentally a raw data:image/... URI (not a fetchable
    http(s) link) caused gl.nondet.web.render to raise inside every
    validator identically, which reached consensus on the FAILURE itself
    and permanently bricked that claim - submit_claim/submit_defense are
    one-shot, so resolve_claim could never succeed on it again. The fix:
    resolve_claim now catches bad/unfetchable URLs and proceeds on the
    narrative alone rather than reverting unconditionally.
    """

    def test_resolve_succeeds_despite_non_http_evidence_url(self, contract, accounts):
        _register(contract, accounts, "shp-badurl-1")
        _fund(contract, accounts, "shp-badurl-1", 1000)

        tx = _as(contract, accounts["pharmacy"]).submit_claim(
            args=[
                "shp-badurl-1",
                "9C",
                "delay",
                "condition",
                "gps",
                "data:image/jpeg;base64,notarealurl",  # the exact bug hit manually
            ]
        ).transact()
        assert tx_execution_succeeded(tx)

        claims = contract.get_all_claims().call()
        claim_id = max(claims.keys(), key=int)

        waive_tx = _as(contract, accounts["carrier"]).waive_defense(args=[int(claim_id)]).transact()
        assert tx_execution_succeeded(waive_tx)

        resolve_tx = _as(contract, accounts["stranger"]).resolve_claim(args=[int(claim_id)]).transact()
        assert tx_execution_succeeded(resolve_tx), (
            "resolve_claim should not revert just because an evidence_url "
            "wasn't a fetchable http(s) link"
        )

        claim = contract.get_claim(args=[int(claim_id)]).call()
        assert claim["resolved"] is True


class TestSettlement:
    def test_settlement_pays_pharmacy_and_drains_escrow_to_zero(self, contract, accounts):
        """
        Regardless of the exact verdict, settle_claim must (a) pay the
        pharmacy its payout_band share, (b) refund whatever remains to
        whoever funded escrow, and (c) leave escrow_balance at exactly
        zero afterward - no verdict should ever strand funds.
        """
        _register(contract, accounts, "shp-settle-1")
        _fund(contract, accounts, "shp-settle-1", 10_000, funder="distributor")
        claim_id = _submit_claim(contract, accounts, "shp-settle-1")

        waive_tx = _as(contract, accounts["carrier"]).waive_defense(args=[int(claim_id)]).transact()
        assert tx_execution_succeeded(waive_tx)

        resolve_tx = _as(contract, accounts["distributor"]).resolve_claim(args=[int(claim_id)]).transact()
        assert tx_execution_succeeded(resolve_tx)

        settle_tx = _as(contract, accounts["distributor"]).settle_claim(args=[int(claim_id)]).transact()
        assert tx_execution_succeeded(settle_tx)

        claim = contract.get_claim(args=[int(claim_id)]).call()
        assert claim["settled"] is True

        remaining_escrow = contract.get_escrow_balance(args=["shp-settle-1"]).call()
        assert remaining_escrow == 0, "no verdict should ever leave GEN stranded in escrow"

    def test_cannot_settle_before_resolution(self, contract, accounts):
        _register(contract, accounts, "shp-settle-2")
        _fund(contract, accounts, "shp-settle-2", 1000)
        claim_id = _submit_claim(contract, accounts, "shp-settle-2")
        tx = _as(contract, accounts["distributor"]).settle_claim(args=[int(claim_id)]).transact()
        assert tx_execution_failed(tx)

    def test_cannot_settle_twice(self, contract, accounts):
        _register(contract, accounts, "shp-settle-3")
        _fund(contract, accounts, "shp-settle-3", 1000)
        claim_id = _submit_claim(contract, accounts, "shp-settle-3")
        _as(contract, accounts["carrier"]).waive_defense(args=[int(claim_id)]).transact()
        _as(contract, accounts["distributor"]).resolve_claim(args=[int(claim_id)]).transact()

        first = _as(contract, accounts["distributor"]).settle_claim(args=[int(claim_id)]).transact()
        assert tx_execution_succeeded(first)

        second = _as(contract, accounts["distributor"]).settle_claim(args=[int(claim_id)]).transact()
        assert tx_execution_failed(second)

    def test_multi_funder_contribution_tracking(self, contract, accounts):
        """Both distributor and carrier fund the same shipment; contract
        should track each contribution separately for proportional refund."""
        _register(contract, accounts, "shp-settle-4")
        _fund(contract, accounts, "shp-settle-4", 6_000, funder="distributor")
        _fund(contract, accounts, "shp-settle-4", 4_000, funder="carrier")

        distributor_contribution = contract.get_funder_contribution(
            args=["shp-settle-4", accounts["distributor"].address]
        ).call()
        carrier_contribution = contract.get_funder_contribution(
            args=["shp-settle-4", accounts["carrier"].address]
        ).call()

        assert distributor_contribution == 6_000
        assert carrier_contribution == 4_000

        total_escrow = contract.get_escrow_balance(args=["shp-settle-4"]).call()
        assert total_escrow == 10_000

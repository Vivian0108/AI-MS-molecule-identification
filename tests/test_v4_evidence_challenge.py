"""v4 counterfactual science checks on curated development cases."""
import hashlib
import json

from spectrapilot.demo import DemoService


def test_counterfactual_is_side_effect_free_and_acquired_only():
    pilot = DemoService()
    try:
        cid = pilot.manifest["cases"][0]["case_id"]
        pilot.start_case(cid)
        initial = pilot.get_evidence(cid)
        audit = pilot.session(cid).counterfactual_audit("CID20")
        assert audit["method"] == "single_peak_leave_one_out"
        assert pilot.get_evidence(cid) == initial
        assert audit["peaks_tested"] <= 12
        try:
            pilot.session(cid).counterfactual_audit("EAD16")
        except ValueError:
            pass
        else:
            raise AssertionError("Unacquired EAD spectrum must never be probed")
    finally:
        pilot.close()


def test_precommit_binds_prediction_before_oracle_and_verifies_after():
    pilot = DemoService()
    try:
        cid = pilot.manifest["cases"][0]["case_id"]
        pilot.start_case(cid)
        session = pilot.session(cid)
        before = pilot.get_evidence(cid)
        suggested = before["plan"]["recommended"]["key"]
        assert suggested in {"CID40", "EAD16"}
        prediction = session.premeasurement_challenge(suggested)
        digest = prediction["sha256"]
        unsigned = dict(prediction)
        del unsigned["sha256"]
        assert hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == digest
        assert pilot.get_evidence(cid) == before
        pilot.measure(cid, suggested)
        after = pilot.get_evidence(cid)
        assert after["premeasurement_commit"]["sha256"] == digest
        assert after["experimental_challenge_result"]["precommit_sha256"] == digest
        assert after["experimental_challenge_result"]["evaluated"] is True
        pilot.stop(cid)
        report = pilot.report(cid)["investigation"]
        assert report["premeasurement_commit"]["sha256"] == digest
        assert report["experimental_challenge_result"]["action"] == suggested
    finally:
        pilot.close()


def test_peak_edit_preserves_unedited_verdict_and_raw_observations():
    pilot = DemoService()
    try:
        cid = pilot.manifest["cases"][0]["case_id"]
        pilot.start_case(cid)
        before = pilot.get_evidence(cid)
        raw = pilot.session(cid).observation("CID20")
        event = pilot.exclude_observed_peak(cid, "CID20", 0, "test sensitivity")
        edited = event["evidence"]
        assert edited["user_modified_evidence"]
        assert edited["original_decision_if_stopped"] == before["decision_if_stopped"]
        assert (pilot.session(cid).observation("CID20").mz == raw.mz).all()
        pilot.undo_intervention(cid, event["intervention"]["intervention_id"], "restore")
        assert pilot.get_evidence(cid)["decision_if_stopped"] == before["decision_if_stopped"]
    finally:
        pilot.close()

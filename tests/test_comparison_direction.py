import pytest

from unknownid.eval.evaluate import pairwise_comparisons


@pytest.mark.parametrize(
    "a,b,sign,wins,losses", [(1, 0, 1, 3, 0), (0, 1, -1, 0, 3), (1, 1, 0, 0, 0)]
)
def test_unknownid_benefit_direction(a, b, sign, wins, losses):
    results = {
        name: {str(i): {"top1_1": value} for i in range(3)}
        for name, value in [("unknownid", a), ("fixed", b)]
    }
    diff = pairwise_comparisons(results, list(results["unknownid"]), metrics=["top1_1"])["fixed"][
        "top1_1"
    ]
    assert diff["mean_difference"] == sign
    assert diff["ci_low"] == diff["ci_high"] == sign
    assert (diff["wins"], diff["losses"]) == (wins, losses)
    assert diff["ties"] == 3 - wins - losses


def test_scan_savings_direction():
    results = {"unknownid": {"a": {"scans_1": 0}}, "fixed": {"a": {"scans_1": 1}}}
    diff = pairwise_comparisons(results, ["a"], metrics=["scans_1"])["fixed"]["scans_1"]
    assert diff["mean_difference"] == diff["ci_low"] == diff["ci_high"] == 1
    assert (diff["wins"], diff["losses"]) == (1, 0)

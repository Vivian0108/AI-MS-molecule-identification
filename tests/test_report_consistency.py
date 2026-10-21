import json
from pathlib import Path
from unknownid.eval.artifacts import render_report

ROOT = Path(__file__).resolve().parents[1]


def test_generated_markdown_exactly_matches_json():
    payload = json.loads((ROOT/'reports/evaluation.json').read_text())
    assert (ROOT/'reports/evaluation.md').read_text() == render_report(payload)
    row = payload['summaries']['ambiguous']['unknownid']
    per_case = payload['per_case']['unknownid']
    ambiguous = [m for m in per_case.values() if m['n_candidates']>=2]
    assert row['n'] == len(ambiguous)
    assert abs(row['coverage_1']-sum(m['coverage_1'] for m in ambiguous)/len(ambiguous)) < .0001
    assert row['accepted_correct_count_1'] == sum(m['accepted_correct_1'] for m in ambiguous)

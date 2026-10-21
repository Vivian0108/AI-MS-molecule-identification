# Historical baseline

Baseline commit: e5b6ad80aeb904c8bd6faed03002a8e94f1dac72 (main).
The fresh clone was clean; hackathon-ready was created from main (no remote branch existed).
Read README, implementation specification, evaluation, data audit and calibration before edits.
Initial system-Python attempt failed collection (Python 3.9, missing pandas).
Python 3.12.12: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`: **44 passed in 1.58s**.
Configuration/calibration/error-model hashes and all 100 frozen test identities are in baseline.json.
Historical headline: 11 ambiguous test molecules, top-1@1 9/11 for adaptive/fixed/random/single scan;
0.6364 optional scans for adaptive versus 1 for fixed, but coverage was incorrectly mixed with stage two.
Historical reports remain available at the baseline commit. No thresholds, seeds, split or filters will change.

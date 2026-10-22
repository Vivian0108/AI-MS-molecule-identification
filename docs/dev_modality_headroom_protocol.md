# Development-only modality headroom check

Exploratory diagnostic, not an independent test or an accuracy claim. This
protocol is recorded before running policy outcomes. No MCP or canvas work.

## Cohort and controls

- All complete, precursor-ambiguous development cases in the committed MultiMS2
  cases table (72 cases, selected using metadata alone). Do not select on hidden
  CID40/EAD16 outcomes or load frozen test query records.
- Use the existing candidate universe, reference templates, scorer, planner,
  acceptance thresholds, one-optional-scan budget, and configured seeds unchanged.
- Reconstruct only these development archived measurements and evaluator truth
  from committed dev records/compound metadata. Truth remains evaluator-side;
  do not supply it to sessions or the planner.
- For every case start fresh independent sessions for CID20-only, CID20+CID40,
  CID20+EAD16, and the existing separation planner. Verify identical initial
  evidence. No peak exclusions or other interventions.
- The random comparator is the exact 50:50 expectation over the two independent
  measurement branches; no new Monte Carlo seed or fitted policy.

## Outputs

- For each policy: top-1, accepted-correct, accepted coverage, error count,
  selective risk (accepted errors / accepted cases; null if none), optional
  scans and total acquisitions (initial CID20 plus optional scans).
- CID40-only and EAD16-only successes, both successes and neither successes,
  separately for top-1 correctness and accepted-correct identification.
- Metric-specific hindsight ceilings over the two measurements, and over
  stop/CID40/EAD16. These use truth and are diagnostic, not deployable policies.
- Existing planner action counts, selection accuracy on cases where measurement
  branches differ (ties excluded and STOP counted as a missed measurement choice),
  and outcome regret relative to stop/CID40/EAD16. This subset is diagnostic only.
- Paired planner-minus-fixed differences in top-1, accepted-correct and optional
  scans with molecule bootstrap 95% intervals (2,000 resamples, configured seed
  20261021). Exact two-sided McNemar tests for binary correctness metrics.
- Full discordant case lists; any illustrative outcome-selected development
  examples are labelled as illustrations, not independent validation evidence.
- True-candidate reference cosine and reference-source summaries to help identify
  template-quality limitations, without changing references or fitting anything.

## Interpretation

Complementarity means each modality succeeds on at least some cases where the
other fails. A useful planner advantage requires an actual paired improvement
over fixed policies; do not infer it from the existence of a hindsight ceiling.
Do not declare statistical equivalence from an interval that includes zero.
No tuned follow-up is included in this check.

The CID40 branch may use measured CID60 library references while EAD16 uses
train-only kNN templates. Comparisons therefore evaluate the current end-to-end
pipeline, not an intrinsic physical superiority of CID or EAD. The benchmark is
closed-world, not a new open-world identification experiment.

Generate new `reports/spectrapilot/dev_modality_headroom.json` and `.md` from code;
preserve all existing reports and frozen inputs. Record source/input hashes and
execution metadata. Stop after reporting findings.

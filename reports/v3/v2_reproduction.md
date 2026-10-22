# v2 reproduction and coverage regressions

Generated `2026-10-22T18:40:44+00:00` on the frozen **test** cohort (**n = 157**).

The v2 decision path is retained in the v3 tree behind `decision_version="v2_legacy"`; the numbers below are regenerated from the current working tree, not copied from an earlier report.

## Artifact hashes

| artifact | sha256 |
|---|---|
| `cases` | `ca5eb993948b2048…` |
| `records` | `b331116edc591e09…` |
| `templates` | `8620a57f7a1bce7a…` |
| `truth` | `c7c6ca87b703503d…` |
| `oracle` | `e9a80d8b5803d58c…` |
| `mgf` | `4ef86f75a12ad2fd…` |

## Frozen v2 policies

| policy | n | top-1 | 95% CI | scans | MS/MS cov. | any cov. | false-ID |
|---|---:|---:|---|---:|---:|---:|---:|
| cid20_only | 157 | 0.834 | [0.771, 0.892] | 0.00 | 0.032 | 0.032 | 0.200 |
| always_cid40 | 157 | 0.936 | [0.892, 0.968] | 1.00 | 0.701 | 0.701 | 0.018 |
| always_ead16 | 157 | 0.834 | [0.771, 0.892] | 1.00 | 0.032 | 0.032 | 0.200 |
| random | 157 | 0.889 | [0.845, 0.927] | 1.00 | 0.368 | 0.368 | 0.025 |
| separation | 157 | 0.936 | [0.898, 0.968] | 0.37 | 0.268 | 0.268 | 0.048 |
| hindsight_best | 157 | 0.955 | [0.924, 0.981] | 1.00 | 0.688 | 0.688 | 0.019 |

`any cov.` includes `MASS_ONLY_MATCH`; `MS/MS cov.` does not. The v2 engine emitted `IDENTIFIED`, which is normalised to `MSMS_SUPPORTED` for reporting.

## Coverage regressions (v2 abstained, always-CID40 identified)

**68 cases.** Mechanism counts: `{'precursor_unique_candidate_abstained': 67, 'no_independent_support_and_no_mass_only_rule': 1}`.

| case | candidates | initial peaks | v2 separation | always-CID40 | root cause | v3 status | v3 accepted |
|---|---:|---:|---|---|---|---|---:|
| `case-011a9c569858` | 1 | 8 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-0137f644f393` | 1 | 15 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-124315db17c2` | 1 | 7 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-170f6ae67f04` | 1 | 9 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-1710e6a9cb50` | 1 | 7 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-1a1c8f766567` | 1 | 9 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-1e748a2e967d` | 1 | 8 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-2776c0c11200` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-29a2ae16680d` | 1 | 9 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-2a00ca3311c6` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-2cb79a2ff091` | 1 | 9 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-2e6a76fdce96` | 1 | 5 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-37bc286ae00e` | 1 | 11 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-3838e66f5874` | 1 | 13 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-3b709ed8d100` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-3e1b0cb08832` | 1 | 3 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-42d75810380b` | 1 | 3 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-43e3f9458f00` | 1 | 7 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-4647f5235f90` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-47b5c3e687f5` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-4d01937ffd49` | 1 | 7 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-562bf2f91c14` | 1 | 11 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-5d63915adb3e` | 1 | 8 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-63f83148e59b` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-66a875c774bd` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-727b52a4ea79` | 1 | 12 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-729c7faab096` | 1 | 8 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MASS_ONLY_MATCH | 1 |
| `case-741c1fec2840` | 1 | 10 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-76688d89ac7c` | 1 | 10 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-794ea96b6db7` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-79a52959e651` | 1 | 13 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-7af145d93b62` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-7b0cae1d973c` | 1 | 5 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-7f862d49d6e4` | 1 | 9 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-7f863fbda159` | 2 | 8 | OUT_OF_LIBRARY | MSMS_SUPPORTED | no_independent_support_and_no_mass_only_rule | MSMS_SUPPORTED | 1 |
| `case-858677e74265` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-8b0c72204a13` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-8c6e64246b14` | 1 | 6 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-8e70f4414120` | 1 | 12 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-91b4be7013b9` | 1 | 3 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-9240367fb5cf` | 1 | 8 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-9576c9a3715f` | 1 | 7 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-99c3ee832c43` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-99ca6ac12c4b` | 1 | 9 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-9dd4bd230ce6` | 1 | 5 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-9eb51398aadf` | 1 | 5 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-a193e0214627` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-a26ead2275a7` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-ab750677c4b0` | 1 | 9 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-b651445954c6` | 1 | 13 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-c1a209180e7f` | 1 | 3 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-c994c80dcdc3` | 1 | 3 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-ca3cb937c8b5` | 1 | 5 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-cdc91e66cd60` | 1 | 7 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-d05867c0309d` | 1 | 12 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-d69b37d377b5` | 1 | 3 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-d6c47110e98c` | 1 | 9 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-dabd693b7734` | 1 | 12 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-e825c7c68286` | 1 | 6 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-edbd0e3e4a24` | 1 | 13 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-f27d8decc72a` | 1 | 5 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-f59dc23c3fa6` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-f6ee135cc009` | 1 | 5 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-f99d3faa69ea` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-fb7c7cb5e977` | 1 | 5 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-fc5727e31169` | 1 | 4 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-fd885a5631ae` | 1 | 9 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |
| `case-fe2206d38370` | 1 | 3 | OUT_OF_LIBRARY | MSMS_SUPPORTED | precursor_unique_candidate_abstained | MSMS_SUPPORTED | 1 |

### Diagnosis

The regressions were **classification errors, not retrieval errors**: the v2 contract had no `MASS_ONLY_MATCH` status, so a unique precursor-consistent candidate whose kNN template fit fell below the 0.30 floor was reported as `OUT_OF_LIBRARY`. The v3 contract separates a unique mass match from an MS/MS confirmation and states the proof tier explicitly.

**68 of 68** regression cases are accepted under the v3 contract, at unchanged retrieval accuracy. The one remaining mechanism is a multi-candidate case where the v2 separation policy stopped measuring and then reported `OUT_OF_LIBRARY`; the v3 planner measures and reaches `MSMS_SUPPORTED`.

The QC sparsity change (first-scan peaks → best-observation peaks) is not responsible for any of these 68 cases, but it is retained and tested because a sparse CID20 followed by an informative CID40 was previously misclassified as insufficient data.

Runtime: 31.9 s.

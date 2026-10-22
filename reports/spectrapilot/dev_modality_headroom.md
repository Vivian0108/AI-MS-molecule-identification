# CID40 versus EAD16: development-only headroom check

**Exploratory development diagnostic, n = 72. Not a held-out test.** Frozen test queries were not loaded. No fitting or tuning.

All policies start from identical CID20 evidence with at most one optional acquisition. Random is the exact 50:50 expected outcome, not a rounded Monte Carlo result.

| Policy | Top-1 correct | Accepted-correct | Coverage | Selective risk | Optional scans (total / mean) | Total acquisitions (mean) |
|---|---:|---:|---:|---:|---:|---:|
| cid20_only | 47/72 | 5/72 | 8.3% | 16.7% | 0 / 0.000 | 1.000 |
| always_cid40 | 56/72 | 38/72 | 58.3% | 9.5% | 72 / 1.000 | 2.000 |
| always_ead16 | 50/72 | 6/72 | 8.3% | 0.0% | 72 / 1.000 | 2.000 |
| separation | 57/72 | 36/72 | 54.2% | 7.7% | 67 / 0.931 | 1.931 |
| random_expected_50_50 | 53/72 | 22/72 | 33.3% | 8.3% | 72 / 1.000 | 2.000 |

Selective risk = accepted errors / accepted cases. For random, this is the ratio of expected counts, not the expectation of the risk ratio. Top-1 alone does not mean an accepted identification.

## Do the modalities complement each other? (truth-aware diagnostic)

| Success definition | CID40 only | EAD16 only | Both | Neither | Hindsight best measurement |
|---|---:|---:|---:|---:|---:|
| top1_correct | 14 | 8 | 42 | 8 | 64 |
| accepted_correct | 34 | 2 | 4 | 32 | 40 |

Top-ranked identity differs between measurements on 24/72 cases; decision status differs on 46/72.

## Does the existing planner exploit it?

Chosen actions: `{"CID40": 63, "EAD16": 4, "STOP": 5}`.

| Success definition | Sensitive cases | Ties excluded | Measured / stopped on sensitive cases | Successful modality choices | Best stop-or-measure count | Planner count | Regret count |
|---|---:|---:|---:|---:|---:|---:|---:|
| top1_correct | 22 | 50 | 22 / 0 | 15 | 64 | 57 | 7 |
| accepted_correct | 36 | 36 | 34 / 2 | 32 | 40 | 36 | 4 |

Sensitive subsets and hindsight ceilings use hidden outcomes and are diagnostic only. STOP is not counted as a modality choice and can still be appropriate.

### Is there a successful adaptive EAD rescue to demonstrate?

EAD16 repairs a wrong initial top-ranked identity where CID40 does not on 3 development cases. The existing planner chooses EAD16 and repairs a wrong initial ranking on 0 cases. Its EAD-selected investigations produce 0 accepted-correct identifications.

## Paired planner-minus-fixed differences

Positive benefit differences favor the planner; negative optional-scan differences mean fewer scans. Intervals are molecule bootstrap 95%; p-values are unadjusted exact two-sided McNemar tests.

| Fixed comparator | Metric | Difference per case | 95% CI | Planner-only / fixed-only successes | McNemar p |
|---|---|---:|---|---:|---:|
| cid20_only | top1_correct | +0.1389 | [+0.0278, +0.2500] | 14 / 4 | 0.0308838 |
| cid20_only | accepted_correct | +0.4306 | [+0.3056, +0.5556] | 32 / 1 | 7.91624e-09 |
| cid20_only | optional_scans | +0.9306 | [+0.8750, +0.9861] | — | — |
| always_cid40 | top1_correct | +0.0139 | [+0.0000, +0.0417] | 1 / 0 | 1 |
| always_cid40 | accepted_correct | -0.0278 | [-0.0694, +0.0000] | 0 / 2 | 0.5 |
| always_cid40 | optional_scans | -0.0694 | [-0.1250, -0.0139] | — | — |
| always_ead16 | top1_correct | +0.0972 | [-0.0278, +0.2222] | 14 / 7 | 0.189247 |
| always_ead16 | accepted_correct | +0.4167 | [+0.2917, +0.5417] | 32 / 2 | 6.93835e-08 |
| always_ead16 | optional_scans | -0.0694 | [-0.1250, -0.0139] | — | — |

## True-candidate template fit (diagnostic)

| Action | Median cosine | Template sources |
|---|---:|---|
| CID20 | 0.1936 | {"train_only_structure_knn": 72} |
| CID40 | 0.4927 | {"reference_cid60": 61, "train_only_structure_knn": 11} |
| EAD16 | 0.1007 | {"train_only_structure_knn": 72} |

## Discordant development cases (outcome-conditioned illustrations only)

CID/EAD cells are top-1 correctness / accepted-correct. Full identities, scores, plans and outcomes are in the JSON. Cases below do not define the primary dev cohort.

| Case | Compound | CID40 | EAD16 | Planner action | Planner accepted-correct |
|---|---|---:|---:|---|---:|
| case-07a97a0a6a07 | 4-({4-[(4-Fluorophenyl)methyl]piperazinyl}methyl)-6-methoxychromen-2-one | 1 / 1 | 1 / 0 | STOP | 0 |
| case-0b7596d031d3 | 4,6-dimethyl-8-(morpholin-4-ylsulfonyl)quinolin-2(1H)-one | 1 / 1 | 0 / 0 | CID40 | 1 |
| case-1fa9f510fe09 | FQACVCUXLWECJC-UHFFFAOYSA-N | 0 / 0 | 1 / 0 | CID40 | 0 |
| case-212b7974f8e1 | 2-[(1-Methylbeta-carbolin-3-yl)carbonylamino]benzoic acid | 1 / 1 | 0 / 0 | CID40 | 1 |
| case-2864fbe58d34 | 8-[(2-chlorobenzyl)sulfanyl]-9-(4-methylphenyl)-1,9-dihydro-6H-purin-6-one | 0 / 0 | 1 / 0 | CID40 | 0 |
| case-2b488515581d | OMWMLPHREGHXPR-UHFFFAOYSA-N | 0 / 0 | 1 / 1 | CID40 | 0 |
| case-3b99cfdbc294 | Cyproheptadine | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-402380559fd5 | 4-methoxy-N-[2-(2-methyl-1H-indol-3-yl)ethyl]benzenesulfonamide | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-4037093bf675 | 2-(3,4-Dimethoxyphenyl)-3-hydroxy-5,7-dimethoxy-2,3-dihydro-4H-chromen-4-one | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-512e44f9c8c2 | N-[(2,3-dimethoxyphenyl)methyl]-2-(4-hydroxyquinazolin-2-ylthio)acetamide | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-537e327cb02b | LFHNVTKRYWORIP-UHFFFAOYSA-N | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-68a30378c690 | methyl 2-amino-5-oxo-4-[3-(trifluoromethyl)phenyl]-4H-pyrano[3,2-c]chromene-3-carboxylate | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-6a6d54772f1f | 6-Amino-9-(2-p-tolyloxy-ethyl)-9H-purine-8-thiol | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-6eb83b85a5ba | MKWLCWJMHDISIT-UHFFFAOYSA-N | 0 / 0 | 1 / 0 | CID40 | 0 |
| case-6f9f1032bb70 | YAJJMVCTNZUFSE-UHFFFAOYSA-N | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-71ea97d4ded8 | FQTHQCIXDOKIDK-UHFFFAOYSA-N | 1 / 0 | 0 / 0 | CID40 | 0 |
| case-726ad0291719 | (2-Methylindolin-1-yl)(3,4,5-trimethoxyphenyl)methanone | 1 / 0 | 0 / 0 | CID40 | 0 |
| case-786b3acded07 | 4-{[Cyclopentyl(2-furylmethyl)amino]methyl}-6-ethoxychromen-2-one | 1 / 1 | 0 / 0 | CID40 | 1 |
| case-790b8147cfab | MTTQBZWFVUEGSE-UHFFFAOYSA-N | 1 / 0 | 0 / 0 | CID40 | 0 |
| case-7c7b657f0f19 | COLNVLDHVKWLRT-UHFFFAOYSA-N | 1 / 1 | 1 / 0 | STOP | 0 |
| case-7e91f0a750ba | PSAIYBQGWPCVCW-UHFFFAOYSA-N | 1 / 1 | 0 / 0 | CID40 | 1 |
| case-82a52bc50520 | RLHSBYZNSQPGCC-UHFFFAOYSA-N | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-86acfd72bdba | 11-{4-[(3-chlorophenyl)methoxy]phenyl}-3,3-dimethyl-2,3,4-trihydro-5H,10H,11H-benzo[b]benzo[2,1-f]1,4-diazepin-1-one | 1 / 1 | 0 / 0 | CID40 | 1 |
| case-8780fc9ed045 | CQKIZXJBWFRKOW-UHFFFAOYSA-N | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-8857cd352e0a | (E)-1-(1,3-benzodioxol-5-yl)-3-(2-thienyl)prop-2-en-1-one | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-8d3fc214db7d | 8-({[2-(2-chlorophenyl)-5-methyl-1,3-oxazol-4-yl]methyl}sulfanyl)-9-methyl-1,9-dihydro-6H-purin-6-one | 0 / 0 | 1 / 1 | CID40 | 0 |
| case-8f8282e0abcb | UXRKUKRXVWJFER-UHFFFAOYSA-N | 0 / 0 | 1 / 0 | EAD16 | 0 |
| case-98f7363b7c4d | 2-(7-hydroxy-4-methyl-2-oxo-2H-chromen-3-yl)-N-(2-phenylethyl)acetamide | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-9db31cee0158 | NXMBDZNOCKTDCN-UHFFFAOYSA-N | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-a162096ee5ad | 3-(3-Chlorophenyl)-7-methoxychromen-2-one | 1 / 0 | 0 / 0 | CID40 | 0 |
| case-a48fd4752b58 | MSDGTBGJKOTHCN-SOFGYWHQSA-N | 1 / 1 | 0 / 0 | CID40 | 1 |
| case-b18a35a3567b | Gestodene | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-b81bc946915c | NGTSRFJHFKEKPL-UHFFFAOYSA-N | 1 / 0 | 0 / 0 | CID40 | 0 |
| case-c1a3c066a602 | YHYKUSGACIYRML-KRWDZBQOSA-N | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-c3f287265e6a | IVVNZDGDKPTYHK-UHFFFAOYSA-N | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-ca3d464c92ec | 3-Ethyl-4-hydroxy-1-benzylhydroquinolin-2-one | 1 / 1 | 0 / 0 | CID40 | 1 |
| case-cee7ed2a0bf1 | LKSJDCKSSYHRME-UHFFFAOYSA-N | 0 / 0 | 1 / 0 | CID40 | 0 |
| case-d0a5dc4a2235 | YZYDSXGJSSYZJX-UHFFFAOYSA-N | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-d0e1d1508d12 | N-(2,4-dimethoxyphenyl)-2-(3,4-dimethoxyphenyl)acetamide | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-dc4a494f5bc5 | CVIIZIOAYADPTH-UHFFFAOYSA-N | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-e072d27a3e6b | N-(3-chloro-2-methylphenyl)-2-[(9-ethyl-6-oxo-6,9-dihydro-1H-purin-8-yl)sulfanyl]acetamide | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-e31bd4b5771e | XHEYZPULKRBNFS-UHFFFAOYSA-N | 0 / 0 | 1 / 0 | CID40 | 0 |
| case-edba875049b8 | 2-[2-(phenylcarbonyl)benzimidazolyl]-N-(2-phenylethyl)acetamide | 1 / 1 | 0 / 0 | CID40 | 1 |
| case-ef59de0f4faf | 3,3-dimethyl-11-(4-prop-2-ynyloxyphenyl)-2,3,4-trihydro-5H,10H,11H-benzo[1,2-f]benzo[b]1,4-diazepin-1-one | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-f2875538bb88 | YLSVTPWSJHSAGE-UHFFFAOYSA-N | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-f4e04a981995 | Dienogest | 1 / 0 | 0 / 0 | CID40 | 0 |
| case-fb392c0ff34e | 1-(1,3-Benzodioxol-5-YL)-3-(3,4-dimethylanilino)-1-propanone | 1 / 1 | 1 / 0 | CID40 | 1 |
| case-fd676f5a1ca8 | GQDLPNHRNYTHJA-UHFFFAOYSA-N | 1 / 1 | 1 / 0 | CID40 | 1 |

## Limitations

- Development-only exploratory analysis, not an independent test or generalization estimate.
- Closed-world library: true identity is present; no open-world identification claim.
- CID40 can use measured CID60 references; EAD16 uses predicted kNN templates. Pipeline comparison is confounded by reference quality.
- Relative support is uncalibrated; all existing acceptance thresholds were left unchanged.
- Hindsight ceilings and sensitive-case subsets use truth only inside this evaluator and are not deployable policies.
- Random numbers are exact expected outcomes of equal-probability measurement choice.
- No fitting, tuning, peak interventions, MCP work or canvas work was performed.
- Main has no dependency lockfile; package versions are recorded, using the existing research environment.

Reproduce: `make modality-headroom` after dependency installation.

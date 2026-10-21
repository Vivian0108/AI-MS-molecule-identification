# Judge questions

**What part uses AI?**
The planner uses a learned observation-error model and Monte Carlo expected information
gain to choose among bounded experimental actions. Candidate scoring and abstention
are deterministic numerical routines. No LLM identifies molecules or generates measured spectra.

**What is scientifically novel?**
The contribution is budget-aware experiment selection with explicit stopping, sealed
archived measurements and auditable abstention. Library matching, interpolation,
MassBank data and cosine evidence are prior work. The small test supports an observed
scan-efficiency result, not a new accuracy state of the art.

**How is leakage prevented?**
Scaffold-grouped molecular splits separate fitting and evaluation. Training fits the
error model; dev chooses the planner method. Frozen test outcomes do not change
thresholds, filters or cohort membership. References contain only 10/50 eV endpoints.
The planner accepts no truth or oracle handle. Explicit measurement reveals one
energy, consumes budget and logs the action. Tests verify the public payload boundary.
The oracle ceiling and energy-sensitive subsets are clearly labelled diagnostics.

**Why is this not de novo identification?**
Candidates are known structures with endpoint reference spectra, and the true identity
is in that library. The system ranks candidates; it does not propose arbitrary unseen
molecular structures or prove a new structure from MS/MS.

**How many genuinely ambiguous test molecules exist?**
Eleven of the frozen 100 test molecules have at least two precursor-consistent
candidates at 10 ppm. Four meet the historical close-call margin rule. The primary
ambiguous definition uses initial information, not hidden-energy success.

**Why should the result be trusted?**
All policies share the initial observation, references, candidate universe and frozen
rules. Paired bootstrap intervals resample molecules. The corrected stage-one table
separates ranking accuracy, acceptance and cost. Generation metadata and input hashes
support reproduction. Tests check comparison signs, independent oracle branches,
stages, Markdown/JSON agreement and hidden-data isolation. The corrected oracle
comes from a byte-exact reconstruction of the historical sealed artifact. Wide
intervals and failure examples remain visible. This is proof of concept, not validation
for a broad population.

**What fails in open-world identification?**
When the true identity is removed, the method can confidently select a plausible
wrong alternative. In the stress test it does so in 6/11 molecules with alternatives.
Closed-world relative support cannot establish that the true structure is present.
A robust unknown-class model and external prospective evaluation are needed.

**What would real-instrument deployment require?**
A vendor-supported acquisition interface, instrument-specific collision-energy and
latency calibration, instrument/metadata QC, validated peak preprocessing, robust
safety and failure handling, and a prospective study with independent standards,
replicates and mixtures. Throughput and false identification risk must be measured
on that deployment instrument. Archived-scan savings alone do not establish them.

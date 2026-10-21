# UnknownID: three-minute judge presentation

Before judging: run `make setup`, `make verify`, then `make demo` and open
http://localhost:8501. Start a fresh session. The demo banner must remain visible.
This presentation uses curated training/development examples, not frozen test cases.

## 0:00–0:20 — The problem

“Every unnecessary MS/MS measurement uses instrument time. A single fragmentation
spectrum can leave several known compounds plausible. Our question is whether to
spend one more scan, at 30 or 40 eV, or stop. UnknownID makes that decision explicit
and keeps an evidence trail.”

## 0:20–0:50 — Initial evidence

Open **Investigation**, choose `case-127895a5f433`, and click **Start**.
Show the competing candidates and the measured 20 eV spectrum. Point out the initial
relative supports and the unresolved ranking.

“This is a curated training example chosen to explain the interaction. We do not
use it as evidence that the method generalizes. Only the initial 20 eV observation
is visible. Reference templates come from separate 10 and 50 eV endpoint records.”

## 0:50–1:20 — The next experiment

Open **Next experiment**. Show the predicted acquisition values, reliability and
remaining budget. Explain the recommended 40 eV action.

“The planner simulates possible measurements around interpolated templates using
an error model fitted on training identities. The real hidden spectrum is sealed.
A separate stop action avoids spending the optional scan when the policy thinks
it is not worth the cost. These supports are not calibrated identity probabilities.”

## 1:20–1:50 — A real archived measurement

Press **Measure 40 eV**. Show the newly measured stick spectrum and changed ranking.
Show that the optional budget is now zero. If needed, return to Investigation to
compare measured and interpolated evidence.

“This action reveals an existing experimental MassBank record. We did not generate
that spectrum. The additional evidence now clears the fixed acceptance rule.”

## 1:50–2:15 — Evidence report

Open **Final report**, stop the investigation if still open, and download both
Markdown and JSON. Show the before/after ranking, released observed accessions,
QC conditions and limitations.

“The report names the evidence we actually measured and records our decision.
Other cases remain ambiguous and explicitly abstain. Try `case-e40ea5350560` for
that behavior, or `case-250b6ac895d0` for a correct stop without the optional scan.”

## 2:15–3:00 — Measured result and limits

Open **Evaluation** at stage one on the ambiguous cohort. Point to the Pareto plot
and the paired scan-savings interval.

“Our frozen test has 100 molecules, but only 11 are precursor-ambiguous. UnknownID
and always-40 each accepted nine correct identifications with no observed accepted
errors. UnknownID used seven optional measurements, compared with eleven. The
paired 95% interval for mean savings is 0.091 to 0.636 optional scans per molecule.
Top-1 accuracy is the same, so we do not claim an accuracy gain. This small cohort
does not establish equivalence. The method can miss useful follow-up measurements,
and open-world rejection fails when the true structure is absent. This is known-library
identification using archived data. A real-instrument deployment needs prospective
validation and instrument integration.”

## Backup if live networking fails

The local app does not require external networking after installation.
Use the [five screenshots](screenshots/) and [generated scientific report](../reports/evaluation.md)
if the browser itself fails. The automated HTTP rehearsal is
`.venv/bin/python scripts/rehearse_demo.py`.

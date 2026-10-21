# Data attribution and redistribution

The MIT license covers UnknownID code only. It does not relicense MassBank records.
MassBank / University of Athens data retain the per-record CC BY or CC BY-SA designation.
The records do not specify a Creative Commons version; preserve that designation rather
than inventing one. Consult [MassBank](https://github.com/MassBank/MassBank-data) and each
record before further redistribution. Creative Commons license descriptions:
[CC BY](https://creativecommons.org/licenses/by/), [CC BY-SA](https://creativecommons.org/licenses/by-sa/).

The demo includes verbatim records from the pinned snapshot
`befc8a1e2f2aef899747797c081a5d80fab12fe7` under `data/demo/source_records/`.
Original AUTHORS, COPYRIGHT, LICENSE, accessions and all record text are preserved.
`data/demo/attribution.json` maps every included spectrum to its original SHA-256,
record URL, author/copyright/license fields and transformations. Authors include
Nikiforos Alygizakis and Nikolaos Thomaidis, University of Athens; see each record
for its exact statement. CC BY-SA adaptations retain their source share-alike obligations.
Credit the authors and MassBank, link the source and license, indicate modifications,
and preserve applicable share-alike terms when distributing adapted data.

Derived spectra remove invalid peaks and peaks below 1% of the base peak and normalize
intensities to a unit base peak. Reference templates interpolate 10/50 eV endpoints.
The original raw record files in the demo are unchanged. Data outside the demo follow
the accession, license and SHA-256 map in `data/manifest.json`; that manifest includes
all parsed records, so it is broader than the accepted cohort.

Scientific prior work: *Augmentation of MS/MS Libraries with Spectral Interpolation
for Improved Identification*, JCIM (2022), [doi:10.1021/acs.jcim.2c00620](https://doi.org/10.1021/acs.jcim.2c00620).
MassBank archive: [doi:10.5281/zenodo.3378723](https://doi.org/10.5281/zenodo.3378723).

# Measured data reality

Measured on 2026-09-08 from the local corpus. This is partial geographic coverage,
not a national finding. Reproduce with `python scripts/profile_data.py` from the
project root after installing `requirements.txt`; full measurements are in
`reports/data_profile.json`, and console output is saved in `reports/profile_summary.txt`.
All percentages below describe this corpus only.

## Corpus and joins

| Measurement | Current result | Prior review |
|---|---:|---:|
| Completed CSVs | 79 | 76 |
| Completed rows | 5,611 | 5,133 |
| States | 5 | 5 |
| Sanctioned CSVs | 87 | 8 |
| Sanctioned rows | 11,832 | 1,763 |
| Completed rows joined to sanction records | 5,611 (100%) | 929 |
| Actual amount above sanction | 0 | 0 |
| Actual amount equal to sanction | 4,613 | 551 |
| Actual amount below sanction | 998 | 378 |

Completed state counts: Bihar 2,711; Telangana 1,407; Andhra Pradesh 1,065;
Arunachal Pradesh 221; Assam 207. A CSV count measures constituencies with exported
rows, not every constituency visited by the scraper. Progress counters and existing
parquet counts are independently reported in the JSON and must not substitute for
the current raw-row count. Both scraper progress lists contain 93 entries. The
master parquet has only 2,682 rows and is preserved unchanged.

## F1 — Confirmed design issue, corrected counts

`WORK_CATEGORY`: Normal/Others 5,532; Repair and Renovation 75; Trust and Society 4.
There are 206 derived activities after removing the work-sanction prefix, trimming
and uppercasing, rather than the prior 205. Top activities are roads 1,209; street
lights 606; lighting public spaces 530; tube/bore wells 508; community centres/halls
403. Category is still unsuitable as the principal activity peer key. The proposed
fallback ladder and minimum size are not yet assigned or validated.

## F2 — PDF evidence confirmed; single-image assumption contradicted

The profiler walks all attachment extensions and analyzes only paths linked from
completed CSVs. It probes every embedded JPEG marker stream, rather than taking the
first image. Real PDFs contain multiple scans and also narrow page tiles. For
example, `163131_1.pdf` contains many strips approximately 2336x37 pixels; treating
all such strips as scanner watermarks would erase document content.

Consequently, neither embedded-image counts nor a dimension threshold establish
the number of usable photographs. The review's 3,550 usable-image estimate and
24%/66%/10% semantic composition are **not reproduced**. Page-aware extraction and
visual classification are pending Phase 1. Failed JPEG probing means unsupported
or unreadable by this method, not that the PDF contains no evidence.

Final attachment inventory: 4,461 files (3,388 PDF, 856 JPEG, 216 JPG, one DOCX).
There are 4,229 CSV-referenced paths, all present, and 232 unreferenced files excluded
from analysis (six have the legacy injector's 900000... naming pattern; the others
are not assumed synthetic). The probe decoded 21,978 images, 21,025 inside PDFs.
It recorded 187 PDFs with no embedded JPEG found and 195 failed image decodes;
these are image/probe outcomes, not counts of unusable PDF documents. There are
3,445 decoded images with a minimum dimension below 200 pixels. This does not
identify which are junk. Median entropy is 3.734 bits; median thumbnail colorfulness
is 6.997. Original dimensions, distributions, errors and identity groups are in the
machine-readable report; per-image rows are in the regenerable attachments CSV.

## F3 — GPS unverified; universal EXIF absence contradicted

No OCR or visual GPS-overlay prevalence measurement has been performed in this
increment. No Tesseract binary was on PATH. Image EXIF presence is measured by the
profiler: **3,501 decoded images contain nonempty EXIF**. This contradicts universal
metadata-stripping claims, but does not establish that these tags contain GPS or
valid capture dates, nor whether coordinates exist in pixels. No map or
document-intelligence feature is justified yet.

## F4 — Identity measurement only; prior detector claims unverified

SHA-256 groups across different CSV work IDs are recorded in the JSON. Identity
proves equal image bytes, not that an asset claim is duplicated. Groups still
include common scanner marks and page tiles. No severity or officer alert is
produced. The current raw identity count is 357 cross-work SHA-256 groups before
semantic triage. The prior 70 MD5 groups, 2,439 pHashes, 176-image bucket and 3,687 near
pairs are **not confirmed on an equivalent extraction/triage population**; pHash
and keypoint measurements remain pending. Do not present raw identity counts as
usable duplicate cases.

## F5 — Confirmed richer sanction data; join scope corrected

Every completed row joins on `WORK_RECOMMENDATION_DTL_ID`; there is currently no
need for a sanction-date proxy on those rows. No joined completion precedes its
sanction or recommendation date in the additional tabular inspection.

Sanctioned stages: Physical Inspection 5,592; Sanction 3,301; Vendor Identification
1,287; Work Completed 881; Work partially Completed 708; Time Estimation 63.
Within the completed join, 4,730 rows are Physical Inspection and only 881 Work
Completed. Preserve the two source statuses and resolve the meaning before an
idle detector filters on sanctioned stage alone.

## F6 — Confirmed dead fields, corrected distributions

Completed `AVERAGE_RATING` is 0.0 in all 5,611 rows; `FLAG` is 3 throughout.
`FILE_STATUS` is True for 3,611 and null for 2,000; 2,000 rows have zero downloaded
attachments. Do not interpret this as work status. There are 18 amounts at most
INR 1, and 760 amounts are exact INR 100,000 multiples (including zero).

All completed letter numbers parse after whitespace normalization, with no invalid
fiscal-year sequence. Fiscal-year start counts: 2024: 2,550; 2025: 2,988; 2026: 73.
All populated dates parse with their actual formats: ordinary dates `%d-%b-%Y`,
tenure timestamps `%b %d, %Y %I:%M:%S %p`. Completed dates range 2024-09-05 through
2026-09-07; recommendation dates 2024-07-12 through 2026-09-03; sanction dates
2024-07-14 through 2026-09-07. Future-year projections need to acknowledge partial years.

## F7 — Amount claim corrected; legal verification incomplete

551 works fall in INR 900,000 inclusive to 1,000,000 exclusive, and 700 exceed
INR 1,000,000. The prior claims of 546 and 759 respectively are not the current
measurements. Amount clustering does not verify a legal threshold.

No INR 1,000,000 sanction/scrutiny rule has been sourced. The official 2023 index
was located but could not be fetched; the 2016 search extract supports a 75-day
receipt-based rule with exclusions, which is insufficient to establish the
applicable 2023 provision. See DECISIONS.md for source links. No legal rule is
implemented in this phase. Annual entitlement, trust/society and outside-constituency
ceilings require exact applicable sources and observable predicates before scoring.

## F8 — Environment corrected

The runtime used here is Python 3.12.14, not 3.13.7. A project-local `.venv` now
contains the exact Phase 0 packages pinned in `requirements.txt`. Pandas, NumPy,
Pillow, pyarrow, pytest and requests are installed; later ML, backend and OCR
libraries remain absent in that environment. Docker CLI is on PATH; PostgreSQL,
psql and Tesseract are not. This is a PATH check, not proof no installation exists
elsewhere. No GPU or system installation was attempted. Python 3.13 compatibility
and clean-machine full-stack reproducibility remain unverified.

## Reproduction and runtime

Final command: `./.venv/Scripts/python.exe -u scripts/profile_data.py`, exit 0.
Measured elapsed time: **457.90 seconds** (7 minutes 38 seconds), including all CSVs
and the full CSV-linked attachment pass. Two slower preliminary full-resolution
passes were interrupted for diagnosis; they are not counted as successful runs.
`reports/profile_summary.txt` contains the exact summary printed by the successful
command. The original feature function was executed over all 5,611 rows in memory;
it produced 35 columns without overwriting the old parquet.

The additional completed/sanctioned status comparison in `reports/join_audit.json`
can be reproduced with:

```python
from pathlib import Path
from scripts.profile_data import load_family, counts
import pandas as pd
c, _ = load_family(Path('mplads_india'), 'works_with_images.csv')
s, _ = load_family(Path('mplads_india'), 'works_sanctioned.csv')
j = c.merge(s, on='WORK_RECOMMENDATION_DTL_ID', suffixes=('', '_sanctioned'), validate='one_to_one')
print(counts(j.WORK_STAGE))
for name in ['RECOMMENDATION_DATE', 'SANCTION_DATE']:
    print(name, (pd.to_datetime(j[name], format='%d-%b-%Y') > pd.to_datetime(j.ACTUAL_END_DATE, format='%d-%b-%Y')).sum())
```

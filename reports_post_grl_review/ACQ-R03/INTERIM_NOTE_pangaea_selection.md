# ACQ-R03 §1.4 interim note to Steve — PANGAEA selection files published (2026-09-30)

The §1.2 file selections are published here as soon as they exist, so you can download in parallel with the
automated fetch (`ingest_manual.py` skips what the fetch already holds, and the fetch skips what you ingested).

| cruise | OAK cruise dir | selection csv | url list | selected / whole cruise |
|---|---|---|---|---|
| M114/1 (Chapopote, pu01; PANGAEA 864677) | `raw_lr_swath/PANGAEA_864677/` | `pangaea_selection_PANGAEA_864677.csv` | `pangaea_selection_PANGAEA_864677_urls.txt` | **59 files, 1.40 GB** of 349 files, 8.04 GB (per-file WKT ship track ∩ HR footprint buffered 4 km) |
| M112/1 (Venere, pu00; PANGAEA 892317) | `raw_lr_swath/PANGAEA_892317/` | `pangaea_selection_PANGAEA_892317.csv` (pending) | `pangaea_selection_PANGAEA_892317_urls.txt` (pending) | positions are being derived from 2 MB Range reads of each of the 1,170 `.all` files (no M112 navigation dataset exists on PANGAEA); the selection is written by the running job when that finishes (≈ 1–2 h) |

- Every URL is the complete file URL taken verbatim from the dataset's tab export (`?format=textfile`); opening one
  downloads that single file. **Do not open the folder part of a URL** (`/bathy/m114/`, `/bathy/M112/EM122/`): that is what
  returns "Directory listings … are disabled".
- `wget -i pangaea_selection_<cruise>_urls.txt` (or any download manager) works on the url lists.
- Manual path: put downloaded files in OAK `raw_lr_swath/_inbox/<cruise dir>/`, then (in an `sh_dev` session)
  `python -m src.acq_r03.ingest_manual --cruise PANGAEA_864677` (or `PANGAEA_892317`). Accepted = name in the
  selection, size = advertised (±1 kB), `mbinfo` reads it; rejects stay in the inbox and are listed in
  `manual_ingest_<cruise>.json`.
- The automated fetch (one worker, 1 s throttle, Range-resume, back-off on 429/503) runs in Slurm job
  `acq_r03_pangaea` (48 h limit); progress in `fetch_progress_<cruise>.json`, summary in `fetch_summary_<cruise>.json`.

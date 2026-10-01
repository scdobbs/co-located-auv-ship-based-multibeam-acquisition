# ACQ-R03 R3 interim note to Steve — M112 cruise report not reachable from the cluster (2026-10-01)

R3 step 1 asks for the M112 cruise report (Bohrmann 2015, METEOR-Berichte, doi:10.2312/cr_m112) to derive the
Venere working-area time windows. From Sherlock:

- `https://doi.org/10.2312/cr_m112` → 302 → `https://www.tib.eu/en/search/id/awi:c41df8510165df2d3689a8f76c9a75bffb9d38fe`
  (HTML record page). Its "download" action (`tx_tibsearch_search[action]=download`, docid above) returns the TIB
  search page (HTML, 7–117 kB), not the PDF — the download is browser-session driven.
- Leitstelle Deutsche Forschungsschiffe (`ldf.uni-hamburg.de/meteor/wochenberichte/…/m112-scr.pdf`, `m112-wb1.pdf`): 404.
- No PDF text tool is available on the cluster (`pdftotext` absent; the `poppler/0.47.0` module ships the library only;
  no `pypdf` in the environment). If you place the PDF at
  `$GROUP_SCRATCH/auv_ship_colocated_bathy/acq_r03_ref/cr_m112.pdf` (or anywhere readable), I will install `pypdf` into
  the repo environment and parse the station list and daily narrative from it, then apply the R3 pre-filter.

Until then the M112 position job (46140636) keeps running under its existing rule (heads at the host's pace; 69 of
1,166 after 17 h), and the rest of §6 proceeds without pu00 (R3 step 6: pu00 enters as v2.1.1 when its chain finishes).

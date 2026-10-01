# Co-located AUV / Ship-Multibeam Bathymetry Pairs

Data acquisition and harmonization for **real, physically-independent low-resolution /
high-resolution (LR/HR) seafloor bathymetry pairs**.

## Why this exists

We are building a super-resolution model that generates ultra-high-resolution seafloor
bathymetry from a lower-resolution input. The core data-integrity risk is **circularity**:
the global LR products everyone reaches for (GEBCO, GMRT) *ingest* the same high-resolution
multibeam we would use as ground truth, so using them as the LR input leaks the answer.

The key realization is that **AUV bathymetry surveys are flown over pre-existing ship
multibeam maps**, so for many sites the same patch of seafloor has been measured twice by
genuinely independent acquisitions:

- **HR** — near-bottom AUV multibeam (~1–2 m grids, flown ~50–80 m off the seafloor).
- **LR** — hull-mounted ship multibeam (~10–50 m grids) over the *same* footprint.

Because these are two independent measurements, a (ship-LR → AUV-HR) pair is a **real**
super-resolution example, not a synthetic one — the gold-standard validation of the actual
deployment pathway.

> **Correctness constraint:** the LR side must be a *real ship measurement*. LR is never
> synthesized by downsampling the AUV HR. Resampling is used only for CRS alignment and to
> place HR and LR on a common grid/footprint.

## What this repo does

For each co-located pair: download HR and LR via each repository's API, reproject to a
common CRS, clip to the shared HR∩LR footprint, co-register the AUV to the ship grid where
needed, and record everything in a provenance-rich manifest plus a QA report.

Data comes from FAIR repositories with stable DOIs — **PANGAEA** (`pangaeapy`),
**USGS ScienceBase** (`sciencebasepy`), and **MGDS / marine-geo.org**. APIs only, never
HTML scraping.

## Repository layout

```
config/harmonization.yaml   # all human decisions: CRS, resampling, datum, QA thresholds, data_root
src/                        # acquisition + harmonization code (CLI: python -m src.cli)
src/discovery/              # ship-companion discovery (read-only / append-only)
src/acq_r01/, src/acq_r03/  # post-GRL-review directives ACQ-R01/R02/R03 (lockbox guard, raw swath, ship products, manifest v2/v2.1)
manifest/pairs.parquet      # the June pair catalog (schema documented in CLAUDE.md §5) — frozen
manifest/pairs_v2_1.parquet # the current catalog (ACQ-R03); pairs_v2*_dropped.csv list every dropped pair and why
reports_post_grl_review/    # directives + interface contracts (verbatim), rulings, per-directive reports and artifacts
sbatch/                     # Slurm batch scripts for running stages on Sherlock
reports/                    # June stage reports (on disk, not tracked since 238ea61)
docs/                       # CHANGES_since_first_iteration.md — how the repo evolved from the first iteration
logs/
```

**Large binary files do not live in this repo.** Raw ship swath, raw AUV grids, harmonized
GeoTIFFs, masks and ship-product rasters are kept on Oak
(`/oak/stanford/groups/hilley/auv_ship_colocated_bathy/`); Sherlock scratch (`data_root` in the
config) holds only working files, because scratch is purged after 90 days. Nothing goes to
`$HOME`. Only small text artifacts (code, config, manifests, logs, reports) are
version-controlled. See [`docs/CHANGES_since_first_iteration.md`](docs/CHANGES_since_first_iteration.md)
for how this changed from the first iteration, when `data_root` on scratch was the only data location.

## Usage

Runs on Sherlock. Load the Python environment, then drive the pipeline through the CLI:

```bash
pip install -r requirements.txt          # in a scratch/group venv, not $HOME

python -m src.cli check-config           # validate config + that data_root resolves to scratch
python -m src.cli ingest --pair <pair_id>  # download + harmonize a pair, write manifest row
python -m src.cli report                 # regenerate the acquisition + QA report
```

Heavy work is submitted through Slurm (`sbatch/`), not run on the login node.

## Provenance & licensing

Each pair carries a full citation and license in its `metadata.json` sidecar. PANGAEA data
are **CC-BY** — attribution is preserved. DOIs are fixed and verified; they are never
fabricated or guessed.

## Agent / contributor working rules

The detailed acquisition directive — scope, target datasets, harmonization steps, the
manifest schema, and the hard rules — lives in [`CLAUDE.md`](CLAUDE.md). Read it before
making changes.

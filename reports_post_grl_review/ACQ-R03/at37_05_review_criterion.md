# ACQ-R03 §3.1 — AT37-05__MGDS_24043 review criterion (committed before the package is built)

**Question (directive §3).** Are the bimodal in-cell soundings of the AT37-05 ship swath under the Sentry HR
(contract-v2 QA: median rsd/sd 0.08, ship-median − `lr.tif` = +46 m, HR−LR dz −74 m) an inconsistency in the ship
data, or real steep terrain (Siqueiros transform)?

**Keep the pair** if the two depth populations co-occur within single lines and pings at a spatial pattern
consistent with slope: inside one swath file and one ping, adjacent beams step from one population to the other
across a coherent boundary that follows the terrain (the HR hillshade shows the scarp there), and lines that
overlap agree with each other in their shared cells.

**Drop the pair** if the populations separate by survey line, file or time: overlapping lines disagree in their
shared cells by a line-to-line median depth difference that exceeds the local robust spread (the median
within-line 1.4826·MAD of the same cells), so that `lr.tif` averaged two inconsistent ship surfaces into the LR
input. Such a separation is a ship-internal inconsistency.

**How the package reads (directive §3.2).** `bimodal_gap.tif` / `bimodal_minor_frac.tif`: per cell with ≥ 6
soundings, the exact 1-D 2-means split (gap between the two cluster means; fraction of soundings in the minor
cluster). A cell is counted as bimodal when the minor cluster holds ≥ 20 % of its soundings and the gap is
≥ 10 m. `line_offsets.csv`: for every pair of overlapping swath files, the median over shared cells of
(median depth of line i − median depth of line j), its MAD, the number of shared cells and the local robust
spread. `windows_top3_points.gpkg`: every sounding (file, ping, beam, depth, cluster) of the three 2 × 2 km windows
with the most bimodal cells. Hillshades of `lr.tif` and the HR, `ship_count` and `ship_rsd` give the context.

The numbers are reported; the decision (keep / drop) is Steve's.

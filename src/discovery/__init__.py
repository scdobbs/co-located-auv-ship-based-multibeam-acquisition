"""v1.4 pair-discovery engine.

Read-only / append-only against existing acquisition state. Harvests HR
(AUV bathymetry grids) and LR (ship-multibeam footprints) catalogs from
public APIs and produces a ranked candidate-pairs catalog for human
triage. NEVER modifies the existing manifest, harmonized rasters, or any
prior result.
"""

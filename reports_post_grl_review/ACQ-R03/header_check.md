# ACQ-R03 §2.2 header check (grid registration)

GDAL/rasterio placement on a current mbgrid grid (`TN399__union.grd`): left edge − first x node = -0.5 cells, top edge − last y node = 0.5 cells → pixel centres on the nodes (correct for mbgrid node values). `node_offset` attribute: None; Conventions CF-1.7.

| pair | raw LR registration | raw HR registration | harmonize_pair reader | harmonized lr.tif origin vs raw (cells) | mismatch | frame offset (m) |
|---|---|---|---|---|---|---|
| ccz_so268_1 | PixelIsArea | PixelIsArea | GDAL PixelIsArea (rasterio/rioxarray) | 297.0 | False | 0.0, 0.0 |
| discol_so242_1 | PixelIsArea | PixelIsArea | GDAL PixelIsArea (rasterio/rioxarray) | 420.0 | False | 0.0, 0.0 |
| tag_m127 | PixelIsArea | PixelIsArea (GTRasterTypeGeoKey absent; GeoTIFF default) | GDAL PixelIsArea (rasterio/rioxarray) | reprojected | False | 0.0, 0.0 |
| EW0207__MGDS_32556 | mbgrid CF/COARDS netCDF (x/y coordinate variables; GMT_version 6.1.1) | MBARI classic GMT netCDF (1-D z, x_range/y_range) | GDAL PixelIsArea (rasterio/rioxarray) | reprojected | False | 0.0, 0.0 |
| EW9801__MGDS_31425 | mbgrid CF/COARDS netCDF (x/y coordinate variables; GMT_version 6.1.1) | float GeoTIFF (EPSG:4326) | GDAL PixelIsArea (rasterio/rioxarray) | reprojected | False | 0.0, 0.0 |

Code paths:

- **ccz_so268_1**: src/pipeline.py -> src/harmonize.harmonize_pair: rioxarray.open_rasterio (GDAL GeoTIFF reader, PixelIsArea semantics); same CRS -> no reprojection, clip only (grid alignment preserved: lr.tif edges are multiples of 50 m as in the raw grid)
- **discol_so242_1**: src/pipeline.py -> src/harmonize.harmonize_pair: rioxarray.open_rasterio; same CRS -> clip only (lr.tif origin = raw origin + integer number of cells)
- **tag_m127**: src/pipeline.py -> src/harmonize.harmonize_pair: rioxarray.open_rasterio (EPSG:4326 GeoTIFF, PixelIsArea) -> rio.reproject to EPSG:32623, bilinear
- **EW0207__MGDS_32556**: LR: mbgrid CF/COARDS netCDF (x/y coordinate variables) read by src/discovery/stage_c1_harmonize.materialize -> rasterio.open (GDAL netCDF driver; gmt_grd.is_gmt_grd is False for the 2-D COARDS layout, and the _read_coards_grd fallback is not reached because rasterio opens the file) -> src/harmonize.harmonize_pair reproject to EPSG:32609, bilinear. HR: MBARI classic GMT grid via src/gmt_grd.convert (from_bounds on x_range/y_range: node range treated as outer edges, a half-cell + 1/nx scale error on the HR side only); the HR was then rigidly co-registered to lr.tif (stage F masked coreg), so the pair is internally consistent and the HR registration does not enter the ship products.
- **EW9801__MGDS_31425**: LR: mbgrid CF/COARDS netCDF read by src/discovery/stage_f_harmonize._lr_to_tif -> rasterio.open (GDAL netCDF driver) -> src/harmonize.harmonize_pair reproject to EPSG:32605, bilinear. HR: float GeoTIFF (EPSG:4326) via rasterio.

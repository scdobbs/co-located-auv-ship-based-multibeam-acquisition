# v1.2 §B — User-provided Cal DIG HR inventory (28 files)

Each file got: SHA256, raster metadata, hillshade PNG, FFT spectrum PNG of a flat window, and a `<file>.provenance.json` sidecar with `attested_artifact_free: null` awaiting human attestation.

Heuristic spectral metrics (informational; HUMAN attests artifact-free per addendum §B.3):
- `radial_log_slope`: log-log slope of the radial 1D spectrum on the flat window. Smoother bathymetry → steeper (more negative) slope.
- `axis_excess`: high-frequency power on the cardinal axes ÷ same-frequency radial baseline. **A sustained value >> 1 is the prescribed signature of grid-axis spectral spikes from NN reprojection.**

| file | CRS | pixel (m) | width × height | depth (min/med/max) | radial slope | axis excess | hillshade | FFT |
|---|---|---|---|---|---:|---:|---|---|
| `1000mGully_Topo1m_UTMinterp_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 5619 × 6067 | -989/-938/-863 | -1.92 | 67465.95 | `1000mGully_Topo1m_UTMinterp_utm_hillshade.png` | `1000mGully_Topo1m_UTMinterp_utm_fft.png` |
| `600mGully_2m.tif` | EPSG:32610 | 2.00 × 2.00 | 5940 × 4365 | -932/-818/-623 | -2.86 | 483091.08 | `600mGully_2m_hillshade.png` | `600mGully_2m_fft.png` |
| `600mGully_Topo1m_UTMinterp_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 11879 × 8728 | -932/-818/-623 | -2.25 | 185591.21 | `600mGully_Topo1m_UTMinterp_utm_hillshade.png` | `600mGully_Topo1m_UTMinterp_utm_fft.png` |
| `6thHeadlessCanyon_2m.tif` | EPSG:32610 | 2.00 × 2.00 | 3299 × 2016 | -990/-747/-492 | -3.16 | 142238.48 | `6thHeadlessCanyon_2m_hillshade.png` | `6thHeadlessCanyon_2m_fft.png` |
| `BankFlankHoles_MAUV_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 5168 × 3344 | -903/-813/-749 | -1.69 | 12266.05 | `BankFlankHoles_MAUV_Topo1m_UTM_utm_hillshade.png` | `BankFlankHoles_MAUV_Topo1m_UTM_utm_fft.png` |
| `BankFlankIncipCh_2m.tif` | EPSG:32610 | 2.00 × 2.00 | 1617 × 3169 | -761/-675/-567 | -2.90 | 47895.94 | `BankFlankIncipCh_2m_hillshade.png` | `BankFlankIncipCh_2m_fft.png` |
| `BankFlankIncipientChannel_Topo1m_converted.tif` | EPSG:32610 | 1.16 × 1.16 | 2779 × 5448 | -761/-675/-567 | -2.41 | 65955.15 | `BankFlankIncipientChannel_Topo1m_converted_hillshade.png` | `BankFlankIncipientChannel_Topo1m_converted_fft.png` |
| `BankTopEastofCanyon3_Topo1m_converted.tif` | EPSG:32610 | 1.01 × 1.01 | 8481 × 2734 | -560/-443/-410 | -1.64 | 18251.69 | `BankTopEastofCanyon3_Topo1m_converted_hillshade.png` | `BankTopEastofCanyon3_Topo1m_converted_fft.png` |
| `BankTopEofCanyon3_2m.tif` | EPSG:32610 | 2.00 × 2.00 | 4301 × 1387 | -560/-443/-410 | -1.59 | 76090.59 | `BankTopEofCanyon3_2m_hillshade.png` | `BankTopEofCanyon3_2m_fft.png` |
| `BasinFlank_MAUV_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 5401 × 4343 | -937/-895/-846 | -3.65 | 184549.97 | `BasinFlank_MAUV_Topo1m_UTM_utm_hillshade.png` | `BasinFlank_MAUV_Topo1m_UTM_utm_fft.png` |
| `CableSurvey_MAUV_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 19392 × 2714 | -881/-695/-466 | nan | nan | `CableSurvey_MAUV_Topo1m_UTM_utm_hillshade.png` | `CableSurvey_MAUV_Topo1m_UTM_utm_fft.png` |
| `Channel700_2m.tif` | EPSG:32610 | 2.00 × 2.00 | 2377 × 2238 | -878/-813/-771 | -2.00 | 738800.72 | `Channel700_2m_hillshade.png` | `Channel700_2m_fft.png` |
| `ChannelSurvey_1000_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 4483 × 5326 | -1106/-989/-948 | -3.23 | 223272.10 | `ChannelSurvey_1000_Topo1m_UTM_utm_hillshade.png` | `ChannelSurvey_1000_Topo1m_UTM_utm_fft.png` |
| `ChannelSurvey_700_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 4754 × 4476 | -878/-812/-771 | -1.57 | 36476.49 | `ChannelSurvey_700_Topo1m_UTM_utm_hillshade.png` | `ChannelSurvey_700_Topo1m_UTM_utm_fft.png` |
| `HeadlessCanyon_2m.tif` | EPSG:32610 | 2.00 × 2.00 | 3595 × 1357 | -971/-726/-478 | -2.90 | 27916.32 | `HeadlessCanyon_2m_hillshade.png` | `HeadlessCanyon_2m_fft.png` |
| `HeadlessCanyon_Topo1m_converted.tif` | EPSG:32610 | 1.02 × 1.02 | 7054 × 2662 | -971/-726/-478 | -3.48 | 1699391.55 | `HeadlessCanyon_Topo1m_converted_hillshade.png` | `HeadlessCanyon_Topo1m_converted_fft.png` |
| `LuciaChica1100_2m.tif` | EPSG:32610 | 2.00 × 2.00 | 3305 × 2654 | -1189/-1094/-1034 | -2.67 | 1190910.50 | `LuciaChica1100_2m_hillshade.png` | `LuciaChica1100_2m_fft.png` |
| `LuciaChica2019_repeat_1100m_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 6603 × 5311 | -1189/-1094/-1034 | -1.53 | 170083.28 | `LuciaChica2019_repeat_1100m_Topo1m_UTM_utm_hillshade.png` | `LuciaChica2019_repeat_1100m_Topo1m_UTM_utm_fft.png` |
| `LuciaChica2019_repeat_970m_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 4394 × 3855 | -1014/-981/-940 | -2.17 | 48351.73 | `LuciaChica2019_repeat_970m_Topo1m_UTM_utm_hillshade.png` | `LuciaChica2019_repeat_970m_Topo1m_UTM_utm_fft.png` |
| `LuciaChica970_2m.tif` | EPSG:32610 | 2.00 × 2.00 | 2198 × 1932 | -1014/-981/-940 | -3.45 | 142011.06 | `LuciaChica970_2m_hillshade.png` | `LuciaChica970_2m_fft.png` |
| `LuciaChica_2007_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 5688 × 5395 | -1048/-1011/-963 | -2.05 | 17750.49 | `LuciaChica_2007_Topo1m_UTM_utm_hillshade.png` | `LuciaChica_2007_Topo1m_UTM_utm_fft.png` |
| `LuciaChica_2008_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 16880 × 14238 | -1253/-1069/-932 | -1.36 | 10898.39 | `LuciaChica_2008_Topo1m_UTM_utm_hillshade.png` | `LuciaChica_2008_Topo1m_UTM_utm_fft.png` |
| `LuciaChica_2009_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 10733 × 9717 | -1118/-1045/-1017 | -1.63 | 193912.23 | `LuciaChica_2009_Topo1m_UTM_utm_hillshade.png` | `LuciaChica_2009_Topo1m_UTM_utm_fft.png` |
| `MorroBay_all_2020_interp_32m_converted.tif` | EPSG:32610 | 32.00 × 32.00 | 6428 × 7512 | -4617/-1125/1 | -2.39 | 10401.34 | `MorroBay_all_2020_interp_32m_converted_hillshade.png` | `MorroBay_all_2020_interp_32m_converted_fft.png` |
| `PockmarkNorth_MAUV_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 4199 × 3676 | -971/-937/-907 | -3.32 | 65400.61 | `PockmarkNorth_MAUV_Topo1m_UTM_utm_hillshade.png` | `PockmarkNorth_MAUV_Topo1m_UTM_utm_fft.png` |
| `PockmarkSouth_MAUV_Topo1m_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 5095 × 4708 | -997/-948/-911 | -2.19 | 108754.43 | `PockmarkSouth_MAUV_Topo1m_UTM_utm_hillshade.png` | `PockmarkSouth_MAUV_Topo1m_UTM_utm_fft.png` |
| `Transect_60_1060m_Topo1m_interp_converted.tif` | EPSG:32610 | 1.03 × 1.03 | 31745 × 14809 | -1063/-896/-614 | nan | nan | `Transect_60_1060m_Topo1m_interp_converted_hillshade.png` | `Transect_60_1060m_Topo1m_interp_converted_fft.png` |
| `Transit_frmPocN_chan_cab_UTM_utm.tif` | EPSG:32610 | 1.00 × 1.00 | 26428 × 23203 | -947/-827/-609 | nan | nan | `Transit_frmPocN_chan_cab_UTM_utm_hillshade.png` | `Transit_frmPocN_chan_cab_UTM_utm_fft.png` |

## Sidecars

Provenance sidecars written next to each file:

- `1000mGully_Topo1m_UTMinterp_utm.tif.provenance.json` (sha256 `8e16b71d6e6c478b…`)
- `600mGully_2m.tif.provenance.json` (sha256 `a3c42e8a44d21e02…`)
- `600mGully_Topo1m_UTMinterp_utm.tif.provenance.json` (sha256 `b71021a1c780ec13…`)
- `6thHeadlessCanyon_2m.tif.provenance.json` (sha256 `8ed7615a4819fd92…`)
- `BankFlankHoles_MAUV_Topo1m_UTM_utm.tif.provenance.json` (sha256 `1566b6fbafa703ac…`)
- `BankFlankIncipCh_2m.tif.provenance.json` (sha256 `6cfa1bd4fb2e5bb8…`)
- `BankFlankIncipientChannel_Topo1m_converted.tif.provenance.json` (sha256 `a8772430919a8a97…`)
- `BankTopEastofCanyon3_Topo1m_converted.tif.provenance.json` (sha256 `41e34ff5f628754b…`)
- `BankTopEofCanyon3_2m.tif.provenance.json` (sha256 `9037eee497985f41…`)
- `BasinFlank_MAUV_Topo1m_UTM_utm.tif.provenance.json` (sha256 `04d0455be6c9dfef…`)
- `CableSurvey_MAUV_Topo1m_UTM_utm.tif.provenance.json` (sha256 `d80236aafee3604d…`)
- `Channel700_2m.tif.provenance.json` (sha256 `033d16994c72afda…`)
- `ChannelSurvey_1000_Topo1m_UTM_utm.tif.provenance.json` (sha256 `b47be1831b2fe8c8…`)
- `ChannelSurvey_700_Topo1m_UTM_utm.tif.provenance.json` (sha256 `43e38bbf8b46bd0a…`)
- `HeadlessCanyon_2m.tif.provenance.json` (sha256 `e59e3f95b71914b2…`)
- `HeadlessCanyon_Topo1m_converted.tif.provenance.json` (sha256 `f3c5d199cd152645…`)
- `LuciaChica1100_2m.tif.provenance.json` (sha256 `176163cee1d1cfbe…`)
- `LuciaChica2019_repeat_1100m_Topo1m_UTM_utm.tif.provenance.json` (sha256 `00d9509615cea59c…`)
- `LuciaChica2019_repeat_970m_Topo1m_UTM_utm.tif.provenance.json` (sha256 `da82580e1a72f1ae…`)
- `LuciaChica970_2m.tif.provenance.json` (sha256 `99fdb7d3ee9305da…`)
- `LuciaChica_2007_Topo1m_UTM_utm.tif.provenance.json` (sha256 `60eae5d91c0736d7…`)
- `LuciaChica_2008_Topo1m_UTM_utm.tif.provenance.json` (sha256 `d1a0ea09f2fbed88…`)
- `LuciaChica_2009_Topo1m_UTM_utm.tif.provenance.json` (sha256 `45d24a0561523cc5…`)
- `MorroBay_all_2020_interp_32m_converted.tif.provenance.json` (sha256 `e868e349c3b5ccc2…`)
- `PockmarkNorth_MAUV_Topo1m_UTM_utm.tif.provenance.json` (sha256 `8829a2d876ec9faa…`)
- `PockmarkSouth_MAUV_Topo1m_UTM_utm.tif.provenance.json` (sha256 `7c7b1c01b95d3bbd…`)
- `Transect_60_1060m_Topo1m_interp_converted.tif.provenance.json` (sha256 `b94983473b9736ac…`)
- `Transit_frmPocN_chan_cab_UTM_utm.tif.provenance.json` (sha256 `6d69955dcce12a4a…`)

## Required human action

1. Review hillshade + FFT PNGs (in this report's directory). The criss-cross artifact, if present, is most clearly visible as bright spikes on the kx=0 or ky=0 lines of the FFT spectrum, and as a diamond/grid texture in the hillshade.
2. For each file, set `attested_artifact_free: true|false` in the matching `.provenance.json` sidecar.
3. Files with `attested_artifact_free: false` will be excluded from §C matching.

# Fetch plan (ACQ-R02 §6.1)

{
 "n_cruises": 19,
 "n_planned": 13,
 "needs_format_review": [
  "RP15DI86"
 ],
 "failed": [
  "EX1202L2",
  "EX1202L3"
 ],
 "total_gb": 58.7,
 "cap_gb": 500.0,
 "within_cap": true,
 "n_files": 3383
}

| LR cruise | source | status | HR served | designations | files total → planned | whole GB | planned GB | mode | note |
|---|---|---|---|---|---|---|---|---|---|
| 2009_Amundsen | nan | already_on_oak | MGDS:30047 | nan | nan → nan | nan | 0.0 | nan | nan |
| AT37-05 | NCEI | planned | MGDS:24043 | development (joins existing unit) | 274.0 → 274.0 | 5.66 | 5.66 | whole |  |
| AT42-06 | NCEI | planned | MGDS:5174 | development (ruling H1) | 90.0 → 90.0 | 1.93 | 1.93 | whole |  |
| EX0909 | NCEI | planned | MGDS:24002 | development (ruling H1) | 368.0 → 368.0 | 5.14 | 5.14 | whole | ISO path 404; recovered via https://data.ngdc.noaa.gov/platforms/ocean/ships/oke |
| EX1202L2 | nan | no_data_dir | MGDS:20815 | development (ruling H1) | nan → nan | nan | nan | nan | ISO path 404; no usable version dir (tried 5 ship variants) |
| EX1202L3 | nan | no_data_dir | MGDS:31321 | development (ruling H1) | nan → nan | nan | nan | nan | ISO path 404; no usable version dir (tried 5 ship variants) |
| EX1206 | NCEI | planned | MGDS:31831 | development (ruling H1) | 614.0 → 614.0 | 15.45 | 15.45 | subset (nav ∩ footprint buffered 4.0 km) | ISO path 404; recovered via https://data.ngdc.noaa.gov/platforms/ocean/ships/oke |
| EX1402L2 | NCEI | planned | MGDS:31073 | development (ruling H1) | 311.0 → 311.0 | 10.16 | 10.16 | subset (nav ∩ footprint buffered 4.0 km) | ISO path 404; recovered via https://data.ngdc.noaa.gov/platforms/ocean/ships/oke |
| FK151121 | NCEI | planned | MGDS:22383 | development | 274.0 → 274.0 | 7.37 | 7.37 | whole |  |
| FK171110 | NCEI | planned | MGDS:24424 | development (joins existing unit) | 324.0 → 50.0 | 21.52 | 3.0 | subset (nav ∩ footprint buffered 4.0 km) |  |
| KM0923 | NCEI | planned | MGDS:31429 | development (joins existing unit) | 229.0 → 229.0 | 0.78 | 0.78 | whole |  |
| KN182L03 | NCEI | planned | MGDS:30193 | confirmatory | 28.0 → 28.0 | 1.18 | 1.18 | whole |  |
| NA080 | nan | already_on_oak | MGDS:31289 | nan | nan → nan | nan | 0.0 | nan | nan |
| NR07-1 | NCEI | planned | MGDS:31813;MGDS:31814 | development (ruling H1) | 58.0 → 58.0 | 0.9 | 0.9 | whole |  |
| RC2511 | NCEI | planned | MGDS:32239 | confirmatory | 107.0 → 107.0 | 0.05 | 0.05 | whole |  |
| RP15DI86 | nan | needs_format_review | MGDS:30368 | development | nan → nan | nan | nan | nan | no recognised swath files; exts {'gps': 2, 'inf': 2} |
| SUM1004 | NCEI | planned | MGDS:33090 | confirmatory | 222.0 → 222.0 | 4.68 | 4.68 | whole |  |
| TN399 | nan | already_on_oak | MGDS:33068 | nan | nan → nan | nan | 0.0 | nan | nan |
| lostcity2005 | NCEI | planned | MGDS:21847 | development (ruling H1) | 758.0 → 758.0 | 2.41 | 2.41 | whole | ISO path 404; recovered via https://data.ngdc.noaa.gov/platforms/ocean/ships/ron |
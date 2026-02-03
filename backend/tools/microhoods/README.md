# Sprint 1 – Monitoring des Quartiers microhoods (official catalog)

This folder contains **one** script:

- `build_monitoring_microhoods.py`

It will:
1) download the official Monitoring des Quartiers polygons from the Brussels Mobility WFS,
2) write `monitoring_quartiers_full.geojson` and `monitoring_quartiers_missing_11.geojson`,
3) update `brussels.json` so **every one of 19 communes** has **8–12 microhoods** selected coverage-first.

## Run (Windows / PowerShell) from backend/

Activate your tagging venv (the one with requests installed), then:

```powershell
python .\tools\microhoods\build_monitoring_microhoods.py `
  --pack .\city_packs\brussels.json `
  --out-pack .\city_packs\brussels.json `
  --out-full-geojson .\city_packs\monitoring_quartiers_full.geojson `
  --out-missing-geojson .\city_packs\monitoring_quartiers_missing_11.geojson `
  --current-partial-geojson .\city_packs\monitoring_quartiers.geojson `
  --n-min 8 --n-max 12 --page-size 500 --timeout 60
```

After that, re-run your tagging script (microhood metrics/tags) as usual:
- it should now find microhoods for all communes because the full monitoring file is present.

# City Pack Tagging Pipeline (OSM-driven)

This folder contains a reusable pipeline to compute *objective* commune metrics
(cafes/bars/restaurants/schools/childcare, green share, metro/tram/train stop density) and then
assign tags using **percentiles inside each city**.

## Metrics (per commune)
- cafes_density = cafes_count / area_km2  
- bars_density = bars_count / area_km2  
- restaurants_density = restaurants_count / area_km2  
- parks_share = parks_area_km2 / area_km2  
- metro_density = metro_stops / area_km2  
- tram_density = tram_stops / area_km2  
- train_density = train_stations / area_km2  
- schools_density = schools_count / area_km2  
- childcare_density = childcare_count / area_km2  

## Tag rules (per city)
- cafes_brunch: top 30% by cafes_density  
- nightlife: top 20% by bars_density  
- restaurants: top 30% by restaurants_density  
- green_parks: top 30% by parks_share  
- metro_strong: top 30% by metro_density (or none if city has no metro)  
- tram_strong: top 30% by tram_density  

## Confidence
- high: commune is in top 15% for the metric  
- medium: commune is in top 30% for the metric  
- otherwise: tag not assigned by the automatic pipeline  

**Important:** This pipeline recomputes only these 6 “data-driven tags”.
Other tags (premium_feel, mixed_vibes, night_caution, etc.) are meant to stay curated/manual.

## Install
Create a virtualenv, then:

pip install -r tagging_requirements.txt

## Run (example)
python compute_metrics_and_tags.py --city-pack ../city_packs/brussels.json --country Belgium --out ../city_packs/brussels.json

It will also write a `*_metrics.csv` next to the output for inspection.

## Notes on data source
Uses OpenStreetMap via OSMnx (Overpass + Nominatim). Results depend on OSM coverage.

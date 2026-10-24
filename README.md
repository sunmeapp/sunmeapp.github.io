# sunme

A live map of sun and shade. Pick a time in 30-minute steps (or leave it on Live) and see which streets, patios and parks are in the sun. Cafés and parks in sunshine get a little sun icon.

## How it works

- **Sun position** is computed in the browser for the map's location and its local time zone.
- **Shade** is cast from buildings (and trees where data exists) onto the ground, also computed in the browser, only when you stop moving the map or change the time.
- **Everywhere:** basemap, buildings with heights, cafés, bars and parks come from [OpenFreeMap](https://openfreemap.org) vector tiles (OpenStreetMap data). Building heights in OpenStreetMap are partly estimated, so shade is approximate in places.
- **Toronto (detail layer):** building heights from the City of Toronto 3D Massing model (lidar-derived) and about 56,000 surveyed trees with heights, plus wooded areas. Deciduous tree shade follows the season.

No accounts, keys, trackers or servers: it is a static site, free to host and light on energy.


## Accuracy and cross-checks

Each spot's details end with a **Sources** list and an agreement rating (high, medium or low) so you can see what the answer rests on.

| What | Everywhere | City layers (capitals) | Toronto (detail layer) |
|---|---|---|---|
| Sun position | Calculated for the place, date and local time | same | same |
| Buildings | Overture Maps (OpenStreetMap, Microsoft, Google footprints) with recorded heights or floor counts where known; OpenStreetMap as fallback | Overture Maps | City of Toronto 3D Massing (lidar-derived); 80% match NRCan federal lidar within 3 m, median difference 0.3 m |
| Trees | Mapped woods | Every tree crown found in the Meta/WRI canopy height model, kept off Overture building footprints; Ottawa checked against NRCan lidar | 56,424 City-surveyed trees, height = median of City survey, NRCan lidar and Meta/WRI canopy model (48,366 confirmed by all three); crowns measured from lidar; 12,582 unrecorded trees added where lidar and the canopy model agree |
| Seating | OpenStreetMap `outdoor_seating` / `leisure=outdoor_seating`, checked when you open a spot | same | City of Toronto CaféTO licensed patios (sidewalk, curb-lane, private), matched to places by licence name |
| Weather | Open-Meteo hourly cloud cover and UV | same | same |

**How good are the canopy-model trees?** Tested in central Toronto against NRCan lidar: 97.9% of the model's trees stand where lidar shows something at least 3 m tall, and the model reads about 1.4 m shorter than lidar on City-surveyed trees (75% within 3 m). In Ottawa, where the lidar is used as a second opinion, 14% of model trees were dropped as false and the rest take the lidar height.

City layers cover roughly 8–10 km across the centre of: Ottawa, Washington, London, Paris, Berlin, Madrid, Rome, Amsterdam, Tokyo, Canberra, Mexico City, Lisbon, Dublin, Copenhagen, Stockholm, Oslo, Vienna, Brussels, Seoul and Buenos Aires.

### Adding a city (free)

1. Add a line to `tools/cities.csv` (slug, name, centre, half-width in km; optional lidar COG template).
2. In GitHub, open **Actions → Build city layers → Run workflow** and type the slug (or `all`). GitHub's runners are free for public repos; the job builds `cities/<slug>.json`, updates `cities/index.json` and commits. The app picks the city up on the next visit.

Or locally: `pip install numpy scipy rasterio pyproj shapely duckdb` then `python tools/build_city.py <slug>`.

The Toronto layer is rebuilt with `tools/build_data.py` then `tools/build_corroborate.py`.

## Data and licences

- Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL), tiles by [OpenFreeMap](https://openfreemap.org) and [© OpenMapTiles](https://www.openmaptiles.org/).
- Toronto: City of Toronto Open Data — 3D Massing, Topographic Mapping (trees and treed areas), Street Tree Data, CaféTO locations — Open Government Licence – Toronto.
- Lidar: Natural Resources Canada HRDEM mosaic (DSM and DTM, 1 m) — Open Government Licence – Canada.
- Canopy height: Meta and World Resources Institute, [Canopy Height Maps v2](https://registry.opendata.aws/dataforgood-fb-forests/) (CC BY 4.0).
- Buildings worldwide: [Overture Maps](https://overturemaps.org/) (ODbL / CDLA Permissive).
- UV index forecast: [Open-Meteo](https://open-meteo.com/) (CC BY 4.0; free for non-commercial use), fetched only when you open a spot.
- Place search: [Nominatim](https://nominatim.org/) (OpenStreetMap), sent only when you press Enter.
- Libraries: [MapLibre GL JS](https://maplibre.org/) (BSD-3), [tz-lookup](https://github.com/darkskyapp/tz-lookup) (CC0).

## Files

- `index.html` — the whole app.
- `toronto.json` — Toronto detail layer (buildings, trees, woods), loaded only when you're in central Toronto.
- `cities/index.json` and `cities/<slug>.json` — city tree layers (2–6 MB each, about a third of that over the wire), loaded only when you're in that city.

## Limits

Shade comes from buildings and trees only; terrain and awnings are not modelled. Places inside buildings are checked just outside their nearest open wall, as a stand-in for a patio or doorway.

The canopy model does not know species, so outside Toronto every tree is treated as one that drops its leaves; evergreens will look too sunny in winter. Where Overture has few recorded heights (central Tokyo, for example, about one building in six) most buildings are given a default height, so building shade there is rough.

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

| What | Everywhere | Toronto (detail layer) |
|---|---|---|
| Sun position | Calculated for the place, date and local time | same |
| Buildings | Overture Maps (OpenStreetMap, Microsoft, Google footprints) with recorded heights or floor counts where known; OpenStreetMap as fallback | City of Toronto 3D Massing (lidar-derived); 80% match NRCan federal lidar within 3 m, median difference 0.3 m |
| Trees | Mapped woods | 56,424 City-surveyed trees, height = median of City survey, NRCan lidar and Meta/WRI canopy model (48,366 confirmed by all three); crowns measured from lidar; 12,582 unrecorded trees added where lidar and the canopy model agree |
| Seating | OpenStreetMap `outdoor_seating` / `leisure=outdoor_seating`, checked when you open a spot | City of Toronto CaféTO licensed patios (sidewalk, curb-lane, private), matched to places by licence name |
| Weather | Open-Meteo hourly cloud cover and UV | same |

The Toronto layer is rebuilt with `tools/build_data.py` then `tools/build_corroborate.py`.

## Data and licences

- Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL), tiles by [OpenFreeMap](https://openfreemap.org) and [© OpenMapTiles](https://www.openmaptiles.org/).
- Toronto: City of Toronto Open Data — 3D Massing, Topographic Mapping (trees and treed areas), Street Tree Data, CaféTO locations — Open Government Licence – Toronto.
- Lidar: Natural Resources Canada HRDEM mosaic (DSM and DTM, 1 m) — Open Government Licence – Canada.
- Canopy height: Meta and World Resources Institute, Canopy Height Maps v2.
- Buildings worldwide: [Overture Maps](https://overturemaps.org/) (ODbL / CDLA Permissive).
- UV index forecast: [Open-Meteo](https://open-meteo.com/) (CC BY 4.0; free for non-commercial use), fetched only when you open a spot.
- Place search: [Nominatim](https://nominatim.org/) (OpenStreetMap), sent only when you press Enter.
- Libraries: [MapLibre GL JS](https://maplibre.org/) (BSD-3), [tz-lookup](https://github.com/darkskyapp/tz-lookup) (CC0).

## Files

- `index.html` — the whole app.
- `toronto.json` — Toronto detail layer (buildings, trees, woods), loaded only when you're in central Toronto.

## Limits

Shade comes from buildings and trees only; terrain and awnings are not modelled. Places inside buildings are checked just outside their nearest open wall, as a stand-in for a patio or doorway.

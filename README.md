# sunme

A live map of sun and shade. Pick a time in 30-minute steps (or leave it on Live) and see which streets, patios and parks are in the sun. Cafés and parks in sunshine get a little sun icon.

## How it works

- **Sun position** is computed in the browser for the map's location and its local time zone.
- **Shade** is cast from buildings (and trees where data exists) onto the ground, also computed in the browser, only when you stop moving the map or change the time.
- **Everywhere:** basemap, buildings with heights, cafés, bars and parks come from [OpenFreeMap](https://openfreemap.org) vector tiles (OpenStreetMap data). Building heights in OpenStreetMap are partly estimated, so shade is approximate in places.
- **Toronto (detail layer):** building heights from the City of Toronto 3D Massing model (lidar-derived) and about 56,000 surveyed trees with heights, plus wooded areas. Deciduous tree shade follows the season.

No accounts, keys, trackers or servers: it is a static site, free to host and light on energy.

## Data and licences

- Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL), tiles by [OpenFreeMap](https://openfreemap.org) and [© OpenMapTiles](https://www.openmaptiles.org/).
- Toronto: City of Toronto Open Data — 3D Massing, Topographic Mapping (trees and treed areas), Street Tree Data — under the Open Government Licence – Toronto.
- Place search: [Nominatim](https://nominatim.org/) (OpenStreetMap), sent only when you press Enter.
- Libraries: [MapLibre GL JS](https://maplibre.org/) (BSD-3), [tz-lookup](https://github.com/darkskyapp/tz-lookup) (CC0).

## Files

- `index.html` — the whole app.
- `toronto.json` — Toronto detail layer (buildings, trees, woods), loaded only when you're in central Toronto.

## Limits

Shade comes from buildings and trees only; terrain and awnings are not modelled. Places inside buildings are checked just outside their nearest open wall, as a stand-in for a patio or doorway.

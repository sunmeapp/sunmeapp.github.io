"""Build compact map data for sunme (central Toronto).

Inputs (in raw/): City of Toronto 3D Massing 2025 shapefile, Overture Maps
parquet extracts (place, water, land_use, segment).
Output: data/toronto.json — local metric coordinates in 0.5 m units,
origin at LON0/LAT0, x east, y north.
"""
import json, math
import duckdb, shapefile
from shapely import wkt as W
from shapely.geometry import Polygon, box, Point, LineString
from shapely.strtree import STRtree
from shapely.ops import unary_union

W_, S_, E_, N_ = -79.445, 43.625, -79.355, 43.685
LON0, LAT0 = -79.400, 43.655
phi = math.radians(LAT0)
MLAT = 111132.92 - 559.82 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi)
MLON = 111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi)
U = 2.0  # units per metre

def ll2m(lon, lat):
    return ((lon - LON0) * MLON, (lat - LAT0) * MLAT)

def merc2ll(x, y):
    R = 6378137.0
    return (math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2))

def enc_ring(coords, closed=True):
    pts = list(coords)
    if closed and len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    out, px, py = [], 0, 0
    for i, (x, y) in enumerate(pts):
        ix, iy = round(x * U), round(y * U)
        if i == 0:
            out += [ix, iy]
        else:
            if ix == px and iy == py:
                continue
            out += [ix - px, iy - py]
        px, py = ix, iy
    return out

def to_local(geom):
    from shapely.ops import transform
    return transform(lambda x, y, z=None: ll2m(x, y), geom)

BB = to_local(box(W_, S_, E_, N_))

# ---------- buildings ----------
r = shapefile.Reader('raw/3DMassingShapefile_2025_WGS84')
blds, bpolys, bh = [], [], []
for sr in r.iterShapeRecords():
    rec = sr.record
    lo, la = rec['LONGITUDE'], rec['LATITUDE']
    if not (W_ - 0.002 <= lo <= E_ + 0.002 and S_ - 0.002 <= la <= N_ + 0.002):
        continue
    mx, av = rec['MAX_HEIGHT'] or 0, rec['AVG_HEIGHT'] or 0
    h = (mx + av) / 2 if mx > 0 and av > 0 else max(mx, av)
    if h < 2:
        continue
    shp = sr.shape
    parts = list(shp.parts) + [len(shp.points)]
    for a, b in zip(parts[:-1], parts[1:]):
        ring = [ll2m(*merc2ll(x, y)) for x, y in shp.points[a:b]]
        if len(ring) < 4:
            continue
        p = Polygon(ring)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty:
            continue
        geoms = [p] if p.geom_type == 'Polygon' else [g for g in p.geoms if g.geom_type == 'Polygon']
        for g in geoms:
            # skip interior holes when g is the outer ring of a courtyard building: keep exterior only
            g = Polygon(g.exterior).simplify(0.45, preserve_topology=True)
            if g.is_empty or g.area < 6:
                continue
            ext = g.exterior
            if not ext.is_ccw:
                g = Polygon(list(ext.coords)[::-1])
            bpolys.append(g)
            bh.append(h)
            blds.append([round(h * 10)] + enc_ring(g.exterior.coords))
print('buildings', len(blds), 'coords', sum(len(b) - 1 for b in blds) // 2)
btree = STRtree(bpolys)

def q(sql):
    return duckdb.sql(sql).fetchall()

# ---------- water ----------
water = []
for cls, w in q("select class, wkt from 'raw/water.parquet' where wkt like 'POLYGON%' or wkt like 'MULTIPOLYGON%'"):
    g = to_local(W.loads(w)).intersection(BB.buffer(300)).simplify(1.0)
    for p in ([g] if g.geom_type == 'Polygon' else getattr(g, 'geoms', [])):
        if p.geom_type != 'Polygon' or p.area < 40:
            continue
        rings = [enc_ring(p.exterior.coords)] + [enc_ring(i.coords) for i in p.interiors if Polygon(i).area > 400]
        water.append(rings)
print('water', len(water))

# ---------- green ----------
GREEN = ('park', 'grass', 'garden', 'pitch', 'playground', 'dog_park', 'recreation_ground', 'meadow', 'village_green', 'flowerbed', 'cemetery')
green, parks = [], []
for cls, name, w in q(f"select class, name, wkt from 'raw/land_use.parquet' where class in {GREEN}"):
    g = to_local(W.loads(w)).intersection(BB.buffer(200)).simplify(0.8)
    polys = [g] if g.geom_type == 'Polygon' else [p for p in getattr(g, 'geoms', []) if p.geom_type == 'Polygon']
    for p in polys:
        if p.area < 30:
            continue
        green.append([enc_ring(p.exterior.coords)] + [enc_ring(i.coords) for i in p.interiors if Polygon(i).area > 60])
    if cls in ('park', 'dog_park', 'recreation_ground') and name and g.area > 2500:
        parks.append((name, g))
print('green', len(green), 'named parks', len(parks))

# ---------- roads ----------
RCLS = {'motorway': 0, 'trunk': 0, 'primary': 1, 'secondary': 2, 'tertiary': 3, 'residential': 4,
        'living_street': 4, 'unclassified': 4, 'service': 5, 'pedestrian': 6, 'footway': 7, 'cycleway': 7, 'path': 7}
roads, rnames, roadlines, named_lines = [], {}, [], []
for cls, name, w in q("select class, name, wkt from 'raw/segment.parquet'"):
    if cls not in RCLS:
        continue
    g = to_local(W.loads(w)).intersection(BB.buffer(100))
    lines = [g] if g.geom_type == 'LineString' else [l for l in getattr(g, 'geoms', []) if l.geom_type == 'LineString']
    for l in lines:
        l = l.simplify(0.7)
        if l.length < 3:
            continue
        c = RCLS[cls]
        ni = -1
        if name and c <= 4:
            if name not in rnames:
                rnames[name] = len(rnames)
            ni = rnames[name]
        roads.append([c, ni] + enc_ring(l.coords, closed=False))
        if c <= 4:
            roadlines.append(l)
        if ni >= 0:
            named_lines.append((ni, l))
print('roads', len(roads))
rtree = STRtree(roadlines)


# ---------- trees ----------
import csv, re
CONIFER = ('picea', 'pinus', 'abies', 'thuja', 'juniperus', 'tsuga', 'taxus', 'pseudotsuga', 'larix', 'chamaecyparis', 'metasequoia')
st_pts, st_con = [], []
csv.field_size_limit(10**8)
with open('raw/trees.csv', newline='') as f:
    for row in csv.DictReader(f):
        m = re.search(r'\[\[?\s*(-?[\d.]+),\s*(-?[\d.]+)', row['geometry'] or '')
        if not m: continue
        lo, la = float(m.group(1)), float(m.group(2))
        if not (W_ <= lo <= E_ and S_ <= la <= N_): continue
        x, y = ll2m(lo, la)
        st_pts.append(Point(x, y))
        st_con.append((row['BOTANICAL_NAME'] or '').lower().startswith(CONIFER))
st_tree = STRtree(st_pts)
print('street trees', len(st_pts), 'conifers', sum(st_con))

# treed areas (woodland canopy) as low prisms
canopy, cpolys = [], []
r2 = shapefile.Reader('raw/ta/TOPO_TREED_AREA_WGS84')
for sr in r2.iterShapeRecords():
    bb = sr.shape.bbox
    if bb[2] < W_ or bb[0] > E_ or bb[3] < S_ or bb[1] > N_: continue
    from shapely.geometry import shape as _shape
    g = to_local(_shape(sr.shape.__geo_interface__)).buffer(0).intersection(BB.buffer(100))
    polys = [g] if g.geom_type == 'Polygon' else [p for p in getattr(g, 'geoms', []) if p.geom_type == 'Polygon']
    for p in polys:
        p = Polygon(p.exterior).simplify(1.0, preserve_topology=True)
        if p.is_empty or p.area < 30: continue
        if not p.exterior.is_ccw: p = Polygon(list(p.exterior.coords)[::-1])
        cpolys.append(p)
        canopy.append(enc_ring(p.exterior.coords))
ctree = STRtree(cpolys) if cpolys else None
print('canopy polygons', len(canopy))

trees = []
r3 = shapefile.Reader('raw/tp/TOPO_TREE_WGS84')
for sr in r3.iterShapeRecords():
    lo, la = sr.shape.points[0]
    if not (W_ <= lo <= E_ and S_ <= la <= N_): continue
    h = sr.record['DERIVED_HE'] or 0
    if h < 3: continue
    x, y = ll2m(lo, la)
    pt = Point(x, y)
    if ctree is not None and any(cpolys[i].contains(pt) for i in ctree.query(pt)): continue
    if any(bpolys[i].contains(pt) for i in btree.query(pt)): continue
    con = 0
    j = st_tree.nearest(pt)
    if j is not None and st_pts[j].distance(pt) < 3.0 and st_con[j]: con = 1
    trees.append((round(y * U), round(x * U), min(round(h * 10), 600), con))
trees.sort()
tflat, px, py = [], 0, 0
for yy, xx, hh, cc in trees:
    tflat += [xx - px, yy - py, hh, cc]; px, py = xx, yy
print('trees', len(trees), 'conifer', sum(t[3] for t in trees))

# ---------- named street intersections ----------
ntree = STRtree([l for _, l in named_lines])
pairs = {}
for i, (na, la) in enumerate(named_lines):
    for j in ntree.query(la):
        if j <= i: continue
        nb, lb = named_lines[j]
        if nb == na: continue
        g = la.intersection(lb)
        pts = [g] if g.geom_type == 'Point' else [p for p in getattr(g, 'geoms', []) if p.geom_type == 'Point']
        key = (min(na, nb), max(na, nb))
        for p in pts:
            lst = pairs.setdefault(key, [])
            if not any(math.hypot(p.x - a, p.y - b) < 60 for a, b in lst):
                lst.append((p.x, p.y))
xings = []
for (a, b), lst in pairs.items():
    for x, y in lst:
        xings += [a, b, round(x * U), round(y * U)]
print('intersections', len(xings) // 4)

# ---------- places ----------
CAT = {
    'coffee_shop': 'c', 'cafe': 'c', 'tea_room': 'c', 'bakery': 'c', 'juice_bar': 'c', 'ice_cream_shop': 'c', 'dessert_shop': 'c',
    'bar': 'b', 'pub': 'b', 'brewery': 'b', 'wine_bar': 'b', 'cocktail_bar': 'b', 'beer_bar': 'b', 'beer_garden': 'b',
    'restaurant': 'r', 'casual_eatery': 'r',
}
seen = set()
places = []
rows = q("""select name, cat, tax, wkt, confidence from 'raw/place.parquet'
 where name is not null and coalesce(operating_status,'open')='open' and confidence>=0.55""")
moved = 0
for name, cat, tax, w, conf in rows:
    k = CAT.get(cat) or CAT.get(tax)
    if not k:
        continue
    p = to_local(W.loads(w))
    if not BB.contains(p):
        continue
    key = (name.lower(), round(p.x / 15), round(p.y / 15))
    if key in seen:
        continue
    seen.add(key)
    # if inside a building, walk toward the nearest street until outside (frontage / patio side)
    inside = [i for i in btree.query(p) if bpolys[i].contains(p)]
    if inside:
        ri = rtree.nearest(p)
        tgt = roadlines[ri].interpolate(roadlines[ri].project(p))
        dx, dy = tgt.x - p.x, tgt.y - p.y
        d = math.hypot(dx, dy) or 1
        ux, uy = dx / d, dy / d
        q2 = p
        for s in range(1, 61):
            q2 = Point(p.x + ux * s, p.y + uy * s)
            if not any(bpolys[i].contains(q2) for i in btree.query(q2)):
                q2 = Point(q2.x + ux * 1.5, q2.y + uy * 1.5)
                break
        p = q2
        moved += 1
    places.append([name, k, round(p.x * U), round(p.y * U)])
print('places', len(places), 'moved to frontage', moved)

# parks as places with sample points
for name, g in parks:
    c = g.representative_point()
    minx, miny, maxx, maxy = g.bounds
    step = max(12.0, math.sqrt(g.area / 40))
    samp = []
    y = miny + step / 2
    while y < maxy:
        x = minx + step / 2
        while x < maxx:
            pt = Point(x, y)
            if g.contains(pt) and not any(bpolys[i].contains(pt) for i in btree.query(pt)):
                samp += [round(x * U), round(y * U)]
            x += step
        y += step
    if len(samp) < 4:
        continue
    places.append([name, 'p', round(c.x * U), round(c.y * U), samp[:120]])
print('with parks', len(places))

minx, miny, maxx, maxy = BB.bounds
data = {
    'v': 1, 'origin': [LON0, LAT0], 'unit': U, 'bounds': [round(minx * U), round(miny * U), round(maxx * U), round(maxy * U)],
    'b': blds, 'w': water, 'g': green, 'r': roads, 'rn': sorted(rnames, key=rnames.get), 'p': places,
    't': tflat, 'ca': canopy, 'x': xings,
}
import os
os.makedirs('data', exist_ok=True)
s = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
open('data/toronto.json', 'w').write(s)
print('size MB', round(len(s) / 1e6, 2))

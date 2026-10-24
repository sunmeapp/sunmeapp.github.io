"""Build a sunme city detail layer: trees from Meta/WRI Canopy Height Maps v2, kept off building roofs
using Overture Maps footprints. Output: cities/<slug>.json and an updated cities/index.json.

    python tools/build_city.py london paris        # build listed cities
    python tools/build_city.py --all               # build every city in cities.csv

Free to run anywhere with internet (e.g. GitHub Actions). Data: Meta/WRI CHM v2 (public S3),
Overture Maps buildings (public S3). Tree records: [dx, dy, height dm, crown radius dm, flags=8 (model)].
"""
import csv, json, math, os, sys, time
import numpy as np, rasterio, duckdb
from rasterio.windows import from_bounds
from rasterio.features import rasterize
from pyproj import Transformer
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely import wkb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'cities')
CHM = 'https://dataforgood-fb-data.s3.amazonaws.com/forests/v2/global/dinov3_global_chm_v2_ml3/chm/{qk}.tif'
OVERTURE = 's3://overturemaps-us-west-2/release/{rel}/theme=buildings/type=building/*'
U = 2              # units per metre
RES = 2.4          # working grid, metres (half of the model's native 1.2 m)
T3857 = Transformer.from_crs(4326, 3857, always_xy=True)
INV = Transformer.from_crs(3857, 4326, always_xy=True)

def quadkeys(w, s, e, n, z=10):
    def tile(lon, lat):
        x = (lon + 180) / 360; sn = math.sin(math.radians(lat)); y = 0.5 - math.log((1 + sn) / (1 - sn)) / (4 * math.pi)
        return int(x * 2 ** z), int(y * 2 ** z)
    x0, y1 = tile(w, s); x1, y0 = tile(e, n); out = []
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            q = ''
            for i in range(z, 0, -1):
                m = 1 << (i - 1); q += str((1 if tx & m else 0) + (2 if ty & m else 0))
            out.append(q)
    return out

def lidar_heights(tpl, lon, lat):
    """Tallest lidar surface (DSM - DTM) within about 3 m of each point, or NaN. tpl has {} for dsm/dtm."""
    if not tpl: return None
    with rasterio.open('/vsicurl/' + tpl.format('dsm')) as s0:
        crs = s0.crs
    T = Transformer.from_crs(4326, crs, always_xy=True)
    X, Y = T.transform(lon, lat)
    b = (X.min() - 10, Y.min() - 10, X.max() + 10, Y.max() + 10); arrs = {}
    for k in ('dsm', 'dtm'):
        with rasterio.open('/vsicurl/' + tpl.format(k)) as s:
            w = from_bounds(*b, s.transform); h, wd = max(1, int(w.height / 2)), max(1, int(w.width / 2))
            arrs[k] = s.read(1, window=w, out_shape=(h, wd), boundless=True, fill_value=s.nodata).astype('float32')
            tf = s.window_transform(w) * rasterio.Affine.scale(w.width / wd, w.height / h); nod = s.nodata
    bad = (arrs['dsm'] == nod) | (arrs['dtm'] == nod) | (arrs['dsm'] < -1000)
    nd = ndimage.maximum_filter(np.where(bad, np.nan, arrs['dsm'] - arrs['dtm']), size=3)
    c, r = (~tf) * (X, Y); c = np.floor(c).astype(int); r = np.floor(r).astype(int)
    ok = (r >= 0) & (c >= 0) & (r < nd.shape[0]) & (c < nd.shape[1])
    out = np.full(len(lon), np.nan); out[ok] = nd[r[ok], c[ok]]
    return out

def latest_release(con):
    rels = con.sql("SELECT DISTINCT split_part(file, '/', 5) AS r FROM glob('s3://overturemaps-us-west-2/release/*/theme=buildings/type=building/*') ORDER BY r DESC LIMIT 1").fetchall()
    return rels[0][0]

def build(city):
    slug, name, lat, lon, half = city['slug'], city['name'], float(city['lat']), float(city['lon']), float(city.get('half_km') or 4.5)
    dlat = half / 111.0; dlon = half / (111.0 * math.cos(math.radians(lat)))
    w, s, e, n = lon - dlon, lat - dlat, lon + dlon, lat + dlat
    t0 = time.time()
    # grid in web mercator covering the bbox
    xs, ys = T3857.transform([w, e], [s, n])
    gx0, gx1, gy0, gy1 = min(xs), max(xs), min(ys), max(ys)
    nx, ny = int((gx1 - gx0) / RES), int((gy1 - gy0) / RES)
    tf = rasterio.Affine(RES, 0, gx0, 0, -RES, gy1)
    chm = np.zeros((ny, nx), 'float32'); have = False
    for qk in quadkeys(w, s, e, n):
        try:
            with rasterio.open('/vsicurl/' + CHM.format(qk=qk)) as src:
                b = src.bounds
                ix0, iy0, ix1, iy1 = max(gx0, b.left), max(gy0, b.bottom), min(gx1, b.right), min(gy1, b.top)
                if ix0 >= ix1 or iy0 >= iy1: continue
                win = from_bounds(ix0, iy0, ix1, iy1, src.transform).round_offsets().round_lengths()
                c0, r0 = int((ix0 - gx0) / RES), int((gy1 - iy1) / RES)
                cw, rh = min(nx - c0, int((ix1 - ix0) / RES)), min(ny - r0, int((iy1 - iy0) / RES))
                if cw <= 0 or rh <= 0: continue
                a = src.read(1, window=win, out_shape=(rh, cw), resampling=rasterio.enums.Resampling.nearest).astype('float32')
                chm[r0:r0 + rh, c0:c0 + cw] = np.maximum(chm[r0:r0 + rh, c0:c0 + cw], a); have = True
        except rasterio.errors.RasterioIOError:
            continue
    if not have:
        print(slug, 'no canopy data'); return None
    # building footprints (Overture) -> mask so trees never sit on roofs
    con = duckdb.connect(); con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; CREATE SECRET (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2');")
    rel = city.get('_rel') or latest_release(con)
    rows = con.sql(f"""SELECT ST_AsWKB(geometry) FROM read_parquet('{OVERTURE.format(rel=rel)}', hive_partitioning=1)
                       WHERE bbox.xmin < {e} AND bbox.xmax > {w} AND bbox.ymin < {n} AND bbox.ymax > {s}""").fetchall()
    shapes = []
    for (g,) in rows:
        geom = wkb.loads(bytes(g))
        for poly in (geom.geoms if geom.geom_type == 'MultiPolygon' else [geom]):
            if poly.geom_type != 'Polygon': continue
            x, y = T3857.transform(*poly.exterior.xy)
            shapes.append(({'type': 'Polygon', 'coordinates': [list(zip(x, y))]}, 1))
    bmask = rasterize(shapes, out_shape=chm.shape, transform=tf, fill=0, dtype='uint8') > 0 if shapes else np.zeros(chm.shape, bool)
    bmask = ndimage.binary_dilation(bmask, iterations=1)
    can = np.where(bmask, 0, chm)
    # tree tops: local maxima >= 4 m, at least ~5 m apart
    peaks = (can == ndimage.maximum_filter(can, size=5)) & (can >= 4) & (can <= 60)
    pr, pc = np.nonzero(peaks)
    hs = can[pr, pc]
    order = np.argsort(-hs); pr, pc, hs = pr[order], pc[order], hs[order]
    px, py = tf * (pc + 0.5, pr + 0.5)
    kd = cKDTree(np.c_[px, py]); taken = np.zeros(len(px), bool); keep = []
    for i in range(len(px)):
        if taken[i]: continue
        keep.append(i); taken[kd.query_ball_point([px[i], py[i]], 5.0)] = True
    keep = np.array(keep, int)
    # crown radius from the connected canopy above 45% of the tree's height
    radii = np.zeros(len(keep))
    for j, i in enumerate(keep):
        r, c, h = pr[i], pc[i], hs[i]
        if 5 <= r < can.shape[0] - 5 and 5 <= c < can.shape[1] - 5:
            win = can[r - 5:r + 6, c - 5:c + 6]
            lab, _ = ndimage.label(win > max(2.0, 0.45 * h)); l = lab[5, 5]
            area = (lab == l).sum() * RES * RES if l else 0
            radii[j] = math.sqrt(area / math.pi) if area else 0
    lon_, lat_ = INV.transform(px[keep], py[keep])
    hs_k = hs[keep].astype('float64'); flags = np.full(len(keep), 8)
    lid = lidar_heights(city.get('lidar') or '', np.asarray(lon_), np.asarray(lat_))
    if lid is not None:
        # second opinion from free airborne lidar: drop model trees with nothing tall there, use the lidar height
        has = ~np.isnan(lid)
        drop = has & (lid < 2.5)
        use = has & (lid >= 2.5) & (lid <= 60)
        print(f'  lidar: {has.sum()} checked, {drop.sum()} dropped, median model-lidar {np.median(hs_k[use] - lid[use]):.2f} m')
        hs_k = np.where(use, lid, hs_k); flags = np.where(use, 12, flags)
        keepm = ~drop; keep, radii, hs_k, flags = keep[keepm], radii[keepm], hs_k[keepm], flags[keepm]
        lon_, lat_ = np.asarray(lon_)[keepm], np.asarray(lat_)[keepm]
    phi = math.radians(lat)
    mlat = 111132.92 - 559.82 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi)
    mlon = 111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi)
    lx = (np.asarray(lon_) - lon) * mlon; ly = (np.asarray(lat_) - lat) * mlat
    recs = []
    for j in range(len(keep)):
        h = float(hs_k[j]); r = radii[j]
        r = r if 1.2 <= r <= 11 else max(1.5, min(9, 0.9 + 0.27 * h))
        recs.append((round(ly[j] * U), round(lx[j] * U), min(600, round(h * 10)), round(r * 10), int(flags[j])))
    recs.sort()
    flat, ax, ay = [], 0, 0
    for yy, xx, hh, rr, ff in recs:
        flat += [xx - ax, yy - ay, hh, rr, ff]; ax, ay = xx, yy
    out = {'v': 1, 'slug': slug, 'name': name, 'origin': [round(lon, 6), round(lat, 6)], 'unit': U, 'bbox': [round(w, 5), round(s, 5), round(e, 5), round(n, 5)],
           't': flat, 'meta': {'trees': len(recs), 'source': 'Meta/WRI Canopy Height Maps v2', 'lidar': city.get('lidar_name') or None, 'lidar_trees': int((flags & 4 > 0).sum()), 'buildings_mask': f'Overture Maps {rel}', 'built': time.strftime('%Y-%m-%d')}}
    os.makedirs(OUT, exist_ok=True)
    s_ = json.dumps(out, separators=(',', ':'))
    open(os.path.join(OUT, slug + '.json'), 'w').write(s_)
    print(f'{slug}: {len(recs)} trees, {len(shapes)} buildings masked, {len(s_) / 1e6:.2f} MB, {time.time() - t0:.0f}s')
    return {'slug': slug, 'name': name, 'bbox': out['bbox'], 'trees': len(recs), 'lidar': out['meta']['lidar'], 'built': out['meta']['built'], 'release': rel}

def main():
    cities = list(csv.DictReader(open(os.path.join(HERE, 'cities.csv'))))
    want = cities if '--all' in sys.argv else [c for c in cities if c['slug'] in sys.argv[1:]]
    idx_path = os.path.join(OUT, 'index.json')
    index = {c['slug']: c for c in json.load(open(idx_path))['cities']} if os.path.exists(idx_path) else {}
    con = duckdb.connect(); con.sql("INSTALL httpfs; LOAD httpfs; CREATE SECRET (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2');")
    rel = latest_release(con)
    for c in want:
        c['_rel'] = rel
        r = build(c)
        if r: index[r['slug']] = r
        os.makedirs(OUT, exist_ok=True)
        json.dump({'cities': sorted(index.values(), key=lambda x: x['slug'])}, open(idx_path, 'w'), separators=(',', ':'))

if __name__ == '__main__':
    main()

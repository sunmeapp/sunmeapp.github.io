"""Cross-check and enrich sunme's Toronto layer with independent sources.

Inputs
  data/toronto.json         City 3D massing buildings, City tree points, treed areas (from build_data.py)
  HRDEM 1 m lidar (NRCan)   DSM - DTM = height of everything above ground (Open Government Licence - Canada)
  Meta/WRI CHM v2           AI canopy height model, 1.2 m (licence permits commercial use)
  CaféTO (City of Toronto)  licensed sidewalk / curb-lane / private patios

Output
  ../sunme-global/toronto.json
    b   buildings (unchanged; heights corroborated against lidar, stats in meta)
    t   trees: [dx, dy, height dm, crown radius dm, flags]  flags: 1 conifer, 2 city survey, 4 lidar, 8 meta model
    ca  wooded areas
    pt  patios: [x, y, kind, name, address]   kind: s sidewalk, c curb lane, p private patio
    meta  source notes and agreement statistics
"""
import json, math, collections
import numpy as np, rasterio, requests
from rasterio.windows import from_bounds
from rasterio.features import rasterize
from pyproj import Transformer
from scipy import ndimage
from scipy.spatial import cKDTree

D = json.load(open('data/toronto.json'))
U = D['unit']; LON0, LAT0 = D['origin']
phi = math.radians(LAT0)
MLAT = 111132.92 - 559.82 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi)
MLON = 111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi)
W_, S_, E_, N_ = -79.445, 43.625, -79.355, 43.685
to_ll = lambda x, y: (LON0 + np.asarray(x) / MLON, LAT0 + np.asarray(y) / MLAT)
ll_to_local = lambda lon, lat: ((np.asarray(lon) - LON0) * MLON, (np.asarray(lat) - LAT0) * MLAT)
T3979 = Transformer.from_crs(4326, 3979, always_xy=True)
T3857 = Transformer.from_crs(4326, 3857, always_xy=True)

def decode(arr, start):
    n = (len(arr) - start) // 2; xs = np.cumsum(arr[start::2][:n]) / U; ys = np.cumsum(arr[start + 1::2][:n]) / U
    return xs, ys

# ---------------- rasters on a 2 m grid ----------------
def read(url, crs_t, res_scale, pad=60):
    xs, ys = crs_t.transform([W_, E_, W_, E_], [S_, S_, N_, N_])
    with rasterio.open('/vsicurl/' + url) as s:
        win = from_bounds(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad, s.transform).round_offsets().round_lengths()
        shape = (int(win.height / res_scale), int(win.width / res_scale))
        a = s.read(1, window=win, out_shape=shape, resampling=rasterio.enums.Resampling.nearest)
        t = s.window_transform(win) * rasterio.Affine.scale(win.width / shape[1], win.height / shape[0])
        return a, t, s.nodata

print('reading lidar…')
DSM, tf, nod = read('https://canelevation-dem.s3.ca-central-1.amazonaws.com/hrdem-mosaic-1m/8_2-mosaic-1m-dsm.tif', T3979, 2)
DTM, tf2, _ = read('https://canelevation-dem.s3.ca-central-1.amazonaws.com/hrdem-mosaic-1m/8_2-mosaic-1m-dtm.tif', T3979, 2)
valid = (DSM != nod) & (DTM != nod) & (DSM > -100) & (DTM > -100)
NDSM = np.where(valid, np.clip(DSM - DTM, 0, 400), np.nan).astype('float32')
print('lidar grid', NDSM.shape, 'valid %.1f%%' % (100 * valid.mean()))
print('reading canopy model…')
CHM, tfm, _ = read('https://dataforgood-fb-data.s3.amazonaws.com/forests/v2/global/dinov3_global_chm_v2_ml3/chm/0302231312.tif', T3857, 2)
CHM = CHM.astype('float32')

def rc(transform, X, Y):
    inv = ~transform
    c, r = inv * (np.asarray(X), np.asarray(Y))
    return np.floor(r).astype(int), np.floor(c).astype(int)

# ---------------- buildings vs lidar ----------------
print('buildings…')
blds = []
for a in D['b']:
    xs, ys = decode(a, 1)
    lon, lat = to_ll(xs, ys); px, py = T3979.transform(lon, lat)
    blds.append((a[0] / 10, list(zip(px, py))))
labels = rasterize(((({'type': 'Polygon', 'coordinates': [ring + [ring[0]]]}), i + 1) for i, (_, ring) in enumerate(blds)), out_shape=NDSM.shape, transform=tf, fill=0, dtype='int32')
BMASK = labels > 0
lab = labels.ravel(); v = NDSM.ravel(); ok = (lab > 0) & ~np.isnan(v)
order = np.argsort(lab[ok], kind='stable'); L = lab[ok][order]; V = v[ok][order]
starts = np.searchsorted(L, np.arange(1, len(blds) + 1)); ends = np.searchsorted(L, np.arange(1, len(blds) + 1), side='right')
checked = agree = 0; diffs = []
for i, (h, _) in enumerate(blds):
    seg = V[starts[i]:ends[i]]
    if len(seg) < 6: continue
    lh = float(np.percentile(seg, 75))  # roof level, robust to edges
    checked += 1; d = h - lh; diffs.append(d)
    if abs(d) <= max(3.0, 0.15 * h): agree += 1
print('buildings checked', checked, 'agree', agree, '%.1f%%' % (100 * agree / max(1, checked)), 'median diff %.2f m' % float(np.median(diffs)))

# ---------------- trees: city + lidar + canopy model ----------------
print('trees…')
tx, ty, th, tcon = [], [], [], []
x = y = 0
for i in range(0, len(D['t']), 4):
    x += D['t'][i]; y += D['t'][i + 1]
    tx.append(x / U); ty.append(y / U); th.append(D['t'][i + 2] / 10); tcon.append(D['t'][i + 3])
tx, ty, th = np.array(tx), np.array(ty), np.array(th)
CAN = np.where(BMASK | np.isnan(NDSM), 0, NDSM)  # vegetation-ish heights: lidar off buildings
CANF = ndimage.maximum_filter(CAN, size=3)           # max within ~3 m
CHMF = ndimage.maximum_filter(CHM, size=3)

def sample(arr, transform, crs_t, X, Y):
    lon, lat = to_ll(X, Y); px, py = crs_t.transform(lon, lat)
    r, c = rc(transform, px, py)
    inside = (r >= 0) & (c >= 0) & (r < arr.shape[0]) & (c < arr.shape[1])
    out = np.full(len(X), np.nan, 'float32'); out[inside] = arr[r[inside], c[inside]]
    return out

lid = sample(CANF, tf, T3979, tx, ty); met = sample(CHMF, tfm, T3857, tx, ty)
def crown(X, Y, H):
    lon, lat = to_ll(X, Y); px, py = T3979.transform(lon, lat); r0, c0 = rc(tf, px, py)
    out = np.zeros(len(X))
    for k in range(len(X)):
        r, c, h = r0[k], c0[k], H[k]
        if not (5 <= r < CAN.shape[0] - 5 and 5 <= c < CAN.shape[1] - 5) or h <= 0: out[k] = 0; continue
        win = CAN[r - 5:r + 6, c - 5:c + 6]
        lab_, n = ndimage.label(win > max(2.0, 0.45 * h))
        l = lab_[5, 5]
        area = (lab_ == l).sum() * 4.0 if l else 0
        out[k] = math.sqrt(area / math.pi) if area else 0
    return out

final_h, flags = [], []
for k in range(len(tx)):
    vals = [th[k]]; f = 2 | (1 if tcon[k] else 0)
    if lid[k] == lid[k] and lid[k] >= 2.5: vals.append(float(lid[k])); f |= 4
    if met[k] == met[k] and met[k] >= 2.5: vals.append(float(met[k])); f |= 8
    final_h.append(float(np.median(vals))); flags.append(f)
final_h = np.array(final_h)
cr = crown(tx, ty, final_h)
three = sum(1 for f in flags if f & 12 == 12)
print('city trees', len(tx), 'with lidar', sum(1 for f in flags if f & 4), 'with model', sum(1 for f in flags if f & 8), 'all three', three)

# new trees seen by lidar AND the canopy model but missing from the city survey (private yards, parks)
print('finding unrecorded trees…')
ca_polys = [decode(a, 0) for a in D['ca']]
ca_mask = np.zeros(CAN.shape, bool)
if ca_polys:
    shapes = []
    for xs, ys in ca_polys:
        lon, lat = to_ll(xs, ys); px, py = T3979.transform(lon, lat); ring = list(zip(px, py))
        shapes.append(({'type': 'Polygon', 'coordinates': [ring + [ring[0]]]}, 1))
    ca_mask = rasterize(shapes, out_shape=CAN.shape, transform=tf, fill=0, dtype='uint8') > 0
peaks = (CAN == ndimage.maximum_filter(CAN, size=5)) & (CAN >= 4) & (CAN <= 45) & ~ndimage.binary_dilation(BMASK, iterations=1) & ~ca_mask
pr, pc = np.nonzero(peaks)
pxs, pys = tf * (pc + 0.5, pr + 0.5)
inv3979 = Transformer.from_crs(3979, 4326, always_xy=True)
plon, plat = inv3979.transform(pxs, pys)
PX, PY = ll_to_local(plon, plat)
inb = (plon > W_) & (plon < E_) & (plat > S_) & (plat < N_)
PX, PY, ph = PX[inb], PY[inb], CAN[pr[inb], pc[inb]]
pm = sample(CHMF, tfm, T3857, PX, PY)
keep = pm >= 3
PX, PY, ph, pm = PX[keep], PY[keep], ph[keep], pm[keep]
tree_kd = cKDTree(np.c_[tx, ty])
d, _ = tree_kd.query(np.c_[PX, PY], k=1)
far = d > 6
PX, PY, ph, pm = PX[far], PY[far], ph[far], pm[far]
# thin peaks closer than 5 m to each other
kd = cKDTree(np.c_[PX, PY]); taken = np.zeros(len(PX), bool); order = np.argsort(-ph); sel = []
for i in order:
    if taken[i]: continue
    sel.append(i); taken[kd.query_ball_point([PX[i], PY[i]], 5)] = True
sel = np.array(sel, int)
nx, ny, nh = PX[sel], PY[sel], (ph[sel] + pm[sel]) / 2
ncr = crown(nx, ny, nh)
print('added trees seen by lidar and model', len(sel))

def crown_or_default(r, h):
    return r if 1.2 <= r <= 11 else max(1.5, min(9, 0.9 + 0.27 * h))
allx = np.r_[tx, nx]; ally = np.r_[ty, ny]; allh = np.r_[final_h, nh]; allr = np.r_[cr, ncr]
allf = flags + [4 | 8] * len(sel)
recs = sorted(((round(ally[k] * U), round(allx[k] * U), min(600, round(allh[k] * 10)), round(crown_or_default(allr[k], allh[k]) * 10), allf[k]) for k in range(len(allx)) if allh[k] >= 2.5))
tflat, px_, py_ = [], 0, 0
for yy, xx, hh, rr, ff in recs:
    tflat += [xx - px_, yy - py_, hh, rr, ff]; px_, py_ = xx, yy

# ---------------- CaféTO patios ----------------
print('patios…')
pk = requests.get('https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show?id=cafeto-curb-lane-parklet-cafe-locations').json()['result']
url = [r for r in pk['resources'] if r['name'].endswith('4326.geojson')][0]['url']
gj = requests.get(url).json()
KIND = {'SIDEWALK CAFE': 's', 'CURB LANE CAFE': 'c', 'PRIVATE PROPERTY PATIO': 'p'}
pt = []; kinds = collections.Counter()
for f in gj['features']:
    p = f['properties']; coords = f['geometry']['coordinates']
    lon, lat = (coords[0] if f['geometry']['type'] == 'MultiPoint' else coords)[:2]
    if not (W_ < lon < E_ and S_ < lat < N_): continue
    x, y = ll_to_local(lon, lat)
    it = (p.get('INTERVENTION_TYPE') or '').lower(); kinds[p.get('INTERVENTION_TYPE')] += 1
    k = 'c' if 'curb' in it or 'parklet' in it else 'p' if 'private' in it or 'patio' in it else 's'
    name = (p.get('OPERATOR_NAME') or '').strip()
    if name.upper() == 'PUBLIC PARKLET': k = 'c'
    pt.append([round(float(x) * U), round(float(y) * U), k, name.title(), (p.get('MUNICIPAL_ADDRESS') or p.get('BUSINESS_ADDRESS') or '').title()])
print('patios in area', len(pt), dict(kinds))

out = {
    'v': 2, 'origin': D['origin'], 'unit': U, 'bounds': D['bounds'], 'b': D['b'], 't': tflat, 'ca': D['ca'], 'pt': pt,
    'meta': {
        'buildings': {'source': 'City of Toronto 3D Massing 2025', 'checked': checked, 'agree_pct': round(100 * agree / max(1, checked), 1), 'median_diff_m': round(float(np.median(diffs)), 2), 'against': 'NRCan HRDEM 1 m lidar (DSM - DTM)'},
        'trees': {'city': int(len(tx)), 'with_lidar': int(sum(1 for f in flags if f & 4)), 'with_model': int(sum(1 for f in flags if f & 8)), 'all_three': int(three), 'added': int(len(sel)), 'height_rule': 'median of available sources'},
        'patios': {'source': 'City of Toronto CaféTO', 'count': len(pt)},
    },
}
s = json.dumps(out, separators=(',', ':'), ensure_ascii=False)
open('../sunme-global/toronto.json', 'w').write(s)
print('wrote', round(len(s) / 1e6, 2), 'MB'); print(json.dumps(out['meta'], indent=1))

"""The model + geospatial core: load the Random Forest and the training/sector
data at import, engineer the 17 features, run the three-rule risk classifier, and
provide both the live Earth Engine path and the nearest-sample fallback.

Loading happens once at import (gunicorn runs with --preload), exactly as it did
at the top of app_cadastral.py.
"""

from __future__ import annotations

import json
import os
import pickle

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .config import (BASE_END, BASE_START, CLEARED_NDVI, EE_PROJECT, FEATURE_COLS,
                     MODEL_PATH, NOW_END, NOW_START, SECTORS_GEOJSON, TRAINING_CSV)

# ── Load the trained model ──
print("[boot] loading trained Random Forest model rf_D_national.pkl …")
_MODEL = pickle.load(open(MODEL_PATH, "rb"))
print(f"[boot]   model has {_MODEL.n_features_in_} features, classes={list(_MODEL.classes_)}")

# ── Load training data with geometry (nearest-sample fallback + neighbourhood) ──
print("[boot] loading training data with geometry …")
_train_raw = pd.read_csv(TRAINING_CSV)
_geos = _train_raw['.geo'].apply(lambda s: json.loads(s)['coordinates'])
_train_raw['lng'] = _geos.apply(lambda c: c[0])
_train_raw['lat'] = _geos.apply(lambda c: c[1])
# Build a KD-tree on (lat,lng) for fast nearest-neighbour lookup. Spherical
# distance approximation is fine inside one country; pyproj projection would
# be more accurate but slower for per-request use.
_TREE = cKDTree(_train_raw[['lat', 'lng']].values)
print(f"[boot]   training set: {len(_train_raw):,} pixels, classes={_train_raw['label'].value_counts().to_dict()}")
print(f"[boot]   CLEARED_NDVI reference = {CLEARED_NDVI:.2f} (literature default)")

# ── Load the 416 sector polygons for click-to-analyse ──
print("[boot] loading 416 sector polygons for click-to-analyse …")
_SECTORS = gpd.read_file(SECTORS_GEOJSON)
# Compute centroids in a projected CRS (UTM-35S, EPSG:32735) so they're spatially
# correct, then project back to WGS-84 for storage.
_centroids_wgs = _SECTORS.geometry.to_crs(32735).centroid.to_crs(4326)
_SECTORS["centroid_lat"] = _centroids_wgs.y
_SECTORS["centroid_lng"] = _centroids_wgs.x
print(f"[boot]   {len(_SECTORS)} sectors loaded with centroids")

# ── Earth Engine live-mode state ──
_EE_READY = False
_EE_IMG   = None     # cached 17-band feature image
_EE_TRIED = False    # only attempt init once unless it succeeds


def find_nearest_pixels(lat: float, lng: float, k: int = 25):
    """K-nearest training pixels + the distance to the closest one (in km).
    The distance is the confidence signal: small = in-domain, large =
    out-of-distribution (the model's prediction is less trustworthy)."""
    distances, idx = _TREE.query([lat, lng], k=k)
    deg_to_km = 111.0
    nearest_km = float(distances[0] * deg_to_km) if hasattr(distances, "__iter__") else float(distances * deg_to_km)
    return _train_raw.iloc[idx], nearest_km


def _ee_build_feature_image(ee):
    """Build the same 17-band feature image as 02b_GEE_Export_Sectors_Current.js."""
    rwanda = (ee.FeatureCollection("FAO/GAUL/2015/level1")
              .filter(ee.Filter.eq("ADM0_NAME", "Rwanda")).geometry())
    cs = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")

    def mask_s2(col):
        return col.linkCollection(cs, ["cs_cdf"]).map(
            lambda img: img.updateMask(img.select("cs_cdf").gte(0.60)).divide(10000))

    s2_base = mask_s2(ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                      .filterBounds(rwanda).filterDate(BASE_START, BASE_END)).median()
    s2_now  = mask_s2(ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                      .filterBounds(rwanda).filterDate(NOW_START, NOW_END)).median()

    ndvi_train  = s2_base.normalizedDifference(["B8", "B4"]).rename("NDVI_train")
    ndvi_test   = s2_now.normalizedDifference(["B8", "B4"]).rename("NDVI_test")
    ndvi_change = ndvi_test.subtract(ndvi_train).rename("NDVI_change")
    evi_train = s2_base.expression(
        "2.5 * (NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1)",
        {"NIR": s2_base.select("B8"), "RED": s2_base.select("B4"),
         "BLUE": s2_base.select("B2")}).rename("EVI_train")
    swir_train = s2_base.select("B11").rename("SWIR_train")
    swir_test  = s2_now.select("B11").rename("SWIR_test")
    nbr_train  = s2_base.normalizedDifference(["B8", "B12"]).rename("NBR_train")

    def s1(start, end):
        return (ee.ImageCollection("COPERNICUS/S1_GRD")
                .filterBounds(rwanda).filterDate(start, end)
                .filter(ee.Filter.eq("instrumentMode", "IW"))
                .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
                .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
                .select(["VV", "VH"]).median())
    s1_base, s1_now = s1(BASE_START, BASE_END), s1(NOW_START, NOW_END)
    ratio = s1_base.select("VH").divide(s1_base.select("VV")).rename("VH_VV_ratio")

    srtm = ee.Image("USGS/SRTMGL1_003")
    elevation = srtm.select("elevation")
    slope  = ee.Terrain.slope(srtm).rename("slope")
    aspect = ee.Terrain.aspect(srtm).rename("aspect")

    return ee.Image.cat([
        ndvi_train, ndvi_test, ndvi_change, evi_train, swir_train, swir_test,
        nbr_train, s2_base.select("B4").rename("RED_train"),
        s2_base.select("B8").rename("NIR_train"),
        s1_base.select("VH").rename("VH_train"), s1_base.select("VV").rename("VV_train"),
        s1_now.select("VH").rename("VH_test"), s1_now.select("VV").rename("VV_test"),
        ratio, elevation, slope, aspect,
    ]).float().clip(rwanda)


def ensure_ee() -> bool:
    """Lazy-init Earth Engine once. Returns True if live mode is usable."""
    global _EE_READY, _EE_IMG, _EE_TRIED
    if _EE_READY:
        return True
    if _EE_TRIED:
        return False
    _EE_TRIED = True
    try:
        import ee
        sa_key = os.environ.get("EE_SERVICE_ACCOUNT_JSON")
        if sa_key:   # production: service-account JSON in an env var
            info = json.loads(sa_key)
            creds = ee.ServiceAccountCredentials(info["client_email"], key_data=sa_key)
            ee.Initialize(creds, project=EE_PROJECT)
        else:        # local: cached `earthengine authenticate` credentials
            ee.Initialize(project=EE_PROJECT)
        _EE_IMG = _ee_build_feature_image(ee)
        _EE_READY = True
        print("[boot] Earth Engine LIVE parcel mode ready")
        return True
    except Exception as e:
        print(f"[warn] Earth Engine unavailable — using nearest-sample fallback ({e})")
        return False


def _subrisks(prob, tree_cover_pct, deforested_pct_500m):
    """Two presentation-level sub-risks shown side by side in the citizen UI.
    They do NOT change the combined risk_level — they just make transparent
    whether a HIGH is driven by the parcel itself or by the surrounding area."""
    if prob > 0.65 or tree_cover_pct < 30:
        parcel = 'HIGH'
    elif 0.35 < prob <= 0.65:
        parcel = 'MEDIUM'
    else:
        parcel = 'LOW'
    if deforested_pct_500m > 50:
        neighbourhood = 'HIGH'
    elif deforested_pct_500m > 25:
        neighbourhood = 'MEDIUM'
    else:
        neighbourhood = 'LOW'
    return parcel, neighbourhood


def classify_and_build(*, prob, ndvi_current, ndvi_2020, ndvi_change,
                       deforested_pct_500m, avg_ndvi_500m, area_ha, lat, lng,
                       confidence, confidence_note, data_source, extra=None):
    """Shared 3-rule classifier + result dict, used by both the live and the
    nearest-sample paths so the risk logic can never diverge between them."""
    tree_cover_pct = max(0.0, min(100.0, ndvi_current * 100.0))
    rule1_high = (prob > 0.65) or (tree_cover_pct < 30)
    rule2_high = (deforested_pct_500m > 50) and (ndvi_current < avg_ndvi_500m * 0.70)
    rule3_med  = (0.35 < prob <= 0.65) and (deforested_pct_500m > 0)
    if rule1_high or rule2_high:
        risk_level = 'HIGH'
        fired_rule = 'Rule 1 (parcel)' if rule1_high else 'Rule 2 (neighbourhood)'
    elif rule3_med:
        risk_level = 'MEDIUM'
        fired_rule = 'Rule 3 (intermediate)'
    else:
        risk_level = 'LOW'
        fired_rule = 'default'
    parcel_risk, neighbourhood_risk = _subrisks(prob, tree_cover_pct, deforested_pct_500m)
    result = {
        'risk_level':           risk_level,
        'rule_fired':           fired_rule,
        'lat':                  round(lat, 6),
        'lng':                  round(lng, 6),
        'deforestation_prob':   round(prob, 3),
        'ndvi_current':         round(ndvi_current, 3),
        'ndvi_2020':            round(ndvi_2020, 3),
        'ndvi_change':          round(ndvi_change, 3),
        'tree_cover_pct':       round(tree_cover_pct, 1),
        'neighbourhood_500m_avg_ndvi':       round(avg_ndvi_500m, 3),
        'neighbourhood_500m_deforested_pct': round(deforested_pct_500m, 1),
        'parcel_risk':          parcel_risk,
        'neighbourhood_risk':   neighbourhood_risk,
        'parcel_area_ha':       area_ha,
        'analysis_id':          abs(hash((round(lat, 5), round(lng, 5)))) % 10_000_000,
        'confidence':           confidence,
        'confidence_note':      confidence_note,
        'data_source':          data_source,
    }
    if extra:
        result.update(extra)
    return result


def analyse_parcel_live(lat: float, lng: float, area_ha: float = None) -> dict:
    """Live analysis: pull CURRENT Sentinel/SRTM features for the exact parcel
    from Earth Engine and run the model. Raises on any failure so the caller can
    fall back to the nearest-sample path."""
    import ee
    pt  = ee.Geometry.Point([lng, lat])
    buf = pt.buffer(500)   # 500 m neighbourhood, same radius as the proxy path
    fc  = _EE_IMG.sample(region=buf, scale=30, numPixels=60, geometries=False)
    rows = [f["properties"] for f in fc.getInfo()["features"]]
    if not rows:
        raise RuntimeError("no Sentinel pixels returned for this parcel")

    df = pd.DataFrame(rows)
    missing = [c for c in FEATURE_COLS if c not in df.columns]
    if missing:
        raise RuntimeError(f"missing features {missing}")
    df[FEATURE_COLS] = df[FEATURE_COLS].replace(-9999, np.nan)
    df = df.dropna(subset=FEATURE_COLS, thresh=len(FEATURE_COLS) - 3)
    if df.empty:
        raise RuntimeError("all sampled pixels were cloud/no-data")
    df[FEATURE_COLS] = df[FEATURE_COLS].fillna(df[FEATURE_COLS].median())

    feats = df[FEATURE_COLS].median().values.reshape(1, -1)
    prob  = float(_MODEL.predict_proba(feats)[0][1])
    ndvi_current   = float(df['NDVI_test'].median())
    ndvi_2020      = float(df['NDVI_train'].median())
    ndvi_change    = float(df['NDVI_change'].median())
    pix_probs = _MODEL.predict_proba(df[FEATURE_COLS].values)[:, 1]
    deforested_pct_500m = float((pix_probs >= 0.5).mean() * 100)
    avg_ndvi_500m       = float(df['NDVI_test'].mean())

    return classify_and_build(
        prob=prob, ndvi_current=ndvi_current, ndvi_2020=ndvi_2020,
        ndvi_change=ndvi_change, deforested_pct_500m=deforested_pct_500m,
        avg_ndvi_500m=avg_ndvi_500m, area_ha=area_ha, lat=lat, lng=lng,
        confidence='HIGH',
        confidence_note=('Live Sentinel-2/1 + SRTM imagery for this parcel '
                         f'({NOW_START[:4]}–{NOW_END[:4]} vs 2020 baseline)'),
        data_source='live_gee',
        extra={'n_live_pixels': int(len(df))},
    )


def analyse_parcel(lat: float, lng: float, area_ha: float = None) -> dict:
    """Nearest-sample analysis: median features of the 25 nearest training pixels.

    Returns a `confidence` field based on distance from the nearest training pixel:
        ≤ 5 km   → HIGH   (close to a national training sample)
        ≤ 50 km  → MEDIUM (near a sample)
        > 50 km  → LOW    (sparse sampling here — surface result only)
    """
    nbrs, nearest_km = find_nearest_pixels(lat, lng, k=25)
    feats = nbrs[FEATURE_COLS].median().values.reshape(1, -1)
    prob = float(_MODEL.predict_proba(feats)[0][1])

    ndvi_current = float(nbrs['NDVI_test'].median())
    ndvi_train_avg = float(nbrs['NDVI_train'].median())
    ndvi_change = float(nbrs['NDVI_change'].median())

    # 500-metre neighbourhood: K-nearest as a spatial proxy
    deforested_pct_500m = float(nbrs['label'].mean() * 100)
    avg_ndvi_500m = float(nbrs['NDVI_test'].mean())

    if nearest_km <= 5:
        confidence = 'HIGH'
        confidence_note = 'Close to a national training sample'
    elif nearest_km <= 50:
        confidence = 'MEDIUM'
        confidence_note = f'Near a training sample ({nearest_km:.0f} km away)'
    else:
        confidence = 'LOW'
        confidence_note = (f'Sparse sampling here ({nearest_km:.0f} km from nearest '
                           f'sample) — production deployment should query GEE live')

    return classify_and_build(
        prob=prob, ndvi_current=ndvi_current, ndvi_2020=ndvi_train_avg,
        ndvi_change=ndvi_change, deforested_pct_500m=deforested_pct_500m,
        avg_ndvi_500m=avg_ndvi_500m, area_ha=area_ha, lat=lat, lng=lng,
        confidence=confidence, confidence_note=confidence_note,
        data_source='nearest_sample',
        extra={'km_from_training': round(nearest_km, 1)},
    )


def sector_for_point(lat, lng):
    """Resolve (lat,lng) → the sector polygon that contains it, or None."""
    try:
        from shapely.geometry import Point
        mask = _SECTORS.geometry.contains(Point(float(lng), float(lat)))
        hit = _SECTORS[mask]
        if hit.empty:
            return None
        s = hit.iloc[0]
        return {"sector_id": str(s["sector_id"]), "sector": str(s["sector"]),
                "district": str(s["district"]), "province": str(s["province"])}
    except Exception as e:
        print(f"[warn] sector lookup failed for {lat},{lng}: {e}")
        return None

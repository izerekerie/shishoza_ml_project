// ============================================================
// FILE: 02b_GEE_Export_Sectors_Current.js
// PURPOSE: Export CURRENT (2026) satellite features for forest
//          pixels across all of Rwanda, so the sector-risk map
//          reflects what the land looks like NOW — not the 2024
//          imagery frozen inside the training CSV.
//
// HOW THIS DIFFERS FROM 01_GEE_Export_National.js:
//   - That script exports a BALANCED training sample (defor/stable)
//     with Hansen LABELS, recent window = 2023-2024.
//   - THIS script exports UNLABELLED forest pixels with recent
//     window = 2025-01-01 .. 2026-06-30 (current). No labels: we are
//     SCORING with the trained model, not training a new one.
//   - The 17 feature bands + their names are IDENTICAL, so the model
//     (rf_D_national.pkl) and the precompute script read them unchanged.
//
// IMPORTANT — keep the BASELINE window at 2020-2022:
//   The model learned "change relative to a 2020-2022 baseline"
//   (NDVI_change = recent - baseline, and the *_train bands ARE the
//   baseline). So *_train stays 2020-2022; only the recent (*_test)
//   window slides forward to today. That is what makes the result
//   "deforestation since 2020, measured with 2026 imagery".
//
// HOW TO USE:
//   1. code.earthengine.google.com  →  paste  →  RUN
//   2. Open Tasks (top right)  →  RUN  TreeSight_Sector_Features_Current
//   3. Download from Drive: TreeSight_Rwanda/sector_features_current.csv
//   4. Put it in data/raw/  and run:
//        .venv/bin/python scripts/precompute_sector_current.py
// ============================================================

// ── STUDY AREA: all of Rwanda, split into its 5 provinces ───
var provinces = ee.FeatureCollection('FAO/GAUL/2015/level1')
  .filter(ee.Filter.eq('ADM0_NAME', 'Rwanda'));
var rwanda = provinces.geometry();
var N_PROV = provinces.size().getInfo();
Map.centerObject(rwanda, 8);
print('Provinces:', provinces.aggregate_array('ADM1_NAME'));

// ── DATE RANGES ─────────────────────────────────────────────
var BASE_START = '2020-01-01';   // baseline — MUST match model training
var BASE_END   = '2022-12-31';
var NOW_START  = '2025-01-01';   // CURRENT window (slides forward to today)
var NOW_END    = '2026-06-30';

// ── SENTINEL-2 OPTICAL (Cloud Score+ masking) ───────────────
var CLEAR_THRESHOLD = 0.60;
var csPlus = ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED');
function maskS2(collection) {
  return collection.linkCollection(csPlus, ['cs_cdf']).map(function(img) {
    return img.updateMask(img.select('cs_cdf').gte(CLEAR_THRESHOLD)).divide(10000);
  });
}
var s2_base = maskS2(ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(rwanda).filterDate(BASE_START, BASE_END)).median().clip(rwanda);
var s2_now  = maskS2(ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(rwanda).filterDate(NOW_START, NOW_END)).median().clip(rwanda);

// ── VEGETATION INDICES (same names the model expects) ───────
var ndvi_train  = s2_base.normalizedDifference(['B8','B4']).rename('NDVI_train');
var ndvi_test   = s2_now .normalizedDifference(['B8','B4']).rename('NDVI_test');
var ndvi_change = ndvi_test.subtract(ndvi_train).rename('NDVI_change');
var evi_train = s2_base.expression(
  '2.5 * (NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1)',
  {NIR:s2_base.select('B8'), RED:s2_base.select('B4'), BLUE:s2_base.select('B2')}
).rename('EVI_train');
var swir_train = s2_base.select('B11').rename('SWIR_train');
var swir_test  = s2_now .select('B11').rename('SWIR_test');
var nbr_train  = s2_base.normalizedDifference(['B8','B12']).rename('NBR_train');

// ── SENTINEL-1 RADAR ────────────────────────────────────────
function s1composite(start, end) {
  return ee.ImageCollection('COPERNICUS/S1_GRD')
    .filterBounds(rwanda).filterDate(start, end)
    .filter(ee.Filter.eq('instrumentMode','IW'))
    .filter(ee.Filter.listContains('transmitterReceiverPolarisation','VV'))
    .filter(ee.Filter.listContains('transmitterReceiverPolarisation','VH'))
    .select(['VV','VH']).median().clip(rwanda);
}
var s1_base = s1composite(BASE_START, BASE_END);
var s1_now  = s1composite(NOW_START, NOW_END);
var radar_ratio_train = s1_base.select('VH').divide(s1_base.select('VV')).rename('VH_VV_ratio');

// ── SRTM TERRAIN ────────────────────────────────────────────
var srtm      = ee.Image('USGS/SRTMGL1_003').clip(rwanda);
var elevation = srtm.select('elevation');
var slope     = ee.Terrain.slope(srtm).rename('slope');
var aspect    = ee.Terrain.aspect(srtm).rename('aspect');

// ── FOREST MASK: where it was forest in 2000 (same def as labels) ──
// We score risk on land that was forest at baseline (treecover2000 >= 30).
var hansen = ee.Image('UMD/hansen/global_forest_change_2025_v1_13').clip(rwanda);
var forest_mask = hansen.select('treecover2000').gte(30).selfMask();

// ── 17-FEATURE STACK (identical schema to training, NO label) ──
var features = ee.Image.cat([
  ndvi_train, ndvi_test, ndvi_change,
  evi_train, swir_train, swir_test, nbr_train,
  s2_base.select('B4').rename('RED_train'),
  s2_base.select('B8').rename('NIR_train'),
  s1_base.select('VH').rename('VH_train'),
  s1_base.select('VV').rename('VV_train'),
  s1_now .select('VH').rename('VH_test'),
  s1_now .select('VV').rename('VV_test'),
  radar_ratio_train,
  elevation, slope, aspect
]).float().unmask(-9999);   // precompute script treats -9999 as missing

// ── PER-PROVINCE SAMPLING of forest pixels (for even coverage) ──
var PER_PROVINCE = 18000;   // ~90k pixels nationally → good per-sector coverage
var provList = provinces.toList(N_PROV);
var allPts = ee.FeatureCollection([]);
for (var i = 0; i < N_PROV; i++) {
  var geom = ee.Feature(provList.get(i)).geometry();
  var pts = features.updateMask(forest_mask).sample({
    region: geom, scale: 30, numPixels: PER_PROVINCE,
    seed: 7, geometries: true, tileScale: 16
  });
  allPts = allPts.merge(pts);
}
print('Sampled forest pixels (current features):', allPts.size());

// ── EXPORT ──────────────────────────────────────────────────
Export.table.toDrive({
  collection: allPts,
  description: 'TreeSight_Sector_Features_Current',
  folder: 'TreeSight_Rwanda',
  fileNamePrefix: 'sector_features_current',
  fileFormat: 'CSV'
});
print('==============================================');
print('Queued. Open Tasks (top right) and RUN');
print('  TreeSight_Sector_Features_Current.');
print('Then: data/raw/sector_features_current.csv  →');
print('  .venv/bin/python scripts/precompute_sector_current.py');
print('==============================================');

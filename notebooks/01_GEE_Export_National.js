// ============================================================
// FILE: 01_GEE_Export_National.js
// PURPOSE: Export NATIONAL training data for all of Rwanda,
//          stratified by PROVINCE (5 ecological zones) so the
//          model learns variety, not just the Nyungwe pattern.
//
// WHY PROVINCE (not sector, not district):
//   The model cares about ECOLOGY, not admin borders. Rwanda's
//   5 provinces map closely to its 5 landscape types (western
//   montane, volcanic north, central plateau, eastern savanna,
//   Kigali urban). Sampling per province guarantees each zone is
//   represented while keeping the export to 5 reliable tasks.
//   (Per-sector = 416 tiny exports, most with zero deforestation.
//    Per-sector belongs AFTER training, when you SCORE each sector.)
//
// HOW TO USE:
//   1. Go to code.earthengine.google.com
//   2. Paste this entire script, press RUN
//   3. Read the per-province counts printed in the Console
//   4. Open Tasks panel (top right) — click RUN on the CSV task
//   5. Download from Google Drive: TreeSight_Rwanda/training_data_national.csv
//   6. Put it in data/raw/  and retrain (notebook 03)
//
// TARGET: ~3,000 deforested + ~3,000 stable per province
//         => up to ~30,000 balanced pixels nationally (3x current).
//         Provinces with little forest loss will return fewer
//         deforested points — that is REAL and expected, not a bug.
// ============================================================

// ── STUDY AREA: all of Rwanda, split into its 5 provinces ───
var provinces = ee.FeatureCollection('FAO/GAUL/2015/level1')
  .filter(ee.Filter.eq('ADM0_NAME', 'Rwanda'));

var rwanda = provinces.geometry();          // dissolved national boundary
var N_PROV = provinces.size().getInfo();    // = 5 (client-side, fine in editor)

Map.centerObject(rwanda, 8);
Map.addLayer(rwanda, {color: 'red'}, 'Rwanda');
print('Provinces found:', provinces.aggregate_array('ADM1_NAME'));
print('Province count:', N_PROV);

// ── DATE RANGES ─────────────────────────────────────────────
var TRAIN_START = '2020-01-01';
var TRAIN_END   = '2022-12-31';
var TEST_START  = '2023-01-01';
var TEST_END    = '2024-12-31';

// ── SENTINEL-2: OPTICAL (Cloud Score+ masking) ──────────────
var CLEAR_THRESHOLD = 0.60;
var csPlus = ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED');

function maskS2withCloudScorePlus(collection) {
  return collection
    .linkCollection(csPlus, ['cs_cdf'])
    .map(function(img) {
      return img.updateMask(img.select('cs_cdf').gte(CLEAR_THRESHOLD))
                .divide(10000);
    });
}

var s2_train = maskS2withCloudScorePlus(
  ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(rwanda).filterDate(TRAIN_START, TRAIN_END)
).median().clip(rwanda);

var s2_test = maskS2withCloudScorePlus(
  ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(rwanda).filterDate(TEST_START, TEST_END)
).median().clip(rwanda);

print('Sentinel-2 loaded (national, Cloud Score+ masked)');

// ── VEGETATION INDICES ───────────────────────────────────────
var ndvi_train = s2_train.normalizedDifference(['B8','B4']).rename('NDVI_train');
var ndvi_test  = s2_test.normalizedDifference(['B8','B4']).rename('NDVI_test');
var ndvi_change = ndvi_test.subtract(ndvi_train).rename('NDVI_change');

var evi_train = s2_train.expression(
  '2.5 * (NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1)',
  {NIR:s2_train.select('B8'), RED:s2_train.select('B4'), BLUE:s2_train.select('B2')}
).rename('EVI_train');

var swir_train = s2_train.select('B11').rename('SWIR_train');
var swir_test  = s2_test.select('B11').rename('SWIR_test');
var nbr_train  = s2_train.normalizedDifference(['B8','B12']).rename('NBR_train');

// ── SENTINEL-1: RADAR ────────────────────────────────────────
function s1composite(start, end) {
  return ee.ImageCollection('COPERNICUS/S1_GRD')
    .filterBounds(rwanda).filterDate(start, end)
    .filter(ee.Filter.eq('instrumentMode','IW'))
    .filter(ee.Filter.listContains('transmitterReceiverPolarisation','VV'))
    .filter(ee.Filter.listContains('transmitterReceiverPolarisation','VH'))
    .select(['VV','VH']).median().clip(rwanda);
}
var s1_train = s1composite(TRAIN_START, TRAIN_END);
var s1_test  = s1composite(TEST_START, TEST_END);
var radar_ratio_train = s1_train.select('VH').divide(s1_train.select('VV')).rename('VH_VV_ratio');
print('Sentinel-1 radar loaded (national)');

// ── SRTM: TERRAIN ────────────────────────────────────────────
var srtm      = ee.Image('USGS/SRTMGL1_003').clip(rwanda);
var elevation = srtm.select('elevation');
var slope     = ee.Terrain.slope(srtm).rename('slope');
var aspect    = ee.Terrain.aspect(srtm).rename('aspect');
print('SRTM terrain loaded (national)');

// ── HANSEN GLOBAL FOREST CHANGE: LABELS ──────────────────────
var hansen = ee.Image('UMD/hansen/global_forest_change_2023_v1_11').clip(rwanda);

// Forest loss 2020-2022 = training label (lossyear 20..22)
var loss_train = hansen.select('lossyear').gte(20)
  .and(hansen.select('lossyear').lte(22)).rename('label');
var label_train = loss_train.toByte().rename('label');

// Stable forest = >=30% cover in 2000 AND never lost. unmask(0) so the
// mask doesn't hide stable pixels from the sampler (same fix as before).
var stable_forest = hansen.select('treecover2000').gte(30)
  .and(hansen.select('loss').eq(0)).unmask(0);
print('Hansen labels loaded (national)');

// ── FEATURE STACK (Experiment D — the 17 features the model uses) ──
// Identical schema to the Nyungwe export so notebook 03 + the app
// keep working with no column changes.
var features_D = ee.Image.cat([
  ndvi_train, ndvi_test, ndvi_change,
  evi_train, swir_train, swir_test, nbr_train,
  s2_train.select('B4').rename('RED_train'),
  s2_train.select('B8').rename('NIR_train'),
  s1_train.select('VH').rename('VH_train'),
  s1_train.select('VV').rename('VV_train'),
  s1_test.select('VH').rename('VH_test'),
  s1_test.select('VV').rename('VV_test'),
  radar_ratio_train,
  elevation, slope, aspect,
  label_train
]).float().addBands(label_train, ['label'], true);

var feature_bands = features_D
  .select(features_D.bandNames().remove('label'))
  .unmask(-9999);   // notebook 02 treats -9999 as null and imputes

// Class masks (1 only, rest masked) — sampled separately per province
var deforested_mask = loss_train.eq(1).selfMask();
var stable_mask     = stable_forest.eq(1).selfMask();

// ── PER-PROVINCE STRATIFIED SAMPLING ─────────────────────────
// Target per province; tune these after reading the printed counts.
var PER_CLASS   = 3000;     // pixels per class per province (cap)
var DEFOR_OVERSAMPLE = 600000;  // deforestation is rare → oversample hard
var STABLE_OVERSAMPLE = 20000;  // stable is common → light oversample

var provList = provinces.toList(N_PROV);
var allSamples = ee.FeatureCollection([]);

for (var i = 0; i < N_PROV; i++) {
  var prov  = ee.Feature(provList.get(i));
  var geom  = prov.geometry();
  var pname = prov.get('ADM1_NAME');

  var defor_pts = ee.Image.constant(1).byte().rename('label')
    .updateMask(deforested_mask)
    .sample({region: geom, scale: 30, numPixels: DEFOR_OVERSAMPLE,
             seed: 42, geometries: true, tileScale: 16})
    .limit(PER_CLASS)
    .map(function(f){ return f.set('province', pname); });

  var stable_pts = ee.Image.constant(0).byte().rename('label')
    .updateMask(stable_mask)
    .sample({region: geom, scale: 30, numPixels: STABLE_OVERSAMPLE,
             seed: 43, geometries: true, tileScale: 16})
    .limit(PER_CLASS)
    .map(function(f){ return f.set('province', pname); });

  allSamples = allSamples.merge(defor_pts).merge(stable_pts);
}

// Diagnostics — how many points, and how many DEFORESTED, per province?
// (Low deforested counts in the East/Kigali are expected and honest.)
print('Total sample points:', allSamples.size());
print('Points per province (both classes):', allSamples.aggregate_histogram('province'));
print('DEFORESTED points per province:',
      allSamples.filter(ee.Filter.eq('label', 1)).aggregate_histogram('province'));
print('Class balance overall:', allSamples.aggregate_histogram('label'));

// Attach the 17 features to every sampled point
var training_data = feature_bands.sampleRegions({
  collection: allSamples,
  properties: ['label', 'province'],
  scale: 30, tileScale: 16, geometries: true
});
print('Training rows with features:', training_data.size());

// ── EXPORT: the national training CSV (the file you need) ────
Export.table.toDrive({
  collection: training_data,
  description: 'TreeSight_Training_Data_National',
  folder: 'TreeSight_Rwanda',
  fileNamePrefix: 'training_data_national',
  fileFormat: 'CSV'
});

// ── OPTIONAL national imagery (large; delete tasks if not needed) ──
// Export.image.toDrive({
//   image: s2_train.select(['B4','B3','B2']),
//   description: 'TreeSight_RGB_National', folder: 'TreeSight_Rwanda',
//   fileNamePrefix: 'rwanda_s2_rgb', region: rwanda, scale: 30,
//   crs: 'EPSG:4326', maxPixels: 1e9
// });

print('==============================================');
print('National export queued. Open Tasks (top right) and RUN');
print('  TreeSight_Training_Data_National.');
print('If a province returns < ~1000 deforested points, raise');
print('DEFOR_OVERSAMPLE (e.g. to 1e6) and re-run.');
print('==============================================');

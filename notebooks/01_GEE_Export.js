// ============================================================
// FILE: 01_GEE_Export.js
// PURPOSE: Export satellite training data for Rwanda Nyungwe
// HOW TO USE:
//   1. Go to code.earthengine.google.com
//   2. Paste this entire script
//   3. Press RUN
//   4. Open Tasks panel (top right) — click RUN on each task
//   5. Wait 10-20 minutes
//   6. Download from Google Drive folder: TreeSight_Rwanda
// ============================================================

// ── STUDY AREA: Nyungwe Buffer Zone, Rwanda ─────────────────
// This is the area your model will be trained on
var studyArea = ee.Geometry.Rectangle([
  28.85, -2.95,   // southwest corner (longitude, latitude)
  29.40, -2.40    // northeast corner
]);

// Show on map so you can see what area is being analysed
Map.centerObject(studyArea, 10);
Map.addLayer(studyArea, {color:'red'}, 'Study Area');
print('Study area loaded. You should see a red rectangle on the map.');

// ── DATE RANGES ─────────────────────────────────────────────
var TRAIN_START = '2020-01-01';
var TRAIN_END   = '2022-12-31';
var TEST_START  = '2023-01-01';
var TEST_END    = '2024-12-31';

// ── SENTINEL-2: OPTICAL (10 metre resolution) ────────────────
// Cloud masking via Cloud Score+ (Google's current recommended approach,
// replaces the older QA60-based masking that was over-aggressive in tropical
// rainforest interiors and silently hid stable-forest pixels from sampling).
// Reference: https://medium.com/google-earth/all-clear-with-cloud-score-bd6ee2e2235e
//
// CLEAR_THRESHOLD: 0.60 is the official tutorial recommendation. Lower (0.5)
// keeps more pixels at the cost of more residual cloud. We use cs_cdf because
// it gives more usable pixels in mountainous terrain like Nyungwe.
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

// Training period Sentinel-2 (cloud-masked composite)
var s2_train = maskS2withCloudScorePlus(
  ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(studyArea)
    .filterDate(TRAIN_START, TRAIN_END)
).median().clip(studyArea);

// Test period Sentinel-2 (cloud-masked composite)
var s2_test = maskS2withCloudScorePlus(
  ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(studyArea)
    .filterDate(TEST_START, TEST_END)
).median().clip(studyArea);

print('Sentinel-2 loaded (Cloud Score+ masked)');

// ── VEGETATION INDICES ───────────────────────────────────────
// NDVI: how green/healthy the vegetation is
// High NDVI (0.7-0.9) = forest. Low NDVI (0.1-0.2) = cleared.
var ndvi_train = s2_train.normalizedDifference(['B8','B4']).rename('NDVI_train');
var ndvi_test  = s2_test.normalizedDifference(['B8','B4']).rename('NDVI_test');

// NDVI change: how much vegetation changed between periods
var ndvi_change = ndvi_test.subtract(ndvi_train).rename('NDVI_change');

// EVI: Enhanced Vegetation Index (handles dense canopy better)
var evi_train = s2_train.expression(
  '2.5 * (NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1)',
  {NIR:s2_train.select('B8'), RED:s2_train.select('B4'), BLUE:s2_train.select('B2')}
).rename('EVI_train');

// SWIR: sensitive to moisture and soil - useful for detecting clearing
var swir_train = s2_train.select('B11').rename('SWIR_train');
var swir_test  = s2_test.select('B11').rename('SWIR_test');

// NBR: Normalized Burn Ratio - also sensitive to forest loss
var nbr_train = s2_train.normalizedDifference(['B8','B12']).rename('NBR_train');

// ── SENTINEL-1: RADAR (10 metre, works through clouds) ───────
// VH backscatter: sensitive to vegetation structure
// Trees have high VH. Bare cleared land has low VH.
var s1_train = ee.ImageCollection('COPERNICUS/S1_GRD')
  .filterBounds(studyArea)
  .filterDate(TRAIN_START, TRAIN_END)
  .filter(ee.Filter.eq('instrumentMode','IW'))
  .filter(ee.Filter.listContains('transmitterReceiverPolarisation','VV'))
  .filter(ee.Filter.listContains('transmitterReceiverPolarisation','VH'))
  .select(['VV','VH'])
  .median()
  .clip(studyArea);

var s1_test = ee.ImageCollection('COPERNICUS/S1_GRD')
  .filterBounds(studyArea)
  .filterDate(TEST_START, TEST_END)
  .filter(ee.Filter.eq('instrumentMode','IW'))
  .filter(ee.Filter.listContains('transmitterReceiverPolarisation','VV'))
  .filter(ee.Filter.listContains('transmitterReceiverPolarisation','VH'))
  .select(['VV','VH'])
  .median()
  .clip(studyArea);

// VH/VV ratio: useful feature for separating forest from cleared land
var radar_ratio_train = s1_train.select('VH')
  .divide(s1_train.select('VV')).rename('VH_VV_ratio');

print('Sentinel-1 radar loaded');

// ── SRTM: ELEVATION AND TERRAIN ──────────────────────────────
// Steep slopes = harder to farm = more likely to stay forested
// Gentle slopes = easier to clear for agriculture
var srtm      = ee.Image('USGS/SRTMGL1_003').clip(studyArea);
var elevation = srtm.select('elevation');
var slope     = ee.Terrain.slope(srtm).rename('slope');
var aspect    = ee.Terrain.aspect(srtm).rename('aspect');

print('SRTM terrain loaded');

// ── HANSEN GLOBAL FOREST CHANGE: TRAINING LABELS ─────────────
// This tells the model WHICH pixels actually had forest loss
// It is the "answer key" the model learns from
var hansen = ee.Image('UMD/hansen/global_forest_change_2023_v1_11')
  .clip(studyArea);

// Pixels that lost forest between 2020 and 2022 (training labels)
// lossyear = 20 means year 2020, 22 means 2022
var loss_train = hansen.select('lossyear')
  .gte(20).and(hansen.select('lossyear').lte(22))
  .rename('label');

// stratifiedSample requires the class band to be integer typed
var label_train = loss_train.toByte().rename('label');

// Pixels that lost forest between 2023 and 2024 (test labels)
var loss_test = hansen.select('lossyear')
  .gte(23).and(hansen.select('lossyear').lte(24))
  .rename('label');

// Stable forest = was forest in 2000, no loss ever detected
// .unmask(0) is critical: treecover2000.gte(30) masks (not zeros) pixels with
// less than 30% cover, and that mask propagates through .or() below, hiding
// every stable-forest pixel from stratifiedSample. Forcing unmasked 0/1 fixes
// the bug where the CSV came back with 5000 deforested and 0 stable pixels.
var stable_forest = hansen.select('treecover2000').gte(30)
  .and(hansen.select('loss').eq(0))
  .unmask(0);

print('Hansen labels loaded');
print('Deforestation pixels (training):', loss_train.reduceRegion({
  reducer: ee.Reducer.sum(),
  geometry: studyArea,
  scale: 30,
  maxPixels: 1e9
}));
// Sanity check: how many stable-forest pixels exist in the study area?
// If this is 0 or near 0, our stable_forest definition is wrong.
// If this is millions, the source data is fine and any 0-stable result must
// come from the sampling step.
print('Stable forest pixels (source data):', stable_forest.reduceRegion({
  reducer: ee.Reducer.sum(),
  geometry: studyArea,
  scale: 30,
  maxPixels: 1e9
}));

// ── BUILD FEATURE STACKS ─────────────────────────────────────
// Combine all satellite measurements into one image

// EXPERIMENT A: Sentinel-2 optical only
var features_A = ee.Image.cat([
  ndvi_train, ndvi_test, ndvi_change,
  evi_train, swir_train, swir_test, nbr_train,
  s2_train.select('B4').rename('RED_train'),
  s2_train.select('B3').rename('GREEN_train'),
  s2_train.select('B8').rename('NIR_train'),
  label_train
]).float();

// EXPERIMENT B: Sentinel-2 + terrain
var features_B = ee.Image.cat([
  ndvi_train, ndvi_test, ndvi_change,
  evi_train, swir_train, swir_test, nbr_train,
  elevation, slope, aspect,
  label_train
]).float();

// EXPERIMENT C: Sentinel-2 + Sentinel-1 radar
var features_C = ee.Image.cat([
  ndvi_train, ndvi_test, ndvi_change,
  evi_train, swir_train, swir_test, nbr_train,
  s1_train.select('VH').rename('VH_train'),
  s1_train.select('VV').rename('VV_train'),
  s1_test.select('VH').rename('VH_test'),
  s1_test.select('VV').rename('VV_test'),
  radar_ratio_train,
  label_train
]).float();

// EXPERIMENT D: All three combined (expected best performance)
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
]).float().addBands(label_train, ['label'], true);  // restore integer label after .float()

// ── SAMPLE PIXELS FOR TRAINING ───────────────────────────────
// BULLETPROOF SAMPLING — sample each class independently, then merge.
//
// Earlier attempts all silently produced label=1 only. Root causes ruled out
// step by step: (1) mask propagation through .or() — fixed with .unmask(0);
// (2) cloud-masked footprint excluding stable forest — fixed with Cloud
// Score+; (3) sampleRegions dropping points where feature bands are masked.
// This version eliminates all three at once:
//
//   - sample deforested pixels and stable pixels in SEPARATE image.sample()
//     calls so there's no possibility of one class hiding the other
//   - unmask the feature image with a sentinel value (-9999) before
//     sampleRegions so cloud-masked pixels still produce output rows. The
//     notebook treats -9999 as null and imputes via median.
//
// Diagnostic prints below report each step's count so future failures are
// visible in the GEE console instead of silent.

// Image of just the deforested-pixel mask (1 where deforested 2020-22)
var deforested_mask = loss_train.eq(1).selfMask();   // 1 only, rest masked
// Image of just the stable-forest mask (1 where stable)
var stable_mask     = stable_forest.eq(1).selfMask(); // 1 only, rest masked

// image.sample(numPixels: N) picks N RANDOM LOCATIONS in the region, then
// keeps whichever are unmasked. So if your class covers X% of the region,
// you get roughly N×X% pixels back. Deforested pixels are ~1.25% of Nyungwe
// (51,345 of ~4M), so numPixels:5000 returned only ~62.
//
// Fix: oversample heavily, then .limit(5000) to get exactly the count we
// need. Oversample factors are based on observed class coverage:
//   deforested = 1.25%  → need 5000/0.0125 = 400k candidates  → use 500k
//   stable     = ~70%   → need 5000/0.70   = 7.1k candidates  → use 10k

// Sample deforested pixels — labelled 1
var deforested_pts = ee.Image.constant(1).byte().rename('label')
  .updateMask(deforested_mask)
  .sample({
    region: studyArea,
    scale: 30,
    numPixels: 500000,       // oversample 100× to compensate for 1.25% coverage
    seed: 42,
    geometries: true,
    tileScale: 16
  })
  .limit(5000);              // trim to exactly 5000

// Sample stable-forest pixels — labelled 0
var stable_pts = ee.Image.constant(0).byte().rename('label')
  .updateMask(stable_mask)
  .sample({
    region: studyArea,
    scale: 30,
    numPixels: 10000,        // light oversample, stable covers ~70% already
    seed: 43,                // different seed so the two classes don't collide
    geometries: true,
    tileScale: 16
  })
  .limit(5000);              // trim to exactly 5000

print('Deforested points sampled:', deforested_pts.size());  // expect 5000
print('Stable forest points sampled:', stable_pts.size());   // expect 5000

var sample_points = deforested_pts.merge(stable_pts);

// Attach features. Unmask first so cloud-masked pixels still produce rows
// (notebook 02 converts -9999 back to NaN and imputes via median).
var feature_bands = features_D
  .select(features_D.bandNames().remove('label'))
  .unmask(-9999);

var training_data = feature_bands.sampleRegions({
  collection: sample_points,
  properties: ['label'],
  scale: 30,
  tileScale: 16,
  geometries: true
});

print('Training samples collected:', training_data.size());          // expect ~10000
print('Class breakdown:', training_data.aggregate_histogram('label'));

// ── EXPORT TASKS ─────────────────────────────────────────────
// After pressing RUN, go to Tasks panel and click RUN on each

// Export 1: Training CSV (main file you need)
Export.table.toDrive({
  collection: training_data,
  description: 'TreeSight_Training_Data',
  folder: 'TreeSight_Rwanda',
  fileNamePrefix: 'training_data',
  fileFormat: 'CSV'
});

// Export 2: Sentinel-2 GeoTIFF (for visual map display)
Export.image.toDrive({
  image: s2_train.select(['B4','B3','B2']),
  description: 'TreeSight_Sentinel2_RGB',
  folder: 'TreeSight_Rwanda',
  fileNamePrefix: 'nyungwe_s2_rgb',
  region: studyArea,
  scale: 30,
  crs: 'EPSG:4326',
  maxPixels: 1e9
});

// Export 3: NDVI change map (shows where forest was lost)
Export.image.toDrive({
  image: ndvi_change,
  description: 'TreeSight_NDVI_Change',
  folder: 'TreeSight_Rwanda',
  fileNamePrefix: 'nyungwe_ndvi_change',
  region: studyArea,
  scale: 30,
  crs: 'EPSG:4326',
  maxPixels: 1e9
});

// Export 4: Hansen loss labels (ground truth)
Export.image.toDrive({
  image: loss_train.byte(),
  description: 'TreeSight_Hansen_Labels',
  folder: 'TreeSight_Rwanda',
  fileNamePrefix: 'nyungwe_labels',
  region: studyArea,
  scale: 30,
  crs: 'EPSG:4326',
  maxPixels: 1e9
});

print('==============================================');
print('All exports queued!');
print('Go to Tasks panel (top right) and click RUN on each task.');
print('Files udpated will appear in Google Drive: TreeSight_Rwanda folder');
print('==============================================');

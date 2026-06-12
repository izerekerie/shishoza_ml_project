# RQ1 — Optimal feature combination for deforestation detection in Nyungwe

**RQ1**: *What is the optimal combination of satellite features (optical, radar, terrain) for detecting deforestation in Nyungwe's smallholder context?*

## §4.X.1 — Experiment progression

To answer RQ1, four feature-set configurations were trained and evaluated on the same held-out 80/20 stratified split (n = 2,000 test pixels, 50 % deforested). Table 4.X reports F1, Precision, Recall and AUC for each experiment; Figure 4.X panel (a) visualises the F1 progression.

| Experiment | Feature set | Features | F1 | Precision | Recall | AUC | Δ vs A |
|---|---|---|---|---|---|---|---|
| A | Sentinel-2 optical only | 9 | 0.698 | 0.716 | 0.681 | 0.775 | — |
| B | S2 + SRTM terrain | 12 | 0.777 | 0.757 | 0.798 | 0.848 | **+0.079** |
| C | S2 + S1 radar | 14 | 0.736 | 0.734 | 0.737 | 0.817 | **+0.037** |
| D | **S2 + S1 + SRTM (all)** | 17 | **0.791** | **0.777** | **0.805** | **0.865** | **+0.093** |

Three findings emerge:

1. **Experiment A (Sentinel-2 only) under-performs the Ygorra et al. (2024) global baseline of F1 = 0.71.** Optical features alone are insufficient for Nyungwe's small-patch, frequently cloudy context; the F1 = 0.698 suggests cloud-masked Sentinel-2 leaves too many pixels with imputed values to support reliable detection.

2. **Adding SRTM terrain (Experiment B) provides the largest single improvement: +0.079 F1.** This was not the expected result — much of the published deforestation-detection literature emphasises Sentinel-1 radar's cloud-penetration advantages. The terrain finding is, however, consistent with the Rwandan context: deforestation pressure concentrates at *accessible* elevations and gentler slopes where smallholder farms can replace forest. Slope and elevation therefore carry strong discriminative signal, independent of cloud cover.

3. **Adding Sentinel-1 radar to S2 (Experiment C) helps less than terrain (+0.037 F1 vs +0.079).** Radar still contributes meaningfully, but Nyungwe's relatively persistent partial-cloud regime (rather than complete cloud cover) means Cloud Score+ masking already salvages enough optical observations to mute radar's main advantage.

4. **Experiment D (all three sources) achieves the best overall performance: F1 = 0.791.** This +0.081 improvement over the global baseline confirms the project hypothesis that multi-sensor fusion outperforms any single sensor for tropical smallholder deforestation.

## §4.X.2 — Information share by data source (Figure 4.X panel b)

Aggregating per-feature Random Forest importance values from the deployed rf_D model and grouping by data source yields:

| Source | Share of model importance | Top feature |
|---|---|---|
| Sentinel-2 optical | 51 % | NDVI_change (multi-temporal) |
| SRTM terrain | 25 % | **elevation** — single most important feature at 16.7 % |
| Sentinel-1 radar | 24 % | VH/VV ratio |

The single most discriminative feature in the deployed model is **elevation** (importance = 0.167), surpassing every spectral and radar feature by roughly a factor of two. This corroborates Finding 2 above: Nyungwe deforestation is strongly stratified by elevation band, and the model exploits this stratification.

## §4.X.3 — Direct answer to RQ1

The optimal feature combination is **Experiment D — Sentinel-2 optical bands (B2, B3, B4, B8, B11) with derived NDVI/EVI/NBR and NDVI_change, plus Sentinel-1 VV/VH backscatter and VH/VV ratio, plus SRTM elevation, slope and aspect** — totalling 17 features across three data sources. This combination achieves F1 = 0.791, Recall = 0.805 and AUC = 0.865 on a held-out test set, exceeding the published Ygorra et al. (2024) global baseline by +0.081 F1.

A noteworthy by-finding for the literature is that **terrain features contribute more to detection accuracy than radar in this study area**, a counter-intuitive but defensible result attributable to (a) Nyungwe's elevation-stratified clearing pressure and (b) the effectiveness of Cloud Score+ masking at reducing cloud-induced optical noise to a level where radar's resilience offers diminishing returns. This may not generalise to areas with denser persistent cloud cover (e.g. parts of the Congo Basin) where radar would likely re-dominate.

## Linked figures

- Figure 4.X — *RQ1 synthesis* (`data/rq1_synthesis.png`)
- Figure 4.Y — *Per-feature importance* (`data/feature_importance.png`)
- Table 4.X — Experiment results (`data/experiment_results.csv`)

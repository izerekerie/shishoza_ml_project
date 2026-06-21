# Research-Question Findings — draft prose for the dissertation

> Draft write-ups generated 2026-06-22 from the actual saved results. Numbers are
> traceable to `results/metrics/`. Edit freely — this is a starting point, not final text.
> Honesty note: the per-experiment F1 values below are standard 5-fold CV (for *comparing
> feature sets*); the model's defensible generalization figure is the **spatial-CV F1 ≈ 0.75**
> (see D-014). Quote spatial CV as the headline, these as the comparison.

---

## RQ1 — Does adding Sentinel-1 radar to Sentinel-2 optical improve detection?

**Answer: Yes — radar adds a real but secondary gain; the best model fuses all three sources.**

Four feature sets were compared under identical 5-fold cross-validation (200-tree Random
Forest, national data, *n* = 23,319 pixels):

| Experiment | Features | National F1 |
|---|---|---|
| A — Optical only (Sentinel-2) | 9 | 0.7545 |
| B — Optical + Terrain (SRTM) | 12 | 0.8208 |
| C — Optical + Radar (Sentinel-1) | 14 | 0.7937 |
| D — All combined | 17 | **0.8319** |

**Interpretation.** Adding radar to optical (A → C) raises F1 by **+0.039** (0.7545 → 0.7937),
confirming that Sentinel-1 backscatter carries deforestation signal not present in optical bands
alone — consistent with radar's ability to sense structural change and to see through the cloud
cover that frequently obscures optical imagery over Rwanda. Radar's contribution is corroborated
by feature importance: of the model's total decision weight, **optical = 50.7%, radar = 25.9%,
terrain = 23.4%** — radar is the second most influential source.

The gain is *secondary* to terrain: adding terrain instead (A → B, +0.066) helps more, because
elevation and slope strongly condition where clearing occurs in Rwanda's hilly landscape. When
terrain is already present, radar's *marginal* gain narrows (B → D, +0.011) — the two sources
partly explain the same variance. Nonetheless the full fusion model (D) is best, and **radar is a
justified, non-redundant component**, especially valuable for cloud-robust monitoring.

*Files:* `results/metrics/national_comparison.json`, `results/metrics/national_rq_analysis.json`.

---

## RQ2 — How does accuracy change with clearing patch size? (down to ~0.18 ha)

**Answer: Recall falls for small clearings but stays usable at parcel scale.** *(Done — see
`notebooks/08_RQ2_PatchSize.ipynb` and D-017.)* Using real Hansen connected-component patch sizes
and honest out-of-fold predictions, recall rises monotonically with clearing size:

| Real patch size | Recall |
|---|---|
| 0.09–0.18 ha (1–2 px, parcel scale) | 0.771 |
| 0.18–0.45 ha | 0.799 |
| 0.45–0.9 ha | 0.833 |
| 0.9–1.8 ha | 0.837 |
| >1.8 ha | 0.873 |

Small clearings are measurably the hard case, yet the system still recovers ~3 of every 4
parcel-scale (0.09–0.18 ha) clearings — the under-monitored case this project targets. *Limit:*
below 0.09 ha is sub-pixel at 30 m and not assessed (true of every 30 m product, incl. Hansen).

---

## RQ3 — What does the 500 m neighbourhood analysis add beyond the permit process?

**Answer: It situates a parcel in its surroundings, adding cumulative-pressure and
recovery-trajectory evidence that a single-parcel permit review cannot see.**

A standard clearing permit assesses one parcel in isolation. TreeSight additionally computes, for
the ~500 m neighbourhood around the parcel (via the K-nearest sampled pixels — see D-001):

- **`deforested_pct_500m`** — the share of the surrounding area already classified as deforested,
  i.e. *cumulative clearing pressure*. A parcel in an area that is being progressively cleared
  carries different risk from an identical parcel in intact forest.
- **`avg_ndvi_500m`** — the recent greenness (NDVI) of the surroundings, a proxy for whether the
  neighbouring landscape is *recovering / regrowing*.

These feed a neighbourhood rule (Rule 2): the parcel is flagged HIGH when the surroundings are
already heavily cleared (`deforested_pct_500m > 50%`) **and** the parcel is markedly less green
than its recovering neighbours (`ndvi_current < 0.70 × avg_ndvi_500m`). This captures the case a
per-parcel permit misses entirely: **a single small cut that is individually minor but part of a
larger clearing front, or one that interrupts a recovering forest patch.**

The cut-simulation extends this forward: it projects the neighbourhood's deforested fraction
*after* a proposed cut and returns a **recovery-time estimate (~6–8 years)** for the cleared
vegetation — turning an abstract permit decision into concrete, location-specific evidence the
landholder and manager can weigh.

**Contribution beyond the permit:** (1) cumulative/landscape context, (2) recovery-trajectory
evidence, (3) a forward what-if with a recovery-time estimate — none of which a single-parcel,
point-in-time permit captures.

*Honesty caveat:* the neighbourhood is approximated from the nearest sampled training pixels
(D-001), not a live satellite read; accuracy degrades far from sampled pixels (surfaced via the
confidence indicator). A live Earth Engine neighbourhood query is documented as future work.

*Files:* `app_cadastral.py` (`/api/analyse` neighbourhood fields, `/api/simulate`).

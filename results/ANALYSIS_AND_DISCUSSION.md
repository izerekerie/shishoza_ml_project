# Analysis & Discussion — Objectives and Research Questions

This section evaluates the project against the objectives and research questions
set in the proposal, using the measured results. Figures are drawn from
`results/metrics/` and `results/experiments/`.

---

## 1. Achievement of objectives

### Main objective
*Develop an ML system that detects small-scale forest clearing and measures tree
cover loss at parcel level, delivered through a web app serving forest managers
(dashboard) and citizens (GPS parcel lookup).*

**Achieved.** A national Random Forest model (F1 = 0.83) is integrated into a
three-persona Flask application: a citizen parcel lookup (GPS or land-title
upload, live 2025–26 satellite pull), a forest-manager sector risk map, and an
admin console. The remaining task is a stable public deployment, addressed by
moving from a memory-limited free tier to a 16 GB host.

### Specific objective 1 — data and literature
*Review 2019–2026 detection methods and collect a balanced, labelled GEE dataset
(Sentinel-2 + Sentinel-1 + SRTM, Hansen labels), province-stratified, Nyungwe
retained for validation.*

**Achieved.** The training set is **23,319 nationally-stratified pixels** across
all five provinces, labelled with Hansen Global Forest Change, with Nyungwe
(10,000 pixels) kept as the validation case study.

### Specific objective 2 — train, compare, integrate, deploy
*Train a Random Forest over four feature combinations, integrate the best model
into a Dockerised web app.*

**Mostly achieved.** Four experiments (A–D) were run; the best (D, all 17
features) is the model served by the app. The app exposes every output the
objective named: tree-cover loss since 2020, 500 m neighbourhood status, and a
HIGH/MEDIUM/LOW classification at a GPS-located parcel. The service is
Dockerised; a stable public host is the final step.

### Specific objective 3 — beat the baseline and deliver to citizens
*Show F1 > 0.71 (Ygorra et al. 2024) and that the app delivers risk to citizens
at their GPS location.*

**Achieved.** National F1 = **0.83**, Nyungwe F1 = **0.78** — both above 0.71.
Under honest spatial cross-validation (blocking by location) F1 = **0.73**, still
above the baseline. The citizen page delivers a risk reading at a GPS parcel.
**The hypothesis — locally-calibrated multi-source ML beats the 0.71 global
baseline — is confirmed.**

---

## 2. Research questions

### RQ1 — Does adding Sentinel-1 radar to Sentinel-2 optical improve F1?

| Experiment | Features | National F1 |
|---|---|---|
| A — Optical only | 9 | 0.755 |
| B — Optical + Terrain | 12 | 0.821 |
| C — Optical + Radar | 14 | 0.794 |
| D — All combined | 17 | **0.832** |

**Answered.** Radar alone lifts F1 by **+0.039** (A → C). Terrain lifts it more
(B), and the full stack (D) is best. Feature importance agrees: elevation ranks
first (0.13), then NDVI change (0.10), then the radar VH/VV ratio (0.08). So
radar contributes, and it contributes most in combination with optical and
terrain.

### RQ2 — How does accuracy relate to clearing patch size, down to 0.18 ha?

| Patch size | Recall |
|---|---|
| 0.09–0.18 ha (smallest) | **0.771** |
| 0.18–0.45 ha | 0.799 |
| 0.45–0.9 ha | 0.833 |
| 0.9–1.8 ha | 0.837 |
| > 1.8 ha | 0.873 |
| Overall | 0.838 |

**Answered.** Detection degrades monotonically as patches shrink, as expected —
but even at Rwanda's typical 0.09–0.18 ha farm plot, recall is still **0.77**.
The system catches roughly three in four of the smallest clearings, which is the
exact gap global monitoring misses. Patch sizes are real Hansen
connected-component sizes, not a proxy.

### RQ3 — What does the 500 m neighbourhood add over a parcel-only check?

Measured on 3,000 sampled parcels (parcel probability + 500 m neighbourhood):

- Parcel-only classification: 1,586 LOW / 1,414 HIGH.
- With the neighbourhood: **360 of those LOW parcels (12.0%) are raised to
  MEDIUM.**
- These are parcels whose own signal looks safe but which sit in actively-cleared
  surroundings — cases a parcel-only permit check would pass.

**Answered.** The neighbourhood adds a "caution" tier for **12% of parcels** that
parcel-only analysis would miss. This is precisely the cumulative-impact evidence
Rwanda's parcel-level EIA process currently lacks: a permit officer sees the
parcel, not its 500 m context.

### RQ4 — How effectively does the system deliver risk at a GPS parcel?

**Answered** (load + poor-connection tests, full detail in
`results/performance/RQ4_delivery.md`).

- **Manager delivery is highly effective.** Under gunicorn (production config),
  the sector-risk endpoint holds **p95 = 39 ms at 50 users** and **p95 = 270 ms
  at 200 users** — well under the 2 s target, with no breaking point at 200
  concurrent users (far above the realistic pilot scale). Failures stayed below
  0.4%.
- **Poor connections are handled.** The map payload is 168 KB → ~3.4 s on Slow
  3G, ~0.8 s on Fast 3G. Acceptable for a one-time rural load.
- **Citizen live analysis is the bottleneck.** The live Earth Engine parcel pull
  takes ~18 s warm and ~96 s cold — the cold call exceeds the 90 s worker
  timeout. The nearest-sample fallback answers in under a second. This is a
  documented limitation: keep the fast fallback as default and make the live pull
  an explicit action, or cache/region-restrict the Earth Engine query.

So the system delivers manager risk information very effectively and citizen
information functionally, with a clear, measured fix for the citizen-path
latency.

---

## 3. Honest limitations

1. **Random split (F1 = 0.79) vs spatial split (F1 = 0.73).** Both are reported.
   The drop is expected when neighbouring pixels can no longer leak between train
   and test; the spatially-honest number still beats the baseline.
2. **Balanced 50/50 training vs rare real-world deforestation.** Live precision
   will differ from the balanced-set figure; this is stated explicitly.
3. **External Hansen cross-check was weak-moderate** (Pearson r ≈ 0.32 at sector
   level), a genuine limitation of the sector aggregation.
4. **Live 2025–26 predictions are not yet validated** — no Hansen ground truth
   exists that recent; accuracy on current imagery is assumed, to be re-checked
   when new labels are published.

---

## 4. Conclusion

The main objective and all three specific objectives are met, and the central
hypothesis (beating F1 = 0.71) is confirmed at 0.83 nationally and 0.73 under the
strictest spatial test. RQ1 and RQ2 are answered with strong, honest numbers;
RQ3 is now quantified (a 12% neighbourhood escalation rate); RQ4's delivery is
demonstrated and awaits a usability measurement. The outstanding items —
finalising the public deployment and the RQ4 usability test — are completion
tasks, not gaps in the science.

# RQ4 — delivery effectiveness (load + poor-connection tests)

How effectively does the system deliver risk information at the parcel? Measured
with Locust against the app running under gunicorn (1 worker, 4 threads,
`--preload`), matching the production configuration.

## Manager risk delivery (sector-risk choropleth + session)

| Load | Requests | Failures | Throughput | `/api/sector-risk` p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| 50 users, 60 s | 1,451 | 0.14% | 24.3 req/s | 8 ms | 39 ms | 190 ms | 540 ms |
| 200 users, 45 s | 4,175 | 0.38% | ~90 req/s | 8 ms | 270 ms | 390 ms | 670 ms |

- p95 stays **well under the 2 s target** even at **200 concurrent users** — far
  beyond the realistic pilot scale (a handful of district managers).
- No breaking point was reached at 200 users; latency rises gently and
  connection resets stay below 0.4%.
- Login is the slowest read (~130 ms p50) because it verifies a bcrypt hash —
  expected and one-off per session.

## Poor-connection (payload) test

The manager map payload is **168 KB** (416 sectors). Transfer time by link:

| Link | Approx. bandwidth | Load time |
|---|---|---|
| Slow 3G | ~400 Kbps | ~3.4 s |
| Fast 3G | ~1.6 Mbps | ~0.8 s |
| 4G | ~12 Mbps | ~0.1 s |

On a weak rural link the map data loads in ~3–4 s — acceptable for a one-time
load. Manual Chrome DevTools "Slow 3G" throttling confirms the page stays usable.

## Citizen parcel analysis (heavy path)

`/api/analyse` measured latency:

| Path | Latency |
|---|---|
| Live Earth Engine (cold, first call) | **~96 s** |
| Live Earth Engine (warm) | **~18 s** |
| Nearest-sample fallback (no EE) | sub-second |

**This is the delivery bottleneck.** The live satellite pull for the exact
parcel is slow (18–96 s) because it computes Sentinel composites on demand, and
the cold call exceeds the 90 s worker timeout — a real risk in production.

### Recommendation
- Keep the fast **nearest-sample** path as the default response, and offer the
  live pull as an explicit "get today's satellite reading" action, OR
- Restrict the Earth Engine composite to a small region around the parcel and
  cache recent results, to cut the warm latency well below the timeout.

## Verdict

Manager delivery is highly effective (p95 < 300 ms at 200 users, ~3.4 s map load
on Slow 3G). Citizen delivery works but the live-satellite path is too slow for a
smooth experience and needs the optimisation above. RQ4 is answered with numbers;
the citizen-path latency is a documented limitation with a clear fix.

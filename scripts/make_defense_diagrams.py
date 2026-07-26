"""Draw the system-design diagrams used in the defense deck.

Renders three PNGs into results/diagrams/:
  architecture.png  - layered architecture + data flow (offline training + online serving)
  erd.png           - entity-relationship diagram of the live SQLite schema
  class_diagram.png - the 13 application classes and their dependencies

Sources of truth: docs/diagrams/*.puml and ARCHITECTURE_DIAGRAM_PROMPT.md.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = Path("results/diagrams")
OUT.mkdir(parents=True, exist_ok=True)

# Brand palette (matches the deck)
GREEN = "#455E28"
GREEN_DK = "#2C3E19"
GREEN_LT = "#EAF0E1"
CREAM = "#F6F3EA"
INK = "#12130F"
MUTED = "#6B6B60"
AMBER = "#B26B18"
AMBER_LT = "#FBF0DE"
BLUE = "#2F5D7C"
BLUE_LT = "#E6EEF4"
PLUM = "#5A4470"
PLUM_LT = "#EEE9F3"
RISK = "#C0492F"

FONT = "DejaVu Sans"
plt.rcParams["font.family"] = FONT


def zone(ax, x, y, w, h, label, face, edge):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0,rounding_size=0.22",
                                fc=face, ec=edge, lw=1.4, alpha=1.0, zorder=1))
    ax.text(x + 0.22, y + h - 0.26, label.upper(), fontsize=10.5, color=edge,
            weight="bold", va="center", ha="left", zorder=3,
            fontstretch="condensed")


def card(ax, x, y, w, h, title, sub=None, face="#FFFFFF", edge="#C9C9BE",
         tcol=INK, ts=10.5, ss=8.2, lw=1.1, bold=True):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0,rounding_size=0.14",
                                fc=face, ec=edge, lw=lw, zorder=4))
    if sub:
        ax.text(x + w / 2, y + h * 0.63, title, fontsize=ts, color=tcol,
                ha="center", va="center", weight="bold" if bold else "normal", zorder=5)
        ax.text(x + w / 2, y + h * 0.27, sub, fontsize=ss, color=MUTED,
                ha="center", va="center", zorder=5, linespacing=1.35)
    else:
        ax.text(x + w / 2, y + h / 2, title, fontsize=ts, color=tcol,
                ha="center", va="center", weight="bold" if bold else "normal",
                zorder=5, linespacing=1.35)
    return (x, y, w, h)


def arrow(ax, p1, p2, label=None, style="-", col=GREEN, rad=0.0, ls="solid",
          fs=8.0, lx=0.0, ly=0.12):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=11,
                                 lw=1.25, color=col, zorder=3, linestyle=ls,
                                 connectionstyle=f"arc3,rad={rad}",
                                 shrinkA=2, shrinkB=3))
    if label:
        mx, my = (p1[0] + p2[0]) / 2 + lx, (p1[1] + p2[1]) / 2 + ly
        ax.text(mx, my, label, fontsize=fs, color=col, ha="center", va="center",
                zorder=6, bbox=dict(fc=CREAM, ec="none", pad=1.4))


def route(ax, pts, label=None, col=GREEN, ls="solid", fs=8.0, lpos=0.5, ly=0.22,
          lface=None):
    """Elbow connector through a list of points; arrowhead on the last segment."""
    for i in range(len(pts) - 2):
        ax.add_patch(FancyArrowPatch(pts[i], pts[i + 1], arrowstyle="-", lw=1.25,
                                     color=col, linestyle=ls, zorder=3,
                                     shrinkA=0, shrinkB=0))
    ax.add_patch(FancyArrowPatch(pts[-2], pts[-1], arrowstyle="-|>",
                                 mutation_scale=11, lw=1.25, color=col,
                                 linestyle=ls, zorder=3, shrinkA=0, shrinkB=3))
    if label:
        # place the label along the longest segment
        best, blen = 0, -1
        for i in range(len(pts) - 1):
            d = abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1])
            if d > blen:
                best, blen = i, d
        (x1, y1), (x2, y2) = pts[best], pts[best + 1]
        mx, my = x1 + (x2 - x1) * lpos, y1 + (y2 - y1) * lpos + ly
        ax.text(mx, my, label, fontsize=fs, color=col, ha="center", va="center",
                zorder=6, bbox=dict(fc=lface or CREAM, ec="none", pad=1.6))


# ----------------------------------------------------------------- architecture
def architecture():
    fig, ax = plt.subplots(figsize=(17.4, 7.2), dpi=170)
    fig.patch.set_facecolor(CREAM)
    ax.set_facecolor(CREAM)
    ax.set_xlim(0, 34)
    ax.set_ylim(0, 13.6)
    ax.axis("off")


    # ---- Zone: users
    zone(ax, 0.2, 7.2, 5.0, 5.9, "Users", PLUM_LT, PLUM)
    card(ax, 0.6, 11.4, 4.2, 1.15, "Citizen", "anonymous · no account", edge=PLUM)
    card(ax, 0.6, 9.85, 4.2, 1.15, "Forest manager", "district-scoped login", edge=PLUM)
    card(ax, 0.6, 8.3, 4.2, 1.15, "Admin", "all districts", edge=PLUM)

    # ---- Zone: serving
    zone(ax, 5.9, 4.9, 17.6, 8.2,
         "Online serving — Flask app on Hugging Face Spaces (Docker + gunicorn)",
         BLUE_LT, BLUE)
    card(ax, 6.4, 11.5, 7.6, 1.2, "Browser client",
         "Leaflet map · upload certificate (PDF/photo) · draw parcel", edge=BLUE)
    card(ax, 6.4, 9.7, 7.6, 1.3, "Flask REST API",
         "/extract · /analyse · /simulate · /requests · /decision", edge=BLUE, ts=11.5)

    pw, ph = 3.65, 1.05
    card(ax, 6.40, 8.15, pw, ph, "Cadastral extractor", "PyMuPDF · Tesseract · OpenCV", edge=BLUE, ts=9.6, ss=7.6)
    card(ax, 10.35, 8.15, pw, ph, "Geometry resolver", "geopandas · shapely · pyproj", edge=BLUE, ts=9.6, ss=7.6)
    card(ax, 6.40, 6.85, pw, ph, "Earth Engine client", "live Sentinel-2 · 8 s timeout", edge=BLUE, ts=9.6, ss=7.6)
    card(ax, 10.35, 6.85, pw, ph, "Model loader", "Random Forest .pkl · 325 MB", edge=BLUE, ts=9.6, ss=7.6)
    card(ax, 6.40, 5.40, pw, 1.05, "Cut simulator", "NDVI impact of a planned cut", edge=BLUE, ts=9.6, ss=7.6)
    card(ax, 10.35, 5.40, pw, 1.05, "Risk classifier", "HIGH / MEDIUM / LOW", edge=RISK, ts=9.6, ss=7.6, tcol=RISK)

    card(ax, 14.60, 9.70, 8.30, 1.30, "Review service",
         "district-scoped decisions on citizen requests", edge=BLUE, ts=10.5)
    card(ax, 14.60, 7.25, 3.95, 1.10, "Email / SMTP",
         "async decision notice\nto the citizen", edge=AMBER, ts=9.6, ss=7.6)
    card(ax, 18.95, 7.25, 3.95, 1.10, "predictions_log.csv",
         "drift + latency\nmonitoring", edge=AMBER, ts=9.6, ss=7.6)
    card(ax, 14.60, 5.40, 8.30, 1.05, "500 m neighbourhood analysis",
         "25-NN parcel probability + surrounding pressure · escalates 12% of parcels",
         face=GREEN_LT, edge=GREEN, ts=10.5, ss=8.0)

    # ---- Zone: data (rows aligned to the serving components that use them)
    zone(ax, 25.0, 4.9, 8.8, 8.2, "Data & external services", AMBER_LT, AMBER)
    card(ax, 25.4, 11.35, 8.0, 1.2, "Hugging Face Hub", "hosts the trained model artefact", edge=AMBER)
    card(ax, 25.4, 9.75, 8.0, 1.2, "SQLite", "users · citizens · requests · cache", edge=AMBER)
    card(ax, 25.4, 8.10, 8.0, 1.2, "GeoJSON", "416 sector boundaries", edge=AMBER)
    card(ax, 25.4, 6.15, 8.0, 1.2, "Google Earth Engine", "Sentinel-2 · Sentinel-1 · SRTM", edge=AMBER)

    # ---- Zone: training
    zone(ax, 0.2, 0.3, 33.6, 4.1, "Offline ML training pipeline (run once, in notebooks)", GREEN_LT, GREEN)
    steps = [
        ("GEE export", "Sentinel-2 · S1 · SRTM"),
        ("Hansen labels", "loss 2020–2024"),
        ("Feature build", "23,319 px · 17 features"),
        ("Model training", "RF · XGBoost · LightGBM"),
        ("Tuning", "96-combination grid"),
        ("Spatial CV", "F1 = 0.753 ± 0.081"),
        ("Model registry", "rf_D.pkl → HF Hub ↑"),
    ]
    sw, gap, sy = 4.20, 0.45, 1.35
    sx = 0.70
    prev = None
    for t, s in steps:
        card(ax, sx, sy, sw, 1.5, t, s, face="#FFFFFF", edge=GREEN, ts=10, ss=7.8)
        if prev is not None:
            arrow(ax, (prev, sy + 0.75), (sx, sy + 0.75), col=GREEN)
        prev = sx + sw
        sx += sw + gap

    # ---- user flows
    arrow(ax, (4.8, 12.0), (6.4, 12.1), "HTTPS", col=PLUM, fs=8, ly=0.28)
    arrow(ax, (4.8, 10.4), (6.4, 11.9), col=PLUM, rad=-0.15)
    arrow(ax, (4.8, 8.85), (6.4, 11.7), col=PLUM, rad=-0.2)

    # ---- inside the app
    arrow(ax, (10.2, 11.5), (10.2, 11.0), col=BLUE)
    arrow(ax, (10.2, 9.7), (8.25, 9.20), col=BLUE)
    arrow(ax, (10.2, 9.7), (12.15, 9.20), col=BLUE)
    arrow(ax, (8.25, 8.15), (8.25, 7.90), col=BLUE)
    arrow(ax, (12.15, 8.15), (12.15, 7.90), col=BLUE)
    arrow(ax, (8.25, 6.85), (8.25, 6.45), col=BLUE)
    arrow(ax, (12.15, 6.85), (12.15, 6.45), col=BLUE)
    arrow(ax, (14.00, 5.92), (14.60, 5.92), col=GREEN)
    arrow(ax, (14.00, 10.35), (14.60, 10.35), col=BLUE)
    route(ax, [(16.55, 9.70), (16.55, 8.35)], col=AMBER, ls="dashed")
    route(ax, [(13.20, 9.70), (13.20, 8.75), (20.90, 8.75), (20.90, 8.35)],
          "monitoring log", col=AMBER, ls="dashed", fs=7.8, lface=BLUE_LT)

    # ---- app <-> data (each in its own free corridor)
    route(ax, [(22.90, 10.35), (25.40, 10.35)], "read / write", col=AMBER, fs=8, lface=BLUE_LT)
    route(ax, [(14.00, 8.68), (24.20, 8.68), (24.20, 8.70), (25.40, 8.70)],
          "sector boundaries", col=AMBER, fs=8, lface=BLUE_LT)
    route(ax, [(8.25, 6.85), (8.25, 6.68), (24.30, 6.68), (24.30, 6.75), (25.40, 6.75)],
          "live Sentinel-2 pull", col=AMBER, fs=8, lface=BLUE_LT)
    route(ax, [(25.40, 11.95), (14.15, 11.95), (14.15, 7.38), (14.00, 7.38)],
          "deploy the trained model", col=GREEN, fs=8, lface=BLUE_LT)

    fig.text(0.012, 0.012,
             "Citizens are anonymous (no account, SHA-256-hashed IP); officers authenticate and see only their district.",
             fontsize=9, color=MUTED)

    fig.tight_layout(pad=0.4)
    fig.savefig(OUT / "architecture.png", facecolor=CREAM, bbox_inches="tight")
    plt.close(fig)


# -------------------------------------------------------------------------- ERD
def erd():
    fig, ax = plt.subplots(figsize=(16.5, 7.9), dpi=170)
    fig.patch.set_facecolor(CREAM)
    ax.set_facecolor(CREAM)
    ax.set_xlim(0, 32)
    ax.set_ylim(0, 16.6)
    ax.axis("off")
    ax.text(0.2, 16.1, "Shishoza — entity-relationship diagram (live SQLite schema)",
            fontsize=15, color=INK, weight="bold", va="center")

    def entity(x, y, w, name, keys, fields):
        head = 0.95
        body = 0.52 * (len(keys) + len(fields)) + 0.45
        ax.add_patch(FancyBboxPatch((x, y - body), w, body,
                                    boxstyle="round,pad=0,rounding_size=0.12",
                                    fc="#FFFFFF", ec=GREEN, lw=1.2, zorder=3))
        ax.add_patch(FancyBboxPatch((x, y - 0.02), w, head,
                                    boxstyle="round,pad=0,rounding_size=0.12",
                                    fc=GREEN, ec=GREEN, lw=1.2, zorder=4))
        ax.text(x + w / 2, y + head / 2 - 0.02, name, fontsize=11.5, color="#FFFFFF",
                ha="center", va="center", weight="bold", zorder=5)
        yy = y - 0.5
        for k in keys:
            ax.text(x + 0.28, yy, k, fontsize=9.2, color=GREEN_DK, va="center",
                    weight="bold", zorder=5)
            yy -= 0.52
        for f in fields:
            ax.text(x + 0.28, yy, f, fontsize=9.2, color=MUTED, va="center", zorder=5)
            yy -= 0.52
        return (x, y - body, w, body)

    entity(0.4, 15.0, 7.4, "CITIZENS",
           ["PK  citizen_id"],
           ["email", "password_hash", "full_name", "phone", "created_at", "last_login"])
    entity(0.4, 7.2, 7.4, "USERS  (officers)",
           ["PK  user_id"],
           ["email", "password_hash", "role", "district_scope"])
    entity(11.0, 15.0, 9.6, "REQUESTS",
           ["PK  request_id", "FK  citizen_email", "FK  analysis_id", "FK  reviewed_by"],
           ["upi · district · sector", "lat · lng · area_ha", "risk_level · parcel_risk",
            "neighbourhood_risk", "tree_cover_pct", "deforestation_prob", "reason",
            "status", "reviewed_at · review_note"])
    entity(23.6, 15.0, 8.0, "ANALYSIS_CACHE",
           ["PK  analysis_id"],
           ["lat · lng · area_ha", "risk_level", "data_source"])
    entity(23.6, 8.0, 8.0, "SIMULATION_RUNS",
           ["PK  sim_id", "FK  analysis_id"],
           ["planned cut geometry", "NDVI impact"])
    entity(11.0, 6.2, 9.6, "ALTERNATIVES",
           ["PK  alt_id"],
           ["reason · risk_level", "language", "suggestion_text", "gov_program_url"])

    def rel(p1, p2, label, rad=0.0):
        ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-", lw=1.3, color=GREEN_DK,
                                     zorder=2, connectionstyle=f"arc3,rad={rad}"))
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        ax.text(mx, my + 0.28, label, fontsize=9, color=GREEN_DK, ha="center",
                va="center", zorder=6, bbox=dict(fc=CREAM, ec="none", pad=1.6))

    rel((7.8, 12.6), (11.0, 12.6), "1 ─── ∞  submits")
    rel((7.8, 5.6), (11.0, 9.6), "1 ─── ∞  reviews", rad=0.08)
    rel((23.6, 13.0), (20.6, 12.6), "1 ─── ∞  from")
    rel((27.6, 10.7), (27.6, 8.0), "1 ─── ∞  has")
    ax.text(0.4, 0.5,
            "predictions_log.csv is a flat monitoring file, not a table · sector boundaries live in GeoJSON · the model is a .pkl artefact",
            fontsize=9.5, color=MUTED, va="center")

    fig.tight_layout(pad=0.4)
    fig.savefig(OUT / "erd.png", facecolor=CREAM, bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------- class diagram
def class_diagram():
    fig, ax = plt.subplots(figsize=(16.5, 8.0), dpi=170)
    fig.patch.set_facecolor(CREAM)
    ax.set_facecolor(CREAM)
    ax.set_xlim(0, 33.2)
    ax.set_ylim(0, 15.5)
    ax.axis("off")
    ax.text(0.2, 15.0, "Shishoza — class diagram (13 application classes)",
            fontsize=15, color=INK, weight="bold", va="center")

    def cls(x, y, w, h, name, stereo, face="#FFFFFF", edge=GREEN):
        ax.add_patch(FancyBboxPatch((x, y), w, h,
                                    boxstyle="round,pad=0,rounding_size=0.14",
                                    fc=face, ec=edge, lw=1.3, zorder=4))
        ax.text(x + w / 2, y + h * 0.62, name, fontsize=10.5, color=INK,
                ha="center", va="center", weight="bold", zorder=5)
        ax.text(x + w / 2, y + h * 0.27, f"«{stereo}»", fontsize=8.4, color=edge,
                ha="center", va="center", zorder=5, style="italic")
        return (x + w / 2, y, w, h)

    W, H = 6.2, 1.5
    api = cls(12.9, 12.4, W, H, "FlaskAPI", "boundary", face=BLUE_LT, edge=BLUE)

    rowy = 9.6
    ctrl_r = cls(19.6, rowy, W, H, "ReviewController", "control", face=GREEN_LT)
    risk = cls(6.2, rowy, W, H, "RiskClassifier", "control", face=GREEN_LT)
    geom = cls(0.3, 6.6, 5.4, H, "GeometryResolver", "service")
    cutsim = cls(12.9, rowy, W, H, "CutSimulator", "service")
    sect = cls(26.0, rowy, 5.7, H, "SectorAnalyser", "entity")

    dm = cls(0.3, 3.6, 5.4, H, "DeforestationModel", "entity")
    na = cls(6.2, 3.6, 5.9, H, "NeighbourhoodAnalyser", "entity")
    alt = cls(12.6, 3.6, 5.9, H, "AlternativesSuggester", "entity")
    rr = cls(19.0, 3.6, 5.6, H, "ReviewRequest", "entity")
    cit = cls(25.1, 3.6, 5.0, H, "Citizen", "entity")

    ns = cls(19.0, 0.8, 5.6, H, "NotificationService", "service")
    pl = cls(25.1, 0.8, 5.0, H, "PredictionLogger", "service")

    def dep(p1, p2, rad=0.0):
        ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=10,
                                     lw=1.15, color=MUTED, linestyle="dashed",
                                     zorder=3, connectionstyle=f"arc3,rad={rad}",
                                     shrinkA=2, shrinkB=3))

    dep((14.5, 12.4), (9.3, 11.1), rad=0.08)
    dep((16.0, 12.4), (16.0, 11.1))
    dep((17.5, 12.4), (22.7, 11.1), rad=-0.08)
    dep((18.6, 12.6), (28.8, 11.1), rad=-0.1)
    route(ax, [(19.1, 13.15), (32.6, 13.15), (32.6, 1.55), (30.1, 1.55)],
          col=MUTED, ls="dashed")
    dep((3.0, 9.6), (3.0, 8.1), rad=0.0)
    dep((13.4, 12.4), (2.6, 8.1), rad=0.14)
    dep((7.4, 9.6), (3.0, 5.1), rad=0.1)
    dep((9.3, 9.6), (9.1, 5.1))
    dep((11.0, 9.6), (15.5, 5.1), rad=-0.1)
    dep((21.0, 9.6), (21.8, 5.1))
    dep((23.0, 9.6), (27.6, 5.1), rad=-0.1)
    dep((21.8, 3.6), (21.8, 2.3))

    ax.text(0.3, 0.2,
            "dashed arrows = «uses» dependency · the boundary class is the only entry point; services and entities never call the API back",
            fontsize=9.5, color=MUTED, va="center")

    fig.tight_layout(pad=0.4)
    fig.savefig(OUT / "class_diagram.png", facecolor=CREAM, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    architecture()
    erd()
    class_diagram()
    print("wrote:", *(p.name for p in sorted(OUT.glob("*.png"))))

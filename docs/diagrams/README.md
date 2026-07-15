# Updated system diagrams (PlantUML specs)

These `.puml` files are the **updated** Chapter 3 diagrams that add the four
features built after the report was written: **citizen accounts**, the
**manager review workflow**, **email notifications**, and **prediction logging**.
Each file has a `note` at the bottom stating what changed versus the report.

| File | Report figure it replaces | Was → Becomes |
|---|---|---|
| `05_architecture.puml` | Fig 3.1 System Architecture | +Email/SMTP service, +predictions_log.csv monitoring store |
| `01_use_case.puml` | Fig 3.2 Use Case | 10 use cases / 2 actors → ~15 use cases / 2 human + 1 email actor |
| `02_class.puml` | Fig 3.3 Class | 8 classes → ~12 (ReviewController, ReviewRequest, Citizen, NotificationService, PredictionLogger) |
| `03_sequence.puml` | Fig 3.4 Sequence | 6 lifelines / 4 phases → ~8 lifelines / 6 phases |
| `04_erd.puml` | Fig 3.5 ERD | 6 entities → ~8 (+CITIZENS, +REQUESTS) |

## How to render to an image

- **Online (easiest):** paste the file contents into <https://www.plantuml.com/plantuml>, then download the PNG/SVG and drop it into the report in place of the old figure.
- **VS Code:** install the "PlantUML" extension, open a `.puml`, then `Alt+D` to preview / export.
- **CLI:** `plantuml docs/diagrams/*.puml` (needs Java + the PlantUML jar).

The written change-list (requirements + per-diagram edits + text search/replace)
is in [`../../REPORT_UPDATES_new_features.md`](../../REPORT_UPDATES_new_features.md).
The same per-figure notes are also inserted **inside the report itself**, directly
above each figure, tagged "REPORT UPDATE".

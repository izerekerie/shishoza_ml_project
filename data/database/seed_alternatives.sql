-- ============================================================
-- TreeSight — seed_alternatives.sql
-- Populates the ALTERNATIVES lookup table with verified content
-- All URLs HTTP-checked and returning 200 as of 2026-06-02.
--
-- Run:  sqlite3 treesight.db < data/seed_alternatives.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS ALTERNATIVES (
    alternative_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    reason           VARCHAR(20)  NOT NULL CHECK (reason IN ('firewood', 'timber', 'farming', 'income')),
    risk_level       VARCHAR(10)  NOT NULL CHECK (risk_level IN ('HIGH', 'MEDIUM', 'LOW')),
    language         VARCHAR(2)   NOT NULL CHECK (language IN ('rw', 'en', 'fr')),
    suggestion_text  TEXT         NOT NULL,
    gov_program_url  VARCHAR(255),
    source_verified  DATE         DEFAULT '2026-06-02'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alt_lookup
    ON ALTERNATIVES (reason, risk_level, language, alternative_id);

-- Wipe any prior seed before reseeding
DELETE FROM ALTERNATIVES;

-- ============================================================
-- FIREWOOD — HIGH risk (English baseline; Kinyarwanda/French TODO)
-- ============================================================

INSERT INTO ALTERNATIVES (reason, risk_level, language, suggestion_text, gov_program_url) VALUES
('firewood', 'HIGH', 'en',
 'Switch to an improved cookstove instead of cutting wood. The Rwanda Clean Cooking Results-Based Financing (CC-RBF) scheme covers between 45% and 90% of the cost based on your Ubudehe category. The programme aims to reach 500,000 households by 2026 and works with 25 approved suppliers nationwide.',
 'https://www.reg.rw/what-we-do/rbf-programs/rbf-clean-cooking/');

INSERT INTO ALTERNATIVES (reason, risk_level, language, suggestion_text, gov_program_url) VALUES
('firewood', 'HIGH', 'en',
 'If you keep cattle, install a household biogas digester through the National Domestic Biogas Programme. The Government of Rwanda provides a per-household subsidy, with micro-finance available for the balance. Biogas eliminates the daily need for firewood entirely.',
 'https://www.reg.rw/what-we-do/biomass/');

-- ============================================================
-- TIMBER — HIGH risk
-- ============================================================

INSERT INTO ALTERNATIVES (reason, risk_level, language, suggestion_text, gov_program_url) VALUES
('timber', 'HIGH', 'en',
 'Plant bamboo instead of cutting slow-growing timber trees. Bamboo poles are ready to harvest in 3 to 4 years versus 15 years or more for eucalyptus or pine. Rwanda Forestry Authority (RFA) supports smallholder Forest Owner Associations with seedlings and technical guidance.',
 'https://www.rfa.rw/forestry-management');

INSERT INTO ALTERNATIVES (reason, risk_level, language, suggestion_text, gov_program_url) VALUES
('timber', 'HIGH', 'en',
 'Consider phased cutting: harvest only 30% of mature trees now and wait for two-year regrowth on the rest. This preserves the soil and the future timber yield. Contact the Rwanda Forestry Authority for sustainable harvest planning advice.',
 'https://www.rfa.rw/');

-- ============================================================
-- FARMING — HIGH risk
-- ============================================================

INSERT INTO ALTERNATIVES (reason, risk_level, language, suggestion_text, gov_program_url) VALUES
('farming', 'HIGH', 'en',
 'Use agroforestry: grow crops between rows of trees instead of clearing the trees. The TREPA programme (Transforming Eastern Province through Adaptation) targets 75,000 smallholder farmers and 60,000 hectares of restoration through 2027, run by RFA and CIFOR-ICRAF. Seedlings and training are provided.',
 'https://www.cifor-icraf.org/trepa/');

INSERT INTO ALTERNATIVES (reason, risk_level, language, suggestion_text, gov_program_url) VALUES
('farming', 'HIGH', 'en',
 'Intercropping with nitrogen-fixing trees such as Grevillea robusta improves crop yield and protects soil. CIFOR-ICRAF runs Rwanda-specific agroforestry research and extension support that you can join through your sector agronomist.',
 'https://www.cifor-icraf.org/locations/africa/rwanda/');

-- ============================================================
-- INCOME — HIGH risk
-- ============================================================

INSERT INTO ALTERNATIVES (reason, risk_level, language, suggestion_text, gov_program_url) VALUES
('income', 'HIGH', 'en',
 'Earn income from protecting trees instead of cutting them: Rwanda has active Article 6 carbon credit frameworks with Singapore and Sweden. Smallholder forestry projects can register through Rwanda Environment Management Authority (REMA) and the Ministry of Environment.',
 'https://climatechange.gov.rw/about/overview-3-3-3-9');

INSERT INTO ALTERNATIVES (reason, risk_level, language, suggestion_text, gov_program_url) VALUES
('income', 'HIGH', 'en',
 'Rwanda''s National Carbon Market Framework provides a path for community forest projects to earn revenue from verified emission reductions. See the official guidance from the Rwanda Environment Management Authority.',
 'https://climatechange.gov.rw/about/overview-3-1');

-- ============================================================
-- MEDIUM-risk gentler suggestions
-- ============================================================

INSERT INTO ALTERNATIVES (reason, risk_level, language, suggestion_text, gov_program_url) VALUES
('income', 'MEDIUM', 'en',
 'Before clearing for cash crops, check whether your sector has an active Forest Investment Programme grant. RFA supports smallholder Forest Owner Associations with technical and financial assistance.',
 'https://www.rfa.rw/forestry-management');

INSERT INTO ALTERNATIVES (reason, risk_level, language, suggestion_text, gov_program_url) VALUES
('firewood', 'MEDIUM', 'en',
 'Dead and fallen wood collection requires no permit in Rwanda and is preferable to cutting living trees. If you need more, the Clean Cooking subsidy scheme reduces lifelong firewood demand.',
 'https://www.reg.rw/what-we-do/rbf-programs/rbf-clean-cooking/');

-- ============================================================
-- SIMULATION_RUNS TABLE
-- One row per /api/simulate request — the BEFORE/AFTER record for
-- forward-simulation of a proposed cut on a drawn parcel. Linked
-- back to the original PARCEL_ANALYSES row so a citizen who slides
-- the cut amount up and down generates multiple SIMULATION_RUNS
-- against a single PARCEL_ANALYSES.
-- ============================================================
CREATE TABLE IF NOT EXISTS SIMULATION_RUNS (
    simulation_id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id                         INTEGER NOT NULL,
    cut_area_ha                         FLOAT   NOT NULL CHECK (cut_area_ha > 0),
    cleared_ndvi_reference              FLOAT   NOT NULL,
    new_ndvi                            FLOAT,
    new_tree_cover_pct                  FLOAT,
    new_neighbourhood_deforested_pct    FLOAT,
    new_risk_level                      VARCHAR(10) CHECK (new_risk_level IN ('HIGH','MEDIUM','LOW')),
    risk_level_changed                  BOOLEAN DEFAULT 0,
    simulated_at                        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (analysis_id) REFERENCES PARCEL_ANALYSES(analysis_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sim_analysis ON SIMULATION_RUNS (analysis_id);
CREATE INDEX IF NOT EXISTS idx_sim_risk_changed ON SIMULATION_RUNS (risk_level_changed);

-- ============================================================
-- PARCEL_ANALYSES — column additions for the reason flow
-- These are no-ops if the columns already exist (SQLite has no
-- IF NOT EXISTS for columns; the deploy script should detect via
-- PRAGMA table_info before running)
-- ============================================================
-- ALTER TABLE PARCEL_ANALYSES ADD COLUMN reason_selected     VARCHAR(20);
-- ALTER TABLE PARCEL_ANALYSES ADD COLUMN reason_selected_at  TIMESTAMP;

-- ============================================================
-- VERIFICATION QUERIES (run after seeding)
-- ============================================================
-- SELECT reason, risk_level, language, COUNT(*) AS rows, gov_program_url
-- FROM ALTERNATIVES
-- GROUP BY reason, risk_level, language, gov_program_url
-- ORDER BY reason, risk_level;
--
-- SELECT name, sql FROM sqlite_master
-- WHERE type='table' AND name IN ('ALTERNATIVES','SIMULATION_RUNS');

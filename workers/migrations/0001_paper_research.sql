-- Additive private paper research only. Existing market tables are untouched.
CREATE TABLE IF NOT EXISTS paper_designs_v1 (
 id TEXT PRIMARY KEY, registered_at TEXT NOT NULL, forward_start TEXT NOT NULL, holdout_start TEXT NOT NULL,
 config_json TEXT NOT NULL, config_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_decisions_v1 (
 id TEXT PRIMARY KEY, design_id TEXT NOT NULL, strategy TEXT NOT NULL,
 root TEXT NOT NULL, decision_at TEXT NOT NULL, exit_at TEXT NOT NULL,
 selected INTEGER NOT NULL CHECK(selected IN (0,1)), reason TEXT NOT NULL,
 contracts_json TEXT NOT NULL, context_json TEXT NOT NULL,
 config_sha256 TEXT NOT NULL, evidence_mode TEXT NOT NULL CHECK(evidence_mode='prospective')
);
CREATE INDEX IF NOT EXISTS paper_decisions_design_time_v1 ON paper_decisions_v1(design_id,decision_at);
CREATE TABLE IF NOT EXISTS paper_open_v1 (
 slot INTEGER PRIMARY KEY CHECK(slot=1), decision_id TEXT NOT NULL UNIQUE,
 exit_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_entries_v1 (
 decision_id TEXT PRIMARY KEY, state TEXT NOT NULL, received_at TEXT NOT NULL,
 quotes_json TEXT NOT NULL, quote_sha256 TEXT NOT NULL,
 target_debit REAL, control_debit REAL, target_risk REAL, control_risk REAL,
 reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_marks_v1 (
 decision_id TEXT NOT NULL, observed_minute TEXT NOT NULL, received_at TEXT NOT NULL,
 state TEXT NOT NULL, quotes_json TEXT NOT NULL, missing_json TEXT NOT NULL,
 quote_sha256 TEXT NOT NULL, PRIMARY KEY(decision_id,observed_minute)
);
CREATE TABLE IF NOT EXISTS paper_outcomes_v1 (
 decision_id TEXT PRIMARY KEY, state TEXT NOT NULL, received_at TEXT NOT NULL,
 target_net REAL, control_net REAL, excess_net REAL, stress_net REAL,
 reason TEXT NOT NULL, evidence_mode TEXT NOT NULL CHECK(evidence_mode='prospective')
);
CREATE TABLE IF NOT EXISTS paper_runs_v1 (
 observed_minute TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
 state TEXT NOT NULL, rows_read INTEGER NOT NULL DEFAULT 0,
 rows_written INTEGER NOT NULL DEFAULT 0, provider_requests INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS paper_budget_v1 (
 day TEXT PRIMARY KEY, rows_read INTEGER NOT NULL DEFAULT 0,
 rows_written INTEGER NOT NULL DEFAULT 0, provider_requests INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS paper_scorecards_v1 (
 day TEXT PRIMARY KEY, created_at TEXT NOT NULL, report_json TEXT NOT NULL, report_sha256 TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS paper_designs_no_update BEFORE UPDATE ON paper_designs_v1 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS paper_designs_no_delete BEFORE DELETE ON paper_designs_v1 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS paper_decisions_no_update BEFORE UPDATE ON paper_decisions_v1 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS paper_decisions_no_delete BEFORE DELETE ON paper_decisions_v1 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS paper_entries_no_update BEFORE UPDATE ON paper_entries_v1 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS paper_entries_no_delete BEFORE DELETE ON paper_entries_v1 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS paper_marks_no_update BEFORE UPDATE ON paper_marks_v1 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS paper_marks_no_delete BEFORE DELETE ON paper_marks_v1 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS paper_outcomes_no_update BEFORE UPDATE ON paper_outcomes_v1 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS paper_outcomes_no_delete BEFORE DELETE ON paper_outcomes_v1 BEGIN SELECT RAISE(ABORT,'immutable'); END;

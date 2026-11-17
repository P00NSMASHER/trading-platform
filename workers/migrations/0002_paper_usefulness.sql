-- Bounded cumulative selected-outcome reports; never scan the entire quote archive.
CREATE INDEX IF NOT EXISTS paper_selected_design_time_v2
 ON paper_decisions_v1(design_id,selected,decision_at);
-- Operational stop state is derived only from counts/time, never holdout P&L.
CREATE TABLE IF NOT EXISTS paper_strategy_state_v2 (
 design_id TEXT NOT NULL, strategy TEXT NOT NULL, state TEXT NOT NULL,
 updated_at TEXT NOT NULL, PRIMARY KEY(design_id,strategy)
);

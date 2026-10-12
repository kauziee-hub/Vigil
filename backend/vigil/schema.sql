-- Vigil schema. Money is INTEGER paise. Time is TEXT ISO-8601 UTC with 'Z'.

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,                 -- UPI-style handle, e.g. ramesh@vigil
  display_name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'customer',   -- customer | external
  bank_code TEXT NOT NULL DEFAULT 'VGL',
  primary_device TEXT,
  opened_at TEXT NOT NULL,
  balance_paise INTEGER NOT NULL DEFAULT 0,
  daily_limit_paise INTEGER NOT NULL DEFAULT 10000000,
  persona TEXT,                        -- short description for the demo cast
  is_demo_customer INTEGER NOT NULL DEFAULT 0,
  -- SEED/GROUND-TRUTH ONLY. No scorer may read this column.
  seed_role TEXT,
  -- v10 (display only, SIMULATED; never read by a scorer): hash-derived home + how the account was opened
  home_city TEXT,
  home_lat REAL,
  home_lng REAL,
  opened_via TEXT,                     -- branch | app | agent | kiosk (v10 onboarding cohort)
  opened_city TEXT
);

CREATE TABLE IF NOT EXISTS account_devices (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  device_id TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  PRIMARY KEY (account_id, device_id)
);
CREATE INDEX IF NOT EXISTS ix_devices_device ON account_devices(device_id);

CREATE TABLE IF NOT EXISTS payees (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  payee_id TEXT NOT NULL REFERENCES accounts(id),
  added_at TEXT NOT NULL,
  PRIMARY KEY (account_id, payee_id)
);

-- The ledger. One row = one balanced posting (debit sender, credit recipient).
CREATE TABLE IF NOT EXISTS transactions (
  id TEXT PRIMARY KEY,
  seq INTEGER NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'transfer',   -- transfer | external_credit | external_debit
  sender_id TEXT NOT NULL REFERENCES accounts(id),
  recipient_id TEXT NOT NULL REFERENCES accounts(id),
  amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
  channel TEXT NOT NULL DEFAULT 'upi',
  device_id TEXT,
  note TEXT,
  ts TEXT NOT NULL,
  intent_id TEXT,
  source TEXT NOT NULL DEFAULT 'seed',     -- seed | user | scenario | ambient | cohort_v10
  -- SEED/GROUND-TRUTH ONLY. No scorer may read this column.
  seed_attack TEXT,
  -- v10 SIMULATED location of the posting (display / investigation only; see vigil/geo)
  geo_city TEXT,
  geo_lat REAL,
  geo_lng REAL,
  geo_basis TEXT,                          -- atm_terminal | merchant_pos | device_gps | ip | kyc_home | branch
  geo_accuracy_m INTEGER,
  peer_geo_city TEXT,
  peer_geo_lat REAL,
  peer_geo_lng REAL
);
CREATE INDEX IF NOT EXISTS ix_tx_sender_ts ON transactions(sender_id, ts);
CREATE INDEX IF NOT EXISTS ix_tx_recipient_ts ON transactions(recipient_id, ts);

CREATE TABLE IF NOT EXISTS transaction_intents (
  id TEXT PRIMARY KEY,
  sender_id TEXT NOT NULL REFERENCES accounts(id),
  recipient_id TEXT NOT NULL REFERENCES accounts(id),
  amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
  note TEXT,
  channel TEXT NOT NULL DEFAULT 'upi',
  device_id TEXT,
  source TEXT NOT NULL DEFAULT 'user',
  state TEXT NOT NULL,
  tier INTEGER,
  decision_id TEXT,
  purpose TEXT,
  hold_id TEXT,
  transaction_id TEXT,
  provider TEXT,
  provider_ref TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_intents_sender ON transaction_intents(sender_id, created_at);
CREATE INDEX IF NOT EXISTS ix_intents_state ON transaction_intents(state);

CREATE TABLE IF NOT EXISTS intent_transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  intent_id TEXT NOT NULL REFERENCES transaction_intents(id),
  from_state TEXT,
  to_state TEXT NOT NULL,
  actor TEXT NOT NULL,                  -- system | customer | bank | contact | provider
  detail TEXT,
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_transitions_intent ON intent_transitions(intent_id, id);

-- Account journey events (TrailScore / ContextFlag input).
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  event_type TEXT NOT NULL,
  payload TEXT,                         -- JSON
  ts TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'seed'   -- seed | user | scenario | simulated_context
);
CREATE INDEX IF NOT EXISTS ix_events_account_ts ON events(account_id, ts);

-- Append-only decision records. Never UPDATE.
CREATE TABLE IF NOT EXISTS risk_decisions (
  id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL REFERENCES transaction_intents(id),
  sender_id TEXT NOT NULL,
  recipient_id TEXT NOT NULL,
  amount_paise INTEGER NOT NULL,
  final_score REAL NOT NULL,
  tier INTEGER NOT NULL,
  intervention TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  latency_ms REAL NOT NULL,
  payload_sha256 TEXT NOT NULL,
  record TEXT NOT NULL,                 -- full RiskDecision JSON
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_decisions_intent ON risk_decisions(intent_id);
CREATE TRIGGER IF NOT EXISTS trg_decisions_append_only
BEFORE UPDATE ON risk_decisions
BEGIN
  SELECT RAISE(ABORT, 'risk_decisions is append-only');
END;

CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL,
  decision_id TEXT NOT NULL,
  account_id TEXT NOT NULL,             -- sender
  recipient_id TEXT NOT NULL,
  tier INTEGER NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',  -- open | resolved
  resolution TEXT,
  headline TEXT NOT NULL,
  amount_paise INTEGER NOT NULL,
  ts TEXT NOT NULL,
  resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_account_ts ON alerts(account_id, ts);

CREATE TABLE IF NOT EXISTS scoped_holds (
  id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL,
  account_id TEXT NOT NULL,             -- sender; inbound money is never held
  held_paise INTEGER NOT NULL CHECK (held_paise > 0),
  reference TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  review_by TEXT NOT NULL,
  released_at TEXT,
  outcome TEXT                          -- released | rejected | cancelled_by_customer
);

CREATE TABLE IF NOT EXISTS trusted_contacts (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  name TEXT NOT NULL,
  relation TEXT NOT NULL,
  phone_masked TEXT NOT NULL,
  token TEXT NOT NULL UNIQUE,
  nominated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS circuit_breaker_events (
  id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL,
  decision_id TEXT NOT NULL,
  contact_id TEXT NOT NULL REFERENCES trusted_contacts(id),
  payload TEXT NOT NULL,                -- JSON facts sent to the contact
  fired_at TEXT NOT NULL,
  response TEXT,                        -- acknowledged | calling_user | marked_expected
  responded_at TEXT
);

-- Simulated external fraud intelligence (registry-style).
CREATE TABLE IF NOT EXISTS external_intel (
  identifier TEXT PRIMARY KEY,
  status TEXT NOT NULL,                 -- clean | watchlist | reported | confirmed_mule
  risk_score REAL NOT NULL,
  reason_codes TEXT NOT NULL,           -- JSON list
  source TEXT NOT NULL,
  last_updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fraud_labels (
  id TEXT PRIMARY KEY,
  transaction_id TEXT NOT NULL REFERENCES transactions(id),
  grade TEXT NOT NULL,                  -- reported_unverified | bank_confirmed
  label TEXT NOT NULL,
  labelled_by TEXT NOT NULL,
  ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS taint_runs (
  id TEXT PRIMARY KEY,
  labels_hash TEXT NOT NULL,
  through_seq INTEGER NOT NULL,
  result TEXT NOT NULL,                 -- JSON summary
  digest TEXT NOT NULL,
  ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_attempts (
  id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  status TEXT NOT NULL,                 -- created | succeeded | failed
  provider_order_id TEXT,
  provider_payment_id TEXT,
  detail TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_runs (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL,
  state TEXT NOT NULL,
  step INTEGER NOT NULL DEFAULT 0,
  log TEXT NOT NULL DEFAULT '[]',
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- v8: close monitoring — accounts an analyst pinned for watching. Operator state about the current world,
-- so a demo reset clears it like every other table. Watching never changes a status or a payment tier.
-- v10: static reference data for SIMULATED locations (re-loaded idempotently at startup, not wiped by a reset).
CREATE TABLE IF NOT EXISTS geo_cities (
  city TEXT PRIMARY KEY,
  state TEXT,
  country TEXT,
  lat REAL,
  lng REAL,
  tier INTEGER,
  kind TEXT
);

CREATE TABLE IF NOT EXISTS atm_terminals (
  terminal_id TEXT PRIMARY KEY,
  city TEXT,
  lat REAL,
  lng REAL,
  bank TEXT,
  site TEXT
);

-- v10 Copilot: deterministic incidents + conversations. Operator state about the current world (cleared on reset).
CREATE TABLE IF NOT EXISTS copilot_incidents (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  score REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',   -- open | acknowledged | dismissed | resolved
  entity_ids TEXT NOT NULL,              -- JSON list of account ids
  tx_ids TEXT NOT NULL DEFAULT '[]',     -- JSON list
  title TEXT NOT NULL,
  summary_json TEXT NOT NULL,            -- facts, score_parts, engine, cached brief
  dedupe_key TEXT UNIQUE,
  created_ts TEXT NOT NULL,
  updated_ts TEXT NOT NULL,
  opened_by TEXT NOT NULL DEFAULT 'engine',
  llm_used INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_incidents_status ON copilot_incidents(status, score);

CREATE TABLE IF NOT EXISTS copilot_threads (
  id TEXT PRIMARY KEY,
  incident_id TEXT,
  title TEXT NOT NULL,
  created_ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS copilot_messages (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  role TEXT NOT NULL,                    -- user | assistant
  content TEXT NOT NULL,
  tool_calls_json TEXT NOT NULL DEFAULT '[]',
  ts TEXT NOT NULL,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_messages_thread ON copilot_messages(thread_id, ts);

CREATE TABLE IF NOT EXISTS watchlist (
  account_id TEXT PRIMARY KEY,
  note TEXT,
  added_by TEXT NOT NULL DEFAULT 'operator',
  added_at TEXT NOT NULL
);

"""World digest (overview-v10 P0): the seeded world's pre-existing rows must stay byte-identical.

The v10 work adds columns (geo, opening channel) and appends new rows (the onboarding cohort, tagged
`source='cohort_v10'`) AFTER the main seed. Neither may change a single pre-existing row: this digest hashes
only the columns that existed before v10, over the rows that existed before v10, for a fixed anchor.
If this test fails, the demo world changed — find out why before updating the constant.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

ANCHOR = datetime(2026, 10, 1, 6, 0, 0, tzinfo=timezone.utc)

TX_COLS = ("id", "ts", "sender_id", "recipient_id", "amount_paise", "kind", "channel", "device_id")
ACCOUNT_COLS = ("id", "display_name", "kind", "primary_device", "opened_at", "persona", "daily_limit_paise",
                "is_demo_customer", "seed_role")

# Recorded at P0 (overview-v10 baseline, on top of 278541c).
EXPECTED_TX = "698bb4f7ea9483957644bce16983282c56650f7b5fbbb445a5cb7297052135e4"
EXPECTED_ACCOUNTS = "736b33c44c7fde4fb972f387a2225ff9fc333777bcff2734b91bef8f359f4c0f"
EXPECTED_N_TX = 30983
EXPECTED_N_ACCOUNTS = 553


def world_digest(db) -> tuple[str, str, int, int]:
    """(tx digest, account digest, tx rows, account rows) over pre-v10 columns and rows."""
    try:
        from vigil.sim import cohort_v10
        cohort = set(cohort_v10.account_ids())
    except ImportError:
        cohort = set()
    h_tx = hashlib.sha256()
    n_tx = 0
    for r in db.q(f"SELECT {', '.join(TX_COLS)}, source FROM transactions ORDER BY seq"):
        if r["source"] == "cohort_v10":
            continue
        h_tx.update(repr(tuple(r[c] for c in TX_COLS)).encode())
        n_tx += 1
    h_ac = hashlib.sha256()
    n_ac = 0
    for r in db.q(f"SELECT {', '.join(ACCOUNT_COLS)} FROM accounts ORDER BY id"):
        if r["id"] in cohort:
            continue
        h_ac.update(repr(tuple(r[c] for c in ACCOUNT_COLS)).encode())
        n_ac += 1
    return h_tx.hexdigest(), h_ac.hexdigest(), n_tx, n_ac


def test_preexisting_world_is_byte_identical():
    from vigil import db
    from vigil.sim import seed

    db.connect()
    seed.seed(anchor=ANCHOR)
    tx, ac, n_tx, n_ac = world_digest(db)
    assert (tx, ac, n_tx, n_ac) == (EXPECTED_TX, EXPECTED_ACCOUNTS, EXPECTED_N_TX, EXPECTED_N_ACCOUNTS), (tx, ac, n_tx, n_ac)

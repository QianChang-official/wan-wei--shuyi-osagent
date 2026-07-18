"""Dream engine — placeholder for P1, full implementation in P4.

The scheduler is started from main.py lifespan as a daemon thread.
It checks dream gates every *interval_seconds* and, when all gates pass,
runs the four-phase consolidation (orient/gather/consolidate/prune) plus
dream association and emotional digestion.

P1 status: scheduler loop runs, but the inner dream logic is a no-op
(``_run_dream`` logs and returns immediately).  This lets us validate the
lifespan wiring, thread lifecycle, and /soul/dream manual trigger without
waiting for P4.
"""

import threading
import time
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# P1 placeholder — no-op dream run
# ---------------------------------------------------------------------------

def _run_dream(soul_id: str) -> dict:
    """Placeholder dream run.  Returns a skeleton artifact."""
    logger.info("dream placeholder: _run_dream called for soul_id=%s", soul_id)
    return {
        "soul_id": soul_id,
        "status": "placeholder",
        "phases": {},
        "new_edges": 0,
        "merged_capsules": 0,
        "pruned_capsules": 0,
        "synthesized_insights": 0,
        "emotional_events_digested": 0,
    }


# ---------------------------------------------------------------------------
# Gate checks (placeholder — always returns True for P1 testing)
# ---------------------------------------------------------------------------

def _should_dream(soul_id: str) -> bool:
    """Check the three dream gates.

    Gate 1: time gate  — ≥ MIN_HOURS since last_dream_at
    Gate 2: session gate — ≥ MIN_SESSIONS new conversation_turns
    Gate 3: lock gate   — no active dream_lock held

    P1: simplified to always-True so manual /soul/dream triggers work.
    """
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_dream(soul_id: str) -> dict:
    """Manually trigger a dream cycle for *soul_id*.

    This is the function called by the ``POST /soul/dream`` endpoint.
    """
    return _run_dream(soul_id)


def run_dream_scheduler(interval_seconds: int = 600, stop_event: threading.Event | None = None) -> None:
    """Blocking background loop.  Call from a daemon thread.

    Every *interval_seconds* the scheduler checks every soul that has a
    dream_lock row and, if all gates pass, runs the dream cycle.

    P1: the loop spins but the inner ``_run_dream`` is a no-op.
    """
    from ..db import get_conn

    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        stop_event.wait(timeout=interval_seconds)
        if stop_event.is_set():
            break
        try:
            conn = get_conn()
            rows = conn.execute(
                "SELECT soul_id FROM dream_lock"
            ).fetchall()
            for row in rows:
                soul_id = row["soul_id"]
                try:
                    if _should_dream(soul_id):
                        _run_dream(soul_id)
                except Exception:
                    # Per-soul failure must not kill the scheduler
                    logger.exception("dream scheduler failed for soul_id=%s", soul_id)
        except Exception:
            logger.exception("dream scheduler main loop failed")

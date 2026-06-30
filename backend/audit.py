"""Per-request audit log (Phase 2 observability).

The product sells *auditable* answers to regulated customers, so every request
gets one durable, structured record: what was asked, which tool ran, a compact
summary of the result, timing, and any guard repairs. We write JSONL (one JSON
object per line) so the log is append-only, greppable, and trivially ingestible
by downstream tooling without a parser.

Design rules:
- We persist a *summary* of the result, never the raw rows. Row data can be PII
  and would bloat/leak the log; we keep scalars and replace lists with counts.
- Logging must never break the request path. Any write failure is swallowed
  (warned via the normal logger), never raised back into the handler.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# Keys whose values are inherently scalar summaries worth keeping verbatim.
# We don't hard-restrict to these — any scalar is kept — but this documents the
# intent: counts/sums/flags stay, row lists get collapsed.
_SCALAR_HINT_KEYS = {
    "count",
    "revenue",
    "total_count",
    "by",
    "group_by",
    "order_status",
}


def summarize_result(result: Optional[dict]) -> Optional[dict]:
    """Collapse a tool result into a compact, row-free summary.

    Scalars (and dict values) are kept as-is; any list value is replaced by its
    length under ``<key>_count`` so we record *how many* rows came back without
    persisting the rows themselves (PII / log-bloat avoidance).
    """
    if result is None:
        return None
    summary: dict = {}
    for key, value in result.items():
        if isinstance(value, list):
            summary[key + "_count"] = len(value)
        else:
            summary[key] = value
    return summary


class AuditLogger:
    """Module-level singleton that appends audit records as JSONL.

    Uses a dedicated ``logging.Logger`` named "audit" with a ``FileHandler``
    whose formatter emits the bare message, so each record is exactly one JSON
    line. The handler is built lazily/once from settings; the target directory
    is created if missing.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._logger: Optional[logging.Logger] = None
        self._init_failed = False

    def _get_logger(self) -> Optional[logging.Logger]:
        if self._logger is not None:
            return self._logger
        if self._init_failed:
            return None
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            # Name the logger per-path so distinct AuditLogger instances (e.g.
            # in tests) never share a handler and cross-write each other's file.
            name = "audit." + os.path.abspath(self.path)
            audit_logger = logging.getLogger(name)
            audit_logger.setLevel(logging.INFO)
            # Don't double-write through the root logger's handlers.
            audit_logger.propagate = False
            # Avoid stacking handlers if re-initialized (reloads).
            if not any(
                isinstance(h, logging.FileHandler)
                and getattr(h, "baseFilename", None) == os.path.abspath(self.path)
                for h in audit_logger.handlers
            ):
                handler = logging.FileHandler(self.path, encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(message)s"))
                audit_logger.addHandler(handler)
            self._logger = audit_logger
            return self._logger
        except Exception as e:  # noqa: BLE001 - logging must never break requests
            logger.warning("Audit logger init failed (%s); audit disabled", e)
            self._init_failed = True
            return None

    def log(self, record: dict) -> None:
        """Append one audit record as a JSON line. Never raises."""
        try:
            audit_logger = self._get_logger()
            if audit_logger is None:
                return
            audit_logger.info(json.dumps(record, default=str, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001 - swallow, never break the request
            logger.warning("Failed to write audit record: %s", e)


def build_record(
    request_id: str,
    question: str,
    response: dict,
    latency_ms: int,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict:
    """Assemble the audit record from a ``process_question`` response dict.

    Centralized so main.py stays thin and the field shape is tested in one
    place. B-X identity: every answer is attributable to a user and a
    conversation (both nullable pre-auth).
    """
    guard = response.get("guard") or {}
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "question": question,
        "operation": response.get("operation"),
        "filters": response.get("filters"),
        "result_summary": summarize_result(response.get("result")),
        "source": response.get("source"),
        "cached": bool(response.get("cached", False)),
        "guard_applied": guard.get("applied", []),
        "error": response.get("error"),
        "latency_ms": latency_ms,
        "user_id": user_id,
        "session_id": session_id,
    }


# Module-level singleton, configured from settings.
audit_logger = AuditLogger(settings.audit_log_path)

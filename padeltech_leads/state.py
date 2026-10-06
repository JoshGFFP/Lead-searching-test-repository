"""The system's hidden memory: which applications it has already seen, analysed
and reported. Stored as one JSON file that the daily job commits back to the
repository, so nobody has to manage a database.

It also decides, for each application PlanIt returns, whether anything
*meaningful* has changed since we last looked.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import config

APPROVED_STATES = {"Permitted", "Conditions"}
REFUSED_STATES = {"Rejected"}
WITHDRAWN_STATES = {"Withdrawn"}

# Events, in the order they're shown on a lead card.
EVENT_LABELS = {
    "new": "🆕 New application",
    "approved": "✅ Planning permission granted",
    "courts_up": "📈 Number of courts increased",
    "revised": "📝 Revised proposal / plans",
    "construction": "🏗️ Construction appears imminent",
    "major_developer": "🏢 Major developer identified",
    "refused": "❌ Refused",
    "withdrawn": "↩️ Withdrawn",
}
# Events that justify reporting a lead we've already reported before.
REREPORT_EVENTS = {"approved", "courts_up", "revised", "construction", "major_developer"}


def _other(record: dict, key: str):
    return (record.get("other_fields") or {}).get(key)


def fingerprint(record: dict) -> dict:
    """The fields whose change is meaningful. Cosmetic status text changes
    ("Registered" -> "Under consultation") and re-scrapes are deliberately ignored."""
    return {
        "description": (record.get("description") or "").strip(),
        "app_state": record.get("app_state"),
        "decided_date": record.get("decided_date"),
        "decision": _other(record, "decision"),
        "app_type": record.get("app_type"),
    }


def mentions_padel(record: dict) -> bool:
    text = (record.get("description") or "").lower()
    return "padel" in text or "pádel" in text


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@dataclass
class Plan:
    action: str  # "skip" | "triage" | "analyse"
    events: list[str] = field(default_factory=list)


class State:
    def __init__(self, path: str = config.STATE_PATH):
        self.path = path
        self.data = {"version": 1, "last_success": None, "applications": {}}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)

    @property
    def apps(self) -> dict:
        return self.data["applications"]

    @property
    def is_first_run(self) -> bool:
        return not self.data.get("last_success")

    def lookback_start(self, today: date) -> date:
        if self.is_first_run:
            return today - timedelta(days=config.FIRST_RUN_LOOKBACK_DAYS)
        last = _parse_date(self.data["last_success"]) or today
        # Overlap by a day so nothing slips between runs; cap catch-up length.
        start = last - timedelta(days=1)
        return max(start, today - timedelta(days=config.MAX_LOOKBACK_DAYS))

    def plan(self, record: dict, today: date) -> Plan:
        name = record["name"]
        entry = self.apps.get(name)
        padel = mentions_padel(record) or config.HIGH_SIGNAL_GROUP in record.get("_groups", [])
        fp = fingerprint(record)

        if entry is None:
            start = _parse_date(record.get("start_date"))
            decided = _parse_date(record.get("decided_date"))
            fresh_start = start and start >= today - timedelta(days=config.FRESH_APPLICATION_DAYS)
            fresh_decision = decided and decided >= today - timedelta(days=config.FRESH_DECISION_DAYS)
            if not (fresh_start or fresh_decision):
                self.remember(record, today, analysed=False)
                return Plan("skip")
            if not padel and record.get("app_type") in config.NOISY_GROUP_EXCLUDED_APP_TYPES:
                self.remember(record, today, analysed=True, relevant=False)
                return Plan("skip")
            events = ["new"]
            if fresh_decision and record.get("app_state") in APPROVED_STATES:
                events.append("approved")
            return Plan("analyse" if padel else "triage", events)

        entry["last_seen"] = today.isoformat()
        old = entry.get("fp", {})
        changed = {k for k in fp if fp[k] != old.get(k)}
        if not changed:
            return Plan("skip")

        events = []
        if "app_state" in changed:
            if fp["app_state"] in APPROVED_STATES and old.get("app_state") not in APPROVED_STATES:
                events.append("approved")
            elif fp["app_state"] in REFUSED_STATES:
                events.append("refused")
            elif fp["app_state"] in WITHDRAWN_STATES:
                events.append("withdrawn")
        if "description" in changed:
            events.append("revised")

        known_irrelevant = entry.get("relevant") is False or not entry.get("analysed")
        if known_irrelevant and not padel and "description" not in changed:
            # A status change on something we already know isn't a lead.
            entry["fp"] = fp
            return Plan("skip")
        if not events:
            entry["fp"] = fp
            return Plan("skip")
        if padel or entry.get("relevant"):
            return Plan("analyse", events)
        return Plan("triage", events)

    def remember(self, record: dict, today: date, *, analysed: bool, relevant: bool | None = None,
                 analysis: dict | None = None, score: int | None = None, band: str | None = None):
        name = record["name"]
        entry = self.apps.setdefault(name, {"first_seen": today.isoformat()})
        entry.update({
            "fp": fingerprint(record),
            "last_seen": today.isoformat(),
            "analysed": analysed,
            "relevant": relevant,
        })
        if analysis is not None:
            entry["courts"] = analysis.get("courts")
            entry["major_developer"] = analysis.get("major_developer_involved", False)
            entry["headline"] = analysis.get("headline")
            entry["score"] = score
            entry["band"] = band

    def mark_reported(self, name: str, today: date):
        self.apps[name]["reported_on"] = today.isoformat()

    def prune(self, today: date):
        cutoff = (today - timedelta(days=config.STATE_RETENTION_DAYS)).isoformat()
        for name in [n for n, e in self.apps.items() if e.get("last_seen", "") < cutoff]:
            del self.apps[name]

    def save(self, today: date):
        self.data["last_success"] = today.isoformat()
        self.prune(today)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, self.path)

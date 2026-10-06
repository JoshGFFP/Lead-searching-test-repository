"""Fetch planning applications from the free UK PlanIt API."""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from . import config

log = logging.getLogger(__name__)


class PlanItError(RuntimeError):
    pass


def _get(params: dict) -> dict:
    url = f"{config.PLANIT_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": config.PLANIT_USER_AGENT})
    last_error = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 429:
                wait = int(e.headers.get("Retry-After") or 30)
                log.warning("PlanIt rate limit hit; waiting %ss", wait)
                time.sleep(min(wait, 300))
                continue
            if e.code >= 500:
                time.sleep(10 * (attempt + 1))
                continue
            body = e.read().decode("utf-8", "replace")[:300]
            raise PlanItError(f"PlanIt returned HTTP {e.code}: {body}") from e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_error = e
            time.sleep(10 * (attempt + 1))
    raise PlanItError(f"PlanIt request failed after retries: {last_error}")


def search_changed(search: str, since: date) -> list[dict]:
    """Every application matching `search` whose data changed on/after `since`."""
    records: list[dict] = []
    page = 1
    while True:
        data = _get({
            "search": search,
            "different_start": since.isoformat(),
            "pg_sz": config.PLANIT_PAGE_SIZE,
            "page": page,
            "compress": "on",
        })
        if data.get("error"):
            raise PlanItError(f"PlanIt error: {data['error']}")
        batch = data.get("records") or []
        records.extend(batch)
        total = data.get("total") or 0
        if not batch or len(records) >= total:
            return records
        page += 1
        time.sleep(1)  # be polite to a free service


def fetch_all(since: date) -> dict[str, dict]:
    """Run every search group. Returns {planit_name: record}, each record tagged
    with the search groups that matched it."""
    found: dict[str, dict] = {}
    for group, search in config.SEARCH_GROUPS.items():
        records = search_changed(search, since)
        log.info("PlanIt group %-8s %4d records changed since %s", group, len(records), since)
        for record in records:
            name = record.get("name")
            if not name:
                continue
            entry = found.setdefault(name, record)
            entry.setdefault("_groups", [])
            if group not in entry["_groups"]:
                entry["_groups"].append(group)
        time.sleep(1)
    return found

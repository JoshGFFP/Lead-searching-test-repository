"""The daily job: PlanIt -> filter -> Claude -> score -> email.

Run it with:
    python -m padeltech_leads.main             # real run: emails the report and saves memory
    python -m padeltech_leads.main --dry-run   # writes reports/ files only; no email, memory untouched
    python -m padeltech_leads.main --dry-run --no-ai   # pipeline test without Claude (test-mode analysis)
    python -m padeltech_leads.main --test-email        # real analysis, "[TEST]" email, memory untouched
"""

import argparse
import logging
import os
import re
import sys
import traceback
from datetime import date

from . import config, mailer, planit, report, scoring
from .report import Lead, Summary
from .state import EVENT_LABELS, REREPORT_EVENTS, State, mentions_padel

log = logging.getLogger("padeltech")

MAX_LEADS_IN_EMAIL = 25


def _test_mode_analysis(record: dict) -> dict:
    """Crude stand-in for Claude, used only with --no-ai to test the plumbing."""
    text = record.get("description") or ""
    m = re.search(r"(\d+)\s*(?:no\.?\s*)?(?:new\s+)?(?:outdoor\s+|indoor\s+|covered\s+)?padel", text, re.I)
    unknown = {"name": "Unknown", "basis": "unknown"}
    padel = mentions_padel(record)
    return {
        "headline": f"[TEST MODE] {text[:60]} — {record.get('area_name')}",
        "padel_relevance": "explicit" if padel else "possible",
        "courts": int(m.group(1)) if m else None,
        "courts_basis": "confirmed" if m else "unknown",
        "indoor_outdoor": "unknown",
        "applicant": unknown, "developer": unknown, "planning_agent": unknown,
        "architect": unknown, "operator": unknown,
        "applicant_type": "unknown",
        "site_location": record.get("address") or "Unknown",
        "planning_stage": "approved" if record.get("app_state") in ("Permitted", "Conditions") else "submitted_pending",
        "construction_imminent": False,
        "likely_to_proceed": "unknown",
        "development_scale": "unknown",
        "major_developer_involved": False,
        "padeltech_opportunity": "moderate" if padel else "weak",
        "confirmed_facts": [text[:200]],
        "ai_inferences": ["TEST MODE — no AI analysis was run"],
        "why_lead": "Test mode: keyword match only.",
        "recommended_action": "Test mode — ignore.",
    }


def run(today: date, dry_run: bool, no_ai: bool, test_email: bool = False) -> int:
    state = State()
    summary = Summary()
    since = state.lookback_start(today)
    log.info("Looking for applications changed since %s (first run: %s)", since, state.is_first_run)

    records = planit.fetch_all(since)
    summary.checked = len(records)

    analyse_queue, triage_queue = [], []
    for record in records.values():
        plan = state.plan(record, today)
        if plan.action == "analyse":
            analyse_queue.append((record, plan.events))
        elif plan.action == "triage":
            triage_queue.append((record, plan.events))
    summary.candidates = len(analyse_queue) + len(triage_queue)
    log.info("%d records -> %d direct padel candidates, %d to triage",
             len(records), len(analyse_queue), len(triage_queue))

    claude = None
    if not no_ai:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set (add it as a GitHub Actions secret)")
        from .analyse import Claude
        claude = Claude()

    if triage_queue:
        if claude:
            keep = claude.triage([r for r, _ in triage_queue])
        else:
            keep = set()
        for record, events in triage_queue:
            if record["name"] in keep:
                analyse_queue.append((record, events))
            else:
                state.remember(record, today, analysed=True, relevant=False)
        log.info("Triage kept %d of %d", len(keep), len(triage_queue))

    # Padel mentions and fresh approvals first, in case the safety cap is reached.
    analyse_queue.sort(key=lambda x: (not mentions_padel(x[0]), "approved" not in x[1]))
    if len(analyse_queue) > config.MAX_ANALYSES_PER_RUN:
        deferred = len(analyse_queue) - config.MAX_ANALYSES_PER_RUN
        summary.warnings.append(f"{deferred} candidates deferred to tomorrow (daily analysis cap reached)")
        analyse_queue = analyse_queue[:config.MAX_ANALYSES_PER_RUN]

    leads: list[Lead] = []
    for record, events in analyse_queue:
        name = record["name"]
        previous = dict(state.apps.get(name) or {})
        analysis = claude.analyse(record, events, previous) if claude else _test_mode_analysis(record)
        if analysis is None:
            summary.warnings.append(f"Could not analyse {record.get('area_name')} {record.get('uid')} — will retry")
            continue
        summary.ai_reviewed += 1
        points, reasons = scoring.score(analysis)
        band = scoring.band(points)
        events = list(events)

        if previous.get("analysed") and previous.get("relevant"):
            old_courts, new_courts = previous.get("courts"), analysis.get("courts")
            if isinstance(old_courts, int) and isinstance(new_courts, int) and new_courts > old_courts:
                events.append("courts_up")
            if analysis.get("major_developer_involved") and not previous.get("major_developer"):
                events.append("major_developer")
        if analysis.get("construction_imminent") and not previous.get("construction"):
            events.append("construction")

        relevant = analysis.get("padel_relevance") != "no"
        state.remember(record, today, analysed=True, relevant=relevant, analysis=analysis,
                       score=points, band=band)
        state.apps[name]["construction"] = bool(analysis.get("construction_imminent")) or bool(previous.get("construction"))

        already_reported = bool(previous.get("reported_on"))
        if band == "IGNORE":
            if already_reported and {"refused", "withdrawn"} & set(events):
                label = EVENT_LABELS["refused" if "refused" in events else "withdrawn"]
                summary.updates.append(f"{previous.get('headline') or analysis.get('headline')} "
                                       f"({record.get('area_name')} {record.get('uid')}): {label}")
            continue
        if already_reported and not (set(events) & REREPORT_EVENTS):
            continue
        leads.append(Lead(record, analysis, points, band, reasons, events))

    leads.sort(key=lambda l: -l.score)
    if len(leads) > MAX_LEADS_IN_EMAIL:
        summary.warnings.append(f"{len(leads) - MAX_LEADS_IN_EMAIL} lower-scoring leads not shown")
        leads = leads[:MAX_LEADS_IN_EMAIL]

    if claude:
        researchable = [l for l in leads if l.score >= config.CONTACT_RESEARCH_MIN_SCORE]
        for lead in researchable[:config.MAX_CONTACT_RESEARCH_PER_RUN]:
            try:
                lead.contacts = claude.research_contacts(lead.record, lead.analysis)
            except Exception as e:  # contact research is a bonus; never fail the report for it
                log.warning("Contact research failed for %s: %s", lead.record.get("name"), e)

    subject = report.subject(today, leads)
    text = report.render_text(today, leads, summary)
    html = report.render_html(today, leads, summary)
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    for suffix, body in (("html", html), ("txt", text)):
        with open(os.path.join(config.REPORT_DIR, f"report-{today.isoformat()}.{suffix}"), "w", encoding="utf-8") as f:
            f.write(body)
    log.info("Report: %s", subject)

    if claude:
        cost = claude.estimated_cost_usd()
        log.info("Claude usage: %s%s", claude.usage, f" (~${cost:.2f})" if cost is not None else "")

    if dry_run:
        log.info("Dry run: email not sent, memory not saved. See %s/", config.REPORT_DIR)
        return 0

    if test_email:
        mailer.send("[TEST] " + subject, text, html)
        log.info("Test email sent to %s (memory not saved)", ", ".join(config.EMAIL_TO))
        return 0

    mailer.send(subject, text, html)
    log.info("Email sent to %s", ", ".join(config.EMAIL_TO))
    for lead in leads:
        state.mark_reported(lead.record["name"], today)
    state.save(today)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PadelTech daily planning lead report")
    parser.add_argument("--dry-run", action="store_true", help="don't email or save memory")
    parser.add_argument("--no-ai", action="store_true", help="skip Claude (pipeline test only)")
    parser.add_argument("--test-email", action="store_true",
                        help="send the report with a [TEST] subject but don't save memory")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    today = date.today()
    try:
        return run(today, dry_run=args.dry_run, no_ai=args.no_ai, test_email=args.test_email)
    except Exception as e:
        log.error("Run failed: %s", e)
        traceback.print_exc()
        if not args.dry_run:
            try:
                mailer.send(f"⚠️ PadelTech lead report failed {today:%d %b}",
                            f"Today's lead report could not be produced.\n\nError: {e}\n\n"
                            "Nothing has been lost: the next run will catch up automatically. "
                            "If this repeats, open the repository's Actions tab to see the full log.",
                            f"<p>Today's lead report could not be produced.</p><p><b>Error:</b> {e}</p>"
                            "<p>Nothing has been lost: the next run will catch up automatically. If this repeats, "
                            "open the repository's <b>Actions</b> tab to see the full log.</p>")
            except Exception as mail_error:
                log.error("Could not send failure email either: %s", mail_error)
        return 1


if __name__ == "__main__":
    sys.exit(main())

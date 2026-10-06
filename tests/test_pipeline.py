from datetime import date

from padeltech_leads import report, scoring
from padeltech_leads.state import State

TODAY = date(2026, 10, 6)


def record(**overrides):
    r = {
        "name": "Leeds/26/1234/FUL",
        "uid": "26/1234/FUL",
        "area_name": "Leeds",
        "description": "Erection of 6 outdoor padel courts with floodlighting",
        "app_state": "Undecided",
        "app_type": "Full",
        "start_date": "2026-10-01",
        "decided_date": None,
        "other_fields": {},
        "url": "https://example.gov.uk/app",
        "_groups": ["padel"],
    }
    r.update(overrides)
    return r


def analysis(**overrides):
    unknown = {"name": "Unknown", "basis": "unknown"}
    a = {
        "headline": "6 new outdoor padel courts — Leeds",
        "padel_relevance": "explicit",
        "courts": 6,
        "courts_basis": "confirmed",
        "indoor_outdoor": "outdoor",
        "applicant": {"name": "XYZ Leisure Ltd", "basis": "confirmed"},
        "developer": unknown, "planning_agent": unknown, "architect": unknown, "operator": unknown,
        "applicant_type": "commercial_padel_operator",
        "planning_stage": "submitted_pending",
        "construction_imminent": False,
        "development_scale": "medium",
        "major_developer_involved": False,
        "likely_to_proceed": "high",
        "padeltech_opportunity": "strong",
        "confirmed_facts": ["Six outdoor padel courts proposed"],
        "ai_inferences": ["Commercial operator"],
        "why_lead": "Explicit padel scheme.",
        "recommended_action": "Call the applicant.",
        "site_location": "Leeds",
    }
    a.update(overrides)
    return a


def fresh_state(tmp_path):
    return State(str(tmp_path / "state.json"))


def test_explicit_commercial_padel_scheme_is_hot():
    points, _ = scoring.score(analysis())
    assert scoring.band(points) == "HOT"


def test_no_padel_connection_is_ignored():
    points, reasons = scoring.score(analysis(padel_relevance="no", courts=None))
    assert points <= 30 and scoring.band(points) == "IGNORE"
    assert any("capped" in r for r in reasons)


def test_refused_is_capped():
    points, _ = scoring.score(analysis(planning_stage="refused"))
    assert points <= 35


def test_new_padel_application_goes_to_analysis(tmp_path):
    plan = fresh_state(tmp_path).plan(record(), TODAY)
    assert plan.action == "analyse" and plan.events == ["new"]


def test_old_never_seen_application_is_remembered_silently(tmp_path):
    state = fresh_state(tmp_path)
    plan = state.plan(record(start_date="2025-01-01"), TODAY)
    assert plan.action == "skip"
    assert "Leeds/26/1234/FUL" in state.apps


def test_noisy_keyword_match_goes_to_triage(tmp_path):
    r = record(description="Change of use of unit to gym", _groups=["leisure"])
    assert fresh_state(tmp_path).plan(r, TODAY).action == "triage"


def test_unchanged_application_is_not_repeated(tmp_path):
    state = fresh_state(tmp_path)
    r = record()
    state.remember(r, TODAY, analysed=True, relevant=True, analysis=analysis(), score=85, band="HOT")
    state.mark_reported(r["name"], TODAY)
    rescrape = dict(r, other_fields={"status": "Under consultation"})  # cosmetic change only
    assert state.plan(rescrape, TODAY).action == "skip"


def test_approval_is_detected(tmp_path):
    state = fresh_state(tmp_path)
    r = record()
    state.remember(r, TODAY, analysed=True, relevant=True, analysis=analysis(), score=85, band="HOT")
    plan = state.plan(dict(r, app_state="Permitted", decided_date="2026-10-05"), TODAY)
    assert plan.action == "analyse" and "approved" in plan.events


def test_revised_description_is_detected(tmp_path):
    state = fresh_state(tmp_path)
    r = record()
    state.remember(r, TODAY, analysed=True, relevant=True, analysis=analysis(), score=85, band="HOT")
    plan = state.plan(dict(r, description="Erection of 8 outdoor padel courts"), TODAY)
    assert "revised" in plan.events


def test_status_change_on_irrelevant_application_is_ignored(tmp_path):
    state = fresh_state(tmp_path)
    r = record(description="Home gym in garage", _groups=["leisure"])
    state.remember(r, TODAY, analysed=True, relevant=False)
    assert state.plan(dict(r, app_state="Permitted"), TODAY).action == "skip"


def test_state_round_trip(tmp_path):
    state = fresh_state(tmp_path)
    state.remember(record(), TODAY, analysed=True, relevant=True, analysis=analysis(), score=85, band="HOT")
    state.save(TODAY)
    again = State(state.path)
    assert not again.is_first_run
    assert again.apps["Leeds/26/1234/FUL"]["courts"] == 6


def test_report_renders_and_marks_inferences():
    a = analysis(planning_agent={"name": "Smith Planning", "basis": "inferred"})
    points, reasons = scoring.score(a)
    lead = report.Lead(record(), a, points, scoring.band(points), reasons, ["new"])
    summary = report.Summary(checked=1500, candidates=42, ai_reviewed=18)
    text = report.render_text(TODAY, [lead], summary)
    html = report.render_html(TODAY, [lead], summary)
    assert "🔥 HOT LEADS" in text and "Applications checked: 1,500" in text
    assert "Smith Planning (AI inference)" in text
    assert "6 new outdoor padel courts" in html
    assert "no new qualified leads" in report.subject(TODAY, []).lower()

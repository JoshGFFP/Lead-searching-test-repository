"""Build the weekly email (HTML for the inbox, plain text as a fallback)."""

from dataclasses import dataclass, field
from datetime import date
from html import escape

from .state import EVENT_LABELS

SECTIONS = [("HOT", "🔥 HOT LEADS", "#c0392b"), ("GOOD", "🟠 GOOD LEADS", "#d35400"), ("WATCH", "👀 WATCHLIST", "#2c6e9b")]
STAGE_TEXT = {
    "submitted_pending": "Planning submitted — awaiting decision",
    "approved": "Planning permission granted",
    "condition_discharge": "Approved scheme — conditions being discharged",
    "refused": "Refused",
    "withdrawn": "Withdrawn",
    "appeal": "At appeal",
    "unknown": "Unknown",
}


@dataclass
class Lead:
    record: dict
    analysis: dict
    score: int
    band: str
    reasons: list[str]
    events: list[str]
    contacts: dict | None = None


@dataclass
class Summary:
    checked: int = 0
    candidates: int = 0
    ai_reviewed: int = 0
    period_start: date | None = None
    updates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _party(a: dict, key: str) -> str:
    p = a.get(key) or {}
    name = (p.get("name") or "Unknown").strip() or "Unknown"
    if name.lower() == "unknown":
        return "Unknown"
    return f"{name} (AI inference)" if p.get("basis") == "inferred" else name


def _courts(a: dict) -> str:
    c = a.get("courts")
    if c is None:
        return "Unknown"
    where = (a.get("indoor_outdoor") or "unknown").replace("_", " / ")
    text = f"{c}" + ("" if where == "unknown" else f" ({where})")
    return f"{text} (AI inference)" if a.get("courts_basis") == "inferred" else text


def contact_lines(lead: Lead) -> list[str]:
    a = lead.analysis
    lines = []
    for c in (lead.contacts or {}).get("contacts", []):
        bits = [f"{c['organisation']} — {c['role']}"]
        if c.get("website", "Unknown") != "Unknown":
            bits.append(c["website"])
        if c.get("contact_route", "Unknown") != "Unknown":
            bits.append(c["contact_route"])
        if c.get("basis") == "inferred":
            bits.append("(AI inference — verify)")
        lines.append(" · ".join(bits))
    if not lines:
        for key, role in (("applicant", "applicant"), ("planning_agent", "planning agent"),
                          ("developer", "developer"), ("architect", "architect"), ("operator", "operator")):
            who = _party(a, key)
            if who != "Unknown":
                lines.append(f"{who} — {role}")
    return lines or ["Unknown — see the council planning page"]


def _fields(lead: Lead) -> list[tuple[str, str]]:
    a, r = lead.analysis, lead.record
    return [
        ("Applicant", _party(a, "applicant")),
        ("Planning agent", _party(a, "planning_agent")),
        ("Planning authority", r.get("area_name") or "Unknown"),
        ("Application", r.get("uid") or "Unknown"),
        ("Site", a.get("site_location") or r.get("address") or "Unknown"),
        ("Status", STAGE_TEXT.get(a.get("planning_stage"), "Unknown")),
        ("Courts", _courts(a)),
    ]


def period(today: date, summary: Summary) -> str:
    if summary.period_start and summary.period_start < today:
        return f"{summary.period_start:%-d %b} – {today:%-d %B %Y}"
    return f"{today:%-d %B %Y}"


def subject(today: date, leads: list[Lead]) -> str:
    hot = sum(1 for l in leads if l.band == "HOT")
    good = sum(1 for l in leads if l.band == "GOOD")
    if not leads:
        return f"Weekly padel leads {today:%d %b}: no new qualified leads this week"
    return f"Weekly padel leads {today:%d %b}: {hot} HOT, {good} GOOD, {len(leads) - hot - good} watch"


def render_text(today: date, leads: list[Lead], summary: Summary) -> str:
    out = ["WEEKLY PADEL LEAD REPORT", period(today, summary), ""]
    n = 0
    for band, title, _ in SECTIONS:
        group = [l for l in leads if l.band == band]
        if not group:
            continue
        out += ["=" * 40, title, ""]
        for lead in group:
            n += 1
            a = lead.analysis
            out.append(f"{n}. {a.get('headline')}   [score {lead.score}]")
            if lead.events:
                out.append("   " + " | ".join(EVENT_LABELS[e] for e in lead.events if e in EVENT_LABELS))
            for label, value in _fields(lead):
                out.append(f"   {label}: {value}")
            out.append(f"   Why this is a lead: {a.get('why_lead')}")
            out.append("   Potential contacts:")
            out += [f"     - {c}" for c in contact_lines(lead)]
            out.append(f"   Recommended action: {a.get('recommended_action')}")
            out.append(f"   Official planning application: {lead.record.get('url') or lead.record.get('link')}")
            out.append("")
    if not leads:
        out += ["No new qualified leads this week.", ""]
    if summary.updates:
        out += ["=" * 40, "ℹ️ UPDATES ON EARLIER LEADS", ""] + [f" - {u}" for u in summary.updates] + [""]
    out += _summary_lines(leads, summary)
    return "\n".join(out)


def _summary_lines(leads: list[Lead], s: Summary) -> list[str]:
    count = lambda b: sum(1 for l in leads if l.band == b)  # noqa: E731
    lines = [
        "=" * 40, "WEEKLY SUMMARY", "",
        f"Applications checked: {s.checked:,}",
        f"Potential applications: {s.candidates:,}",
        f"AI-reviewed: {s.ai_reviewed:,}",
        f"New qualified leads: {len(leads)}",
        f"HOT: {count('HOT')}   GOOD: {count('GOOD')}   WATCH: {count('WATCH')}",
    ]
    lines += [f"⚠️ {w}" for w in s.warnings]
    return lines


def render_html(today: date, leads: list[Lead], summary: Summary) -> str:
    h = [
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:680px;margin:0 auto;color:#222;line-height:1.45">',
        '<h1 style="font-size:22px;margin:0">WEEKLY PADEL LEAD REPORT</h1>',
        f'<p style="margin:2px 0 18px;color:#666">{escape(period(today, summary))}</p>',
    ]
    n = 0
    for band, title, colour in SECTIONS:
        group = [l for l in leads if l.band == band]
        if not group:
            continue
        h.append(f'<h2 style="font-size:18px;border-bottom:3px solid {colour};padding-bottom:4px;margin-top:26px">{title}</h2>')
        for lead in group:
            n += 1
            h.append(_card_html(n, lead, colour))
    if not leads:
        h.append('<p style="font-size:16px">No new qualified leads this week. The system ran normally — '
                 'nothing met the quality bar.</p>')
    if summary.updates:
        h.append('<h2 style="font-size:18px;border-bottom:3px solid #999;padding-bottom:4px;margin-top:26px">ℹ️ UPDATES ON EARLIER LEADS</h2><ul>')
        h += [f"<li>{escape(u)}</li>" for u in summary.updates]
        h.append("</ul>")
    lines = _summary_lines(leads, summary)[3:]
    h.append('<h2 style="font-size:18px;border-bottom:3px solid #999;padding-bottom:4px;margin-top:26px">WEEKLY SUMMARY</h2>')
    h.append('<p style="margin:0">' + "<br>".join(escape(l) for l in lines) + "</p>")
    h.append('<p style="color:#888;font-size:12px;margin-top:22px">Scores: 80–100 HOT · 60–79 GOOD · 40–59 WATCH. '
             'Every lead found so far is in the attached spreadsheet. '
             '"AI inference" marks anything not stated in the planning record — please verify before relying on it. '
             'Data: UK PlanIt (planit.org.uk) and council planning portals.</p></div>')
    return "\n".join(h)


def _card_html(n: int, lead: Lead, colour: str) -> str:
    a, r = lead.analysis, lead.record
    url = r.get("url") or r.get("link") or ""
    rows = "".join(
        f'<tr><td style="color:#666;padding:2px 12px 2px 0;vertical-align:top;white-space:nowrap">{escape(k)}</td>'
        f'<td style="padding:2px 0">{escape(str(v))}</td></tr>'
        for k, v in _fields(lead)
    )
    events = " ".join(
        f'<span style="display:inline-block;background:#f3f3f3;border-radius:10px;padding:1px 8px;margin:2px 4px 2px 0;font-size:12px">{escape(EVENT_LABELS[e])}</span>'
        for e in lead.events if e in EVENT_LABELS
    )
    contacts = "".join(f"<li>{escape(c)}</li>" for c in contact_lines(lead))
    facts = "".join(f"<li>{escape(f)}</li>" for f in a.get("confirmed_facts", [])[:5])
    inferences = "".join(f"<li>{escape(f)}</li>" for f in a.get("ai_inferences", [])[:4])
    return f"""
<div style="border:1px solid #ddd;border-left:5px solid {colour};border-radius:6px;padding:12px 14px;margin:14px 0">
  <div style="font-size:16px;font-weight:bold">{n}. {escape(a.get('headline') or 'Untitled')}
    <span style="float:right;color:{colour}">{lead.score}/100</span></div>
  <div style="margin:4px 0 8px">{events}</div>
  <table style="border-collapse:collapse;font-size:14px">{rows}</table>
  <p style="margin:10px 0 4px"><b>Why this is a lead:</b> {escape(a.get('why_lead') or '')}</p>
  <p style="margin:6px 0 2px"><b>Potential contacts:</b></p><ul style="margin:0 0 6px 18px;padding:0;font-size:14px">{contacts}</ul>
  <p style="margin:6px 0"><b>Recommended action:</b> {escape(a.get('recommended_action') or '')}</p>
  <p style="margin:6px 0"><a href="{escape(url, quote=True)}" style="color:#1a5fb4">Official planning application →</a></p>
  <details style="font-size:13px;color:#555"><summary>Confirmed facts / AI inference / score breakdown</summary>
    <p style="margin:6px 0 0"><b>Confirmed fact</b></p><ul style="margin:0 0 0 18px;padding:0">{facts or '<li>None</li>'}</ul>
    <p style="margin:6px 0 0"><b>AI inference</b></p><ul style="margin:0 0 0 18px;padding:0">{inferences or '<li>None</li>'}</ul>
    <p style="margin:6px 0 0"><b>Score:</b> {escape('; '.join(lead.reasons))}</p>
  </details>
</div>"""

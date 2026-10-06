"""Turn Claude's structured analysis into a 0-100 lead score.

Claude extracts the facts; this file does the arithmetic, so the score is
consistent from day to day and every point can be explained.

    Factor                          Max   How points are awarded
    Padel relevance                  35   explicit 35 · likely 22 · possible 10 · none 0
    Number of courts                 15   6+ 15 · 4-5 12 · 2-3 9 · 1 5 · unknown 4 (if padel likely)
    Applicant / commercial type      15   padel operator 15 · gym/leisure or hotel 13 · developer 12 ·
                                          sports/tennis club 11 · school/university or council 9 ·
                                          other/unknown 5 · private house 3
    Planning stage                   15   approved or conditions being discharged 15 · submitted 10 ·
                                          appeal/unknown 6 · refused/withdrawn 0
    Construction appears imminent     5
    Development size                  5   major 5 · medium 3 · small/unknown 1
    People identified                 5   developer named +3 (major developer counts) · agent/architect named +2
    Likely to proceed                 5   high 5 · medium 3 · unknown 2 · low 0
                                    ---
                                    100

    Caps: no padel connection -> max 30 · PadelTech opportunity "none" -> max 30 ·
          refused/withdrawn -> max 35.

    Bands: 80-100 HOT · 60-79 GOOD · 40-59 WATCH · 0-39 IGNORE (not emailed)
"""

from . import config

PADEL = {"explicit": 35, "likely": 22, "possible": 10, "no": 0}
APPLICANT = {
    "commercial_padel_operator": 15,
    "gym_or_leisure_operator": 13,
    "hotel_or_resort": 13,
    "property_developer": 12,
    "sports_or_tennis_club": 11,
    "school_or_university": 9,
    "local_authority_or_public_body": 9,
    "other": 5,
    "unknown": 5,
    "private_individual_residential": 3,
}
STAGE = {
    "approved": 15,
    "condition_discharge": 15,
    "submitted_pending": 10,
    "appeal": 6,
    "unknown": 6,
    "refused": 0,
    "withdrawn": 0,
}
SCALE = {"major": 5, "medium": 3, "small": 1, "unknown": 1}
PROCEED = {"high": 5, "medium": 3, "unknown": 2, "low": 0}


def _known(party: dict | None) -> bool:
    name = (party or {}).get("name", "") or ""
    return bool(name.strip()) and name.strip().lower() != "unknown"


def score(a: dict) -> tuple[int, list[str]]:
    """Returns (score, list of human-readable reasons)."""
    parts: list[tuple[str, int]] = []
    padel = a.get("padel_relevance", "no")
    parts.append((f"padel relevance: {padel}", PADEL.get(padel, 0)))

    courts = a.get("courts")
    if isinstance(courts, int) and courts > 0:
        pts = 15 if courts >= 6 else 12 if courts >= 4 else 9 if courts >= 2 else 5
        parts.append((f"{courts} court(s)", pts))
    elif padel in ("explicit", "likely"):
        parts.append(("court count unknown", 4))

    applicant = a.get("applicant_type", "unknown")
    parts.append((f"applicant type: {applicant.replace('_', ' ')}", APPLICANT.get(applicant, 5)))

    stage = a.get("planning_stage", "unknown")
    parts.append((f"stage: {stage.replace('_', ' ')}", STAGE.get(stage, 6)))

    if a.get("construction_imminent"):
        parts.append(("construction appears imminent", 5))

    scale = a.get("development_scale", "unknown")
    parts.append((f"scale: {scale}", SCALE.get(scale, 1)))

    if a.get("major_developer_involved") or _known(a.get("developer")):
        parts.append(("developer identified", 3))
    if _known(a.get("planning_agent")) or _known(a.get("architect")):
        parts.append(("agent/architect identified", 2))

    proceed = a.get("likely_to_proceed", "unknown")
    parts.append((f"likely to proceed: {proceed}", PROCEED.get(proceed, 2)))

    total = sum(p for _, p in parts)
    reasons = [f"{label} (+{p})" for label, p in parts if p]

    caps = []
    if padel == "no":
        caps.append((30, "no padel connection"))
    if a.get("padeltech_opportunity") == "none":
        caps.append((30, "no opportunity for PadelTech"))
    if stage in ("refused", "withdrawn"):
        caps.append((35, f"application {stage}"))
    for cap, why in caps:
        if total > cap:
            total = cap
            reasons.append(f"capped at {cap}: {why}")
    return max(0, min(100, total)), reasons


def band(points: int) -> str:
    if points >= config.HOT_MIN:
        return "HOT"
    if points >= config.GOOD_MIN:
        return "GOOD"
    if points >= config.WATCH_MIN:
        return "WATCH"
    return "IGNORE"

"""Everything that talks to Claude.

Three kinds of call:
  1. triage()           - cheap screening of noisy keyword matches, 40 at a time
  2. analyse()          - full structured analysis of one candidate application
  3. research_contacts()- for good leads only: look up the organisations involved
                          on the public web (official websites, Companies House)
"""

import json
import logging

import anthropic

from . import config

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Published per-million-token prices, used only to log an estimated daily cost.
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-4-5": (1.00, 5.00)}

COMPANY_CONTEXT = """\
PadelTech supplies and installs padel courts in the UK (indoor, outdoor and covered/canopy courts).
Its sales team wants planning applications where a padel court supply/installation contract could
realistically be won: new padel courts or centres, sports/leisure facilities that include padel,
conversion of tennis courts to padel, sports clubs expanding with padel, hotels/resorts, gyms,
leisure centres, schools and universities adding padel, and similar."""

PARTY = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Name, or 'Unknown'"},
        "basis": {"type": "string", "enum": ["confirmed", "inferred", "unknown"]},
    },
    "required": ["name", "basis"],
    "additionalProperties": False,
}

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "e.g. '6 new outdoor padel courts — Leeds'"},
        "padel_relevance": {"type": "string", "enum": ["explicit", "likely", "possible", "no"]},
        "padel_evidence": {"type": "string", "description": "Exact quote from the record, or 'None'"},
        "courts": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "courts_basis": {"type": "string", "enum": ["confirmed", "inferred", "unknown"]},
        "indoor_outdoor": {"type": "string", "enum": ["indoor", "outdoor", "covered_canopy", "mixed", "unknown"]},
        "project_type": {"type": "string", "enum": [
            "new_padel_facility", "padel_added_to_existing_site", "tennis_court_conversion",
            "multi_sport_facility_including_padel", "wider_development_possible_padel",
            "conditions_or_amendment_for_padel_scheme", "not_relevant"]},
        "applicant": PARTY,
        "developer": PARTY,
        "planning_agent": PARTY,
        "architect": PARTY,
        "operator": PARTY,
        "applicant_type": {"type": "string", "enum": [
            "commercial_padel_operator", "sports_or_tennis_club", "hotel_or_resort",
            "gym_or_leisure_operator", "school_or_university", "local_authority_or_public_body",
            "property_developer", "private_individual_residential", "other", "unknown"]},
        "site_location": {"type": "string", "description": "Site name / town / postcode"},
        "planning_stage": {"type": "string", "enum": [
            "submitted_pending", "approved", "refused", "withdrawn", "condition_discharge", "appeal", "unknown"]},
        "permission_granted": {"type": "string", "enum": ["yes", "no", "unknown"]},
        "construction_imminent": {"type": "boolean"},
        "construction_signal": {"type": "string", "description": "Why construction looks imminent, or 'None'"},
        "likely_to_proceed": {"type": "string", "enum": ["high", "medium", "low", "unknown"]},
        "development_scale": {"type": "string", "enum": ["major", "medium", "small", "unknown"]},
        "major_developer_involved": {"type": "boolean"},
        "padeltech_opportunity": {"type": "string", "enum": ["strong", "moderate", "weak", "none"]},
        "commercial_value": {"type": "string", "description": "One sentence on commercial value (AI inference)"},
        "confirmed_facts": {"type": "array", "items": {"type": "string"}},
        "ai_inferences": {"type": "array", "items": {"type": "string"}},
        "why_lead": {"type": "string", "description": "1-2 sentences for the salesperson"},
        "recommended_action": {"type": "string", "description": "One concrete next step"},
        "related_application_reference": {"type": "string", "description": "Parent/related reference, or 'Unknown'"},
    },
    "required": [
        "headline", "padel_relevance", "padel_evidence", "courts", "courts_basis", "indoor_outdoor",
        "project_type", "applicant", "developer", "planning_agent", "architect", "operator",
        "applicant_type", "site_location", "planning_stage", "permission_granted",
        "construction_imminent", "construction_signal", "likely_to_proceed", "development_scale",
        "major_developer_involved", "padeltech_opportunity", "commercial_value", "confirmed_facts",
        "ai_inferences", "why_lead", "recommended_action", "related_application_reference"],
    "additionalProperties": False,
}

ANALYSIS_SYSTEM = f"""{COMPANY_CONTEXT}

You analyse one UK planning application record at a time and return the requested JSON.

Rules, which matter more than anything else:
- NEVER invent information. If the record does not say something and it cannot be reasonably
  inferred, use "Unknown" (text), null (courts) or the "unknown" option.
- "confirmed" means stated in the record. "inferred" means your judgement from the record.
  Put verbatim-supported statements in confirmed_facts and your judgements in ai_inferences.
- Applicant/agent fields that say "See source", "N/A" or are blank are NOT known: use "Unknown".
- An agent or architect is only "confirmed" if the record names them in that role.
- Do not guess a court count from vague wording ("courts" with no number -> null, unknown).
- padel_relevance: "explicit" = padel is mentioned; "likely" = racquet/indoor sport scheme where padel
  is the natural fit (e.g. "racquet sports centre", warehouse change of use to indoor sport);
  "possible" = sports/leisure scheme that could include padel; "no" = no realistic padel link.
- planning_stage: an application to discharge conditions or amend a permitted padel scheme is
  "condition_discharge" and usually means construction is close (construction_imminent = true).
  Decided-and-approved applications are "approved"; still-undecided ones are "submitted_pending".
- likely_to_proceed is a judgement: commercial operators with permission or discharging conditions are
  high; speculative or residential schemes are lower.
- major_developer_involved only if a substantial developer/operator is actually named.
- recommended_action: one concrete step, e.g. "Contact the agent (X) to ask whether a court supplier
  has been chosen", or "Wait for the decision (target date ...)".
- Write for a busy salesperson: short, plain English, British spelling."""

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["analyse", "skip"]},
                },
                "required": ["id", "decision"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

TRIAGE_SYSTEM = f"""{COMPANY_CONTEXT}

You screen batches of UK planning application descriptions that matched broad keywords
(tennis, sports, leisure, gym, recreation...). For each id answer "analyse" if it could
realistically be a padel court opportunity, otherwise "skip".

"analyse" examples: new or extended sports/leisure/racquet centres; new, resurfaced or converted
tennis courts at clubs, hotels, schools, universities or parks; multi-use games areas; hotels or
resorts adding leisure facilities; change of use of a large unit/warehouse to indoor sport;
sports club redevelopments; holiday parks adding sports facilities.

"skip" examples: home gyms and garden rooms; tree works; adverts; telecoms; housing where "recreation"
only means public open space or play areas; play equipment, toilets, car parks, pavilions repairs;
small shop units changing to a gym/fitness studio; listed-building or condition details unrelated to courts.

When in genuine doubt about a commercial, club or institutional sports scheme, answer "analyse".
Return every id exactly once."""

CONTACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "contacts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "organisation": {"type": "string"},
                    "role": {"type": "string", "description": "applicant / developer / agent / architect / operator"},
                    "website": {"type": "string", "description": "Official website URL, or 'Unknown'"},
                    "contact_route": {"type": "string", "description": "Public phone/email/contact form exactly as published on an official page, or 'Unknown'"},
                    "source_url": {"type": "string"},
                    "basis": {"type": "string", "enum": ["confirmed", "inferred"]},
                },
                "required": ["organisation", "role", "website", "contact_route", "source_url", "basis"],
                "additionalProperties": False,
            },
        },
        "applicant_from_council_page": {"type": "string"},
        "agent_from_council_page": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["contacts", "applicant_from_council_page", "agent_from_council_page", "notes"],
    "additionalProperties": False,
}

CONTACTS_SYSTEM = f"""{COMPANY_CONTEXT}

You help a salesperson know who to approach about a planning application. Using web search and
web fetch, find publicly available BUSINESS information for the organisations involved
(applicant, developer, planning agent, architect, operator).

1. If a council planning page URL is given, try fetching it first to read the applicant and agent
   names (council sites sometimes block automated access - if so, move on).
2. For each organisation, find its official website and the contact route it publishes (main phone
   number, general enquiries email or contact form). Companies House and professional directories
   are acceptable sources for confirming the company.

Strict rules:
- Never fabricate names, emails, phone numbers or URLs. Only report a contact detail if you saw it
  on the source_url page. Otherwise write "Unknown".
- Organisations only. If the applicant is a private individual, do not research them; say so in notes.
- "confirmed" = the source explicitly links this organisation to this application/site;
  "inferred" = likely the same organisation but not explicitly linked.
- Keep it brief. At most 4 contacts. If nothing useful is found, return an empty contacts list."""


class Claude:
    def __init__(self):
        self.client = anthropic.Anthropic(max_retries=4)
        self.use_fallbacks = True
        self.usage = {"input": 0, "output": 0, "web_searches": 0, "calls": 0}

    def _create(self, **kwargs):
        if self.use_fallbacks:
            try:
                return self.client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            except anthropic.BadRequestError as e:
                if "fallback" not in str(e).lower():
                    raise
                log.warning("Refusal fallbacks unavailable on this account; continuing without them")
                self.use_fallbacks = False
        return self.client.beta.messages.create(**kwargs)

    def _json_call(self, *, system: str, user: str, schema: dict, effort: str,
                   max_tokens: int = 8000, tools: list | None = None) -> dict | None:
        messages = [{"role": "user", "content": user}]
        kwargs = dict(
            model=config.CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        if tools:
            kwargs["tools"] = tools
        response = None
        for _ in range(5):  # resume server-tool turns that pause
            response = self._create(messages=messages, **kwargs)
            self._track(response)
            if response.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": response.content}]
        if response is None or response.stop_reason == "refusal":
            log.warning("Claude declined a request (%s)", getattr(response, "stop_details", None))
            return None
        if response.stop_reason == "max_tokens":
            log.warning("Claude response hit max_tokens; skipping")
            return None
        texts = [b.text for b in response.content if b.type == "text"]
        if not texts:
            return None
        try:
            return json.loads(texts[-1])
        except json.JSONDecodeError:
            log.warning("Could not parse Claude JSON: %.200s", texts[-1])
            return None

    def _track(self, response):
        u = response.usage
        self.usage["calls"] += 1
        self.usage["input"] += (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) \
            + (getattr(u, "cache_creation_input_tokens", 0) or 0)
        self.usage["output"] += u.output_tokens or 0
        stu = getattr(u, "server_tool_use", None)
        if stu is not None:
            self.usage["web_searches"] += getattr(stu, "web_search_requests", 0) or 0

    def estimated_cost_usd(self) -> float | None:
        price = PRICES.get(config.CLAUDE_MODEL)
        if not price:
            return None
        return (self.usage["input"] * price[0] + self.usage["output"] * price[1]) / 1e6 \
            + self.usage["web_searches"] * 0.01

    # --- the three jobs -----------------------------------------------------------

    def triage(self, records: list[dict]) -> set[str]:
        """Returns the PlanIt names worth a full analysis."""
        keep: set[str] = set()
        for i in range(0, len(records), config.TRIAGE_BATCH_SIZE):
            batch = records[i:i + config.TRIAGE_BATCH_SIZE]
            ids = {str(n): r["name"] for n, r in enumerate(batch)}
            lines = [
                f'[{n}] {r.get("area_name")} | {r.get("app_type") or ""} | {r.get("app_size") or ""} | '
                f'{(r.get("description") or "")[:600]}'
                for n, r in enumerate(batch)
            ]
            result = self._json_call(system=TRIAGE_SYSTEM, user="\n".join(lines), schema=TRIAGE_SCHEMA,
                                     effort="low", max_tokens=8000)
            if result is None:
                # Fail open: analyse rather than silently drop possible leads.
                keep.update(ids.values())
                continue
            for item in result.get("items", []):
                if item.get("decision") == "analyse" and item.get("id") in ids:
                    keep.add(ids[item["id"]])
        return keep

    def analyse(self, record: dict, events: list[str], previous: dict | None) -> dict | None:
        context = ""
        if previous and previous.get("analysed"):
            context = (
                "\n\nWe have analysed this application before. Previous headline: "
                f"{previous.get('headline') or 'Unknown'}; previous court count: "
                f"{previous.get('courts') if previous.get('courts') is not None else 'Unknown'}. "
                f"Changes detected now: {', '.join(events) or 'none'}."
            )
        return self._json_call(system=ANALYSIS_SYSTEM, user=format_record(record) + context,
                               schema=ANALYSIS_SCHEMA, effort="medium")

    def research_contacts(self, record: dict, analysis: dict) -> dict | None:
        people = {k: analysis.get(k, {}).get("name", "Unknown")
                  for k in ("applicant", "developer", "planning_agent", "architect", "operator")}
        user = (
            f"Lead: {analysis.get('headline')}\nSite: {analysis.get('site_location')}\n"
            f"Council: {record.get('area_name')} — reference {record.get('uid')}\n"
            f"Council planning page: {record.get('url') or 'Unknown'}\n"
            f"Known parties: {json.dumps(people)}\n"
            f"Description: {record.get('description')}"
        )
        tools = [
            {"type": "web_search_20260209", "name": "web_search", "max_uses": 5,
             "user_location": {"type": "approximate", "country": "GB"}},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 4},
        ]
        return self._json_call(system=CONTACTS_SYSTEM, user=user, schema=CONTACTS_SCHEMA,
                               effort="medium", max_tokens=16000, tools=tools)


def format_record(r: dict) -> str:
    other = r.get("other_fields") or {}
    lines = [
        f"Council: {r.get('area_name')}",
        f"Application reference: {r.get('uid')}",
        f"Site address: {r.get('address')}",
        f"Postcode: {r.get('postcode')}",
        f"Description: {r.get('description')}",
        f"Application type: {r.get('app_type') or other.get('application_type')}",
        f"Size: {r.get('app_size')}",
        f"Decision state: {r.get('app_state')}",
        f"Status text: {other.get('status')}",
        f"Decision: {other.get('decision')}",
        f"Received / validated: {r.get('start_date')} / {other.get('date_validated')}",
        f"Decided: {r.get('decided_date')}",
        f"Target decision date: {other.get('target_decision_date')}",
    ]
    for key in ("applicant_name", "applicant_company", "applicant_address", "agent_name",
                "agent_company", "agent_address", "case_officer", "development_type"):
        if other.get(key):
            lines.append(f"{key.replace('_', ' ').capitalize()}: {other[key]}")
    lines.append(f"Council planning page: {r.get('url')}")
    return "\n".join(f"{line}" for line in lines if not line.endswith(": None"))

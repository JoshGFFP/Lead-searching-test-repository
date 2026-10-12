"""All the settings you might want to tweak live in this one file.

Anything marked "env" can also be overridden with an environment variable
(for example in the GitHub Actions workflow) without editing code.
"""

import os


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


# --- Planning data (PlanIt: https://www.planit.org.uk/api/) -----------------

PLANIT_URL = "https://www.planit.org.uk/api/applics/json"
PLANIT_USER_AGENT = "PadelTechLeadReport/1.0 (+https://github.com/JoshGFFP/Lead-searching-test-repository)"
PLANIT_PAGE_SIZE = 300

# Each group is one PlanIt search. "or" is a logical OR, quotes make a phrase.
# The "padel" group is treated as high-signal: every match goes straight to a
# full AI analysis. The other groups are noisier (e.g. "gym" matches home
# gyms), so their matches go through a cheap AI triage first.
SEARCH_GROUPS = {
    "padel": 'padel or pádel or "padel tennis"',
    "tennis": '"tennis court" or "tennis courts" or "tennis club" or "tennis centre"',
    "sports": (
        '"sports court" or "sports courts" or "sports facility" or "sports facilities" '
        'or "sports hub" or "sports club" or "sports centre" or "sports center" '
        'or racquet or racket or "multi-use games area" or "games court"'
    ),
    "leisure": (
        '"leisure facility" or "leisure facilities" or "leisure centre" or "leisure center" '
        'or "leisure club" or "fitness centre" or gym or recreation'
    ),
}
HIGH_SIGNAL_GROUP = "padel"

# How far back to look on the very first run (no memory yet).
FIRST_RUN_LOOKBACK_DAYS = _env_int("FIRST_RUN_LOOKBACK_DAYS", 7)
# Never look back further than this, even if the system hasn't run for weeks.
MAX_LOOKBACK_DAYS = 14
# An application we've never seen before counts as "new" if it was submitted
# within this many days (PlanIt can pick applications up days or weeks late).
FRESH_APPLICATION_DAYS = 60
# ...or if a decision was issued within this many days.
FRESH_DECISION_DAYS = 21

# PlanIt application types that are never court-installation opportunities
# for the noisy keyword groups (the padel group keeps everything, because e.g.
# a padel "Conditions" application means construction is close).
NOISY_GROUP_EXCLUDED_APP_TYPES = {"Trees", "Advertising", "Telecoms", "Conditions", "Amendment"}

# --- Claude -------------------------------------------------------------------

CLAUDE_MODEL = _env_str("CLAUDE_MODEL", "claude-opus-5-5")
TRIAGE_BATCH_SIZE = 40
# Safety caps so a strange day can never run up a large bill.
MAX_ANALYSES_PER_RUN = _env_int("MAX_ANALYSES_PER_RUN", 150)
MAX_CONTACT_RESEARCH_PER_RUN = _env_int("MAX_CONTACT_RESEARCH_PER_RUN", 10)
# Only research contacts for leads scoring at least this much.
CONTACT_RESEARCH_MIN_SCORE = 60

# --- Lead scoring bands ---------------------------------------------------------

HOT_MIN = 80
GOOD_MIN = 60
WATCH_MIN = 40

# --- Email ----------------------------------------------------------------------

SMTP_HOST = _env_str("SMTP_HOST", "smtp.purelymail.com")
SMTP_PORT = _env_int("SMTP_PORT", 465)
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM = _env_str("EMAIL_FROM", SMTP_USERNAME)
EMAIL_TO = [a.strip() for a in os.environ.get("EMAIL_TO", "").split(",") if a.strip()]

# --- Files ----------------------------------------------------------------------

STATE_PATH = _env_str("STATE_PATH", "state/leads_state.json")
REPORT_DIR = _env_str("REPORT_DIR", "reports")
SPREADSHEET_NAME = "PadelTech_leads.xlsx"
# Forget applications we haven't seen change for this long.
STATE_RETENTION_DAYS = 400

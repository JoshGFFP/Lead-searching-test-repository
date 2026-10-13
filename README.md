# PadelTech weekly lead report

Every Monday morning this system emails a short list of UK planning applications that
look like real sales opportunities for PadelTech: new padel courts, padel
centres, tennis-to-padel conversions, sports clubs, hotels, gyms, schools and
leisure schemes that could include padel.

**First time? Follow [SETUP.md](SETUP.md).** It takes about 15 minutes and needs no coding.

## How it works

```
 ⏰ Monday 6–7am every week (GitHub Actions, free)
        │
        ▼
 📥 UK PlanIt: every application mentioning padel, tennis courts, sports/leisure
     facilities, gyms… that changed since the last run (~400 UK councils, free)
        │
        ▼
 🧹 Filter + memory: drop junk and anything already reported with no meaningful change
        │
        ▼
 🤖 Claude: quick screening of noisy matches → full analysis of real candidates
     (padel? courts? indoor/outdoor? applicant, agent, stage, likely to proceed…)
        │
        ▼
 🧮 Lead score 0–100 (fixed, explainable formula, see below)
        │
        ▼
 🔎 Claude contact research for GOOD/HOT leads (official websites only)
        │
        ▼
 📧 Email: 🔥 HOT / 🟠 GOOD / 👀 WATCH + weekly summary
     + 📎 Padel_leads.xlsx: every lead found so far
```

* **No spreadsheet, no database to manage.** The system's memory is one file,
  `state/leads_state.json`, which the weekly job updates by itself. It records
  which applications have already been seen and reported, so you only get a lead
  again when something meaningful happens.
* **Events it alerts on:** 🆕 new padel application · ✅ permission granted ·
  📈 more courts · 📝 revised proposal · 🏗️ construction appears imminent (e.g.
  conditions being discharged) · 🏢 major developer identified. Refusals and
  withdrawals of earlier leads appear as one-line updates.
* **Quality over quantity:** anything scoring under 40 is never emailed. On a
  quiet week you get a short "no new qualified leads" email, so you know it ran.
* **Excel lead database:** every email has `Padel_leads.xlsx` attached: one row
  per lead ever found (score, courts, applicant, agent, council, status, contacts,
  update history, link), with filters and a "New this week" column. It's rebuilt
  from the memory file every week, so it's always complete. It's a read-only export;
  notes typed into a downloaded copy aren't read back.
* **No invented facts:** Claude must answer "Unknown" when the record doesn't
  say. Anything that is Claude's judgement is labelled "AI inference" in the
  email. Contact details are only included if they were seen on an official page.

## Lead score

Claude extracts the facts; the formula in `padeltech_leads/scoring.py` turns
them into points:

| Factor | Max | Points |
|---|---|---|
| Padel relevance | 35 | explicit 35 · likely 22 · possible 10 · none 0 |
| Number of courts | 15 | 6+ 15 · 4–5 12 · 2–3 9 · 1 5 · unknown 4 |
| Applicant type | 15 | padel operator 15 · gym/leisure/hotel 13 · developer 12 · club 11 · school/council 9 · private house 3 |
| Planning stage | 15 | approved / conditions being discharged 15 · submitted 10 · refused/withdrawn 0 |
| Construction imminent | 5 | |
| Development size | 5 | major 5 · medium 3 · small 1 |
| People identified | 5 | developer +3 · agent/architect +2 |
| Likely to proceed | 5 | high 5 · medium 3 · low 0 |

Caps: no padel connection → max 30; refused/withdrawn → max 35.
Bands: **80–100 🔥 HOT · 60–79 🟠 GOOD · 40–59 👀 WATCH · 0–39 ignored**.

## Running costs

| Item | Cost |
|---|---|
| UK PlanIt planning data | Free (donations welcome at planit.org.uk) |
| GitHub Actions (the weekly schedule) | Free: one run uses ~10 of the 2,000 free minutes/month |
| Claude API | Estimated $2–7 per weekly run, about **£8–25/month**, mostly the contact research on good leads. Each run logs its estimated cost; set a monthly spending limit in the Anthropic Console |
| Email | Free (your existing mailbox) |

To roughly halve the Claude cost, add a repository **variable** (Settings → Secrets and
variables → Actions → Variables tab) named `CLAUDE_MODEL` with the value `claude-sonnet-5-5`.
To cut contact-research cost, lower `MAX_CONTACT_RESEARCH_PER_RUN` in `config.py`.

## Changing things

Everything adjustable is in `padeltech_leads/config.py`: search keywords, how far
back to look, score bands, per-run safety caps. The send day/time is the `cron` line in
`.github/workflows/daily-lead-report.yml`.

## Running it on a computer (optional)

```bash
pip install -r requirements.txt
python -m padeltech_leads.main --dry-run --no-ai   # test the plumbing, no AI, no email
ANTHROPIC_API_KEY=... python -m padeltech_leads.main --dry-run   # real analysis, writes reports/ only
```

## Roadmap (after the basic version is proven)

1. Read supporting planning documents (Design & Access statements, site plans,
   noise/lighting assessments) to find padel courts hidden behind wording like
   "new sports facility", and to extract court layout, floodlighting, canopies, etc.
2. Switch to a paid data feed (e.g. PlanWire, £49/month) if PlanIt proves unreliable
   or more applicant/agent detail is needed.

"""Synthetic Ashby workspace for eval runs.

A small but believable company: 6 jobs across Eng/Sales/Design/Product,
15 candidates with varied histories, ~30 applications distributed
across open + closed searches with realistic stage and archive-reason
distributions. Notes attached to the candidates most interesting for
re-engagement and outreach cases.

All timestamps are relative to `TODAY` so the data stays interpretable
("last 18 months", "recent archive", etc.) regardless of when evals run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

TODAY = datetime(2026, 4, 22, tzinfo=timezone.utc)


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Lookup tables (sources, archive reasons, interview stages)
# ---------------------------------------------------------------------------

SOURCES = [
    {"id": "s_linkedin", "title": "LinkedIn", "isArchived": False,
     "sourceType": {"id": "st_jb", "title": "Job Board", "isArchived": False}},
    {"id": "s_referral", "title": "Referral", "isArchived": False,
     "sourceType": {"id": "st_ref", "title": "Referral", "isArchived": False}},
    {"id": "s_inbound", "title": "Inbound", "isArchived": False,
     "sourceType": {"id": "st_inb", "title": "Inbound", "isArchived": False}},
    {"id": "s_agency", "title": "Bridgepoint Talent", "isArchived": False,
     "sourceType": {"id": "st_agency", "title": "Agency", "isArchived": False}},
]

ARCHIVE_REASONS = [
    {"id": "ar_timing",        "title": "Timing (not right now)"},
    {"id": "ar_comp",          "title": "Compensation misalignment"},
    {"id": "ar_location",      "title": "Location mismatch"},
    {"id": "ar_performance",   "title": "Failed bar (performance)"},
    {"id": "ar_nli",           "title": "No longer interested"},
    {"id": "ar_offer_declined","title": "Offer declined"},
    {"id": "ar_role_scope",    "title": "Role-scope mismatch"},
]

INTERVIEW_STAGES = [
    {"id": "is_lead",    "title": "Lead",         "type": "PreInterviewScreen", "orderInInterviewPlan": 0},
    {"id": "is_screen",  "title": "Recruiter Screen","type": "Active",         "orderInInterviewPlan": 1},
    {"id": "is_tech",    "title": "Technical Screen","type": "Active",         "orderInInterviewPlan": 2},
    {"id": "is_onsite",  "title": "Onsite",       "type": "Active",            "orderInInterviewPlan": 3},
    {"id": "is_offer",   "title": "Offer",        "type": "Offer",             "orderInInterviewPlan": 4},
    {"id": "is_hired",   "title": "Hired",        "type": "Hired",             "orderInInterviewPlan": 5},
    {"id": "is_archived","title": "Archived",     "type": "Archived",          "orderInInterviewPlan": 99},
]


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

JOBS = [
    {
        "id": "j_eng_senior", "title": "Senior Software Engineer",
        "status": "Open", "department": {"id": "d_eng", "name": "Engineering"},
        "locations": [{"locationName": "San Francisco"}],
        "createdAt": _iso(180), "updatedAt": _iso(10),
    },
    {
        "id": "j_eng_staff", "title": "Staff Software Engineer",
        "status": "Open", "department": {"id": "d_eng", "name": "Engineering"},
        "locations": [{"locationName": "Remote"}],
        "createdAt": _iso(90), "updatedAt": _iso(5),
    },
    {
        "id": "j_sales_ae_closed", "title": "Account Executive",
        "status": "Closed", "department": {"id": "d_sales", "name": "Sales"},
        "locations": [{"locationName": "New York"}],
        "createdAt": _iso(540), "updatedAt": _iso(320),
    },
    {
        "id": "j_sales_ae_open", "title": "Senior Account Executive",
        "status": "Open", "department": {"id": "d_sales", "name": "Sales"},
        "locations": [{"locationName": "New York"}],
        "createdAt": _iso(60), "updatedAt": _iso(3),
    },
    {
        "id": "j_design_lead", "title": "Design Lead",
        "status": "Closed", "department": {"id": "d_design", "name": "Design"},
        "locations": [{"locationName": "San Francisco"}],
        "createdAt": _iso(420), "updatedAt": _iso(220),
    },
    {
        "id": "j_product_hod", "title": "Head of Product",
        "status": "Closed", "department": {"id": "d_product", "name": "Product"},
        "locations": [{"locationName": "San Francisco"}],
        "createdAt": _iso(360), "updatedAt": _iso(150),
    },
]


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

def _cand(cid: str, name: str, email: str, source_id: str, created_days_ago: int,
          location: str = "San Francisco, US", tags: list[str] | None = None) -> dict:
    source = next(s for s in SOURCES if s["id"] == source_id)
    return {
        "id": cid, "name": name,
        "primaryEmailAddress": {"value": email, "type": "personal", "isPrimary": True},
        "primaryPhoneNumber": {"value": "+1-555-0100", "type": "Mobile", "isPrimary": True},
        "source": {"id": source["id"], "title": source["title"]},
        "location": {"city": location.split(",")[0].strip(),
                     "region": "", "country": location.split(",")[-1].strip()},
        "linkedInUrl": f"https://linkedin.com/in/{cid}",
        "tags": tags or [],
        "createdAt": _iso(created_days_ago),
        "updatedAt": _iso(max(0, created_days_ago - 5)),
    }


CANDIDATES = [
    # Sales — silver medalists from closed AE role (archived timing/comp, not performance)
    _cand("c_sales_01", "Priya Raman",      "priya@example.com",   "s_linkedin", 400),
    _cand("c_sales_02", "Marcus Webb",      "marcus@example.com",  "s_referral", 380),
    _cand("c_sales_03", "Sonia Garcia",     "sonia@example.com",   "s_linkedin", 360),
    _cand("c_sales_04", "Devon Blake",      "devon@example.com",   "s_agency",   340),  # archived perf
    _cand("c_sales_05", "Tomás Oliveira",   "tomas@example.com",   "s_inbound",  320),  # hired
    _cand("c_sales_06", "Kira Nakamura",    "kira@example.com",    "s_linkedin", 50),   # active AE2

    # Engineering — mix of active and historical
    _cand("c_eng_01", "Ada Khoury",         "ada@example.com",     "s_referral", 160),  # active staff
    _cand("c_eng_02", "Jon Park",           "jon@example.com",     "s_linkedin", 140),
    _cand("c_eng_03", "Ravi Sethi",         "ravi@example.com",    "s_inbound",  100),  # active senior
    _cand("c_eng_04", "Lena Brodsky",       "lena@example.com",    "s_linkedin", 80),
    _cand("c_eng_05", "Fiona Zhao",         "fiona@example.com",   "s_referral", 550),  # historical

    # Design Lead search (closed)
    _cand("c_design_01","Ian Ruiz",         "ian@example.com",     "s_agency",   380),
    _cand("c_design_02","Nadia Okafor",     "nadia@example.com",   "s_linkedin", 360),  # hired
    _cand("c_design_03","Ben Carver",       "ben@example.com",     "s_inbound",  340),

    # Head of Product search (closed)
    _cand("c_prod_01", "Harper Velez",     "harper@example.com",  "s_referral", 320),  # hired
    _cand("c_prod_02", "Gavin Ishii",      "gavin@example.com",   "s_linkedin", 300),
    _cand("c_prod_03", "Ruth Alvarez",     "ruth@example.com",    "s_referral", 280),
]


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def _app(aid: str, candidate_id: str, job_id: str, stage_id: str, status: str,
         source_id: str, created_days_ago: int,
         archive_reason_id: str | None = None) -> dict:
    cand = next(c for c in CANDIDATES if c["id"] == candidate_id)
    job = next(j for j in JOBS if j["id"] == job_id)
    stage = next(s for s in INTERVIEW_STAGES if s["id"] == stage_id)
    source = next(s for s in SOURCES if s["id"] == source_id)
    app = {
        "id": aid,
        "candidate": {"id": cand["id"], "name": cand["name"]},
        "job": {"id": job["id"], "title": job["title"]},
        "currentInterviewStage": {"id": stage["id"], "title": stage["title"], "type": stage["type"]},
        "status": status,
        "source": {"id": source["id"], "title": source["title"]},
        "createdAt": _iso(created_days_ago),
        "updatedAt": _iso(max(0, created_days_ago - 15)),
    }
    if archive_reason_id:
        reason = next(r for r in ARCHIVE_REASONS if r["id"] == archive_reason_id)
        app["archiveReason"] = {"id": reason["id"], "title": reason["title"]}
    return app


APPLICATIONS = [
    # Sales AE (closed) — silver medalists and the eventual hire
    _app("a_01", "c_sales_01", "j_sales_ae_closed", "is_archived", "Archived", "s_linkedin", 390, "ar_timing"),
    _app("a_02", "c_sales_02", "j_sales_ae_closed", "is_archived", "Archived", "s_referral", 370, "ar_comp"),
    _app("a_03", "c_sales_03", "j_sales_ae_closed", "is_archived", "Archived", "s_linkedin", 350, "ar_nli"),
    _app("a_04", "c_sales_04", "j_sales_ae_closed", "is_archived", "Archived", "s_agency",   330, "ar_performance"),
    _app("a_05", "c_sales_05", "j_sales_ae_closed", "is_hired",    "Hired",    "s_inbound",  310),

    # Senior AE (open) — current pipeline; c_sales_06 active, c_sales_01 re-engaged but still active
    _app("a_06", "c_sales_06", "j_sales_ae_open",   "is_onsite",   "Active",   "s_linkedin", 40),
    _app("a_07", "c_sales_01", "j_sales_ae_open",   "is_screen",   "Active",   "s_referral", 20),

    # Senior Engineer (open) — active pipeline
    _app("a_08", "c_eng_03", "j_eng_senior", "is_onsite", "Active", "s_inbound",  90),
    _app("a_09", "c_eng_04", "j_eng_senior", "is_tech",   "Active", "s_linkedin", 70),

    # Staff Engineer (open)
    _app("a_10", "c_eng_01", "j_eng_staff", "is_onsite", "Active", "s_referral", 150),
    _app("a_11", "c_eng_02", "j_eng_staff", "is_screen", "Active", "s_linkedin", 130),

    # Historical Engineering candidate (archived timing — good re-engagement target)
    _app("a_12", "c_eng_05", "j_eng_senior", "is_archived", "Archived", "s_referral", 540, "ar_timing"),

    # Design Lead (closed) — full pipeline narrative
    _app("a_13", "c_design_01", "j_design_lead", "is_archived", "Archived", "s_agency",   380, "ar_role_scope"),
    _app("a_14", "c_design_02", "j_design_lead", "is_hired",    "Hired",    "s_linkedin", 360),
    _app("a_15", "c_design_03", "j_design_lead", "is_archived", "Archived", "s_inbound",  340, "ar_offer_declined"),

    # Head of Product (closed)
    _app("a_16", "c_prod_01", "j_product_hod", "is_hired",    "Hired",    "s_referral", 320),
    _app("a_17", "c_prod_02", "j_product_hod", "is_archived", "Archived", "s_linkedin", 300, "ar_comp"),
    _app("a_18", "c_prod_03", "j_product_hod", "is_archived", "Archived", "s_referral", 280, "ar_timing"),
]


# ---------------------------------------------------------------------------
# Candidate notes — attached to re-engagement / outreach targets
# ---------------------------------------------------------------------------

def _note(nid: str, note: str, days_ago: int, author_email: str) -> dict:
    return {
        "id": nid,
        "note": note,
        "createdAt": _iso(days_ago),
        "createdByUser": {"email": author_email},
    }


CANDIDATE_NOTES = {
    "c_sales_01": [
        _note("n_01a", "Strong discovery skills; closed $2M pipeline at Segment. "
              "Declined because we couldn't match their variable comp target — "
              "willing to revisit if base moves up or equity grows.", 385, "hm@example.com"),
        _note("n_01b", "Hiring manager on-hire retro: 'Would've been a top pick if comp had aligned — "
              "recommend re-engaging if new role lands in $220-260 OTE band.'", 300, "hm@example.com"),
    ],
    "c_sales_02": [
        _note("n_02a", "Clean run through onsite. Timing was the blocker — their spouse was "
              "mid-relocation and they needed to pause all searches for 4-6 months. "
              "Exceptional at enterprise motion, not transactional.", 365, "hm@example.com"),
    ],
    "c_sales_03": [
        _note("n_03a", "Candidate withdrew at offer stage — took counteroffer from current employer. "
              "Was our #2 pick. Worth watching; counteroffers rarely hold past 18 months.", 345, "hm@example.com"),
    ],
    "c_eng_05": [
        _note("n_12a", "Brilliant systems designer; we lost them to timing in 2024. "
              "Kept in touch — they're open to conversations again per LinkedIn in March.", 30, "rec@example.com"),
    ],
    "c_prod_02": [
        _note("n_17a", "Deeply impressive product vision; would've been the hire but they needed "
              "HoP comp that was out of band for the role level.", 295, "hm@example.com"),
    ],
    "c_design_03": [
        _note("n_15a", "Declined offer — family reasons (parent's illness). Strong Notion + Figma "
              "background. Would likely be re-open in 6-9 months.", 335, "hm@example.com"),
    ],
}


# ---------------------------------------------------------------------------
# Public accessor
# ---------------------------------------------------------------------------

def workspace() -> dict:
    """Return the workspace as a single dict (for inspection / snapshotting)."""
    return {
        "today": TODAY.isoformat(),
        "sources": SOURCES,
        "archive_reasons": ARCHIVE_REASONS,
        "interview_stages": INTERVIEW_STAGES,
        "jobs": JOBS,
        "candidates": CANDIDATES,
        "applications": APPLICATIONS,
        "candidate_notes": CANDIDATE_NOTES,
    }

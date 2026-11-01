"""
Demo runner + Seeder danych testowych.

Każde wywołanie /demo/run idzie pełną drogą:
  API → Gateway → [Presidio + Policy Engine + claude-haiku-4-5] → audit_log

/demo/seed wypełnia bazę 30 dniami realistycznych danych historycznych.
/demo/reset usuwa wszystkie dane dla agentów demo.
"""
import hashlib
import json
import random
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from dependencies.auth import CurrentUser, get_current_user, require_role
from services.auth_service import create_access_token

from config import settings
from i18n import t
from repositories import demo_repository as demo_repo

router = APIRouter(prefix="/demo", tags=["demo"])

# ── UUID-e seedowane w init.sql ────────────────────────────────────────────────
_A1 = "a1000000-0000-0000-0000-000000000001"
_A2 = "a2000000-0000-0000-0000-000000000002"
_A3 = "a3000000-0000-0000-0000-000000000003"

# Nazwy agentów i treści scenariuszy są w demo.json (demo.agents.<key>,
# demo.scenarios.<agent>.<scenariusz>) i tłumaczone w momencie użycia — dane
# seedu powstają w języku użytkownika, który uruchomił seed.
_AGENTS = {
    _A1: {"key": "customerService", "model": "claude-haiku-4-5-20251001"},
    _A2: {"key": "creditScoring",   "model": "claude-sonnet-4-6"},
    _A3: {"key": "recruitment",     "model": "claude-sonnet-4-6"},
}


def _agent_name(agent_id: str) -> str:
    return t(f"demo.agents.{_AGENTS[agent_id]['key']}")


# ── Scenariusze dla symulatora ─────────────────────────────────────────────────
# Teksty (label, description, wiadomości system/user) w demo.scenarios.<agent>.<key>.
# UWAGA dla tłumaczeń: wiadomości user muszą zawierać frazy wyzwalające polityki
# (G-001 „zmień saldo”, G-002 „ignore previous instructions”) i dane PII (PESEL, IBAN),
# inaczej scenariusz nie da oczekiwanego wyniku.
SCENARIOS: dict[str, dict[str, dict]] = {
    _A1: {
        "normal":          {"key": "normal",         "expected": "allowed"},
        "pii":             {"key": "pii",            "expected": "allowed_with_pii"},
        "block_financial": {"key": "blockFinancial", "expected": "blocked"},
        "block_injection": {"key": "blockInjection", "expected": "blocked"},
    },
    _A2: {
        "credit_good":  {"key": "creditGood",  "expected": "oversight_required"},
        "credit_risky": {"key": "creditRisky", "expected": "oversight_required"},
    },
    _A3: {
        "cv_senior":    {"key": "cvSenior",    "expected": "oversight_required"},
        "cv_injection": {"key": "cvInjection", "expected": "blocked"},
    },
}


def _scenario_text(agent_id: str, scenario: dict, field: str) -> str:
    return t(f"demo.scenarios.{_AGENTS[agent_id]['key']}.{scenario['key']}.{field}")


def _scenario_messages(agent_id: str, scenario: dict) -> list[dict]:
    return [
        {"role": role, "content": _scenario_text(agent_id, scenario, role)}
        for role in ("system", "user")
    ]

# ── Stałe seedera ──────────────────────────────────────────────────────────────

_SEED_META = json.dumps({"seeded": True})
_PII_CATS  = ["PESEL", "PHONE_NUMBER", "NIP", "IBAN", "PL_PHONE", "EMAIL_ADDRESS"]

# ── Realistyczne treści decyzji agentów ───────────────────────────────────────

# Klucze treści w demo.seed.creditDecisions / demo.seed.cvDecisions (+ pewność modelu)
_CREDIT_DECISIONS = [
    ("conditionalAcceptance",       0.87),
    ("verificationIrregularIncome", 0.64),
    ("rejection",                   0.92),
    ("acceptance",                  0.96),
    ("amountCorrection",            0.71),
    ("refinancing",                 0.83),
    ("coBorrowers",                 0.75),
]

_RECRUITMENT_DECISIONS = [
    ("strongSenior",  0.87),
    ("entryLevel",    0.91),
    ("potential",     0.71),
    ("exceptional",   0.94),
    ("noLegacy",      0.68),
    ("microservices", 0.79),
]

# Komentarze recenzentów: demo.seed.reviewerComments.<grupa>.<klucz>
_REVIEWER_DECISIONS = {
    _A2: ("credit", [
        ("analyst.nowak@bank.example.com",       "approved",  "agreeApproved"),
        ("analyst.kowalski@bank.example.com",    "rejected",  "rejectHiddenArrear"),
        ("analyst.nowak@bank.example.com",       "approved",  "approvedAfterVerification"),
        ("analyst.wisniewska@bank.example.com",  "escalated", "escalatedLimit"),
        ("analyst.kowalski@bank.example.com",    "approved",  "approvedAfterValuation"),
        ("analyst.nowak@bank.example.com",       "rejected",  "rejectedDataMismatch"),
        ("analyst.wisniewska@bank.example.com",  "approved",  "approvedStandard"),
    ]),
    _A3: ("recruitment", [
        ("hr.wisniewska@bank.example.com",  "approved",  "invitedInterview"),
        ("hr.kowalski@bank.example.com",    "rejected",  "rejectedNoBanking"),
        ("hr.wisniewska@bank.example.com",  "approved",  "interviewPlanned"),
        ("hr.nowak@bank.example.com",       "escalated", "escalatedDirector"),
        ("hr.kowalski@bank.example.com",    "approved",  "approvedStage2"),
        ("hr.wisniewska@bank.example.com",  "rejected",  "rejectedKeepCv"),
    ]),
}


def _decisions(decision_type: str, group: str, items: list[tuple[str, float]]) -> list[tuple]:
    """(typ decyzji, treść decyzji, pewność) w języku żądania."""
    dtype = t(f"demo.seed.decisionTypes.{decision_type}")
    return [(dtype, t(f"demo.seed.{group}.{key}"), conf) for key, conf in items]


def _reviewers(agent_id: str) -> list[tuple]:
    group, items = _REVIEWER_DECISIONS[agent_id]
    return [(rid, action, t(f"demo.seed.reviewerComments.{group}.{key}"))
            for rid, action, key in items]

# ── Helpery seedera ────────────────────────────────────────────────────────────

def _rnd_hash() -> str:
    return hashlib.sha256(str(random.random()).encode()).hexdigest()[:16]


def _business_ts(base: datetime) -> datetime:
    """Losowy timestamp w godzinach pracy (9-17) z koncentracją w szczycie."""
    hour = random.choices(
        range(8, 18),
        weights=[1, 2, 4, 5, 3, 3, 4, 4, 2, 1],
    )[0]
    return base.replace(
        hour=hour,
        minute=random.randint(0, 59),
        second=random.randint(0, 59),
        microsecond=0,
    )


def _cost(model: str, tok_in: int, tok_out: int) -> float:
    ri, ro = (0.00025, 0.00125) if "haiku" in model else (0.003, 0.015)
    return round(((tok_in / 1000 * ri) + (tok_out / 1000 * ro)) * 0.93, 8)


def _mk_audit(ts, agent_id, policy_result, pii_cats=None, policy_id=None, block_reason=None):
    info = _AGENTS[agent_id]
    blocked  = policy_result == "blocked"
    oversight = policy_result == "oversight_required"

    pii_cats = pii_cats or []
    event_type = "blocked" if blocked else ("oversight_required" if oversight else "call_completed")

    if blocked:
        latency = random.randint(10, 90)
        tok_in = tok_out = None
        cost = 0.0
    else:
        latency = random.randint(600, 3200)
        tok_in  = random.randint(80, 280)
        tok_out = random.randint(150, 480)
        cost = _cost(info["model"], tok_in, tok_out)

    return (
        ts,                                          # $1  time
        agent_id,                                    # $2  agent_id
        _agent_name(agent_id),                       # $3  agent_name
        str(uuid.uuid4()),                           # $4  task_id
        str(uuid.uuid4()),                           # $5  call_id
        event_type,                                  # $6  event_type
        policy_result,                               # $7  policy_result
        policy_id,                                   # $8  policy_id
        pii_cats,                                    # $9  pii_categories
        len(pii_cats),                               # $10 pii_count
        _rnd_hash(),                                 # $11 input_hash
        None if blocked else _rnd_hash(),           # $12 output_hash
        info["model"],                               # $13 model_used
        latency,                                     # $14 latency_ms
        tok_in,                                      # $15 tokens_in
        tok_out,                                     # $16 tokens_out
        cost,                                        # $17 cost_eur
        block_reason,                                # $18 block_reason
        _SEED_META,                                  # $19 metadata (jsonb)
    )


def _mk_oversight(agent_id, decision_tuple, status, reviewer, review_duration_s, created, ttl):
    decision_type, agent_decision, confidence = decision_tuple
    reviewer_id, reviewer_action, reviewer_comment = reviewer if reviewer else (None, None, None)

    if status != "pending" and reviewer:
        review_start = created + timedelta(minutes=random.randint(5, 90))
        reviewed_at  = review_start + timedelta(seconds=review_duration_s)
    else:
        review_start = reviewed_at = None

    return (
        agent_id,          # $1  agent_id
        str(uuid.uuid4()), # $2  task_id
        decision_type,     # $3  decision_type
        agent_decision,    # $4  agent_decision
        None,              # $5  agent_reasoning
        _rnd_hash(),       # $6  input_hash
        confidence,        # $7  confidence
        status,            # $8  status
        reviewer_id,       # $9  reviewer_id
        reviewer_comment,  # $10 reviewer_decision
        review_start,      # $11 review_start_at
        reviewed_at,       # $12 reviewed_at
        ttl,               # $13 ttl_expires_at
        created,           # $14 created_at
    )


def _gen_audit_entries(now: datetime) -> list[tuple]:
    entries = []

    for day_offset in range(30, 0, -1):
        day = (now - timedelta(days=day_offset)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )

        # Agent 1 — 8-15 wywołań/dzień (limited, bez nadzoru)
        for _ in range(random.randint(8, 15)):
            ts = _business_ts(day)
            r  = random.random()
            if r < 0.10:
                pii = random.sample(_PII_CATS, random.randint(1, 2))
                entries.append(_mk_audit(ts, _A1, "allowed", pii_cats=pii))
            elif r < 0.26:
                entries.append(_mk_audit(ts, _A1, "blocked", policy_id="G-001",
                    block_reason=t("demo.seed.blockReasons.financialMutation")))
            elif r < 0.34:
                entries.append(_mk_audit(ts, _A1, "blocked", policy_id="G-002",
                    block_reason=t("demo.seed.blockReasons.promptInjection")))
            else:
                entries.append(_mk_audit(ts, _A1, "allowed"))

        # Agent 2 — 2-5 wywołań/dzień (always oversight)
        for _ in range(random.randint(2, 5)):
            ts = _business_ts(day)
            entries.append(_mk_audit(ts, _A2, "oversight_required", policy_id="A-001"))

        # Agent 3 — 1-4 wywołań/dzień (75% oversight, 25% blocked injection)
        for _ in range(random.randint(1, 4)):
            ts = _business_ts(day)
            if random.random() < 0.25:
                entries.append(_mk_audit(ts, _A3, "blocked", policy_id="G-002",
                    block_reason=t("demo.seed.blockReasons.promptInjectionCv")))
            else:
                entries.append(_mk_audit(ts, _A3, "oversight_required", policy_id="A-001"))

    return entries


def _gen_oversight_entries(now: datetime) -> list[tuple]:
    entries = []

    credit_pool   = _decisions("credit", "creditDecisions", _CREDIT_DECISIONS)
    recruit_pool  = _decisions("cv", "cvDecisions", _RECRUITMENT_DECISIONS)
    random.shuffle(credit_pool)
    random.shuffle(recruit_pool)

    rev_credit  = _reviewers(_A2)
    rev_recruit = _reviewers(_A3)

    # Historyczne wpisy — agent 2 (7 decyzji, mix statusów)
    for i, decision in enumerate(credit_pool):
        day_offset = random.randint(2, 28)
        created = now - timedelta(days=day_offset,
                                  hours=random.randint(0, 7),
                                  minutes=random.randint(0, 59))
        reviewer   = rev_credit[i % len(rev_credit)]
        duration_s = random.randint(45, 320)
        ttl = created + timedelta(hours=1)
        entries.append(_mk_oversight(_A2, decision, reviewer[1], reviewer, duration_s, created, ttl))

    # Historyczne wpisy — agent 3 (6 decyzji)
    for i, decision in enumerate(recruit_pool):
        day_offset = random.randint(2, 28)
        created = now - timedelta(days=day_offset,
                                  hours=random.randint(0, 7),
                                  minutes=random.randint(0, 59))
        reviewer   = rev_recruit[i % len(rev_recruit)]
        duration_s = random.randint(30, 250)
        ttl = created + timedelta(hours=1)
        entries.append(_mk_oversight(_A3, decision, reviewer[1], reviewer, duration_s, created, ttl))

    # Rubber-stamp alerts (< 10s review) — po 1 na każdego agenta
    for agent_id, pool, rev in [(_A2, credit_pool, rev_credit), (_A3, recruit_pool, rev_recruit)]:
        decision   = random.choice(pool)
        day_offset = random.randint(5, 20)
        created    = now - timedelta(days=day_offset, hours=random.randint(1, 5))
        reviewer   = (rev[0][0], "approved", t("demo.seed.reviewerComments.rubberStamp"))
        ttl = created + timedelta(hours=1)
        entries.append(_mk_oversight(agent_id, decision, "approved", reviewer,
                                     random.randint(3, 9), created, ttl))

    # PENDING — 2 kredytowe + 1 rekrutacja (świeże TTL, dla demo live)
    for decision in [credit_pool[0], credit_pool[1]]:
        created = now - timedelta(minutes=random.randint(5, 25))
        ttl     = now + timedelta(minutes=random.randint(46, 58))
        entries.append(_mk_oversight(_A2, decision, "pending", None, 0, created, ttl))

    for decision in [recruit_pool[0]]:
        created = now - timedelta(minutes=random.randint(3, 15))
        ttl     = now + timedelta(minutes=random.randint(50, 59))
        entries.append(_mk_oversight(_A3, decision, "pending", None, 0, created, ttl))

    return entries


# ── Flota demonstracyjna (skala rejestru agentów) ──────────────────────────────
#
# Cel: pokazać, że przy kilkudziesięciu agentach rozproszonych po działach
# ręczne panowanie nad zgodnością z EU AI Act jest niewykonalne. Flota ma
# CELOWO rozsiane luki: high-risk bez nadzoru (art. 14), bez podstawy prawnej,
# zaległe przeglądy compliance, praktyki niedopuszczalne (art. 5).

# Natywny dict — pula asyncpg API ma kodek jsonb (NIE używać json.dumps, bo
# podwójnie zakoduje wartość jako string JSON). Zob. [[jsonb-codec-no-dumps]].
_FLEET_MARKER = {"seeded_fleet": True}

# Klucze demo.fleet.teams.<key>
_TEAMS = [
    "customerService", "riskManagement", "hrRecruitment", "legal",
    "marketing", "it", "finance", "operations",
]

_OWNERS = [
    ("Anna Kowalska",        "a.kowalska@trustbank.example.com"),
    ("Piotr Nowak",          "p.nowak@trustbank.example.com"),
    ("Katarzyna Wiśniewska", "k.wisniewska@trustbank.example.com"),
    ("Marek Zieliński",      "m.zielinski@trustbank.example.com"),
    ("Agnieszka Wójcik",     "a.wojcik@trustbank.example.com"),
    ("Tomasz Kamiński",      "t.kaminski@trustbank.example.com"),
    ("Magdalena Lewandowska","m.lewandowska@trustbank.example.com"),
    ("Paweł Szymański",      "p.szymanski@trustbank.example.com"),
]


# legal_basis (kolumna agents) — podstawa prawna KLASYFIKACJI RYZYKA wg AI Act
# (sprawdzana przez silnik oceny dla high-risk). To NIE jest podstawa RODO —
# tej dotyczy osobna kolumna gdpr_legal_basis (kod z GDPR_BASES w Registry tab).
_AIACT_LEGAL_BASES = [  # klucze demo.fleet.legalBases.<key>
    "legalOpinion",
    "complianceOfficerApproval",
    "riskRegister",
]
# Kody muszą pasować do wartości GDPR_BASES we frontendzie (app/agents/[id]/page.tsx)
_GDPR_CODES = ["contract", "legitimate_interest", "legal_obligation"]

_TECH_CONTACTS = ["it-support@trustbank.example.com", "devops@trustbank.example.com"]
_COMPLIANCE_OFFICERS = ["compliance@trustbank.example.com", "dpo@trustbank.example.com"]

_RETENTION_DAYS = [365, 730, 1095, 1825, 3650]

# Archetypy wg poziomu ryzyka — każdy niesie pełny opis (cel, użytkownicy,
# integracje), żeby zakładka "Zgodność AI Act" miała sensowną treść dla
# KAŻDEGO agenta, nie tylko high-risk.
# Teksty archetypów (name, purpose, users) w demo.fleet.agents.<key>; annex, team
# i integration to klucze demo.fleet.annex / teams / integrations.
_UNACCEPTABLE = [
    {"key": "employeeSocialScoring", "annex": "art5SocialScoring", "team": "hrRecruitment", "users": True, "integration": ["companyChat", "hris", "corporateEmail"]},
    {"key": "predictiveCustomerProfiling", "annex": "art5PredictiveProfiling", "team": "marketing", "users": True, "integration": ["crmSalesforce", "customerDataWarehouse", "offerEngine"]},
]

_HIGH = [
    {"key": "retailCreditScoring", "annex": "annex3Creditworthiness", "team": "riskManagement", "users": True, "integration": ["coreBanking", "bik", "crmSalesforce"]},
    {"key": "mortgageAssessment", "annex": "annex3Creditworthiness", "team": "riskManagement", "users": True, "integration": ["coreBanking", "bik", "propertyValuation"]},
    {"key": "cvRanking", "annex": "annex3Recruitment", "team": "hrRecruitment", "users": True, "integration": ["atsGreenhouse", "hris"]},
    {"key": "interviewShortlisting", "annex": "annex3Recruitment", "team": "hrRecruitment", "users": True, "integration": ["atsGreenhouse", "recruitmentCalendar"]},
    {"key": "employeePerformanceReview", "annex": "annex3EmploymentDecisions", "team": "hrRecruitment", "users": True, "integration": ["hris", "okrTool"]},
    {"key": "biometricIdVerification", "annex": "annex3Biometric", "team": "it", "users": True, "integration": ["kyc", "biometricTemplates"], "modalities": ["text", "image"]},
    {"key": "insuranceRiskAssessment", "annex": "annex3Insurance", "team": "riskManagement", "users": True, "integration": ["policySystem", "ufgClaimsRegister"]},
    {"key": "transactionFraudDetection", "annex": "annex3Creditworthiness", "team": "riskManagement", "users": True, "integration": ["transactionSystem", "sanctionsList"]},
    {"key": "socialBenefitsEligibility", "annex": "annex3PublicBenefits", "team": "operations", "users": True, "integration": ["hris", "socialFundApplications"]},
    {"key": "amlRiskScoring", "annex": "annex3Creditworthiness", "team": "riskManagement", "users": True, "integration": ["transactionSystem", "sanctionsList", "kyc"]},
    {"key": "leasingCreditworthiness", "annex": "annex3Creditworthiness", "team": "finance", "users": True, "integration": ["coreBanking", "bikBig"]},
    {"key": "contentModeration", "annex": "annex3Justice", "team": "it", "users": True, "integration": ["contentPlatform", "cms"]},
    {"key": "debtCollectionSegmentation", "annex": "annex3Creditworthiness", "team": "finance", "users": True, "integration": ["debtCollectionSystem", "crmSalesforce"]},
    {"key": "tenantScreening", "annex": "annex3Creditworthiness", "team": "operations", "users": True, "integration": ["leaseManagement", "big"]},
    {"key": "medicalTriage", "annex": "annex3PublicBenefits", "team": "operations", "users": True, "integration": ["patientQueue", "edm"]},
]

_LIMITED = [
    {"key": "websiteChatAssistant", "team": "customerService", "users": True, "integration": ["website", "crmSalesforce"]},
    {"key": "productFaqBot", "team": "customerService", "users": True, "integration": ["mobileApp", "knowledgeBase"]},
    {"key": "emailReplyGenerator", "team": "customerService", "users": True, "integration": ["mailbox", "crmSalesforce"]},
    {"key": "meetingSchedulingAssistant", "team": "customerService", "users": True, "integration": ["outlookCalendar", "crmSalesforce"]},
    {"key": "virtualProductAdvisor", "team": "marketing", "users": True, "integration": ["website", "offerEngine"]},
    {"key": "techSupportChatbot", "team": "it", "users": True, "integration": ["helpdesk"]},
    {"key": "customerOnboardingAssistant", "team": "customerService", "users": True, "integration": ["mobileApp", "crmSalesforce"]},
    {"key": "marketingContentGenerator", "team": "marketing", "users": True, "integration": ["cms", "emailMarketingTool"]},
    {"key": "satisfactionSurveyBot", "team": "marketing", "users": True, "integration": ["surveyTool", "crmSalesforce"]},
    {"key": "complaintsAssistant", "team": "customerService", "users": True, "integration": ["helpdesk", "crmSalesforce"]},
    {"key": "offerAdvisor", "team": "customerService", "users": True, "integration": ["offerEngine", "crmSalesforce"]},
    {"key": "knowledgeBaseAssistant", "team": "customerService", "users": True, "integration": ["confluence"]},
    {"key": "socialMediaPostGenerator", "team": "marketing", "users": True, "integration": ["socialMediaTool"]},
    {"key": "branchBookingBot", "team": "customerService", "users": True, "integration": ["branchBooking"]},
    {"key": "hrSelfServiceAssistant", "team": "hrRecruitment", "users": True, "integration": ["hris", "intranet"]},
    {"key": "internalChatAssistant", "team": "it", "users": True, "integration": ["companyChat"]},
    {"key": "jobDescriptionGenerator", "team": "hrRecruitment", "users": True, "integration": ["atsGreenhouse"]},
    {"key": "candidatePrescreeningChatbot", "team": "hrRecruitment", "users": True, "integration": ["atsGreenhouse"]},
]

_MINIMAL = [
    {"key": "internalDocSummarization", "integration": ["sharedDrive"]},
    {"key": "documentTranslation", "integration": ["sharedDrive", "corporateEmail"]},
    {"key": "emailClassification", "integration": ["corporateEmail"]},
    {"key": "semanticKnowledgeSearch", "integration": ["confluence"]},
    {"key": "letterProofreading", "integration": ["documentEditor"]},
    {"key": "productDescriptionGenerator", "team": "marketing", "integration": ["cms"]},
    {"key": "invoiceDataExtraction", "team": "finance", "integration": ["accountingSystem"]},
    {"key": "documentTagging", "integration": ["dms"]},
    {"key": "meetingTranscription", "integration": ["videoConferencing"]},
    {"key": "reportSummaries", "integration": ["dataWarehouse"]},
    {"key": "documentFormatConversion", "integration": ["sharedDrive"]},
    {"key": "duplicateDetection", "integration": ["crmSalesforce"]},
    {"key": "reviewSentimentAnalysis", "team": "marketing", "integration": ["surveyTool"]},
    {"key": "formAutofill", "integration": ["intranetPortal"]},
    {"key": "ticketSorting", "integration": ["helpdesk"]},
]

_MODELS_HIGH    = ["claude-sonnet-4-6", "gpt-4o"]
_MODELS_LIGHT   = ["claude-haiku-4-5-20251001", "gpt-4o-mini", "deepseek-chat"]


def _self_decl(risk: str, *, no_oversight: bool, no_legal: bool) -> dict:
    """Samo-deklaracja per artykuł (zakładka Rejestr) — spójna z lukami, które
    silnik oceny (services/compliance.py) wykrywa automatycznie z pól agenta.
    Dzięki temu obie zakładki opowiadają tę samą, spójną historię."""
    if risk in ("high", "unacceptable"):
        return {
            "art9_risk_management":   {"status": "partial" if no_legal else "yes", "notes": ""},
            "art10_data_governance":  {"status": "yes", "notes": ""},
            "art11_technical_docs":   {"status": "partial", "notes": t("demo.fleet.declNotes.docsInProgress")},
            "art13_transparency":     {"status": "yes", "notes": ""},
            "art14_human_oversight":  {"status": "no" if no_oversight else "yes",
                                        "notes": t("demo.fleet.declNotes.oversightPlanned") if no_oversight else ""},
            "art15_accuracy":         {"status": "partial", "notes": t("demo.fleet.declNotes.periodicTests")},
            "conformity_assessment":  {"status": "no", "notes": ""},
            "eu_database_registered": {"status": "no", "notes": ""},
        }
    if risk == "limited":
        return {
            "art13_transparency": {"status": "yes", "notes": t("demo.fleet.declNotes.aiNotice")},
        }
    return {}  # minimal — brak obowiązków deklaracyjnych


def _gen_fleet_agents() -> list[dict]:
    """Generuje 50 agentów z realistycznym rozkładem ryzyka, pełnym opisem
    (cel, użytkownicy, integracje) i celowo rozsianymi lukami compliance."""
    rng = random.Random(42)  # deterministycznie — powtarzalne demo
    today = datetime.now(timezone.utc).date()
    rows: list[dict] = []

    def _mk(item, risk, *, requires_oversight, legal_basis, gdpr,
            overdue, model, ppd, no_oversight, no_legal):
        texts = f"demo.fleet.agents.{item['key']}"
        name = t(f"{texts}.name")
        if overdue:
            next_review = today - timedelta(days=rng.randint(5, 120))
            last_reviewed = datetime.now(timezone.utc) - timedelta(days=rng.randint(200, 500))
        else:
            next_review = today + timedelta(days=rng.randint(30, 300))
            last_reviewed = datetime.now(timezone.utc) - timedelta(days=rng.randint(10, 120))
        budget = rng.choice([0, 50, 100, 250, 500, 1000])
        threshold = budget and rng.choice([0, round(budget * 0.8, 2)])
        owner, email = rng.choice(_OWNERS)
        team = t(f"demo.fleet.teams.{item.get('team') or rng.choice(_TEAMS)}")
        annex = t(f"demo.fleet.annex.{item['annex']}") if item.get("annex") else None
        decl = _self_decl(risk, no_oversight=no_oversight, no_legal=no_legal)
        return {
            "id": str(uuid.uuid4()), "name": name,
            "description": t("demo.fleet.description", risk=risk, name=name.lower()),
            "owner_name": owner, "owner_email": email,
            "team": team,
            "risk_level": risk, "annex_iii_cat": annex, "legal_basis": legal_basis,
            "requires_oversight": requires_oversight, "model_id": model,
            "monthly_budget_eur": budget, "cost_alert_threshold_eur": threshold or 0,
            "next_review_date": next_review, "last_reviewed_at": last_reviewed,
            "processes_personal_data": ppd, "gdpr_legal_basis": gdpr,
            "intended_purpose": t(f"{texts}.purpose"),
            "intended_users": (t(f"{texts}.users") if item.get("users")
                               else t("demo.fleet.defaultUsers", team=team)),
            "geographic_scope": "PL",
            "input_modalities": item.get("modalities", ["text"]),
            "output_modalities": ["text"],
            "integration_points": [t(f"demo.fleet.integrations.{k}") for k in item.get("integration", [])],
            "model_version": model,
            "technical_contact_email": rng.choice(_TECH_CONTACTS),
            "compliance_officer_email": rng.choice(_COMPLIANCE_OFFICERS),
            "compliance_decl": {**decl, **_FLEET_MARKER},
        }

    # ── UNACCEPTABLE (2) — czerwony alert krytyczny (art. 5) ───────────────────
    for item in _UNACCEPTABLE:
        rows.append(_mk(item, "unacceptable",
                        requires_oversight=False, legal_basis=None, gdpr=None,
                        overdue=True, model=rng.choice(_MODELS_HIGH), ppd=True,
                        no_oversight=True, no_legal=True))

    # ── HIGH (15) — z celowymi lukami art. 14 / podstawy prawnej ───────────────
    for i, item in enumerate(_HIGH):
        no_oversight = i % 5 in (2, 4)          # ~6 bez nadzoru (art. 14)
        no_legal     = i % 4 == 2               # ~4 bez podstawy prawnej (klasyfikacji + RODO)
        overdue      = i % 3 == 0               # ~5 zaległych przeglądów
        rows.append(_mk(
            item, "high",
            requires_oversight=not no_oversight,
            legal_basis=None if no_legal else t(f"demo.fleet.legalBases.{rng.choice(_AIACT_LEGAL_BASES)}"),
            gdpr=None if no_legal else rng.choice(_GDPR_CODES),
            overdue=overdue, model=rng.choice(_MODELS_HIGH), ppd=True,
            no_oversight=no_oversight, no_legal=no_legal,
        ))

    # ── LIMITED (18) — obowiązki przejrzystości (art. 50) ──────────────────────
    # Bez klasyfikacji Aneksu III → legal_basis nie dotyczy (None); gdpr_legal_basis
    # tylko tam, gdzie agent faktycznie przetwarza dane osobowe (ppd).
    for i, item in enumerate(_LIMITED):
        ppd = (i % 2 == 0)
        rows.append(_mk(
            item, "limited",
            requires_oversight=False,
            legal_basis=None,
            gdpr=rng.choice(_GDPR_CODES) if ppd else None,
            overdue=(i % 6 == 0),               # ~3 zaległe
            model=rng.choice(_MODELS_LIGHT),
            ppd=ppd,
            no_oversight=False, no_legal=False,
        ))

    # ── MINIMAL (15) — ryzyko minimalne, bez przetwarzania danych osobowych ────
    for i, item in enumerate(_MINIMAL):
        rows.append(_mk(
            item, "minimal",
            requires_oversight=False,
            legal_basis=None,
            gdpr=None,
            overdue=(i % 8 == 0),               # ~2 zaległe
            model=rng.choice(_MODELS_LIGHT),
            ppd=False,
            no_oversight=False, no_legal=False,
        ))

    # Retencja danych — tylko tam, gdzie faktycznie przetwarzane są dane osobowe
    for r in rows:
        r["data_retention_days"] = rng.choice(_RETENTION_DAYS) if r["processes_personal_data"] else None

    return rows


# ── Endpointy seedera ──────────────────────────────────────────────────────────

@router.post("/seed-fleet")
async def seed_fleet(user: CurrentUser = Depends(require_role("partner", "it_admin"))):
    """Wypełnia rejestr flotą 50 agentów z celowymi lukami zgodności EU AI Act."""
    rows = _gen_fleet_agents()
    n = await demo_repo.seed_fleet(rows)

    n_high = sum(1 for r in rows if r["risk_level"] == "high")
    n_unacc = sum(1 for r in rows if r["risk_level"] == "unacceptable")
    n_no_oversight = sum(1 for r in rows if r["risk_level"] in ("high", "unacceptable") and not r["requires_oversight"])
    n_no_legal = sum(1 for r in rows if r["risk_level"] in ("high", "unacceptable") and not r["legal_basis"])
    n_overdue = sum(1 for r in rows if r["next_review_date"] < datetime.now(timezone.utc).date())

    return {
        "status": "seeded",
        "seeded_agents": n,
        "high_risk": n_high,
        "unacceptable": n_unacc,
        "gaps": {
            "high_risk_bez_nadzoru": n_no_oversight,
            "high_risk_bez_podstawy_prawnej": n_no_legal,
            "zalegle_przeglady": n_overdue,
        },
        "message": t(
            "demo.messages.fleetSeeded", n=n, n_high=n_high, n_unacc=n_unacc,
            n_no_oversight=n_no_oversight, n_overdue=n_overdue,
        ),
    }


@router.delete("/seed-fleet")
async def reset_fleet(user: CurrentUser = Depends(require_role("partner", "it_admin"))):
    """Usuwa flotę demonstracyjną z rejestru agentów."""
    n = await demo_repo.reset_fleet()
    return {"status": "reset", "deleted_agents": n}


@router.post("/seed")
async def seed_demo_data(user: CurrentUser = Depends(require_role("partner", "it_admin"))):
    """Wypełnia bazę 30 dniami realistycznych danych historycznych."""
    now   = datetime.now(timezone.utc)

    audit_entries    = _gen_audit_entries(now)
    oversight_entries = _gen_oversight_entries(now)

    await demo_repo.seed_entries(audit_entries, oversight_entries)

    return {
        "status":                    "seeded",
        "seeded_audit_entries":      len(audit_entries),
        "seeded_oversight_entries":  len(oversight_entries),
        "message": t(
            "demo.messages.demoSeeded",
            audit=len(audit_entries), oversight=len(oversight_entries),
        ),
    }


@router.delete("/seed")
async def reset_demo_data(user: CurrentUser = Depends(require_role("partner", "it_admin"))):
    """Usuwa WSZYSTKIE dane demo: audit_log, oversight_queue (3 agenty) oraz flotę."""
    ids  = [_A1, _A2, _A3]

    n_audit, n_oq = await demo_repo.reset_demo(ids)
    n_fleet = await demo_repo.reset_fleet()

    return {
        "status":                   "reset",
        "deleted_audit_entries":    n_audit,
        "deleted_oversight_entries": n_oq,
        "deleted_fleet_agents":     n_fleet,
    }


@router.get("/seed/status")
async def seed_status(user: CurrentUser = Depends(get_current_user)):
    """Sprawdza czy dane demo są zasiane."""
    ids  = [_A1, _A2, _A3]

    n_audit, n_oq = await demo_repo.seed_status(ids)
    n_fleet = await demo_repo.fleet_count()

    return {
        "seeded":          n_audit > 50,
        "audit_entries":   n_audit,
        "oversight_items": n_oq,
        "fleet_agents":    n_fleet,
    }


# ── Symulator scenariuszy ──────────────────────────────────────────────────────

@router.get("/scenarios")
async def list_scenarios(user: CurrentUser = Depends(get_current_user)):
    return {
        agent_id: {
            key: {
                "label":       _scenario_text(agent_id, s, "label"),
                "description": _scenario_text(agent_id, s, "description"),
                "expected":    s["expected"],
            }
            for key, s in agent_scenarios.items()
        }
        for agent_id, agent_scenarios in SCENARIOS.items()
    }


class RunRequest(BaseModel):
    agent_id: str
    scenario: str


@router.post("/run")
async def run_scenario(req: RunRequest, user: CurrentUser = Depends(get_current_user)):
    """Wywołuje gateway z prawdziwym modelem (claude-haiku-4-5)."""
    agent_scenarios = SCENARIOS.get(req.agent_id)
    if not agent_scenarios:
        raise HTTPException(400, t("demo.errors.unknownAgent", agent_id=req.agent_id))

    scenario = agent_scenarios.get(req.scenario)
    if not scenario:
        raise HTTPException(400, t("demo.errors.unknownScenario", scenario=req.scenario))

    task_id = str(uuid.uuid4())

    # Gateway wymaga autoryzacji (AuthMiddleware) — mintujemy token serwisowy
    # z tożsamości zalogowanego użytkownika; API i gateway dzielą JWT_SECRET.
    gw_token = create_access_token(user.id, user.email, user.role)

    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            r = await client.post(
                f"{settings.gateway_url}/v1/chat/completions",
                json={
                    "model":      "claude-haiku-4-5-20251001",
                    "messages":   _scenario_messages(req.agent_id, scenario),
                    "max_tokens": 350,
                },
                headers={
                    "X-Agent-ID":   req.agent_id,
                    "X-Task-ID":    task_id,
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {gw_token}",
                },
            )
        except httpx.ConnectError:
            raise HTTPException(503, t("demo.errors.gatewayUnavailable"))
        except httpx.TimeoutException:
            raise HTTPException(504, t("demo.errors.gatewayTimeout"))

    body = r.json()

    if r.status_code == 403 or (isinstance(body, dict) and body.get("blocked")):
        policy_result = "blocked"
    elif isinstance(body, dict) and body.get("status") == "awaiting_oversight":
        policy_result = "oversight_required"
    elif isinstance(body, dict) and ("choices" in body or "content" in body):
        policy_result = "allowed"
    elif r.status_code >= 500:
        # Brak providera (503) / błąd wywołania LLM (502) — awaria infrastruktury,
        # nie decyzja polityki. Spójne z audit_log.policy_result = 'error'.
        policy_result = "error"
    else:
        policy_result = "unknown"

    return {
        "scenario_label":       _scenario_text(req.agent_id, scenario, "label"),
        "scenario_description": _scenario_text(req.agent_id, scenario, "description"),
        "expected":             scenario["expected"],
        "agent_id":             req.agent_id,
        "task_id":              task_id,
        "http_status":          r.status_code,
        "policy_result":        policy_result,
        "gateway_response":     body,
    }

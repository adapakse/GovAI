"""
Raport Zarządzania AI Przedsiębiorstwa — agregacja danych + generowanie PDF.
"""
import io
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import anthropic
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)

from config import settings
from i18n import language_name_en, t, t_dict
from services import settings_service
from repositories import compliance_repository as compliance_repo
from database import get_pool

# ── Fonty ────────────────────────────────────────────────────────────────────
_FD = "/usr/share/fonts/truetype/dejavu"
try:
    pdfmetrics.registerFont(TTFont("ERpt",      f"{_FD}/DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("ERpt-Bold", f"{_FD}/DejaVuSans-Bold.ttf"))
    pdfmetrics.registerFontFamily("ERpt", normal="ERpt", bold="ERpt-Bold",
                                  italic="ERpt", boldItalic="ERpt-Bold")
except Exception:
    pass  # już zarejestrowane przez report_generator

_F  = "ERpt"
_FB = "ERpt-Bold"

# ── Stałe ─────────────────────────────────────────────────────────────────────
_RISK_HEX = {"minimal": "#2D9C61", "limited": "#1E6FBF",
              "high": "#E67E22", "unacceptable": "#C0392B"}


def _risk_label(risk: str) -> str:
    """Etykieta poziomu ryzyka — wspólna z raportem agenta (report.risk.<poziom>)."""
    return t_dict("report.risk").get(risk, risk)


def _status_label(status: str | None) -> str:
    return t_dict("enterpriseReport.agentStatus").get(status, status or "—")


_ENTERPRISE_PROMPT = """\
Jesteś dyrektorem ds. zgodności AI (Chief AI Compliance Officer) w dużym przedsiębiorstwie.
Na podstawie poniższych danych operacyjnych za okres {days} dni napisz streszczenie wykonawcze
dla zarządu (max 320 słów, bez nagłówków, ciągły tekst).
Write the summary in {language}.

Dane organizacji:
{data}

Streszczenie powinno:
1. Ocenić ogólny stan zarządzania AI w organizacji
2. Wskazać najważniejsze ryzyka i luki compliance (EU AI Act)
3. Skomentować efektywność nadzoru człowieka (art. 14) na podstawie statystyk
4. Wskazać 2-3 priorytety dla zarządu na najbliższy kwartał
5. Ocenić trend (czy sytuacja się poprawia/pogarsza)

Pisz profesjonalnie, konkretnie, bez słownictwa technicznego IT.\
"""


# ── Zbieranie danych ──────────────────────────────────────────────────────────

def _ser(v: Any) -> Any:
    if isinstance(v, Decimal): return float(v)
    if hasattr(v, "isoformat"):  return v.isoformat()
    if isinstance(v, (list, tuple)): return [_ser(x) for x in v]
    return v


def _row(r) -> dict:
    return {k: _ser(v) for k, v in dict(r).items()}


async def collect_enterprise_data(days: int = 30) -> dict:
    pool = get_pool()

    # ── Agenci ────────────────────────────────────────────────────────────────
    agents = await pool.fetch(
        """SELECT id, name, risk_level, status, requires_oversight,
                  model_id, team, monthly_budget_eur, owner_name,
                  next_review_date, compliance_decl,
                  version, last_reviewed_at, annex_iii_cat
           FROM agents ORDER BY risk_level, name"""
    )
    agents_list = []
    for a in agents:
        d = _row(a)
        # JSONB compliance_decl może przyjść jako string
        if isinstance(d.get("compliance_decl"), str):
            try:
                d["compliance_decl"] = json.loads(d["compliance_decl"])
            except Exception:
                d["compliance_decl"] = {}
        d["id"] = str(d["id"])
        agents_list.append(d)

    agent_ids = [a["id"] for a in agents_list]

    # ── KPI globalne ──────────────────────────────────────────────────────────
    kpi = await pool.fetchrow(
        f"""SELECT
            COUNT(*)                                              AS total_calls,
            COUNT(*) FILTER (WHERE policy_result='blocked')      AS blocked,
            COUNT(*) FILTER (WHERE policy_result='oversight_required') AS oversight,
            COUNT(*) FILTER (WHERE pii_count > 0)                AS pii_calls,
            COALESCE(SUM(pii_count), 0)                          AS pii_entities,
            COALESCE(SUM(cost_eur), 0)::numeric(14,4)            AS total_cost,
            ROUND(AVG(latency_ms)::numeric, 0)                   AS avg_latency,
            MAX(latency_ms)                                       AS max_latency,
            COALESCE(SUM(tokens_in),  0)                         AS tokens_in,
            COALESCE(SUM(tokens_out), 0)                         AS tokens_out
        FROM audit_log
        WHERE time > NOW() - ($1 || ' days')::INTERVAL""",
        str(days),
    )

    # ── Statystyki per agent ───────────────────────────────────────────────────
    per_agent = await pool.fetch(
        f"""SELECT
            agent_id::text, agent_name,
            COUNT(*)                                             AS calls,
            COUNT(*) FILTER (WHERE policy_result='blocked')     AS blocked,
            COUNT(*) FILTER (WHERE policy_result='oversight_required') AS oversight,
            COUNT(*) FILTER (WHERE pii_count > 0)               AS pii_calls,
            COALESCE(SUM(cost_eur),0)::numeric(12,4)            AS cost_eur,
            ROUND(AVG(latency_ms)::numeric,0)                   AS avg_latency
        FROM audit_log
        WHERE time > NOW() - ($1 || ' days')::INTERVAL
        GROUP BY agent_id, agent_name
        ORDER BY calls DESC""",
        str(days),
    )

    # ── Trend dzienny ─────────────────────────────────────────────────────────
    daily = await pool.fetch(
        f"""SELECT
            DATE_TRUNC('day', time)::date::text        AS day,
            COUNT(*)                                    AS calls,
            COUNT(*) FILTER (WHERE policy_result='blocked') AS blocked,
            COALESCE(SUM(cost_eur),0)::numeric(10,4)   AS cost_eur
        FROM audit_log
        WHERE time > NOW() - ($1 || ' days')::INTERVAL
        GROUP BY 1 ORDER BY 1""",
        str(days),
    )

    # ── Rozkład PII ────────────────────────────────────────────────────────────
    pii_cats = await pool.fetch(
        f"""SELECT cat, COUNT(*) AS cnt
        FROM audit_log,
             UNNEST(pii_categories) AS cat
        WHERE time > NOW() - ($1 || ' days')::INTERVAL
        GROUP BY cat ORDER BY cnt DESC LIMIT 10""",
        str(days),
    )

    # ── Aktywacje polityk ──────────────────────────────────────────────────────
    policy_hits = await pool.fetch(
        f"""SELECT policy_id, COUNT(*) AS cnt
        FROM audit_log
        WHERE policy_result='blocked'
          AND time > NOW() - ($1 || ' days')::INTERVAL
          AND policy_id IS NOT NULL
        GROUP BY policy_id ORDER BY cnt DESC""",
        str(days),
    )

    # ── Kolejka nadzoru — historia ─────────────────────────────────────────────
    oversight_hist = await pool.fetchrow(
        f"""SELECT
            COUNT(*)                                             AS total,
            COUNT(*) FILTER (WHERE status='approved')           AS approved,
            COUNT(*) FILTER (WHERE status='rejected')           AS rejected,
            COUNT(*) FILTER (WHERE status='escalated')          AS escalated,
            COUNT(*) FILTER (WHERE status='pending')            AS pending,
            ROUND(AVG(EXTRACT(EPOCH FROM (reviewed_at - review_start_at)))::numeric/60, 1)
                                                                AS avg_review_min
        FROM oversight_queue
        WHERE created_at > NOW() - ($1 || ' days')::INTERVAL""",
        str(days),
    )

    # ── Alerty budżetowe ───────────────────────────────────────────────────────
    budget_alerts = []
    agent_stats_map = {r["agent_id"]: _row(r) for r in per_agent}
    for a in agents_list:
        aid = str(a["id"])
        threshold = float(a.get("cost_alert_threshold_eur") or 0)
        actual = float(agent_stats_map.get(aid, {}).get("cost_eur") or 0)
        if threshold > 0 and actual >= threshold:
            budget_alerts.append({
                "name": a["name"], "actual": actual, "threshold": threshold,
                "pct": round(actual / threshold * 100),
            })

    # ── Przeglądy compliance — zaległe ────────────────────────────────────────
    overdue_reviews = [
        a for a in agents_list
        if a.get("next_review_date") and
        a["next_review_date"] < datetime.now(timezone.utc).date().isoformat()
    ]

    # ── Rozkład ryzyka ─────────────────────────────────────────────────────────
    risk_dist: dict[str, int] = {}
    for a in agents_list:
        rl = a.get("risk_level", "minimal")
        risk_dist[rl] = risk_dist.get(rl, 0) + 1

    # ── Katalog wymagań wysokiego ryzyka (dla macierzy deklaracji, sekcja 7) ───
    # Z bazy (ai_act_requirements), nie z listy zaszytej w kodzie — edytowalny
    # w Polityki → Wymagania EU AI Act i od razu odzwierciedlony w tym raporcie.
    high_risk_requirements = [
        dict(r) for r in await compliance_repo.list_requirements(
            risk_level="high", active_only=True,
        )
    ]

    return {
        "high_risk_requirements": high_risk_requirements,
        "period_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agents": agents_list,
        "kpi": _row(kpi) if kpi else {},
        "per_agent": [_row(r) for r in per_agent],
        "daily": [_row(r) for r in daily],
        "pii_cats": [_row(r) for r in pii_cats],
        "policy_hits": [_row(r) for r in policy_hits],
        "oversight_hist": _row(oversight_hist) if oversight_hist else {},
        "budget_alerts": budget_alerts,
        "overdue_reviews": overdue_reviews,
        "risk_dist": risk_dist,
        "agent_stats_map": agent_stats_map,
    }


async def generate_enterprise_narrative(data: dict) -> str:
    kpi = data["kpi"]
    total = int(kpi.get("total_calls") or 0)
    blocked = int(kpi.get("blocked") or 0)
    pii = int(kpi.get("pii_calls") or 0)
    days = data["period_days"]
    n_agents = len(data["agents"])
    n_high = sum(1 for a in data["agents"] if a.get("risk_level") in ("high", "unacceptable"))

    summary = {
        "okres_dni": days,
        "agenci_łącznie": n_agents,
        "agenci_wysokie_ryzyko": n_high,
        "wywołania_łącznie": total,
        "blokady": blocked,
        "blokady_pct": round(blocked / max(total, 1) * 100, 1),
        "incydenty_pii": pii,
        "koszt_eur": float(kpi.get("total_cost") or 0),
        "kolejka_nadzoru_łącznie": int(data["oversight_hist"].get("total") or 0),
        "kolejka_nadzoru_oczekujące": int(data["oversight_hist"].get("pending") or 0),
        "alerty_budżetowe": len(data["budget_alerts"]),
        "zaległe_przeglądy": len(data["overdue_reviews"]),
        "rozkład_ryzyka": data["risk_dist"],
    }

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model=settings_service.get_str("models.classifier_model", settings.classifier_model),
            max_tokens=settings_service.get_int("compliance.enterprise_report_max_tokens", 500),
            messages=[{
                "role": "user",
                "content": _ENTERPRISE_PROMPT.format(
                    days=days,
                    data=json.dumps(summary, ensure_ascii=False, indent=2),
                    language=language_name_en(),
                ),
            }],
        )
        return msg.content[0].text.strip()
    except Exception:
        block_pct = round(blocked / max(total, 1) * 100, 1)
        return t(
            "enterpriseReport.fallbackNarrative",
            days=days, agents=n_agents, high=n_high, total=total, blocked=blocked,
            block_pct=block_pct, pii=pii, cost=f"{float(kpi.get('total_cost') or 0):.2f}",
        )


# ── Helpers PDF ───────────────────────────────────────────────────────────────

def _s(name: str, **kw) -> ParagraphStyle:
    defaults = {"fontName": _F, "fontSize": 10, "leading": 14}
    defaults.update(kw)
    return ParagraphStyle(name, **defaults)


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_md(str(text)), style)


def _md(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*',     r'<i>\1</i>', text)
    return text


def _hr(thick: float = 0.5, color: str = "#CBD5E1", before: float = 4, after: float = 8):
    return HRFlowable(width="100%", thickness=thick,
                      color=colors.HexColor(color), spaceBefore=before, spaceAfter=after)


def _tbl(rows: list[list], widths: list, header_bg: str = "#1B355E") -> Table:
    styles = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), _FB),
        ("FONTNAME",   (0, 1), (-1, -1), _F),
        ("FONTSIZE",   (0, 0), (-1, -1), 8.5),
        ("LEADING",    (0, 0), (-1, -1), 12),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("PADDING",    (0, 0), (-1, -1), 5),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i in range(1, len(rows)):
        bg = colors.HexColor("#EEF3FA") if i % 2 == 0 else colors.white
        styles.append(("BACKGROUND", (0, i), (-1, i), bg))

    rich = []
    for ri, row in enumerate(rows):
        rich.append([
            Paragraph(_md(str(cell)), ParagraphStyle(
                f"tc{ri}", fontName=_FB if ri == 0 else _F, fontSize=8.5, leading=12,
                textColor=colors.white if ri == 0 else colors.HexColor("#1a1a2e"),
            ))
            for cell in row
        ])

    t = Table(rich, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle(styles))
    return t


def _kpi_table(items: list[tuple[str, str, str]]) -> Table:
    """3-column KPI strip: [(label, value, sub), ...]"""
    label_s = _s("kl", fontSize=8,  textColor=colors.HexColor("#64748b"))
    val_s   = _s("kv", fontSize=18, fontName=_FB, leading=22,
                  textColor=colors.HexColor("#0D1B2A"))
    sub_s   = _s("ks", fontSize=7.5, textColor=colors.HexColor("#94a3b8"))

    cells = []
    for label, value, sub in items:
        cells.append([
            Paragraph(label, label_s),
            Paragraph(value, val_s),
            Paragraph(sub,   sub_s),
        ])

    col_w = A4[0] - 5*cm  # szerokość obszaru
    per   = col_w / len(items)
    t = Table([cells], colWidths=[per] * len(items))
    t.setStyle(TableStyle([
        ("BOX",        (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("INNERGRID",  (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("PADDING",    (0, 0), (-1, -1), 8),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
    ]))
    return t


# ── Generowanie PDF ───────────────────────────────────────────────────────────

def render_enterprise_pdf(data: dict, narrative: str) -> bytes:
    buf = io.BytesIO()
    W, H = A4
    lm = rm = 2.2*cm
    tm = bm = 2.2*cm

    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=lm, rightMargin=rm,
                            topMargin=tm, bottomMargin=bm)

    S = {
        "brand":   _s("br", fontSize=26, fontName=_FB, leading=32,
                       textColor=colors.HexColor("#00B4D8"), spaceAfter=4),
        "sub":     _s("su", fontSize=10, leading=14,
                       textColor=colors.HexColor("#1E6FBF"), spaceAfter=8),
        "meta":    _s("me", fontSize=8, leading=12, textColor=colors.grey),
        "h2":      _s("h2", fontSize=13, fontName=_FB, leading=18,
                       textColor=colors.HexColor("#1B355E"), spaceBefore=14, spaceAfter=4),
        "h3":      _s("h3", fontSize=10, fontName=_FB, leading=14,
                       textColor=colors.HexColor("#1B355E"), spaceBefore=8, spaceAfter=3),
        "body":    _s("bo", fontSize=9.5, leading=14, spaceAfter=4),
        "small":   _s("sm", fontSize=7.5, leading=11, textColor=colors.grey),
        "risk_h":  _s("rh", fontSize=10, fontName=_FB, leading=14,
                       textColor=colors.white),
        "alert":   _s("al", fontSize=9, leading=13,
                       textColor=colors.HexColor("#92400e")),
    }

    gen_dt = datetime.fromisoformat(data["generated_at"])
    days   = data["period_days"]
    kpi    = data["kpi"]
    agents = data["agents"]
    oh     = data["oversight_hist"]
    rd     = data["risk_dist"]
    asm    = data["agent_stats_map"]

    total   = int(kpi.get("total_calls") or 0)
    blocked = int(kpi.get("blocked") or 0)
    pii_c   = int(kpi.get("pii_calls") or 0)
    cost    = float(kpi.get("total_cost") or 0)
    lat     = kpi.get("avg_latency")

    story: list = []

    # ══════════════════════════════════════════════════════════════════════════
    # STRONA TYTUŁOWA
    # ══════════════════════════════════════════════════════════════════════════
    # Format daty z tłumaczeń (strftime, wspólny z raportem agenta) — domyślnie dd.mm.rrrr
    gen_str = gen_dt.strftime(t("report.format.dateTime"))
    P = "enterpriseReport.pdf."

    story += [
        Spacer(1, 1.5*cm),
        _p("GovAI", S["brand"]),
        _p(t("report.pdf.tagline"), S["sub"]),
        _hr(thick=3, color="#1E6FBF", before=4, after=20),
        _p(t(P + "title"), _s("rt", fontSize=22, fontName=_FB,
            leading=28, textColor=colors.HexColor("#0D1B2A"), spaceAfter=6)),
        _p(t(P + "period", days=days), _s("rp", fontSize=13, leading=18,
            textColor=colors.HexColor("#334155"), spaceAfter=4)),
        _p(t(P + "generated", date=gen_str), S["meta"]),
        Spacer(1, 1.2*cm),
    ]

    # Skrzynka z kluczowymi liczbami — strona tytułowa
    n_active = sum(1 for a in agents if a.get("status") == "active")
    n_high   = sum(1 for a in agents if a.get("risk_level") in ("high", "unacceptable"))
    story.append(_kpi_table([
        (t(P + "cover.agents"), str(len(agents)), t(P + "cover.agentsActive", n=n_active)),
        (t(P + "cover.calls"), f"{total:,}".replace(",", " "), t(P + "cover.lastDays", days=days)),
        (t(P + "cover.blocks"), f"{blocked:,}".replace(",", " "),
         t(P + "cover.blocksShare", pct=f"{blocked/max(total,1)*100:.1f}")),
        (t(P + "cover.pii"), str(pii_c), t(P + "cover.piiNote")),
        (t(P + "cover.apiCost"), f"{cost:.2f} EUR", t(P + "cover.totalDays", days=days)),
    ]))
    story += [
        Spacer(1, 0.8*cm),
        _hr(thick=0.5),
    ]

    # Alerty
    alerts = data.get("budget_alerts", [])
    overdue = data.get("overdue_reviews", [])
    if alerts or overdue:
        alert_bg = colors.HexColor("#FEF3C7")
        alert_border = colors.HexColor("#F59E0B")
        alert_lines = []
        for b in alerts:
            alert_lines.append(t(
                P + "alerts.budgetExceeded", name=b["name"], actual=f"{b['actual']:.2f}",
                pct=b["pct"], threshold=f"{b['threshold']:.0f}",
            ))
        for o in overdue:
            d = o.get("next_review_date", "")[:10]
            alert_lines.append(t(P + "alerts.overdueReview", name=o["name"], date=d))

        alert_data = [[Paragraph(line, S["alert"])] for line in alert_lines]
        at = Table(alert_data, colWidths=[W - lm - rm])
        at.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), alert_bg),
            ("BOX",        (0,0), (-1,-1), 1, alert_border),
            ("PADDING",    (0,0), (-1,-1), 6),
        ]))
        story += [Spacer(1, 0.3*cm), at, Spacer(1, 0.4*cm)]

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 1. STRESZCZENIE DLA ZARZĄDU
    # ══════════════════════════════════════════════════════════════════════════
    story += [
        _p(t(P + "sections.summary"), S["h2"]),
        _hr(),
        _p(_md(narrative), S["body"]),
        Spacer(1, 0.3*cm),
    ]

    # ══════════════════════════════════════════════════════════════════════════
    # 2. ROZKŁAD RYZYKA
    # ══════════════════════════════════════════════════════════════════════════
    story += [_p(t(P + "sections.riskDistribution"), S["h2"]), _hr()]

    risk_order = ["unacceptable", "high", "limited", "minimal"]
    risk_rows = [[t(P + "risk.level"), t(P + "risk.agentCount"),
                  t(P + "risk.agents"), t(P + "risk.requiresOversight")]]
    for rl in risk_order:
        cnt = rd.get(rl, 0)
        if cnt == 0:
            continue
        names = ", ".join(a["name"] for a in agents if a.get("risk_level") == rl)
        oversight_cnt = sum(1 for a in agents
                            if a.get("risk_level") == rl and a.get("requires_oversight"))
        hex_c = _RISK_HEX.get(rl, "#666")
        label = f'<font color="{hex_c}"><b>{_risk_label(rl)}</b></font>'
        risk_rows.append([label, str(cnt), names, str(oversight_cnt)])

    story += [
        _tbl(risk_rows, [3.5*cm, 2.5*cm, 7.5*cm, 3*cm]),
        Spacer(1, 0.4*cm),
    ]

    # ══════════════════════════════════════════════════════════════════════════
    # 3. KPI OPERACYJNE
    # ══════════════════════════════════════════════════════════════════════════
    story += [_p(t(P + "sections.kpi", days=days), S["h2"]), _hr()]

    oversight_total = int(oh.get("total") or 0)
    oversight_pend  = int(oh.get("pending") or 0)
    avg_rev = oh.get("avg_review_min")
    K = P + "kpi."

    kpi_rows = [
        [t(K + "metric"), t(K + "value"), t(K + "comment")],
        [t(K + "totalCalls"),    f"{total:,}".replace(",", " "), t(K + "totalCallsNote")],
        [t(K + "policyBlocks"),  f"{blocked}  ({blocked/max(total,1)*100:.1f}%)",
                                  t(K + "policyBlocksNote")],
        [t(K + "oversight"),     str(int(kpi.get("oversight") or 0)), t(K + "oversightNote")],
        [t(K + "pii"),           str(pii_c), t(K + "piiNote", n=int(kpi.get("pii_entities") or 0))],
        [t(K + "avgLatency"),    f"{float(lat):.0f} ms" if lat else "—", t(K + "avgLatencyNote")],
        [t(K + "maxLatency"),    f"{int(kpi.get('max_latency') or 0)} ms", t(K + "maxLatencyNote")],
        [t(K + "tokensIn"),      f"{int(kpi.get('tokens_in') or 0):,}".replace(",", " "), t(K + "tokensInNote")],
        [t(K + "tokensOut"),     f"{int(kpi.get('tokens_out') or 0):,}".replace(",", " "), t(K + "tokensOutNote")],
        [t(K + "apiCost"),       f"{cost:.4f} EUR", t(K + "apiCostNote")],
        [t(K + "oversightQueue"), t(K + "oversightQueueValue", total=oversight_total, pending=oversight_pend),
                                  t(K + "avgReview", min=f"{float(avg_rev):.1f}") if avg_rev else t(P + "noData")],
    ]
    story += [_tbl(kpi_rows, [5*cm, 4.5*cm, 7*cm]), Spacer(1, 0.4*cm)]

    # ══════════════════════════════════════════════════════════════════════════
    # 4. REJESTR AGENTÓW
    # ══════════════════════════════════════════════════════════════════════════
    story += [PageBreak(), _p(t(P + "sections.registry"), S["h2"]), _hr()]

    C = P + "columns."
    agent_rows = [[t(C + "agent"), t(C + "risk"), t(C + "status"), t(C + "oversight"),
                   t(C + "calls"), t(C + "blocks"), t(C + "costEur"), t(C + "review")]]
    for a in agents:
        aid = str(a["id"])
        st = asm.get(aid, {})
        calls   = int(st.get("calls") or 0)
        blk     = int(st.get("blocked") or 0)
        cost_a  = float(st.get("cost_eur") or 0)
        rev     = (a.get("next_review_date") or "")[:10] or "—"
        rl      = a.get("risk_level", "minimal")
        hex_c   = _RISK_HEX.get(rl, "#666")
        risk_short = t_dict(P + "riskShort").get(rl, rl[:3].upper())
        risk_lbl = f'<font color="{hex_c}"><b>{risk_short}</b></font>'
        status_lbl = _status_label(a.get("status"))
        agent_rows.append([
            a["name"], risk_lbl, status_lbl,
            t(P + "yes") if a.get("requires_oversight") else t(P + "no"),
            str(calls), str(blk), f"{cost_a:.4f}", rev,
        ])

    story += [
        _tbl(agent_rows, [4.5*cm, 2.3*cm, 2.3*cm, 1.5*cm, 1.8*cm, 1.8*cm, 2.2*cm, 2.1*cm]),
        Spacer(1, 0.4*cm),
    ]

    # ══════════════════════════════════════════════════════════════════════════
    # 5. TOP AGENCI
    # ══════════════════════════════════════════════════════════════════════════
    story += [_p(t(P + "sections.activity"), S["h2"]), _hr()]

    pa = data["per_agent"]
    if pa:
        story += [_p(t(P + "activity.topByCalls"), S["h3"])]
        top_calls = pa[:5]
        top_rows = [[t(C + "agent"), t(C + "calls"), t(C + "blocks"), t(C + "oversight"),
                     t(C + "pii"), t(C + "costEur"), t(C + "avgLatency")]]
        for r in top_calls:
            top_rows.append([
                r["agent_name"],
                str(int(r.get("calls") or 0)),
                str(int(r.get("blocked") or 0)),
                str(int(r.get("oversight") or 0)),
                str(int(r.get("pii_calls") or 0)),
                f"{float(r.get('cost_eur') or 0):.4f}",
                f"{float(r.get('avg_latency') or 0):.0f} ms",
            ])
        story += [_tbl(top_rows, [4.5*cm, 2*cm, 2*cm, 1.8*cm, 1.8*cm, 2.2*cm, 2.2*cm]),
                  Spacer(1, 0.3*cm)]

        # Top wg blokad
        top_blocked = sorted(pa, key=lambda r: int(r.get("blocked") or 0), reverse=True)[:5]
        top_blocked = [r for r in top_blocked if int(r.get("blocked") or 0) > 0]
        if top_blocked:
            story += [_p(t(P + "activity.topByBlocks"), S["h3"])]
            blk_rows = [[t(C + "agent"), t(C + "blocks"), t(C + "calls"), t(C + "blockRate")]]
            for r in top_blocked:
                calls_r = int(r.get("calls") or 0)
                blk_r   = int(r.get("blocked") or 0)
                blk_rows.append([
                    r["agent_name"], str(blk_r), str(calls_r),
                    f"{blk_r/max(calls_r,1)*100:.1f}%",
                ])
            story += [_tbl(blk_rows, [6*cm, 3*cm, 3*cm, 3*cm]), Spacer(1, 0.3*cm)]

    # ══════════════════════════════════════════════════════════════════════════
    # 6. INCYDENTY BEZPIECZEŃSTWA
    # ══════════════════════════════════════════════════════════════════════════
    story += [PageBreak(), _p(t(P + "sections.incidents"), S["h2"]), _hr()]
    I = P + "incidents."

    if data["pii_cats"]:
        story += [_p(t(I + "piiCategories"), S["h3"])]
        pii_rows = [[t(I + "piiCategory"), t(I + "incidentCount")]]
        for r in data["pii_cats"]:
            pii_rows.append([r["cat"], str(int(r["cnt"]))])
        story += [_tbl(pii_rows, [10*cm, 6.5*cm]), Spacer(1, 0.3*cm)]
    else:
        story += [_p(t(I + "noPii"), S["body"])]

    if data["policy_hits"]:
        story += [_p(t(I + "policyHits"), S["h3"])]
        ph_rows = [[t(I + "policyCode"), t(I + "blockCount")]]
        for r in data["policy_hits"]:
            ph_rows.append([r["policy_id"] or "—", str(int(r["cnt"]))])
        story += [_tbl(ph_rows, [10*cm, 6.5*cm]), Spacer(1, 0.3*cm)]

    # Kolejka nadzoru
    story += [_p(t(I + "oversightHistory"), S["h3"])]
    ov_rows = [
        [t(K + "metric"),        t(K + "value")],
        [t(I + "tasksTotal"),    str(int(oh.get("total") or 0))],
        [t(I + "approved"),      str(int(oh.get("approved") or 0))],
        [t(I + "rejected"),      str(int(oh.get("rejected") or 0))],
        [t(I + "escalated"),     str(int(oh.get("escalated") or 0))],
        [t(I + "pending"),       str(int(oh.get("pending") or 0))],
        [t(I + "avgReviewTime"), f"{float(oh.get('avg_review_min') or 0):.1f} min"
                                 if oh.get("avg_review_min") else t(P + "noData")],
    ]
    story += [_tbl(ov_rows, [10*cm, 6.5*cm]), Spacer(1, 0.4*cm)]

    # ══════════════════════════════════════════════════════════════════════════
    # 7. ZGODNOŚĆ EU AI ACT — deklaracje
    # ══════════════════════════════════════════════════════════════════════════
    high_risk_agents = [a for a in agents if a.get("risk_level") in ("high", "unacceptable")]
    # Kolumny macierzy — z katalogu wymagań (ai_act_requirements), nie z listy
    # zaszytej w kodzie. Wymaganie bez decl_key (np. Art. 5 dla unacceptable)
    # nie ma odpowiednika w samo-deklaracji, więc pomijamy je w tej macierzy.
    ARTS = [
        (r["decl_key"], f'{r["article_ref"]}\n{r["requirement_title"]}')
        for r in data.get("high_risk_requirements", []) if r.get("decl_key")
    ]
    if high_risk_agents and ARTS:
        story += [_p(t(P + "sections.declarations"), S["h2"]), _hr()]

        STATUS_ICON = {"yes": "✓", "partial": "◑", "no": "✗", "na": "N/A", "": "—"}
        STATUS_COL  = {"yes": "#166534", "partial": "#92400e", "no": "#991b1b",
                       "na": "#475569", "": "#94a3b8"}

        header = [t(C + "agent")] + [a[1] for a in ARTS]
        decl_rows = [header]
        for a in high_risk_agents:
            decl = a.get("compliance_decl") or {}
            row = [a["name"]]
            for key, _ in ARTS:
                entry = decl.get(key, {})
                st = entry.get("status", "") if isinstance(entry, dict) else ""
                icon = STATUS_ICON.get(st, "—")
                col  = STATUS_COL.get(st, "#94a3b8")
                row.append(f'<font color="{col}"><b>{icon}</b></font>')
            decl_rows.append(row)

        art_w = (W - lm - rm - 4.5*cm) / len(ARTS)
        story += [
            _tbl(decl_rows, [4.5*cm] + [art_w] * len(ARTS)),
            _p(t(P + "declarationsLegend"),
               _s("leg", fontSize=7.5, textColor=colors.grey)),
            Spacer(1, 0.4*cm),
        ]
        sec = 8
    else:
        sec = 7

    # ══════════════════════════════════════════════════════════════════════════
    # 8. ZALECENIA
    # ══════════════════════════════════════════════════════════════════════════
    story += [_p(t(P + "sections.recommendations", n=sec), S["h2"]), _hr()]

    recs = _build_recommendations(data)
    rec_rows = [["#", t(P + "recommendations.priority"), t(P + "recommendations.recommendation"),
                 t(P + "recommendations.basis")]]
    for i, r in enumerate(recs, 1):
        rec_rows.append([str(i), r["priority"], r["text"], r["basis"]])

    # Kolor wg kodu priorytetu; etykieta z tłumaczeń (enterpriseReport.priority.<kod>)
    priority_colors = {"critical": "#991b1b", "high": "#92400e", "medium": "#1e40af"}
    priority_labels = t_dict("enterpriseReport.priority")
    rec_rich = [rec_rows[0]]
    for ri, row in enumerate(rec_rows[1:], 1):
        prio = row[1]
        col  = priority_colors.get(prio, "#1a1a2e")
        rec_rich.append([
            row[0],
            f'<font color="{col}"><b>{priority_labels.get(prio, prio)}</b></font>',
            row[2], row[3],
        ])

    story += [_tbl(rec_rich, [0.8*cm, 2.2*cm, 10*cm, 3.5*cm]), Spacer(1, 0.8*cm)]

    # ══════════════════════════════════════════════════════════════════════════
    # STOPKA
    # ══════════════════════════════════════════════════════════════════════════
    story += [
        _hr(thick=1),
        _p(t("report.footer", date=gen_str), S["small"]),
    ]

    doc.build(story)
    buf.seek(0)
    return buf.read()


def _build_recommendations(data: dict) -> list[dict]:
    recs = []
    agents  = data["agents"]
    kpi     = data["kpi"]
    total   = int(kpi.get("total_calls") or 0)
    blocked = int(kpi.get("blocked") or 0)
    oh      = data["oversight_hist"]

    high_risk = [a for a in agents if a.get("risk_level") in ("high", "unacceptable")]
    no_docs   = [a for a in high_risk
                 if not (a.get("compliance_decl") or {}).get("art11_technical_docs", {}).get("status") == "yes"]
    no_oversight_decl = [a for a in high_risk
                         if not (a.get("compliance_decl") or {}).get("art14_human_oversight", {}).get("status") in ("yes","partial")]
    overdue  = data.get("overdue_reviews", [])
    alerts   = data.get("budget_alerts", [])
    pend     = int(oh.get("pending") or 0)

    # priority = kod (critical/high/medium) — etykieta i kolor nadawane przy renderze
    R = "enterpriseReport.recommendations."

    if [a for a in agents if a.get("risk_level") == "unacceptable"]:
        recs.append({"priority": "critical",
                     "text": t(R + "suspendUnacceptable"),
                     "basis": "Art. 5 EU AI Act"})

    if no_docs:
        names = ", ".join(a["name"] for a in no_docs[:3])
        recs.append({"priority": "critical",
                     "text": t(R + "missingTechnicalDocs", names=names),
                     "basis": "Art. 11 EU AI Act"})

    if no_oversight_decl:
        names = ", ".join(a["name"] for a in no_oversight_decl[:3])
        recs.append({"priority": "critical",
                     "text": t(R + "implementOversight", names=names),
                     "basis": "Art. 14 EU AI Act"})

    if overdue:
        names = ", ".join(a["name"] for a in overdue[:3])
        recs.append({"priority": "high",
                     "text": t(R + "overdueReviews", names=names),
                     "basis": t(R + "basisInternalPolicy")})

    if pend > 0:
        recs.append({"priority": "high",
                     "text": t(R + "pendingOversight", n=pend),
                     "basis": "Art. 14 EU AI Act"})

    if alerts:
        names = ", ".join(a["name"] for a in alerts[:3])
        recs.append({"priority": "high",
                     "text": t(R + "budgetReview", names=names),
                     "basis": t(R + "basisCostControl")})

    if total > 0 and blocked / total > 0.1:
        recs.append({"priority": "medium",
                     "text": t(R + "highBlockRate", pct=f"{blocked/total*100:.1f}"),
                     "basis": "G-001, G-002"})

    if not recs:
        recs.append({"priority": "medium",
                     "text": t(R + "keepMonitoring"),
                     "basis": t(R + "basisBestPractices")})

    return recs

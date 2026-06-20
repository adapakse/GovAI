import io
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import anthropic
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from config import settings
from database import get_pool

# ── Rejestracja fontów z obsługą polskich znaków ──────────────────────────────
_FONT_DIR = "/usr/share/fonts/truetype/dejavu"
pdfmetrics.registerFont(TTFont("DejaVu",      f"{_FONT_DIR}/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", f"{_FONT_DIR}/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold",
                               italic="DejaVu", boldItalic="DejaVu-Bold")
_F  = "DejaVu"
_FB = "DejaVu-Bold"

def _md_to_rl(text: str) -> str:
    """Konwertuje podstawowy markdown na markup ReportLab (<b>, <i>)."""
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*',     r'<i>\1</i>', text)
    return text

_RISK_LABELS = {
    "minimal":      "Minimalne",
    "limited":      "Ograniczone",
    "high":         "Wysokie",
    "unacceptable": "Niedopuszczalne",
}

_RISK_HEX = {
    "minimal":      "#2D9C61",
    "limited":      "#1E6FBF",
    "high":         "#E67E22",
    "unacceptable": "#C0392B",
}

_NARRATIVE_PROMPT = """\
Jesteś doradcą prawnym specjalizującym się w EU AI Act (Rozporządzenie UE 2024/1689).
Na podstawie poniższych danych o systemie AI napisz streszczenie wykonawcze do raportu
zgodności (max 280 słów, po polsku, bez nagłówków, ciągły tekst).

Dane systemu:
{data}

Streszczenie powinno:
1. Określić ogólny poziom zgodności z uwzględnieniem wykrytych luk
2. Wymienić konkretne artykuły EU AI Act mające zastosowanie
3. Wskazać priorytety działań naprawczych z perspektywy prawnej
4. Ocenić adekwatność nadzoru człowieka (art. 14) na podstawie statystyk

Pisz profesjonalnie i konkretnie.\
"""

_GAPS = {
    "high": [
        ("Art. 9",  "System zarządzania ryzykiem",    "Krytyczna", "90 dni"),
        ("Art. 11", "Dokumentacja techniczna",         "Poważna",   "60 dni"),
        ("Art. 13", "Przejrzystość i informowanie",    "Poważna",   "60 dni"),
        ("Art. 14", "Nadzór człowieka",                "Krytyczna", "30 dni"),
        ("Art. 17", "System zarządzania jakością",     "Poważna",   "90 dni"),
        ("Art. 49", "Rejestracja w bazie EU",          "Poważna",   "Przed wdrożeniem"),
    ],
    "unacceptable": [
        ("Art. 5",  "Zakazane praktyki AI",            "Krytyczna", "NATYCHMIAST"),
    ],
    "limited": [
        ("Art. 52", "Obowiązki przejrzystości",        "Drobna",    "180 dni"),
    ],
    "minimal": [
        ("Art. 52", "Obowiązki przejrzystości",        "Drobna",    "180 dni"),
    ],
}

_RECS = {
    "high": [
        "Przeprowadzić pełną ocenę ryzyka (art. 9) z udziałem zewnętrznego audytora w ciągu 30 dni.",
        "Opracować dokumentację techniczną zgodną z Załącznikiem IV EU AI Act (art. 11) w ciągu 60 dni.",
        "Wdrożyć mierzalne procedury nadzoru człowieka (art. 14) — weryfikowane w systemie GovAI.",
        "Zarejestrować system w europejskiej bazie danych AI (art. 49) przed startem produkcyjnym.",
        "Przeprowadzić wewnętrzny audyt zgodności w ciągu 90 dni.",
    ],
    "unacceptable": [
        "PRIORYTET ABSOLUTNY: Wstrzymać działanie systemu natychmiast.",
        "Skonsultować się z radcą prawnym — system może podlegać zakazom z art. 5 EU AI Act.",
        "Poinformować właściwy organ nadzorczy w kraju wdrożenia.",
    ],
    "limited": [
        "Monitorować aktualizacje wytycznych EU AI Act wydawanych przez EU AI Office.",
        "Zapewnić informowanie użytkowników o interakcji z systemem AI (art. 52).",
        "Dokumentować przypadki użycia systemu przez 5 lat na potrzeby ewentualnego audytu.",
    ],
    "minimal": [
        "Monitorować zmiany w wytycznych EU AI Act.",
        "Zapewnić informowanie użytkowników o interakcji z systemem AI (art. 52).",
        "Dokumentować przypadki użycia systemu na potrzeby ewentualnego audytu.",
    ],
}


def _serialize(val):
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, uuid.UUID):
        return str(val)
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if isinstance(val, (list, tuple)):
        return [_serialize(v) for v in val]
    return val


def _row_to_dict(row) -> dict:
    return {k: _serialize(v) for k, v in dict(row).items()}


async def get_agent_report_data(agent_id: str) -> dict | None:
    pool = get_pool()

    row = await pool.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
    if not row:
        return None
    agent = _row_to_dict(row)

    stats_row = await pool.fetchrow(
        """
        SELECT
            COUNT(*)                                                         AS total_calls,
            COUNT(*) FILTER (WHERE policy_result = 'blocked')                AS blocked,
            COUNT(*) FILTER (WHERE policy_result = 'oversight_required')     AS oversight,
            COUNT(*) FILTER (WHERE array_length(pii_categories, 1) > 0)      AS pii_calls,
            ROUND(AVG(latency_ms)::numeric, 1)                               AS avg_latency,
            COALESCE(SUM(cost_eur), 0)::numeric(12,6)                        AS total_cost
        FROM audit_log
        WHERE agent_id = $1 AND time > NOW() - INTERVAL '30 days'
        """,
        agent_id,
    )
    stats = _row_to_dict(stats_row) if stats_row else {}

    oversight_rows = await pool.fetch(
        """
        SELECT status, reviewer_decision,
               EXTRACT(EPOCH FROM (reviewed_at - review_start_at))::int AS review_duration_s,
               created_at
        FROM oversight_queue
        WHERE agent_id = $1 AND status != 'pending'
        ORDER BY created_at DESC
        LIMIT 5
        """,
        agent_id,
    )

    return {
        "agent": agent,
        "stats": stats,
        "oversight_history": [_row_to_dict(r) for r in oversight_rows],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def generate_narrative(report_data: dict) -> str:
    agent = report_data["agent"]
    stats = report_data["stats"]
    total = int(stats.get("total_calls") or 0)
    blocked = int(stats.get("blocked") or 0)

    summary = {
        "nazwa": agent["name"],
        "poziom_ryzyka": agent.get("risk_level"),
        "kategoria_aneksu_III": agent.get("annex_iii_cat") or "brak",
        "nadzor_wymagany": agent.get("requires_oversight"),
        "wywolania_30d": total,
        "blokady_30d": blocked,
        "blokady_pct": round(blocked / max(total, 1) * 100, 1),
        "do_nadzoru_30d": int(stats.get("oversight") or 0),
        "pii_30d": int(stats.get("pii_calls") or 0),
    }

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model=settings.classifier_model,
            max_tokens=450,
            messages=[{
                "role": "user",
                "content": _NARRATIVE_PROMPT.format(
                    data=json.dumps(summary, ensure_ascii=False, indent=2)
                ),
            }],
        )
        return msg.content[0].text.strip()
    except Exception:
        risk = agent.get("risk_level", "minimal")
        return (
            f"System \"{agent['name']}\" sklasyfikowany jako poziom ryzyka {_RISK_LABELS.get(risk, risk)}. "
            "Pełna analiza zgodności wymaga weryfikacji przez klasyfikator AI. "
            "Prosimy ponowić generowanie raportu."
        )


def _cell(text: str, bold: bool = False) -> Paragraph:
    style = ParagraphStyle(
        "tc", fontName=_FB if bold else _F, fontSize=9, leading=13,
        textColor=colors.white if bold else colors.HexColor("#1a1a2e"),
    )
    return Paragraph(str(text), style)


def _table(data: list, col_widths: list) -> Table:
    # Konwertuj stringi na Paragraph żeby font był respektowany
    rich = []
    for row_i, row in enumerate(data):
        rich.append([_cell(str(cell), bold=(row_i == 0)) for cell in row])

    t = Table(rich, colWidths=col_widths, repeatRows=1)
    style = TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), colors.HexColor("#1B355E")),
        ("FONTNAME",    (0, 0), (-1, -1), _F),
        ("FONTNAME",    (0, 0), (-1, 0),  _FB),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("LEADING",     (0, 0), (-1, -1), 13),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("PADDING",     (0, 0), (-1, -1), 6),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ])
    for i in range(1, len(data)):
        bg = colors.HexColor("#EEF3FA") if i % 2 == 0 else colors.white
        style.add("BACKGROUND", (0, i), (-1, i), bg)
    t.setStyle(style)
    return t


def render_pdf(report_data: dict, narrative: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2.5*cm, rightMargin=2.5*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
    )

    S = {
        "brand":  ParagraphStyle("brand",  fontSize=26, fontName=_FB, leading=32,
                                 textColor=colors.HexColor("#00B4D8"), spaceAfter=4),
        "sub":    ParagraphStyle("sub",    fontSize=10, fontName=_F,  leading=14,
                                 textColor=colors.HexColor("#1E6FBF"), spaceAfter=10),
        "h1":     ParagraphStyle("h1",     fontSize=18, fontName=_FB, leading=24,
                                 textColor=colors.HexColor("#0D1B2A"), spaceAfter=4),
        "h2":     ParagraphStyle("h2",     fontSize=12, fontName=_FB, leading=16,
                                 textColor=colors.HexColor("#1B355E"),
                                 spaceBefore=14, spaceAfter=4),
        "body":   ParagraphStyle("body",   fontSize=10, fontName=_F,  leading=15, spaceAfter=6),
        "small":  ParagraphStyle("small",  fontSize=8,  fontName=_F,  leading=11,
                                 textColor=colors.grey),
        "aname":  ParagraphStyle("aname",  fontSize=13, fontName=_FB, leading=18,
                                 textColor=colors.HexColor("#1B355E"), spaceAfter=6),
    }

    agent = report_data["agent"]
    stats = report_data.get("stats", {})
    gen_at = report_data.get("generated_at", datetime.now(timezone.utc).isoformat())
    gen_dt = datetime.fromisoformat(gen_at)

    risk = agent.get("risk_level", "minimal")
    risk_label = _RISK_LABELS.get(risk, risk)
    risk_hex = _RISK_HEX.get(risk, "#666666")

    def hr():
        return HRFlowable(width="100%", thickness=0.5,
                          color=colors.HexColor("#CBD5E1"), spaceAfter=8)

    story = [
        Spacer(1, 1*cm),
        Paragraph("GovAI", S["brand"]),
        Paragraph("Platforma Zarządzania Agentami AI · EU AI Act Compliance", S["sub"]),
        HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1E6FBF"),
                   spaceBefore=6, spaceAfter=16),
        Paragraph("Raport Zgodności EU AI Act", S["h1"]),
        Paragraph(agent["name"], S["aname"]),
        Spacer(1, 0.2*cm),
        Paragraph(
            f'Poziom ryzyka: <font color="{risk_hex}"><b>{risk_label.upper()}</b></font>',
            S["body"],
        ),
        Paragraph(
            f'Wygenerowano: {gen_dt.strftime("%d.%m.%Y %H:%M")} UTC  ·  '
            f'Właściciel: {agent.get("owner_name", "—")}  ·  '
            f'Zespół: {agent.get("team", "—") or "—"}',
            S["small"],
        ),
        Spacer(1, 0.6*cm),
        # 1. Streszczenie
        Paragraph("1. Streszczenie Wykonawcze", S["h2"]),
        hr(),
        Paragraph(_md_to_rl(narrative), S["body"]),
        Spacer(1, 0.4*cm),
        # 2. Profil
        Paragraph("2. Profil Systemu AI", S["h2"]),
        hr(),
        _table(
            [
                ["Właściwość", "Wartość"],
                ["ID systemu",            str(agent.get("id", "—"))],
                ["Właściciel",            agent.get("owner_name", "—")],
                ["Kontakt",               agent.get("owner_email", "—")],
                ["Zespół",                agent.get("team", "—") or "—"],
                ["Model AI",              agent.get("model_id", "—")],
                ["Status",                agent.get("status", "—").upper()],
                ["Kategoria Aneksu III",  agent.get("annex_iii_cat") or "Brak (nie-aneksowy)"],
                ["Nadzór człowieka",      "WYMAGANY" if agent.get("requires_oversight") else "Nie wymagany"],
                ["Budżet miesięczny",     f'{float(agent.get("monthly_budget_eur") or 0):.2f} EUR'],
            ],
            [6*cm, 10*cm],
        ),
        Spacer(1, 0.4*cm),
    ]

    if agent.get("legal_basis"):
        story += [
            Paragraph("3. Podstawa Prawna i Klasyfikacja", S["h2"]),
            hr(),
            Paragraph(agent["legal_basis"], S["body"]),
            Spacer(1, 0.4*cm),
        ]
        sec = 4
    else:
        sec = 3

    total = int(stats.get("total_calls") or 0)
    blocked = int(stats.get("blocked") or 0)
    oversight_cnt = int(stats.get("oversight") or 0)
    pii_cnt = int(stats.get("pii_calls") or 0)
    block_rate = f"{blocked / max(total, 1) * 100:.1f}%"
    avg_lat = stats.get("avg_latency")
    total_cost = float(stats.get("total_cost") or 0)

    story += [
        Paragraph(f"{sec}. Statystyki Operacyjne (ostatnie 30 dni)", S["h2"]),
        hr(),
        _table(
            [
                ["Metryka", "Wartość", "Komentarz"],
                ["Wywołania ogółem",       str(total),                        "wszystkie żądania"],
                ["Blokady polityk",        f"{blocked} ({block_rate})",        "G-001 finansowe, G-002 prompt injection"],
                ["Skierowane do nadzoru",  str(oversight_cnt),                 "polityka A-001"],
                ["Wywołania z PII",        str(pii_cnt),                       "wykryte dane osobowe (Presidio)"],
                ["Śr. latencja",           f"{float(avg_lat):.0f} ms" if avg_lat else "—", "czas odpowiedzi end-to-end"],
                ["Koszt API (30 dni)",     f"{total_cost:.4f} EUR",            "szacowane koszty modelu LLM"],
            ],
            [5.5*cm, 4.5*cm, 6*cm],
        ),
        Spacer(1, 0.4*cm),
    ]
    sec += 1

    gaps = _GAPS.get(risk, _GAPS["minimal"])
    story += [
        Paragraph(f"{sec}. Ocena Zgodności z EU AI Act", S["h2"]),
        hr(),
        _table(
            [["Artykuł", "Wymaganie", "Waga", "Termin"]] +
            [[g[0], g[1], g[2], g[3]] for g in gaps],
            [3*cm, 7*cm, 3*cm, 3*cm],
        ),
        Spacer(1, 0.4*cm),
    ]
    sec += 1

    recs = _RECS.get(risk, _RECS["minimal"])
    story += [
        Paragraph(f"{sec}. Zalecenia Priorytetowe", S["h2"]),
        hr(),
    ]
    for i, r in enumerate(recs, 1):
        story.append(Paragraph(f"{i}. {r}", S["body"]))

    story += [
        Spacer(1, 0.6*cm),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=8),
        Paragraph(
            f"GovAI v0.2.0 · Raport wygenerowany {gen_dt.strftime('%d.%m.%Y %H:%M')} UTC · "
            "Rozporządzenie (UE) 2024/1689 (EU AI Act). "
            "Dokument ma charakter informacyjny i nie stanowi porady prawnej.",
            S["small"],
        ),
    ]

    doc.build(story)
    buf.seek(0)
    return buf.read()

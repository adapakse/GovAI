import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from dependencies.auth import CurrentUser, get_current_user

from services.enterprise_report import (
    collect_enterprise_data,
    generate_enterprise_narrative,
    render_enterprise_pdf,
)
from services.report_generator import (
    generate_narrative,
    get_agent_report_data,
    render_pdf,
)

router = APIRouter(tags=["reports"])


@router.get("/reports/enterprise/pdf")
async def download_enterprise_pdf(
    days: int = Query(30, ge=7, le=90),
    user: CurrentUser = Depends(get_current_user),
):
    data = await collect_enterprise_data(days)
    narrative = await generate_enterprise_narrative(data)
    pdf_bytes = render_enterprise_pdf(data, narrative)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="govai-raport-enterprise-{ts}.pdf"'},
    )


@router.get("/reports/enterprise")
async def get_enterprise_summary(
    days: int = Query(30, ge=7, le=90),
    user: CurrentUser = Depends(get_current_user),
):
    """Dane do podglądu na stronie /reports (bez generowania PDF)."""
    data = await collect_enterprise_data(days)
    return {
        "period_days": days,
        "generated_at": data["generated_at"],
        "kpi": data["kpi"],
        "risk_dist": data["risk_dist"],
        "agents_count": len(data["agents"]),
        "budget_alerts": data["budget_alerts"],
        "overdue_reviews": [
            {"name": a["name"], "next_review_date": a.get("next_review_date")}
            for a in data["overdue_reviews"]
        ],
        "oversight_hist": data["oversight_hist"],
        "top_agents": data["per_agent"][:5],
        "pii_cats": data["pii_cats"],
        "policy_hits": data["policy_hits"],
    }


@router.get("/agents/{agent_id}/report")
async def get_agent_report(agent_id: str, user: CurrentUser = Depends(get_current_user)):
    data = await get_agent_report_data(agent_id)
    if not data:
        raise HTTPException(404, "Agent nie znaleziony")
    narrative = await generate_narrative(data)
    data["narrative"] = narrative
    return data


@router.get("/agents/{agent_id}/report/pdf")
async def download_agent_report_pdf(agent_id: str, user: CurrentUser = Depends(get_current_user)):
    data = await get_agent_report_data(agent_id)
    if not data:
        raise HTTPException(404, "Agent nie znaleziony")
    narrative = await generate_narrative(data)
    pdf_bytes = render_pdf(data, narrative)

    safe_name = data["agent"]["name"].lower().replace(" ", "-")[:40]
    filename = f"ai-act-raport-{safe_name}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

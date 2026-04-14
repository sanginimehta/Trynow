"""
FastAPI web app — form-driven interface for the AI outreach pipeline.
Supports bulk (Groq) and agent (Claude) modes, CSV upload or manual entry.
"""

import csv
import io
import os
import uuid
from datetime import datetime

import anyio
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from core.models import CompanyContext, Prospect, OutreachResult
from core.output import results_to_csv, result_to_dict

load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="webapp/templates")

# In-memory job store: job_id → list of result dicts
results_store: dict[str, list] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/run")
async def run(
    request: Request,
    # Company context
    company_name: str = Form(...),
    product_name: str = Form(...),
    company_website: str = Form(""),
    value_props: str = Form(...),
    icp_description: str = Form(...),
    # Mode
    mode: str = Form(...),  # "bulk" or "agent"
    # Prospects — CSV upload
    csv_file: UploadFile = File(None),
    # Prospects — manual (sent as repeated form fields)
    prospect_name: list[str] = Form(default=[]),
    prospect_title: list[str] = Form(default=[]),
    prospect_company: list[str] = Form(default=[]),
    prospect_industry: list[str] = Form(default=[]),
    prospect_website: list[str] = Form(default=[]),
):
    ctx = CompanyContext(
        name=company_name,
        product=product_name,
        website=company_website,
        value_props=value_props,
        icp_description=icp_description,
    )

    # Build prospect list from CSV upload or manual fields
    prospects: list[Prospect] = []

    if csv_file and csv_file.filename:
        content = await csv_file.read()
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        for row in reader:
            prospects.append(Prospect(
                name=row.get("name", "").strip(),
                title=row.get("title", "").strip(),
                company=row.get("company", "").strip(),
                industry=row.get("industry", "").strip(),
                website=row.get("website", "").strip(),
            ))
    else:
        for i in range(len(prospect_name)):
            n = prospect_name[i].strip()
            if not n:
                continue
            prospects.append(Prospect(
                name=n,
                title=prospect_title[i].strip() if i < len(prospect_title) else "",
                company=prospect_company[i].strip() if i < len(prospect_company) else "",
                industry=prospect_industry[i].strip() if i < len(prospect_industry) else "",
                website=prospect_website[i].strip() if i < len(prospect_website) else "",
            ))

    if not prospects:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": "No prospects found. Please upload a CSV or add prospects manually.",
        })

    # Run the selected pipeline
    results: list[OutreachResult] = []

    if mode == "bulk":
        results = await _run_bulk(prospects, ctx)
    else:
        results = await _run_agent(prospects, ctx)

    # Store results and redirect to results page
    job_id = str(uuid.uuid4())
    results_store[job_id] = [result_to_dict(r) for r in results]

    return RedirectResponse(f"/results/{job_id}", status_code=303)


@app.get("/results/{job_id}", response_class=HTMLResponse)
async def show_results(request: Request, job_id: str):
    results = results_store.get(job_id)
    if results is None:
        return HTMLResponse("Results not found. They may have expired.", status_code=404)

    emailed = [r for r in results if not r["skipped"] and not r["error"]]
    skipped = [r for r in results if r["skipped"]]
    errored = [r for r in results if r["error"]]

    return templates.TemplateResponse("results.html", {
        "request": request,
        "results": results,
        "job_id": job_id,
        "total": len(results),
        "emailed_count": len(emailed),
        "skipped_count": len(skipped),
        "errored_count": len(errored),
    })


@app.get("/download/{job_id}")
async def download_csv(job_id: str):
    result_dicts = results_store.get(job_id)
    if result_dicts is None:
        return Response("Results not found.", status_code=404)

    # Reconstruct OutreachResult objects for the CSV serialiser
    from core.models import LeadScore
    results = []
    for d in result_dicts:
        score = None
        if d.get("score_total") is not None:
            score = LeadScore(
                total=d["score_total"],
                icp_fit=d["score_icp_fit"],
                timing=d["score_timing"],
                reachability=d["score_reachability"],
                signals=d["signals"],
                rationale=d["score_rationale"],
                skip=d["skipped"],
            )
        r = OutreachResult(
            prospect=Prospect(
                name=f"{d['first_name']} {d['last_name']}".strip(),
                title=d["title"],
                company=d["company"],
                industry=d["industry"],
                website=d["website"],
            ),
            mode=d["mode"],
            skipped=d["skipped"],
            skip_reason=d["skip_reason"],
            score=score,
            email_subject=d["email_subject"],
            email_body=d["email_body"],
            date_generated=d["date_generated"],
            error=d["error"],
        )
        results.append(r)

    csv_content = results_to_csv(results)
    filename = f"outreach_{job_id[:8]}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/sample-csv")
async def sample_csv():
    content = "name,title,company,industry,website\n"
    content += "Sarah Chen,Chief Information Security Officer,Pinnacle Financial Partners,Financial Services,https://www.pnfp.com\n"
    content += "Marcus Webb,IT Director,Denny's Corporation,Food & Beverage,https://www.dennys.com\n"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sample_prospects.csv"},
    )


# ---------------------------------------------------------------------------
# Pipeline runners
# ---------------------------------------------------------------------------

async def _run_bulk(prospects: list[Prospect], ctx: CompanyContext) -> list[OutreachResult]:
    from groq import Groq
    from core.pipeline import generate_email

    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        return [
            OutreachResult(prospect=p, mode="bulk", error="GROQ_API_KEY not set")
            for p in prospects
        ]

    client = Groq(api_key=groq_key)
    results = []

    for p in prospects:
        print(f"\n[bulk] Processing {p.name} @ {p.company}")
        try:
            subject, body = generate_email(p, ctx, client)
            results.append(OutreachResult(
                prospect=p,
                mode="bulk",
                email_subject=subject,
                email_body=body,
                date_generated=datetime.now().isoformat(timespec="seconds"),
            ))
        except Exception as e:
            print(f"  Error: {e}")
            results.append(OutreachResult(prospect=p, mode="bulk", error=str(e)))

    return results


async def _run_agent(prospects: list[Prospect], ctx: CompanyContext) -> list[OutreachResult]:
    from core.agent import score_lead, research_and_email, SCORE_THRESHOLD

    results = []

    for p in prospects:
        print(f"\n[agent] Scoring {p.name} @ {p.company}")
        try:
            score = await score_lead(p, ctx)
            print(f"  Score: {score.total}/10  ({'PASS' if not score.skip else 'SKIP'})")

            if score.skip:
                results.append(OutreachResult(
                    prospect=p,
                    mode="agent",
                    skipped=True,
                    skip_reason=f"Score {score.total}/10 — below threshold ({SCORE_THRESHOLD})",
                    score=score,
                    date_generated=datetime.now().isoformat(timespec="seconds"),
                ))
                continue

            print(f"  Generating email…")
            subject, body = await research_and_email(p, ctx)
            results.append(OutreachResult(
                prospect=p,
                mode="agent",
                score=score,
                email_subject=subject,
                email_body=body,
                date_generated=datetime.now().isoformat(timespec="seconds"),
            ))

        except Exception as e:
            print(f"  Error: {e}")
            results.append(OutreachResult(prospect=p, mode="agent", error=str(e)))

    return results

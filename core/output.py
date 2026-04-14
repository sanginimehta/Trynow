"""
CSV and CRM-ready output formatting.
Columns are chosen to map cleanly into HubSpot, Salesforce, or Pipedrive.
"""

import csv
import io
import re
from .models import OutreachResult


def parse_email(raw: str) -> tuple[str, str]:
    """
    Split raw agent/pipeline output into (subject, body).
    Handles 'Subject: ...' lines and markdown bold subject lines.
    """
    lines = raw.strip().splitlines()
    subject = ""
    body_lines = []
    found_subject = False

    for line in lines:
        clean = line.strip()
        # Match "Subject: ..." or "**Subject: ...**"
        m = re.match(r"\*{0,2}Subject\s*:\s*\*{0,2}(.+)\*{0,2}", clean, re.IGNORECASE)
        if m and not found_subject:
            subject = m.group(1).strip().strip("*").strip()
            found_subject = True
            continue
        if found_subject:
            body_lines.append(line)

    if not found_subject:
        # No explicit subject line — use first non-empty line
        for i, line in enumerate(lines):
            if line.strip():
                subject = line.strip().strip("*")
                body_lines = lines[i + 1:]
                break

    body = "\n".join(body_lines).strip()
    return subject, body


def results_to_csv(results: list[OutreachResult]) -> str:
    """
    Serialise a list of OutreachResult objects to a CSV string.
    Column names match common CRM import field names.
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "first_name",
        "last_name",
        "title",
        "company",
        "industry",
        "website",
        "mode",
        "skipped",
        "skip_reason",
        "score_total",
        "score_icp_fit",
        "score_timing",
        "score_reachability",
        "timing_signals",
        "score_rationale",
        "email_subject",
        "email_body",
        "date_generated",
        "error",
    ])
    writer.writeheader()

    for r in results:
        p = r.prospect
        s = r.score

        writer.writerow({
            "first_name":          p.first_name,
            "last_name":           p.last_name,
            "title":               p.title,
            "company":             p.company,
            "industry":            p.industry,
            "website":             p.website,
            "mode":                r.mode,
            "skipped":             "yes" if r.skipped else "no",
            "skip_reason":         r.skip_reason,
            "score_total":         s.total if s else "",
            "score_icp_fit":       s.icp_fit if s else "",
            "score_timing":        s.timing if s else "",
            "score_reachability":  s.reachability if s else "",
            "timing_signals":      " | ".join(s.signals) if s else "",
            "score_rationale":     s.rationale if s else "",
            "email_subject":       r.email_subject,
            "email_body":          r.email_body,
            "date_generated":      r.date_generated,
            "error":               r.error,
        })

    return output.getvalue()


def result_to_dict(r: OutreachResult) -> dict:
    """Serialise a single OutreachResult to a plain dict (for Jinja2 templates)."""
    p = r.prospect
    s = r.score
    return {
        "name":              p.name,
        "first_name":        p.first_name,
        "title":             p.title,
        "company":           p.company,
        "industry":          p.industry,
        "website":           p.website,
        "mode":              r.mode,
        "skipped":           r.skipped,
        "skip_reason":       r.skip_reason,
        "score_total":       s.total if s else None,
        "score_icp_fit":     s.icp_fit if s else None,
        "score_timing":      s.timing if s else None,
        "score_reachability":s.reachability if s else None,
        "signals":           s.signals if s else [],
        "score_rationale":   s.rationale if s else "",
        "email_subject":     r.email_subject,
        "email_body":        r.email_body,
        "date_generated":    r.date_generated,
        "error":             r.error,
    }

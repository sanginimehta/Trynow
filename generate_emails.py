"""
Reads prospects.csv (name, company, url), enriches each prospect with live
company data via the Clearbit API, generates a personalized outreach email
using Groq, and saves results to output.csv.
"""
import os
import sys
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

INPUT_FILE = "prospects.csv"
OUTPUT_FILE = "output.csv"
MODEL = "llama-3.1-8b-instant"


def scrape_homepage(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return text[:3000]


def enrich_company(domain: str) -> dict:
    """
    Fetch live company data from Clearbit's free Company API.
    Returns a dict with keys: name, description, industry, employees,
    location, twitter_bio, tech. Falls back gracefully on any error.
    """
    clearbit_key = os.getenv("CLEARBIT_API_KEY")
    result = {}

    if not clearbit_key:
        return result

    try:
        resp = requests.get(
            "https://company.clearbit.com/v2/companies/find",
            params={"domain": domain},
            auth=(clearbit_key, ""),
            timeout=8,
        )
        if resp.status_code != 200:
            return result

        data = resp.json()
        result["description"] = (data.get("description") or "").strip()
        result["industry"] = (data.get("category") or {}).get("industry", "")
        result["employees"] = data.get("metrics", {}).get("employees")
        result["location"] = ", ".join(
            filter(None, [
                (data.get("geo") or {}).get("city"),
                (data.get("geo") or {}).get("country"),
            ])
        )
        result["twitter_bio"] = (
            (data.get("twitter") or {}).get("bio") or ""
        ).strip()
        tech_list = [t.get("name", "") for t in (data.get("tech") or [])[:5]]
        result["tech"] = ", ".join(filter(None, tech_list))
    except Exception:
        pass

    return result


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path
    return host.removeprefix("www.")


def _format_enrichment(enrichment: dict) -> str:
    if not enrichment:
        return ""
    lines = []
    if enrichment.get("description"):
        lines.append(f"Description: {enrichment['description']}")
    if enrichment.get("industry"):
        lines.append(f"Industry: {enrichment['industry']}")
    if enrichment.get("employees"):
        lines.append(f"Employees: {enrichment['employees']}")
    if enrichment.get("location"):
        lines.append(f"Location: {enrichment['location']}")
    if enrichment.get("twitter_bio"):
        lines.append(f"Brand voice: {enrichment['twitter_bio']}")
    if enrichment.get("tech"):
        lines.append(f"Tech stack: {enrichment['tech']}")
    return "\n".join(lines)


def generate_email(
    name: str,
    company: str,
    homepage_text: str,
    client: Groq,
    enrichment: dict | None = None,
) -> str:
    enrichment_block = ""
    if enrichment:
        formatted = _format_enrichment(enrichment)
        if formatted:
            enrichment_block = f"\nLive company data:\n{formatted}\n"

    prompt = (
        f"You are writing a short, personalized cold outreach email asking {company} for sponsorship.\n\n"
        f"Prospect name: {name}\n"
        f"Company: {company}\n"
        f"{enrichment_block}"
        f"Homepage content:\n{homepage_text}\n\n"
        "Write a 3-sentence email:\n"
        "1. A personalized opener referencing something specific about the company.\n"
        "2. A brief explanation of what we're asking for (sponsorship) and why it's a fit.\n"
        "3. A low-pressure call to action (e.g. a quick call or reply).\n\n"
        "Do not use placeholders like [Your Name]. Keep it natural and direct."
    )
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


def main():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY not set. Add it to your .env file.", file=sys.stderr)
        sys.exit(1)

    clearbit_key = os.getenv("CLEARBIT_API_KEY")
    if not clearbit_key:
        print("Note: CLEARBIT_API_KEY not set — skipping enrichment step.")

    client = Groq(api_key=api_key)
    df = pd.read_csv(INPUT_FILE)
    results = []

    for _, row in df.iterrows():
        name, company, url = row["name"], row["company"], row["url"]
        print(f"Processing {name} at {company}...")

        try:
            homepage_text = scrape_homepage(url)
        except Exception as e:
            print(f"  Skipping {company} — scrape failed: {e}")
            results.append({"name": name, "company": company, "url": url, "email": f"ERROR: {e}"})
            continue

        domain = _domain_from_url(url)
        enrichment = enrich_company(domain)
        if enrichment:
            print(f"  Enriched: {enrichment.get('industry', '')} | {enrichment.get('employees', '?')} employees")
        else:
            print("  No enrichment data.")

        email = generate_email(name, company, homepage_text, client, enrichment)
        results.append({"name": name, "company": company, "url": url, "email": email})
        print("  Done.\n")

    out_df = pd.DataFrame(results)
    out_df.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved {len(results)} emails to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

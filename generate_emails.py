"""
Reads prospects.csv (name, company, url), generates a personalized outreach
email for each one using OpenAI, and saves results to output.csv.
"""
import os
import sys

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

INPUT_FILE = "prospects.csv"
OUTPUT_FILE = "output.csv"


def scrape_homepage(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return text[:3000]


def generate_email(name: str, company: str, homepage_text: str, client: OpenAI) -> str:
    prompt = (
        f"You are writing a short, personalized cold outreach email asking {company} for sponsorship.\n\n"
        f"Prospect name: {name}\n"
        f"Company: {company}\n"
        f"Homepage content:\n{homepage_text}\n\n"
        "Write a 3-sentence email:\n"
        "1. A personalized opener referencing something specific about the company.\n"
        "2. A brief explanation of what we're asking for (sponsorship) and why it's a fit.\n"
        "3. A low-pressure call to action (e.g. a quick call or reply).\n\n"
        "Do not use placeholders like [Your Name]. Keep it natural and direct."
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


def main():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set. Copy .env.example to .env and add your key.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)
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

        email = generate_email(name, company, homepage_text, client)
        results.append({"name": name, "company": company, "url": url, "email": email})
        print(f"  Done.\n")

    out_df = pd.DataFrame(results)
    out_df.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved {len(results)} emails to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

import argparse
import os
import sys

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def scrape_homepage(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return text[:3000]


def generate_opener(company_name: str, homepage_text: str) -> str:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = (
        f"Here is the homepage text for {company_name}:\n\n"
        f"{homepage_text}\n\n"
        "Based on this, write a single, personalized, conversational sentence "
        "that could open a sponsorship ask email. Reference something specific "
        "about what the company does or values. Do not use generic phrases."
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


def main():
    parser = argparse.ArgumentParser(description="Generate a personalized sponsorship email opener.")
    parser.add_argument("company", help="Company name")
    parser.add_argument("url", help="Company homepage URL")
    args = parser.parse_args()

    print(f"Scraping homepage: {args.url}")
    try:
        text = scrape_homepage(args.url)
    except Exception as e:
        print(f"Error scraping page: {e}", file=sys.stderr)
        sys.exit(1)

    print("Generating email opener...\n")
    opener = generate_opener(args.company, text)
    print(f"Email opener for {args.company}:\n\n  {opener}\n")


if __name__ == "__main__":
    main()

# Email Sequencer

Personalized cold outreach email generator for sponsorship campaigns. Scrapes company homepages, enriches with live company data via Clearbit, and uses Groq's LLaMA model to write targeted 3-sentence emails at scale.

## Features

- **Bulk mode** — reads a CSV of prospects and writes personalized emails to `output.csv`
- **Single mode** — CLI tool to generate a one-sentence opener for any company URL
- **Live enrichment** — pulls industry, employee count, location, and tech stack from Clearbit before the prompt (optional, degrades gracefully)
- **Homepage scraping** — strips noise (nav, scripts, footers) and feeds meaningful content to the LLM

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in your keys in .env
```

Required key:

| Variable | Where to get it |
|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) — free tier available |

Optional (enables richer, more personalized output):

| Variable | Where to get it |
|---|---|
| `CLEARBIT_API_KEY` | [clearbit.com](https://clearbit.com) — free tier up to 50 lookups/month |

## Usage

### Bulk email generation

Create a `prospects.csv` with columns `name`, `company`, `url`:

```csv
name,company,url
Jane Smith,Acme Corp,https://acme.com
Bob Lee,Vercel,https://vercel.com
```

Then run:

```bash
python generate_emails.py
```

Output is saved to `output.csv` with an `email` column appended.

### Single opener (CLI)

```bash
python email_opener.py "Stripe" https://stripe.com
```

```
Scraping homepage: https://stripe.com
Enriching company data for stripe.com...
  Found: Financial Services | 4000 employees
Generating email opener...

Email opener for Stripe:

  Given Stripe's mission to grow the GDP of the internet by making payments
  infrastructure accessible to every business, we'd love to explore how a
  sponsorship could connect your brand with the builders we work with daily.
```

## How it works

```
URL → scrape_homepage() → raw text (3000 chars)
          ↓
domain → enrich_company() → Clearbit API → industry, employees, location, tech
          ↓
generate_email() → Groq LLaMA 3.1 8B → 3-sentence email
          ↓
output.csv
```

The enrichment step is additive — if `CLEARBIT_API_KEY` is missing or the lookup fails, the script continues with homepage text only.

## Model

Uses `llama-3.1-8b-instant` via Groq for fast, low-cost inference. Swap the `MODEL` constant in `generate_emails.py` to use a different Groq-hosted model (e.g. `llama-3.3-70b-versatile` for higher quality).

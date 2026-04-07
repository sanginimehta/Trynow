# AI Sales Outreach Agent

A B2B sales outreach system built in two layers: a bulk email generator and an agentic prospect researcher with persistent memory. Built to showcase practical AI application development using the Claude Agent SDK, Groq, and real-time web research.

---

## What it does

### Layer 1 — Bulk email generator (`generate_emails.py`)
- Reads a CSV of prospects
- Scrapes each company's homepage for context
- Enriches with live company data from Clearbit (industry, headcount, tech stack)
- Generates a personalized 3-sentence outreach email via Groq (LLaMA 3.1)
- Saves everything to `output.csv`

### Layer 2 — Agentic prospect researcher (`prospect_agent.py`)
- Uses the **Claude Agent SDK** to spawn an AI agent per prospect
- Agent autonomously runs **WebSearch** and **WebFetch** to find recent news, regulatory filings, M&A activity, and compliance signals before writing anything
- Writes a first-contact cold email grounded in real, current research
- **Persists memory** per prospect — on follow-up runs, injects past emails into the prompt and instructs the agent to find a completely different angle
- Streams live progress to the terminal (tool calls, token usage, turn count)

---

## Architecture

```
prospect_agent.py
│
├── load_memory()          read prospect_memory/{company}__{name}.json
│       ↓
├── build_prompt()         first contact vs. follow-up (different instructions)
│       ↓
├── query()                Claude Agent SDK — spawns agent session
│   ├── WebSearch          agent searches for news, compliance signals, M&A
│   ├── WebFetch           agent reads company pages and news articles
│   └── streams messages   SystemMessage → AssistantMessage (×N) → ResultMessage
│       ↓
└── save_memory()          append email + session_id + date to JSON file
```

Memory file per prospect (`prospect_memory/`):
```json
{
  "prospect": { "name": "Sarah Chen", "company": "Pinnacle Financial Partners", ... },
  "interactions": [
    {
      "date": "2026-04-06T10:30:00",
      "session_id": "abc123",
      "email": "Subject: GRC complexity post-Synovus…\n\nHi Sarah,…"
    }
  ]
}
```

---

## Real output example

Running `prospect_agent.py` against a CISO at a mid-sized regional bank:

```
  [memory] no prior interactions — writing first contact email
  [session started] a1b2c3...
  [turn 1] agent is working…
  [turn 1 · WebSearch] "Pinnacle Financial Partners compliance 2025"
  [turn 2] agent is working…
  [turn 2 · WebFetch] https://www.pnfp.com/news/news-releases/...
  [turn 3] agent is working…
  [turn 3 · agent text] Subject: GRC complexity post-Synovus — how are you managing it?…
  [done] stop_reason=end_turn  turns=3
  [memory saved] prospect_memory/pinnacle_financial_partners__sarah_chen.json
```

Generated email (first contact):
```
Subject: GRC complexity post-Synovus — how are you managing it?

Hi Sarah,

Congratulations on clearing federal regulatory approval for the Synovus merger.
Combining two $50B+ banks is a major milestone — but I imagine the integration
work ahead is keeping your team busy. Two separate control environments, overlapping
vendor inventories, and divergent IT risk frameworks all converging at once is exactly
the scenario where spreadsheet-based GRC programs start to crack.

That's where we help. Risk Cloud by LogicGate gives security and compliance teams a
single platform to unify control frameworks (FFIEC, SOC 2, NIST CSF), automate
evidence collection, and maintain real-time risk visibility — without relying on IT.

Would a 20-minute call be worth your time? Happy to show how other banks have tackled
post-merger GRC consolidation, or send a case study first if that's more useful.

— [Your Name], LogicGate
```

The agent found the Synovus merger news autonomously — no human input beyond the prospect's name and company.

---

## Setup

```bash
git clone https://github.com/sanginimehta/Trynow.git
cd Trynow
pip install -r requirements.txt
cp .env.example .env
# fill in your keys
```

### API keys

| Variable | Used by | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | `prospect_agent.py` | [console.anthropic.com](https://console.anthropic.com) |
| `GROQ_API_KEY` | `generate_emails.py` | [console.groq.com](https://console.groq.com) — free tier |
| `CLEARBIT_API_KEY` | `generate_emails.py` | [clearbit.com](https://clearbit.com) — optional |

---

## Usage

### Agentic researcher (Layer 2)

```bash
python prospect_agent.py
```

Run it once → first contact email, memory file created.
Run it again → follow-up email with a different hook, memory file updated.

To research a different prospect, edit the `prospect` dict in `main()`:

```python
prospect = {
    "name": "Jane Smith",
    "title": "Chief Information Security Officer",
    "company": "Acme Bank",
    "industry": "Financial Services",
    "website": "https://acmebank.com",
}
```

### Bulk generator (Layer 1)

Add prospects to `prospects.csv`:

```csv
name,company,url
Jane Smith,Acme Corp,https://acme.com
```

```bash
python generate_emails.py   # outputs to output.csv
python email_opener.py "Stripe" https://stripe.com   # single prospect CLI
```

---

## Tech stack

| Component | Technology |
|---|---|
| AI agent framework | [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) |
| Agent model | Claude (via Anthropic) |
| Bulk email model | LLaMA 3.1 8B via [Groq](https://groq.com) |
| Company enrichment | [Clearbit](https://clearbit.com) |
| Web research | Claude built-in WebSearch + WebFetch tools |
| Memory | File-based JSON, one file per prospect |
| Async runtime | [anyio](https://anyio.readthedocs.io) |

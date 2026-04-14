# AI Sales Outreach Agent

An AI-powered outreach system that researches prospects, scores them against your ICP, and writes personalized cold emails — grounded in real, current information about each company.

Built for B2B sales teams selling GRC software (Risk Cloud by LogicGate) into regulated industries.

---

## The problem it solves

A typical SDR spends 30–45 minutes researching a single high-value prospect before writing a cold email: reading news, checking LinkedIn, scanning 10-Ks, looking for a hook that doesn't feel generic. At scale, that's most of the working day — before a single word of outreach gets written.

This tool automates that research and writes the email. The result is a message grounded in something real — a merger, a regulatory filing, a compliance initiative — not a mail-merge template with the company name swapped in.

---

## What it does

**Step 1 — Lead scoring**

Before writing anything, the agent researches each prospect and scores them 1–10 across three dimensions:

- **ICP fit** — Is this the right industry (regulated), company size, and title (CISO, CRO, VP Compliance)?
- **Timing signals** — Are there recent urgency triggers? A merger closing, a regulatory fine, a new CISO hire, a breach, an IPO?
- **Reachability** — Is this a real decision-maker or a gatekeeper?

Prospects scoring below 6 are skipped. Only qualified leads get emails written.

**Step 2 — Personalized email generation**

For each lead that passes scoring, the agent reads recent news, regulatory filings, and company context, then writes a cold email that:

- Opens with a specific hook tied to something happening at that company right now
- Connects their compliance and risk challenges to what Risk Cloud solves
- Closes with a low-pressure ask

**Step 3 — Memory**

Every email sent is saved per prospect. On the next outreach cycle, the agent reads the previous emails and finds a completely different angle — a new news hook, a different product angle, a relevant case study. It never sends the same message twice.

---

## Real output

**Scoring pass — 3 prospects evaluated:**

```
  Prospect                          Score   Decision
  ------------------------------------------------
  Sarah Chen @ Pinnacle Financial   8.5/10  EMAIL →
  Marcus Webb @ Denny's Corp        3.0/10  SKIP
  Jennifer Park @ Regions Financial 7.5/10  EMAIL →
```

**Email generated for Sarah Chen, CISO, Pinnacle Financial Partners:**

> **Subject: GRC at $119B — before the next exam cycle**
>
> Sarah,
>
> Closing a merger the size of Pinnacle + Synovus on January 2nd is no small feat — but I'd imagine the GRC aftermath is still very much in motion: two control libraries, two audit programs, two vendor risk inventories, and examiners who won't wait for the dust to settle.
>
> That's exactly where Risk Cloud tends to show up for regional banks at inflection points like this. We replace the patchwork of spreadsheets and point tools with a single connected platform — pre-mapped to FFIEC, NIST CSF, and PCI-DSS — so your team gets unified risk visibility across the combined entity without a lengthy implementation.
>
> I'd welcome a 20-minute conversation to share how a few other post-merger regional banks have used Risk Cloud to consolidate fast. Worth a slot this month?

The agent found the Synovus merger news on its own. No human input beyond the prospect's name and company.

**Follow-up email (run #2 — different angle, found automatically):**

> **Subject: Running two tech stacks through Q2 2027 — the compliance math**
>
> Sarah,
>
> Saw that Pinnacle's full system conversion is expected around Q2 2027 — meaning your team is managing compliance across two parallel environments for the better part of a year. Two control sets, two evidence trails, two audit scopes, one board report due quarterly.
>
> Risk Cloud handles this well. Regional banks in mid-integration use it to maintain a single view across disparate systems — automated evidence collection, unified control mapping, workflow-driven assessments — so you're not stitching together a risk posture while the core conversion is still months out.
>
> I can share a case study from a bank that used Risk Cloud to stay examiner-ready through a multi-year core migration. Worth 20 minutes before the Q2 sprint kicks in?

Same prospect, second touchpoint, completely different hook — found because the agent checked what it had already sent and went looking for something new.

---

## How to run it

```bash
git clone https://github.com/sanginimehta/Trynow.git
cd Trynow
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
python prospect_agent.py
```

To add your own prospects, edit the list in `prospect_agent.py`:

```python
prospects = [
    {
        "name": "First Last",
        "title": "Chief Information Security Officer",
        "company": "Company Name",
        "industry": "Financial Services",
        "website": "https://company.com",
    },
    ...
]
```

---

## Files

| File | What it does |
|---|---|
| `prospect_agent.py` | AI agent: scores leads, researches prospects, writes emails, remembers what was sent |
| `generate_emails.py` | Bulk pipeline: reads a CSV, scrapes homepages, writes emails at scale via Groq |
| `agent_output.csv` | Sample output from the agent — two emails for one prospect, different angles |
| `output.csv` | Sample output from the bulk pipeline — Nike and Stripe |
| `prospect_memory/` | Per-prospect JSON files storing scores and every email ever sent |

---

## Why two approaches?

| | Bulk pipeline (`generate_emails.py`) | Agent (`prospect_agent.py`) |
|---|---|---|
| Speed | Fast — seconds per prospect | Slower — minutes per prospect |
| Cost | Low | Higher |
| Personalization | Good — based on homepage + enrichment | High — based on live research |
| Best for | Top-of-funnel, high volume | High-value accounts, ABM |

In a real workflow: run the pipeline to process a large list, use the agent for your top accounts.

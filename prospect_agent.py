"""
Prospect Research Agent — Step 2: Memory
Uses the Claude Agent SDK to research a B2B prospect and generate
a personalized outreach email for Risk Cloud by LogicGate.

Memory is file-based: one JSON file per prospect stored in
prospect_memory/.  On every run the agent reads what was previously
sent, finds a NEW hook, and the result is appended back to the file.
"""

import json
import anyio
from datetime import datetime
from pathlib import Path
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MEMORY_DIR = Path(__file__).parent / "prospect_memory"

SYSTEM_PROMPT = """You are an expert B2B sales development representative for LogicGate,
a GRC (Governance, Risk, and Compliance) software company. Your product is Risk Cloud —
a flexible, no-code GRC platform that helps organizations manage risk, compliance, and
audit programs in a single connected system.

Your task: research the prospect, then write a highly personalized cold outreach email
that shows you understand their world.

Risk Cloud value propositions most relevant to CISOs in financial services:
- Replaces fragmented spreadsheets and point solutions with one unified GRC platform
- Pre-built control frameworks for SOC 2, ISO 27001, NIST CSF, PCI-DSS, FFIEC, and more
- Real-time risk visibility with automated workflows and evidence collection
- Scales without custom code — business teams can own their own risk programs
- Purpose-built for regulated industries; trusted by 1,000+ companies

Email guidelines:
- Subject line + 3 short paragraphs, under 150 words total
- Paragraph 1: personalized opener referencing something specific about the company
- Paragraph 2: connect their pain points to what Risk Cloud solves
- Paragraph 3: low-pressure CTA — offer a 20-minute call or a relevant resource
- Tone: peer-to-peer, direct, no fluff, no buzzword soup
"""

# ---------------------------------------------------------------------------
# Memory: load and save
# ---------------------------------------------------------------------------

def _memory_path(prospect: dict) -> Path:
    """
    Return the JSON file path for this prospect.
    Key format: {company}__{name}, lowercased, spaces → underscores.
    Example: pinnacle_financial_partners__sarah_chen.json
    """
    company = prospect["company"].lower().replace(" ", "_")
    name = prospect["name"].lower().replace(" ", "_")
    return MEMORY_DIR / f"{company}__{name}.json"


def load_memory(prospect: dict) -> dict:
    """
    Load past interactions for this prospect from disk.

    Returns a dict with:
      - prospect   : the prospect profile
      - interactions: list of past runs, each with date / session_id / email
    Returns a fresh empty structure if no file exists yet (first contact).
    """
    MEMORY_DIR.mkdir(exist_ok=True)
    path = _memory_path(prospect)

    if path.exists():
        return json.loads(path.read_text())

    # First time we've seen this prospect
    return {"prospect": prospect, "interactions": []}


def save_memory(prospect: dict, session_id: str, email: str) -> None:
    """
    Append this run's output to the prospect's memory file.
    Creates the file on first save.
    """
    MEMORY_DIR.mkdir(exist_ok=True)
    memory = load_memory(prospect)

    memory["interactions"].append({
        "date": datetime.now().isoformat(timespec="seconds"),
        "session_id": session_id,
        "email": email,
    })

    _memory_path(prospect).write_text(json.dumps(memory, indent=2))


def _format_past_interactions(interactions: list) -> str:
    """
    Render past interactions as a readable block to inject into the prompt.
    """
    lines = []
    for i, entry in enumerate(interactions, start=1):
        lines.append(f"--- Past email #{i}  ({entry['date']}) ---")
        lines.append(entry["email"].strip())
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

def _print_step(label: str, detail: str = "") -> None:
    if detail:
        print(f"  [{label}] {detail}")
    else:
        print(f"  [{label}]")


def _handle_assistant_message(message: AssistantMessage, turn: int) -> None:
    for block in message.content:
        if isinstance(block, TextBlock) and block.text.strip():
            preview = block.text.strip()
            if len(preview) > 200:
                preview = preview[:200] + "…"
            _print_step(f"turn {turn} · agent text", preview)

        elif hasattr(block, "type") and block.type == "tool_use":
            tool_name = getattr(block, "name", "unknown_tool")
            tool_input = getattr(block, "input", {}) or {}

            if tool_name == "WebSearch":
                _print_step(f"turn {turn} · WebSearch", f'"{tool_input.get("query", "")}"')
            elif tool_name == "WebFetch":
                _print_step(f"turn {turn} · WebFetch", tool_input.get("url", ""))
            else:
                _print_step(f"turn {turn} · tool call", f"{tool_name}({tool_input})")


# ---------------------------------------------------------------------------
# Core agent function
# ---------------------------------------------------------------------------

async def research_and_email(prospect: dict) -> str:
    """
    Research a prospect and generate a personalized outreach email.
    Loads past interactions from memory and instructs the agent to avoid
    repeating previous hooks.  Saves the result back to memory after.

    Args:
        prospect: dict with keys:
            - name      (str)
            - title     (str)
            - company   (str)
            - industry  (str)
            - website   (str, optional)

    Returns:
        The generated email as a plain string.

    Memory flow:
        load memory
            ↓
        build prompt  (first contact vs. follow-up)
            ↓
        run agent  (WebSearch + WebFetch)
            ↓
        save result to memory file
            ↓
        return email
    """
    # ------------------------------------------------------------------
    # 1. Load memory — find out what we've sent before
    # ------------------------------------------------------------------
    memory = load_memory(prospect)
    interactions = memory["interactions"]
    is_followup = len(interactions) > 0

    if is_followup:
        _print_step("memory", f"found {len(interactions)} past interaction(s) — writing follow-up")
    else:
        _print_step("memory", "no prior interactions — writing first contact email")

    # ------------------------------------------------------------------
    # 2. Build the prompt
    #    First contact → research + write cold email
    #    Follow-up     → given past emails, find a NEW angle
    # ------------------------------------------------------------------
    website_line = f"- Website: {prospect['website']}" if prospect.get("website") else ""

    if not is_followup:
        # ---- First contact prompt ----
        prompt = f"""Research this prospect and write a personalized outreach email for
Risk Cloud by LogicGate.

Prospect profile:
- Name: {prospect['name']}
- Title: {prospect['title']}
- Company: {prospect['company']}
- Industry: {prospect['industry']}
{website_line}

Your process:
1. Search for recent news about {prospect['company']} — focus on anything related to
   security incidents, compliance initiatives, regulatory pressure, audits, M&A activity,
   or technology modernization.
2. Look up what {prospect['company']} does, their size, and who they serve.
3. Write a personalized cold outreach email from a LogicGate sales rep to
   {prospect['name']}, {prospect['title']} at {prospect['company']}.

Output ONLY the final email (subject line + body). No research summary, no preamble."""

    else:
        # ---- Follow-up prompt: memory context injected ----
        past_emails_block = _format_past_interactions(interactions)

        prompt = f"""You are following up with a prospect you have contacted before.
You must NOT repeat any hook, subject line, or angle already used.

Prospect profile:
- Name: {prospect['name']}
- Title: {prospect['title']}
- Company: {prospect['company']}
- Industry: {prospect['industry']}
{website_line}

Emails already sent to this prospect:
{past_emails_block}

Your process:
1. Search for news about {prospect['company']} that is DIFFERENT from the topics
   already covered in the emails above. Look for new angles: personnel changes,
   product launches, regulatory filings, earnings news, technology investments, etc.
2. If no new news is available, shift the angle — e.g. lead with a customer story,
   a relevant industry stat, or a specific Risk Cloud capability you haven't mentioned.
3. Write a follow-up outreach email that feels fresh, not like a copy-paste nudge.

Output ONLY the final email (subject line + body). No preamble."""

    # ------------------------------------------------------------------
    # 3. Run the agent
    # ------------------------------------------------------------------
    result_text = ""
    session_id = "unknown"
    turn = 0

    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            allowed_tools=["WebSearch", "WebFetch"],
            max_turns=10,
        ),
    ):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            session_id = message.data.get("session_id", "unknown")
            _print_step("session started", session_id)

        elif isinstance(message, AssistantMessage):
            turn += 1
            _print_step(f"turn {turn}", "agent is working…")
            _handle_assistant_message(message, turn)
            if message.usage:
                inp = message.usage.get("input_tokens", "?")
                out = message.usage.get("output_tokens", "?")
                _print_step(f"turn {turn} · tokens", f"in={inp}  out={out}")

        elif isinstance(message, ResultMessage):
            _print_step("done", f"stop_reason={message.stop_reason}  turns={turn}")
            result_text = message.result

    # ------------------------------------------------------------------
    # 4. Save result to memory
    # ------------------------------------------------------------------
    save_memory(prospect, session_id, result_text)
    _print_step("memory saved", str(_memory_path(prospect)))

    return result_text


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------

async def main():
    prospect = {
        "name": "Sarah Chen",
        "title": "Chief Information Security Officer",
        "company": "Pinnacle Financial Partners",
        "industry": "Financial Services / Regional Banking",
        "website": "https://www.pnfp.com",
    }

    contact_label = "FIRST CONTACT"
    memory = load_memory(prospect)
    if memory["interactions"]:
        contact_label = f"FOLLOW-UP #{len(memory['interactions'])}"

    print()
    print("=" * 64)
    print(f"  PROSPECT RESEARCH AGENT  —  {contact_label}")
    print(f"  Target : {prospect['name']} — {prospect['title']}")
    print(f"  Company: {prospect['company']} ({prospect['industry']})")
    print(f"  Product: Risk Cloud by LogicGate")
    print("=" * 64)
    print()

    email = await research_and_email(prospect)

    print()
    print("=" * 64)
    print(f"  GENERATED OUTREACH EMAIL  ({contact_label})")
    print("=" * 64)
    print()
    print(email)
    print()
    print("=" * 64)


if __name__ == "__main__":
    anyio.run(main)

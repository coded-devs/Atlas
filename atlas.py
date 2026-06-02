"""
atlas.py — Atlas: Data Change Intelligence Agent

A multi-step Gemini agent that:
  1. Reads a natural-language change request
  2. Calls the lineage tool to discover downstream impact
  3. Produces a structured impact report + stakeholder messages

Run:
    python atlas.py             # runs the full 3-scenario demo
    python atlas.py --single    # runs only the headline scenario
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

from google import genai
from google.genai import types
from dotenv import load_dotenv

from lineage import summarize_impact

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("ERROR: GEMINI_API_KEY missing from .env file. Aborting.")
    sys.exit(1)

client = genai.Client(api_key=API_KEY)
MODEL_NAME = "gemini-2.5-flash"

REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Tool declaration — the manual page Gemini reads to know when to call it
# ---------------------------------------------------------------------------

SUMMARIZE_IMPACT_DECL = {
    "name": "summarize_impact",
    "description": (
        "Look up the full downstream impact of changing a specific column in a "
        "Fivetran-landed warehouse table. Returns dbt models, dashboards, "
        "scheduled reports, and ML features that depend on the column, along "
        "with owner contact info (Slack, email, team lead) and the recommended "
        "deprecation notice period based on criticality. "
        "Call this BEFORE making any recommendation about a schema change."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": (
                    "Fully-qualified table name in the warehouse, e.g. "
                    "'stripe.customers', 'hubspot.deals', 'stripe.subscriptions'."
                ),
            },
            "column": {
                "type": "string",
                "description": "Column name within the table, e.g. 'customer_segment'.",
            },
        },
        "required": ["table", "column"],
    },
}

TOOL_FUNCTIONS = {
    "summarize_impact": summarize_impact,
}


# ---------------------------------------------------------------------------
# Atlas's personality and operating rules
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """
You are Atlas, a data change intelligence agent. You help data engineers safely
make changes to data systems by surfacing the full downstream impact and producing
a phased deprecation plan with stakeholder communication.

OPERATING RULES:

1. Identify the table and column involved in the proposed change.
2. Before recommending anything, ALWAYS call summarize_impact. Never guess at impact
   from training data - call the tool and use the real lineage data.
3. Before calling a tool, briefly state in one sentence what you are about to check.
4. After receiving the tool result, produce a final report with these exact sections:

   ## Impact Summary
   One paragraph of plain-English summary: what the change is, how many things it
   affects, and the highest-criticality consequence.

   ## Affected Assets
   Bullet list, one line per downstream asset:
   - **<name>** (<type>) - owned by <team_lead>, <team>, criticality <tier>

   ## Recommended Deprecation Plan
   Numbered phased steps with concrete day offsets (Day 0, Day 7, Day 14, etc.),
   based on the recommended_deprecation_days value from the tool result.

   ## Stakeholder Messages
   For each unique owning team, draft a Slack message (3-5 sentences). Tone:
   - Technical and direct for engineering/analytics teams
   - Business-focused and concise for sales, finance, exec teams
   Include the team's Slack channel as a header for each message.

5. If the column has zero downstream impact, say so clearly in one short paragraph
   and recommend proceeding with a short deprecation window. Skip the stakeholder
   messages section.
6. If the column does not exist, state that plainly. Do not invent a plan.
7. Be direct. No apologies. No "I hope this helps." No sign-off.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(part, attr):
    """Return part.attr if present, else None - protects against SDK variation."""
    return getattr(part, attr, None)


def _slugify(text: str) -> str:
    """Turn a request string into a safe filename fragment."""
    return "".join(c if c.isalnum() else "_" for c in text.lower())[:50]


def _save_report(scenario_num: int, request: str, report: str) -> Path:
    """Write the final report to a markdown file and return its path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"scenario_{scenario_num}_{_slugify(request[:30])}_{timestamp}.md"
    path = REPORTS_DIR / filename

    header = f"# Atlas Report - Scenario {scenario_num}\n\n"
    header += f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    header += f"**Request:** {request}\n\n---\n\n"

    path.write_text(header + report, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The agent loop
# ---------------------------------------------------------------------------

def run_atlas(user_request: str, scenario_num: int = 1) -> str:
    """Run one Atlas planning cycle. Returns the final report string."""

    print(f"\n{'=' * 72}")
    print(f"  SCENARIO {scenario_num}")
    print(f"  Request: {user_request}")
    print(f"{'=' * 72}\n")

    tools = types.Tool(function_declarations=[SUMMARIZE_IMPACT_DECL])
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[tools],
    )

    contents = [
        types.Content(role="user", parts=[types.Part(text=user_request)])
    ]

    final_report = ""

    # Cap iterations so a misbehaving model can't spin forever
    for step in range(1, 6):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=config,
            )
        except Exception as e:
            print(f"[!] Gemini API error: {e}")
            return f"ERROR: {e}"

        if not response.candidates:
            print("[!] No candidates returned. Stopping.")
            return "ERROR: empty response"

        candidate = response.candidates[0]
        parts = candidate.content.parts or []

        # Surface any "thinking out loud" text from this turn
        text_chunks = [_safe(p, "text") for p in parts if _safe(p, "text")]
        if text_chunks:
            for chunk in text_chunks:
                print(chunk)

        # Collect any tool calls
        function_calls = [_safe(p, "function_call") for p in parts]
        function_calls = [fc for fc in function_calls if fc]

        if not function_calls:
            # No more tools - this is the final answer
            final_report = "\n".join(text_chunks).strip()
            break

        # Append the model's tool-call message, then run each tool
        print(f"\n  [step {step}] Atlas is calling tools...")
        contents.append(candidate.content)

        for fc in function_calls:
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}
            print(f"    -> {tool_name}({tool_args})")

            func = TOOL_FUNCTIONS.get(tool_name)
            if not func:
                result = {"error": f"Unknown tool: {tool_name}"}
            else:
                try:
                    result = func(**tool_args)
                except Exception as e:
                    result = {"error": f"Tool crashed: {e}"}

            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_function_response(
                    name=tool_name,
                    response={"result": result},
                )],
            ))

        print()  # blank line before next step

    else:
        # Loop exhausted without break
        print("[!] Atlas hit the 5-step limit without producing a final report.")
        return "ERROR: max steps exceeded"

    # Save the report
    saved_path = _save_report(scenario_num, user_request, final_report)
    print(f"\n  [report saved] {saved_path.relative_to(Path(__file__).parent)}\n")

    return final_report


# ---------------------------------------------------------------------------
# Demo scenarios
# ---------------------------------------------------------------------------

SCENARIOS = [
    # The headline - high-impact change with multiple critical dependencies
    "I want to drop the customer_segment column from stripe.customers. "
    "Tell me what will break and how to deprecate it safely.",

    # The safe case - column with zero dependencies
    "We're cleaning up old fields. Is it safe to drop lead_source_legacy "
    "from hubspot.deals?",

    # The unknown - graceful handling of a column that doesn't exist
    "I need to remove the discount_code column from stripe.customers. "
    "What depends on it?",
]


def main():
    single = "--single" in sys.argv

    print("\n" + "#" * 72)
    print("  ATLAS - Data Change Intelligence Agent")
    print("  Powered by Gemini + Fivetran MCP (lineage layer)")
    print("#" * 72)

    scenarios_to_run = SCENARIOS[:1] if single else SCENARIOS

    for i, request in enumerate(scenarios_to_run, start=1):
        run_atlas(request, scenario_num=i)

    print("\n" + "#" * 72)
    print(f"  Demo complete. {len(scenarios_to_run)} scenario(s) processed.")
    print(f"  Reports saved to: {REPORTS_DIR}/")
    print("#" * 72 + "\n")


if __name__ == "__main__":
    main()

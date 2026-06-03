"""
atlas.py - Atlas: Data Change Intelligence Agent (Full Lifecycle)

The complete agent loop:
  Phase 1 (Analysis):  Discover connector -> confirm column -> check impact -> generate plan
  Phase 2 (Approval):  Human reviews and approves/rejects
  Phase 3 (Execution): Soft-deprecate column -> trigger verification sync -> show proof

Run:
    python atlas.py                # full lifecycle demo (headline scenario)
    python atlas.py --analysis     # analysis only, skip execution
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
from gemini_client import smart_generate
from fivetran_tools import (
    list_connections,
    get_connection_details,
    get_connection_state,
    get_connection_schema_config,
    modify_connection_column_config,
    sync_connection,
    get_change_log,
)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("ERROR: GEMINI_API_KEY missing from .env file.")
    sys.exit(1)

client = genai.Client(api_key=API_KEY)

REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Tool declarations - what Gemini sees
# ---------------------------------------------------------------------------

ANALYSIS_TOOL_DECLS = [
    {
        "name": "list_connections",
        "description": (
            "List all Fivetran connections (data pipelines) in the account. "
            "Use this first to find the connection_id for a given data source like Stripe or HubSpot."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_connection_details",
        "description": "Get sync status, schedule, and health info for a specific Fivetran connection.",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string", "description": "The connection ID from list_connections."},
            },
            "required": ["connection_id"],
        },
    },
    {
        "name": "get_connection_state",
        "description": "Get current sync state (running, scheduled, paused) for a connection.",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string", "description": "The connection ID."},
            },
            "required": ["connection_id"],
        },
    },
    {
        "name": "get_connection_schema_config",
        "description": (
            "Get the full schema configuration for a connection - which schemas, tables, "
            "and columns are currently synced. Use this to confirm a column exists before "
            "checking its downstream impact."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string", "description": "The connection ID."},
            },
            "required": ["connection_id"],
        },
    },
    {
        "name": "summarize_impact",
        "description": (
            "Look up downstream impact of changing a column in a Fivetran-landed warehouse table. "
            "Returns dbt models, dashboards, reports, and ML features that depend on it, plus "
            "owner contacts and recommended deprecation period. "
            "Call this AFTER confirming the column exists via get_connection_schema_config."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Fully-qualified table, e.g. 'stripe.customers'."},
                "column": {"type": "string", "description": "Column name, e.g. 'customer_segment'."},
            },
            "required": ["table", "column"],
        },
    },
]

EXECUTION_TOOL_DECLS = [
    {
        "name": "modify_connection_column_config",
        "description": (
            "Soft-deprecate a column by setting enabled=false. This stops the column from "
            "syncing on the next run but does NOT delete existing data in the warehouse."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string", "description": "The connection ID."},
                "schema_name": {"type": "string", "description": "Schema name, e.g. 'stripe'."},
                "table_name": {"type": "string", "description": "Table name, e.g. 'customers'."},
                "column_name": {"type": "string", "description": "Column to deprecate, e.g. 'customer_segment'."},
                "enabled": {"type": "boolean", "description": "Set to false to soft-deprecate."},
            },
            "required": ["connection_id", "schema_name", "table_name", "column_name", "enabled"],
        },
    },
    {
        "name": "sync_connection",
        "description": "Trigger a verification sync after making changes to confirm everything still works.",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string", "description": "The connection ID."},
            },
            "required": ["connection_id"],
        },
    },
]

# Map names to functions
ALL_TOOL_FUNCTIONS = {
    "list_connections": lambda **kwargs: list_connections(),
    "get_connection_details": lambda **kwargs: get_connection_details(**kwargs),
    "get_connection_state": lambda **kwargs: get_connection_state(**kwargs),
    "get_connection_schema_config": lambda **kwargs: get_connection_schema_config(**kwargs),
    "summarize_impact": lambda **kwargs: summarize_impact(**kwargs),
    "modify_connection_column_config": lambda **kwargs: modify_connection_column_config(**kwargs),
    "sync_connection": lambda **kwargs: sync_connection(**kwargs),
}


# ---------------------------------------------------------------------------
# System prompts - one for each phase
# ---------------------------------------------------------------------------

ANALYSIS_PROMPT = """
You are Atlas, a data change intelligence agent.

The user wants to make a schema change. Your job in this phase is ANALYSIS ONLY.
Do NOT suggest executing anything yet. Follow these steps in order:

1. Call list_connections to find the relevant Fivetran connector.
2. Call get_connection_schema_config to confirm the target column exists and is currently synced.
   -> IF the column or table does not exist in Fivetran, STOP and tell the user it cannot be found. Do not generate the rest of the report.
3. Call get_connection_details to check the connector's health.
4. Call summarize_impact to discover all downstream dependencies.
   -> IF the column or table has no lineage data, state that there are zero known downstream dependencies.
5. Before each tool call, state briefly what you are checking.
6. After gathering all data, produce a report with these sections (only if the column exists):

   ## Connection Info
   One line: connector name, service type, sync status, last successful sync.

   ## Column Status
   One line: confirm the column exists and is currently enabled for sync.

   ## Impact Summary
   One paragraph: what breaks, how many assets affected, highest criticality.

   ## Affected Assets
   Bullet list: **name** (type) - owned by team_lead, team, criticality tier (if none, state "No downstream dependencies").

   ## Recommended Deprecation Plan
   Numbered steps with day offsets based on the recommended notice period (if no dependencies, recommend immediate drop).

   ## Stakeholder Messages
   For each unique team, draft a Slack message (3-5 sentences).
   Technical tone for engineering teams, business tone for exec/sales.
   Include the Slack channel as header. (Skip if no dependencies).

   ## Execution Preview
   State exactly which Fivetran API call will be made if the user approves:
   "modify_connection_column_config(connection_id=X, schema_name=X, table_name=X, column_name=X, enabled=false)"

7. End with: "Awaiting your approval to execute."
8. Be direct. No fluff. No apologies.
"""

EXECUTION_PROMPT = """
You are Atlas, executing an approved deprecation plan.

The user has approved the plan. Now execute it:

1. Call modify_connection_column_config with enabled=false to soft-deprecate the column.
2. Call sync_connection to trigger a verification sync.
3. After both calls succeed, produce a short confirmation:

   ## Execution Complete
   - Column: what was deprecated
   - Action: enabled set to false
   - Sync: triggered, status
   - What happens next: the column will stop syncing on the next run.
     Existing data in the warehouse is preserved.

4. Be brief. The analysis was already presented. Just confirm execution.
"""


# ---------------------------------------------------------------------------
# Core agent loop (used by both phases)
# ---------------------------------------------------------------------------

def _run_agent_loop(contents: list, tool_decls: list, system_prompt: str, phase_name: str, max_steps: int = 8) -> str:
    """Generic agent loop: send messages, handle tool calls, return final text."""

    tools = types.Tool(function_declarations=tool_decls)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[tools],
    )

    final_text = ""

    for step in range(1, max_steps + 1):
        try:
            response = smart_generate(client, contents, config)
        except Exception as e:
            print(f"\n  [!] Gemini API error: {e}")
            return f"ERROR: {e}"

        if not response.candidates:
            print("\n  [!] No response from Gemini.")
            return "ERROR: empty response"

        candidate = response.candidates[0]
        parts = candidate.content.parts or []

        # Print any text Gemini produces this turn
        text_parts = [getattr(p, "text", None) for p in parts]
        text_parts = [t for t in text_parts if t]
        if text_parts:
            for t in text_parts:
                print(t)

        # Collect tool calls
        fc_list = [getattr(p, "function_call", None) for p in parts]
        fc_list = [fc for fc in fc_list if fc]

        if not fc_list:
            final_text = "\n".join(text_parts).strip()
            break

        # Execute tool calls
        print(f"\n  [{phase_name} step {step}] Calling tools...")
        contents.append(candidate.content)

        for fc in fc_list:
            name = fc.name
            args = dict(fc.args) if fc.args else {}
            print(f"    -> {name}({args})")

            func = ALL_TOOL_FUNCTIONS.get(name)
            if not func:
                result = {"error": f"Unknown tool: {name}"}
            else:
                try:
                    result = func(**args)
                except Exception as e:
                    result = {"error": str(e)}

            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_function_response(
                    name=name,
                    response={"result": result},
                )],
            ))
        print()

    else:
        print(f"  [!] {phase_name} hit {max_steps}-step limit.")
        return "ERROR: max steps"

    return final_text


# ---------------------------------------------------------------------------
# The full lifecycle
# ---------------------------------------------------------------------------

def run_full_lifecycle(user_request: str) -> None:
    """Run the complete Atlas lifecycle: analyze -> approve -> execute."""

    # ---- Banner ----
    print("\n" + "#" * 72)
    print("  ATLAS - Data Change Intelligence Agent")
    print("  Full Lifecycle Demo")
    print("#" * 72)

    # ---- Phase 1: Analysis ----
    print(f"\n{'=' * 72}")
    print("  PHASE 1: ANALYSIS")
    print(f"  Request: {user_request}")
    print(f"{'=' * 72}\n")

    analysis_contents = [
        types.Content(role="user", parts=[types.Part(text=user_request)])
    ]

    analysis_report = _run_agent_loop(
        contents=analysis_contents,
        tool_decls=ANALYSIS_TOOL_DECLS,
        system_prompt=ANALYSIS_PROMPT,
        phase_name="analysis",
    )

    if analysis_report.startswith("ERROR"):
        print(f"\n  Analysis failed: {analysis_report}")
        return

    # Save analysis report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"lifecycle_analysis_{timestamp}.md"
    report_header = (
        f"# Atlas Lifecycle Report\n\n"
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"**Request:** {user_request}\n\n---\n\n"
    )
    report_path.write_text(report_header + analysis_report, encoding="utf-8")
    print(f"\n  [analysis saved] {report_path.name}")

    # ---- Phase 2: Human Approval ----
    print(f"\n{'=' * 72}")
    print("  PHASE 2: APPROVAL GATE")
    print(f"{'=' * 72}\n")

    analysis_only = "--analysis" in sys.argv

    if analysis_only:
        print("  [--analysis flag set, skipping execution]")
        return

    print("  Atlas has analyzed the change and produced a deprecation plan.")
    print("  Review the report above before approving.\n")

    try:
        approval = input("  >>> Approve execution? (yes/no): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  [interrupted]")
        return

    if approval not in ("yes", "y"):
        print("\n  Execution cancelled. No changes were made.")
        return

    # ---- Phase 3: Execution ----
    print(f"\n{'=' * 72}")
    print("  PHASE 3: EXECUTION")
    print(f"{'=' * 72}\n")

    # Give Gemini the original request + the analysis it produced + approval
    execution_contents = [
        types.Content(role="user", parts=[types.Part(text=(
            f"Original request: {user_request}\n\n"
            f"Analysis report (already shown to user):\n{analysis_report}\n\n"
            f"The user has APPROVED execution. Proceed with the deprecation now."
        ))]),
    ]

    execution_result = _run_agent_loop(
        contents=execution_contents,
        tool_decls=EXECUTION_TOOL_DECLS,
        system_prompt=EXECUTION_PROMPT,
        phase_name="execution",
    )

    # ---- Change Log ----
    print(f"\n{'=' * 72}")
    print("  CHANGE LOG (proof of execution)")
    print(f"{'=' * 72}\n")

    changes = get_change_log()
    if changes:
        for entry in changes:
            print(f"  [{entry['timestamp']}]")
            print(f"    Action: {entry['action']}")
            print(f"    Target: {entry['target']}")
            print(f"    Change: {entry['change']}")
            print()
    else:
        print("  No changes recorded.\n")

    # Save full report (analysis + execution)
    full_report_path = REPORTS_DIR / f"lifecycle_full_{timestamp}.md"
    full_content = (
        report_header
        + analysis_report
        + "\n\n---\n\n## Execution Result\n\n"
        + (execution_result or "No output")
        + "\n\n## Change Log\n\n```json\n"
        + json.dumps(changes, indent=2)
        + "\n```\n"
    )
    full_report_path.write_text(full_content, encoding="utf-8")
    print(f"  [full report saved] {full_report_path.name}")

    # ---- Done ----
    print(f"\n{'#' * 72}")
    print("  LIFECYCLE COMPLETE")
    print(f"  Reports: {REPORTS_DIR}/")
    print(f"{'#' * 72}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

DEMO_REQUEST = (
    "I want to drop the customer_segment column from stripe.customers. "
    "Tell me what will break and how to deprecate it safely."
)

if __name__ == "__main__":
    run_full_lifecycle(DEMO_REQUEST)

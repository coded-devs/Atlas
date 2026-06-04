"""
app.py - Atlas Web Interface

A Streamlit app that wraps the Atlas agent in a clean UI.
Judges see: request input -> live analysis -> approval button -> execution -> change log.

Run: streamlit run app.py
"""

import streamlit as st
import os
import json
import csv
import io
import requests as http_requests
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from google import genai
from google.genai import types
from dotenv import load_dotenv

from lineage import summarize_impact, load_default, load_graph, calculate_semantic_risk
from gemini_client import smart_generate
from demo_cache import check_analysis_cache, check_execution_cache
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

# Support Streamlit Community Cloud secrets AND local .env
def _get_api_key() -> str:
    # 1. Streamlit secrets (used when deployed to Streamlit Community Cloud)
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
        if key:
            return key
    except Exception:
        pass
    # 2. Environment variable / .env file (used locally)
    return os.getenv("GEMINI_API_KEY", "")

API_KEY = _get_api_key()
if not API_KEY:
    st.error("GEMINI_API_KEY is not set. Add it to .env (local) or Streamlit secrets (cloud).")
    st.stop()

client = genai.Client(api_key=API_KEY)

# ---------------------------------------------------------------------------
# Tool declarations (same as atlas.py)
# ---------------------------------------------------------------------------

ANALYSIS_TOOL_DECLS = [
    {
        "name": "list_connections",
        "description": "List all Fivetran connections in the account. Use first to find the connection_id.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_connection_details",
        "description": "Get sync status, schedule, and health for a Fivetran connection.",
        "parameters": {
            "type": "object",
            "properties": {"connection_id": {"type": "string", "description": "The connection ID."}},
            "required": ["connection_id"],
        },
    },
    {
        "name": "get_connection_state",
        "description": "Get current sync state for a connection.",
        "parameters": {
            "type": "object",
            "properties": {"connection_id": {"type": "string", "description": "The connection ID."}},
            "required": ["connection_id"],
        },
    },
    {
        "name": "get_connection_schema_config",
        "description": "Get schema config - which tables and columns are synced. Use to confirm a column exists.",
        "parameters": {
            "type": "object",
            "properties": {"connection_id": {"type": "string", "description": "The connection ID."}},
            "required": ["connection_id"],
        },
    },
    {
        "name": "summarize_impact",
        "description": "Look up downstream impact of changing a column. Returns dashboards, models, reports, owners, and deprecation policy.",
        "parameters": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name, e.g. 'stripe.customers'."},
                "column": {"type": "string", "description": "Column name, e.g. 'customer_segment'."},
            },
            "required": ["table", "column"],
        },
    },
]

EXECUTION_TOOL_DECLS = [
    {
        "name": "modify_connection_column_config",
        "description": "Soft-deprecate a column by setting enabled=false.",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "schema_name": {"type": "string"},
                "table_name": {"type": "string"},
                "column_name": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
            "required": ["connection_id", "schema_name", "table_name", "column_name", "enabled"],
        },
    },
    {
        "name": "sync_connection",
        "description": "Trigger a verification sync after changes.",
        "parameters": {
            "type": "object",
            "properties": {"connection_id": {"type": "string"}},
            "required": ["connection_id"],
        },
    },
]

ALL_TOOL_FUNCTIONS = {
    "list_connections": lambda **kw: list_connections(),
    "get_connection_details": lambda **kw: get_connection_details(**kw),
    "get_connection_state": lambda **kw: get_connection_state(**kw),
    "get_connection_schema_config": lambda **kw: get_connection_schema_config(**kw),
    "summarize_impact": lambda **kw: summarize_impact(**kw),
    "modify_connection_column_config": lambda **kw: modify_connection_column_config(**kw),
    "sync_connection": lambda **kw: sync_connection(**kw),
}


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

ANALYSIS_PROMPT = """
You are Atlas, a data change intelligence agent built by the coded-devs team.
You help data engineers and data platform teams safely manage schema changes by analyzing downstream impact across Fivetran pipelines.

## Behaviour Rules

### Rule 1 — Conversational mode (default)
If the user's message is a general question, greeting, or anything that does NOT clearly specify a table and column to change, respond conversationally WITHOUT calling any tools.
- Answer questions about what you can do, how you work, what Fivetran is, etc.
- If the user seems to want a change but hasn't given you a table and column, ask a follow-up question to get the specifics.
- Examples of conversational messages: "what can you do?", "how does this work?", "what is Fivetran?", "tell me about data lineage", "hi", "what tables do you support?"

### Rule 2 — Analysis mode (only when you have a clear target)
If the user clearly specifies a table + column they want to drop, deprecate, remove, or evaluate, THEN call tools in this exact order:
1. `list_connections` — find the relevant connector.
2. `get_connection_schema_config` — confirm the column exists in Fivetran.
   → IF NOT FOUND: Stop. Tell the user politely the column/table was not found.
3. `get_connection_details` — check connector health.
4. `summarize_impact` — get downstream dependencies.

Then write a structured report with these sections:

## Connection Info
One line: connector name, service, status, last sync.

## Column Status
Confirm the column exists and is currently synced.

## Impact Summary
One paragraph: what breaks, how many assets are affected, what is the highest criticality tier.

## Affected Assets
Bullet list: **name** (type) — owned by [lead], team: [team], tier: [tier].
If none, write: "No downstream dependencies found — this column is safe to drop immediately."

## Recommended Deprecation Plan
Numbered steps with day offsets based on the highest tier asset found.
If no dependencies, simply say: "Safe for immediate removal."

## Stakeholder Messages
For each unique team affected, a 3-5 sentence Slack message.
Technical language for engineering teams, plain business language for exec/finance teams.
Skip this section entirely if there are no downstream dependencies.

Be direct, clear, and professional. No filler text.
"""

EXECUTION_PROMPT = """
You are Atlas, executing an approved plan.
1. Call modify_connection_column_config with enabled=false.
2. Call sync_connection to verify.
3. Confirm what was done in 3-4 lines. Be brief.
"""


# ---------------------------------------------------------------------------
# Agent loop (adapted for Streamlit)
# ---------------------------------------------------------------------------

def run_agent(contents, tool_decls, system_prompt, status_container):
    """Run the agent loop, updating a Streamlit status container with progress."""

    tools = types.Tool(function_declarations=tool_decls)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[tools],
    )

    tool_log = []
    final_text = ""

    for step in range(1, 9):
        try:
            response = smart_generate(
                client,
                contents,
                config,
                on_status=lambda m: status_container.write(m),
            )
        except Exception as e:
            return f"API Error: {e}", tool_log

        if not response.candidates:
            return "Error: No response from Gemini.", tool_log

        candidate = response.candidates[0]
        parts = candidate.content.parts or []

        text_parts = [getattr(p, "text", None) for p in parts]
        text_parts = [t for t in text_parts if t]

        fc_list = [getattr(p, "function_call", None) for p in parts]
        fc_list = [fc for fc in fc_list if fc]

        if not fc_list:
            final_text = "\n".join(text_parts).strip()
            break

        contents.append(candidate.content)

        for fc in fc_list:
            name = fc.name
            args = dict(fc.args) if fc.args else {}

            status_container.write(f"Calling `{name}({json.dumps(args)})`")
            tool_log.append({"tool": name, "args": args})

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

        if text_parts:
            for t in text_parts:
                status_container.write(t)

    return final_text, tool_log


# ---------------------------------------------------------------------------
# Custom data source loading
# ---------------------------------------------------------------------------

# Standard deprecation policy tiers, reused when a custom upload doesn't
# define its own criticality_levels (CSV uploads never do).
_DEFAULT_CRITICALITY_LEVELS = {
    "tier_1": {"description": "Business-critical. Used by execs or revenue-impacting systems. Requires 2-week deprecation notice minimum.", "deprecation_notice_days": 14},
    "tier_2": {"description": "Important but recoverable. Team-level analytics. Requires 1-week notice.", "deprecation_notice_days": 7},
    "tier_3": {"description": "Internal exploration. Minimal notice required.", "deprecation_notice_days": 2},
}

_TIER_PRIORITY = {"tier_1": 1, "tier_2": 2, "tier_3": 3}

CSV_COLUMNS = [
    "table", "column", "description", "is_pii",
    "downstream_name", "downstream_type", "downstream_tool",
    "owner_team", "owner_lead", "owner_email", "owner_slack", "criticality",
]


def _to_bool(value: str) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes", "y", "t")


def build_graph_from_csv(text: str) -> dict:
    """
    Turn a flat CSV (one row per downstream dependency) into the nested
    lineage dict structure that lineage.json uses.

    Expected columns: see CSV_COLUMNS. Rows are grouped by table + column;
    each row contributes one downstream asset and (optionally) one owner.
    """
    reader = csv.DictReader(io.StringIO(text))

    missing = [c for c in CSV_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

    tables: dict = {}
    owners: dict = {}

    for row in reader:
        table = (row.get("table") or "").strip()
        column = (row.get("column") or "").strip()
        if not table or not column:
            continue

        table_entry = tables.setdefault(
            table, {"criticality": None, "team_owner": "data-platform", "columns": {}}
        )
        col_entry = table_entry["columns"].setdefault(
            column,
            {
                "description": (row.get("description") or "").strip(),
                "is_pii": _to_bool(row.get("is_pii")),
                "downstream": [],
            },
        )

        downstream_name = (row.get("downstream_name") or "").strip()
        if downstream_name:
            asset = {
                "type": (row.get("downstream_type") or "").strip() or "unknown",
                "name": downstream_name,
                "owner": (row.get("owner_team") or "").strip(),
                "criticality": (row.get("criticality") or "").strip() or "tier_3",
            }
            tool = (row.get("downstream_tool") or "").strip()
            if tool:
                asset["tool"] = tool
            col_entry["downstream"].append(asset)

        team = (row.get("owner_team") or "").strip()
        if team and team not in owners:
            owners[team] = {
                "slack": (row.get("owner_slack") or "").strip(),
                "email": (row.get("owner_email") or "").strip(),
                "lead": (row.get("owner_lead") or "").strip(),
            }

    # Derive each table's criticality from the strictest tier among its assets.
    for table_entry in tables.values():
        tiers = [
            a["criticality"]
            for col in table_entry["columns"].values()
            for a in col["downstream"]
        ]
        if tiers:
            table_entry["criticality"] = min(
                tiers, key=lambda t: _TIER_PRIORITY.get(t, 99)
            )
        else:
            table_entry["criticality"] = "tier_3"

    return {
        "tables": tables,
        "owners": owners,
        "criticality_levels": _DEFAULT_CRITICALITY_LEVELS,
    }


def configure_data_source():
    """
    Render the data-source picker in the sidebar and load the chosen graph
    into the lineage module. Runs on every rerun so the active lineage graph
    always matches the current selection.
    """
    st.header("Data source")
    source = st.radio(
        "Lineage data",
        ("Demo data", "Upload JSON", "Upload CSV"),
        label_visibility="collapsed",
    )

    with st.expander("Expected format"):
        st.markdown(
            "**Demo data** — the bundled `lineage.json` sample "
            "(stripe, hubspot connectors).\n\n"
            "**Upload JSON** — a file matching `lineage.json`: top-level "
            "`tables`, `owners`, and `criticality_levels` keys.\n\n"
            "**Upload CSV** — one row per downstream dependency, with columns:"
        )
        st.code(", ".join(CSV_COLUMNS), language=None)
        st.caption(
            "`is_pii` accepts true/false. Multiple rows sharing the same "
            "table + column are grouped into one column with several "
            "downstream assets."
        )

    if source == "Demo data":
        load_default()
        return

    if source == "Upload JSON":
        uploaded = st.file_uploader("Upload a lineage JSON file", type=["json"])
        if uploaded is None:
            load_default()  # keep the app usable until a file arrives
            st.info("Using demo data until a JSON file is uploaded.")
            return
        try:
            data = json.loads(uploaded.getvalue().decode("utf-8"))
            if "tables" not in data:
                raise ValueError("JSON must contain a top-level 'tables' key.")
            data.setdefault("owners", {})
            data.setdefault("criticality_levels", _DEFAULT_CRITICALITY_LEVELS)
            load_graph(data)
            st.success(
                f"Loaded {len(data['tables'])} table(s) from "
                f"`{uploaded.name}`."
            )
        except Exception as e:
            load_default()
            st.error(f"Could not parse JSON: {e}")
        return

    # Upload CSV
    uploaded = st.file_uploader("Upload a lineage CSV file", type=["csv"])
    if uploaded is None:
        load_default()
        st.info("Using demo data until a CSV file is uploaded.")
        return
    try:
        text = uploaded.getvalue().decode("utf-8-sig")
        graph = build_graph_from_csv(text)
        if not graph["tables"]:
            raise ValueError("No valid rows found (need table + column values).")
        load_graph(graph)
        st.success(
            f"Loaded {len(graph['tables'])} table(s) and "
            f"{len(graph['owners'])} team(s) from `{uploaded.name}`."
        )
    except Exception as e:
        load_default()
        st.error(f"Could not parse CSV: {e}")


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Atlas - Data Change Intelligence",
    page_icon="🔍",
    layout="wide",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Outfit', sans-serif !important;
}

/* Base Dark Theme Overrides */
.stApp {
    background-color: #0b0f19 !important;
    color: #e2e8f0 !important;
}

/* Sidebar styling (Glassmorphism) */
[data-testid="stSidebar"] {
    background: rgba(15, 23, 42, 0.4) !important;
    backdrop-filter: blur(12px) !important;
    border-right: 1px solid rgba(255,255,255,0.05);
}

/* Primary Button with Gradient and Micro-animation */
button[kind="primary"] {
    background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    transition: all 0.3s ease !important;
    box-shadow: 0 4px 14px 0 rgba(99, 102, 241, 0.39) !important;
}

button[kind="primary"]:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(99, 102, 241, 0.6) !important;
}

/* Secondary Buttons */
button[kind="secondary"] {
    background-color: rgba(255, 255, 255, 0.05) !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 8px !important;
    transition: all 0.3s ease !important;
    color: #e2e8f0 !important;
}

button[kind="secondary"]:hover {
    background-color: rgba(255, 255, 255, 0.1) !important;
    transform: translateY(-1px) !important;
}

/* Status container styling */
[data-testid="stStatusWidget"] {
    border-radius: 12px;
    background: rgba(30, 41, 59, 0.5) !important;
    border: 1px solid rgba(255,255,255,0.05) !important;
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2);
    backdrop-filter: blur(4px);
}

/* Text area styling */
.stTextArea textarea {
    background-color: #1e293b !important;
    color: #f8fafc !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 8px !important;
}

.stTextArea textarea:focus {
    border-color: #a855f7 !important;
    box-shadow: 0 0 0 1px #a855f7 !important;
}

/* Code blocks (JSON, Tool calls) */
.stCodeBlock {
    border-radius: 8px !important;
    border: 1px solid rgba(255, 255, 255, 0.05) !important;
}

/* File uploader */
[data-testid="stFileUploadDropzone"] {
    background-color: rgba(255,255,255, 0.02) !important;
    border: 2px dashed rgba(255,255,255, 0.1) !important;
    border-radius: 12px !important;
}

/* Warning & Info banners */
.stAlert {
    border-radius: 8px !important;
    border: none !important;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "analysis_report" not in st.session_state:
    st.session_state.analysis_report = None
if "analysis_contents" not in st.session_state:
    st.session_state.analysis_contents = None
if "execution_done" not in st.session_state:
    st.session_state.execution_done = False
if "execution_result" not in st.session_state:
    st.session_state.execution_result = None
if "tool_log" not in st.session_state:
    st.session_state.tool_log = []
if "user_request" not in st.session_state:
    st.session_state.user_request = ""
if "severity" not in st.session_state:
    st.session_state.severity = None
if "followup_history" not in st.session_state:
    st.session_state.followup_history = []


# ---------------------------------------------------------------------------
# UI Layout
# ---------------------------------------------------------------------------

# Hero Header
st.markdown("""
<div style="
    padding: 2rem 0 1rem 0;
    text-align: left;
">
    <h1 style="
        font-size: 3rem;
        font-weight: 600;
        background: linear-gradient(135deg, #a78bfa 0%, #818cf8 40%, #6366f1 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.3rem;
        letter-spacing: -0.02em;
    ">Atlas</h1>
    <p style="
        color: #94a3b8;
        font-size: 1.05rem;
        margin: 0;
        letter-spacing: 0.02em;
    ">Data Change Intelligence Agent &mdash; Powered by <strong style="color:#a78bfa;">Gemini</strong> + <strong style="color:#818cf8;">Fivetran MCP</strong></p>
</div>
<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 0.5rem 0 1.5rem 0;">
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding: 1rem 0 0.5rem 0;">
        <span style="font-size: 2rem;">🔍</span>
        <h2 style="
            font-size: 1.4rem;
            font-weight: 600;
            background: linear-gradient(135deg, #a78bfa, #6366f1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 0.3rem 0 0 0;
        ">Atlas</h2>
        <p style="color: #64748b; font-size: 0.8rem; margin-top:0.2rem;">v1.0 &bull; Hackathon Edition</p>
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    configure_data_source()

    st.divider()
    st.header("Integrations")
    slack_webhook = st.text_input(
        "Slack Webhook URL",
        type="password",
        placeholder="https://hooks.slack.com/services/...",
        help="Paste an Incoming Webhook URL to send notifications directly to Slack. Create one at https://api.slack.com/apps",
    )
    st.markdown("<br>", unsafe_allow_html=True)
    telegram_bot_token = st.text_input(
        "Telegram Bot Token",
        type="password",
        placeholder="123456789:ABCdefGHI...",
        help="Create a bot with BotFather on Telegram and paste the token here.",
    )
    telegram_chat_id = st.text_input(
        "Telegram Chat ID",
        placeholder="-1001234567890",
        help="The chat ID of the group or user to send the notification to.",
    )

    st.divider()
    st.markdown("""
    <div style="padding: 0.5rem 0;">
        <h4 style="color: #cbd5e1; margin-bottom: 0.8rem;">⚡ How it works</h4>
        <div style="display: flex; align-items: flex-start; margin-bottom: 0.7rem;">
            <span style="
                background: linear-gradient(135deg, #6366f1, #a855f7);
                color: white; font-weight: 600; font-size: 0.75rem;
                min-width: 22px; height: 22px; border-radius: 50%;
                display: flex; align-items: center; justify-content: center;
                margin-right: 0.6rem; margin-top: 2px;
            ">1</span>
            <div><strong style="color:#e2e8f0;">Describe your change</strong><br><span style="color:#94a3b8; font-size:0.85rem;">Tell Atlas what schema change you want to make.</span></div>
        </div>
        <div style="display: flex; align-items: flex-start; margin-bottom: 0.7rem;">
            <span style="
                background: linear-gradient(135deg, #6366f1, #a855f7);
                color: white; font-weight: 600; font-size: 0.75rem;
                min-width: 22px; height: 22px; border-radius: 50%;
                display: flex; align-items: center; justify-content: center;
                margin-right: 0.6rem; margin-top: 2px;
            ">2</span>
            <div><strong style="color:#e2e8f0;">Review the analysis</strong><br><span style="color:#94a3b8; font-size:0.85rem;">Atlas discovers connectors, confirms columns, checks downstream impact.</span></div>
        </div>
        <div style="display: flex; align-items: flex-start; margin-bottom: 0.7rem;">
            <span style="
                background: linear-gradient(135deg, #6366f1, #a855f7);
                color: white; font-weight: 600; font-size: 0.75rem;
                min-width: 22px; height: 22px; border-radius: 50%;
                display: flex; align-items: center; justify-content: center;
                margin-right: 0.6rem; margin-top: 2px;
            ">3</span>
            <div><strong style="color:#e2e8f0;">Approve or reject</strong><br><span style="color:#94a3b8; font-size:0.85rem;">You stay in control. Atlas only executes after your explicit approval.</span></div>
        </div>
        <div style="display: flex; align-items: flex-start;">
            <span style="
                background: linear-gradient(135deg, #6366f1, #a855f7);
                color: white; font-weight: 600; font-size: 0.75rem;
                min-width: 22px; height: 22px; border-radius: 50%;
                display: flex; align-items: center; justify-content: center;
                margin-right: 0.6rem; margin-top: 2px;
            ">4</span>
            <div><strong style="color:#e2e8f0;">Execution + proof</strong><br><span style="color:#94a3b8; font-size:0.85rem;">Soft-deprecates the column via Fivetran, triggers a sync, and logs everything.</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    st.markdown("**💡 Example requests:**")
    st.code("Drop customer_segment from stripe.customers", language=None)
    st.code("Is it safe to drop lead_source_legacy from hubspot.deals?", language=None)
    st.code("Drop forecast_category from salesforce.opportunities and lead_source_legacy from hubspot.deals", language=None)

    st.divider()
    st.markdown("""
    <div style="text-align: center; padding: 0.5rem 0;">
        <span style="color: #475569; font-size: 0.75rem;">Built for the</span><br>
        <span style="
            font-size: 0.8rem;
            font-weight: 600;
            background: linear-gradient(135deg, #a78bfa, #38bdf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        ">Google Cloud Rapid Agent Hackathon 2026</span>
    </div>
    """, unsafe_allow_html=True)


# Main area
if st.session_state.analysis_report:
    # Hide input after analysis, show what was asked and a reset button
    st.markdown(f"**Analysis Target:** `{st.session_state.user_request}`")
    if st.button("🔄 Start New Analysis", use_container_width=False):
        st.session_state.analysis_report = None
        st.session_state.tool_log = []
        st.session_state.execution_done = False
        st.session_state.user_request = ""
        st.session_state.followup_history = []
        st.rerun()
    
    # We set these to false/empty strings so the analysis logic below doesn't run again
    analyze_clicked = False
    request = ""
else:
    col_input, col_status = st.columns([3, 1])
    
    with col_input:
        request = st.text_area(
            "Ask me anything about your data stack, or describe a schema change:",
            placeholder="e.g., \"What can you do?\" or \"Drop customer_segment from stripe.customers\"",
            height=80,
        )
    
    with col_status:
        st.markdown("&nbsp;")  # spacing
        st.markdown("&nbsp;")
        analyze_clicked = st.button("Send", type="primary", use_container_width=True)

# Welcome card — only show before first interaction
if not st.session_state.analysis_report and not st.session_state.execution_done:
    st.markdown("""
    <div style="
        background: rgba(30, 41, 59, 0.4);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 14px;
        padding: 2rem 2.5rem;
        margin-top: 1.5rem;
        backdrop-filter: blur(8px);
    ">
        <p style="color: #cbd5e1; font-size: 1rem; margin: 0 0 0.3rem 0;">
            I am <strong style="color:#a78bfa;">Atlas</strong>, your data change intelligence agent.
            I help you safely manage schema changes by analyzing the downstream impact of modifying or removing data columns in your warehouse.
        </p>
        <p style="color: #94a3b8; font-size: 0.95rem; margin: 0.8rem 0 1.2rem 0;">
            You can ask me to evaluate the impact of a proposed change, such as:
            <em style="color:#818cf8;">"What happens if I drop <code>customer_id</code> from <code>stripe.customers</code>?"</em>
        </p>
        <h3 style="color: #e2e8f0; font-size: 1.1rem; margin: 0 0 0.8rem 0;">Here is how I can assist:</h3>
        <ol style="color: #94a3b8; font-size: 0.92rem; line-height: 1.9; margin: 0; padding-left: 1.3rem;">
            <li><strong style="color:#e2e8f0;">Dependency Mapping:</strong> I identify exactly which dashboards, reports, and data models will break if a column is removed or renamed.</li>
            <li><strong style="color:#e2e8f0;">Stakeholder Identification:</strong> I tell you exactly who owns those assets so you know who to notify.</li>
            <li><strong style="color:#e2e8f0;">Risk Assessment:</strong> I check the health and sync status of your Fivetran connectors to ensure you aren&apos;t making changes based on stale or broken pipelines.</li>
            <li><strong style="color:#e2e8f0;">Communication Templates:</strong> I draft targeted Slack messages for both technical and business stakeholders to keep your team informed and minimize friction.</li>
            <li><strong style="color:#e2e8f0;">Deprecation Planning:</strong> I provide a step-by-step timeline to help you decommission columns gracefully.</li>
        </ol>
        <p style="color: #64748b; font-size: 0.88rem; margin: 1.2rem 0 0 0;">
            <strong style="color:#94a3b8;">How to get started:</strong> Just provide the table and column name you are planning to change. For example:
        </p>
        <div style="
            background: rgba(99,102,241,0.08);
            border: 1px solid rgba(99,102,241,0.15);
            border-radius: 8px;
            padding: 0.6rem 1rem;
            margin-top: 0.6rem;
            font-size: 0.9rem;
            color: #94a3b8;
            font-style: italic;
        ">
            &ldquo;Atlas, check the impact of removing <code style="color:#a78bfa;">user_email</code> from <code style="color:#818cf8;">salesforce.leads</code>.&rdquo;
        </div>
    </div>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Phase 1: Analysis
# ---------------------------------------------------------------------------

if analyze_clicked and request.strip():
    st.session_state.analysis_report = None
    st.session_state.execution_done = False
    st.session_state.execution_result = None
    st.session_state.tool_log = []
    st.session_state.user_request = request.strip()
    st.session_state.followup_history = []

    st.divider()

    # Pick a friendly status label based on whether this looks like an analysis or a chat
    _request_lower = request.strip().lower()
    _is_analysis = any(kw in _request_lower for kw in ["drop", "remove", "deprecate", "delete", "rename", "impact", "safe to", "what happens if"])
    _status_label = "Atlas is analyzing your change..." if _is_analysis else "Atlas is thinking..."

    with st.status(_status_label, expanded=True) as status:
        contents = [
            types.Content(role="user", parts=[types.Part(text=request.strip())])
        ]

        # Demo cache: if this matches a rehearsed scenario, serve the pre-baked
        # report and skip Gemini entirely so the demo survives zero API quota.
        _cached = check_analysis_cache(request.strip())
        if _cached:
            status.write("🟢 Demo mode — serving cached analysis (no API quota used).")
            report, tool_log = _cached["report"], _cached["tool_log"]
        else:
            report, tool_log = run_agent(
                contents=contents,
                tool_decls=ANALYSIS_TOOL_DECLS,
                system_prompt=ANALYSIS_PROMPT,
                status_container=status,
            )

        _done_label = "Analysis complete" if tool_log else "Done"
        status.update(label=_done_label, state="complete")

    # --- Feature 2: Lock severity into Gemini's context ---
    # After the first pass, check if the ranker has a result and re-run
    # Gemini with the locked severity injected into the conversation.
    _sev_result = None
    for entry in tool_log:
        if entry["tool"] == "summarize_impact":
            _args = entry["args"]
            _t, _c = _args.get("table", ""), _args.get("column", "")
            if _t and _c:
                _sev_result = calculate_semantic_risk(_t, _c)
                # Also check PII
                _impact = summarize_impact(_t, _c)
                _sev_result["is_pii"] = _impact.get("is_pii", False)
            break

    if _sev_result and _sev_result["severity"] != "INFO":
        # Inject the deterministic severity into the conversation and re-generate
        severity_lock = (
            f"\n\n---\nIMPORTANT — DETERMINISTIC SEVERITY OVERRIDE:\n"
            f"The Semantic Ranker (pure Python, not AI) has classified this change as: {_sev_result['badge']}\n"
            f"Rationale: {_sev_result['rationale']}\n"
            f"You MUST use this exact severity level ({_sev_result['severity']}) in your Impact Summary. "
            f"Do not soften, upgrade, or change the severity. The ranker's classification is authoritative."
        )
        report = report + severity_lock
        # Strip the lock instruction from the displayed report
        report = report.split("\n\n---\nIMPORTANT — DETERMINISTIC SEVERITY OVERRIDE:")[0]

    st.session_state.analysis_report = report
    st.session_state.analysis_contents = contents
    st.session_state.tool_log = tool_log
    st.session_state.severity = _sev_result if tool_log else None


# ---------------------------------------------------------------------------
# Display analysis report
# ---------------------------------------------------------------------------

if st.session_state.analysis_report and not st.session_state.execution_done:
    st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 1.5rem 0;">', unsafe_allow_html=True)

    # --- Severity Badge (deterministic, no LLM) ---
    sev = st.session_state.severity
    if sev:
        _sev_colors = {
            "CRITICAL": ("rgba(239,68,68,0.12)", "rgba(239,68,68,0.35)", "#fca5a5"),
            "HIGH":     ("rgba(249,115,22,0.12)", "rgba(249,115,22,0.35)", "#fdba74"),
            "WARNING":  ("rgba(234,179,8,0.12)",  "rgba(234,179,8,0.35)",  "#fde047"),
            "INFO":     ("rgba(59,130,246,0.12)",  "rgba(59,130,246,0.35)",  "#93c5fd"),
        }
        bg, border, text = _sev_colors.get(sev["severity"], _sev_colors["INFO"])
        st.markdown(f"""
        <div style="
            background: {bg};
            border: 1px solid {border};
            border-radius: 14px;
            padding: 1.2rem 1.8rem;
            margin-bottom: 1.2rem;
            display: flex;
            align-items: center;
            gap: 1rem;
        ">
            <span style="font-size: 2.2rem; line-height: 1;">{sev['badge'].split()[0]}</span>
            <div>
                <div style="font-size: 1.3rem; font-weight: 700; color: {text}; letter-spacing: 0.04em;">
                    {sev['badge']} &mdash; {sev['label']}
                </div>
                <div style="font-size: 0.88rem; color: #94a3b8; margin-top: 0.2rem;">
                    {sev['rationale']}{'&nbsp;&nbsp;|&nbsp;&nbsp;<strong style="color:' + text + ';">Minimum notice: ' + str(sev['notice_days']) + ' days</strong>' if sev['notice_days'] > 0 else ''}
                </div>
                <div style="font-size: 0.75rem; color: #475569; margin-top: 0.4rem;">⚙️ Calculated by deterministic Semantic Ranker &mdash; not AI-generated</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # --- Feature 1: PII Warning Badge ---
    if sev and sev.get("is_pii"):
        st.markdown("""
        <div style="
            background: rgba(245,158,11,0.10);
            border: 1px solid rgba(245,158,11,0.35);
            border-radius: 12px;
            padding: 0.9rem 1.4rem;
            margin-bottom: 1.2rem;
            display: flex;
            align-items: center;
            gap: 0.8rem;
        ">
            <span style="font-size: 1.8rem; line-height: 1;">🔒</span>
            <div>
                <div style="font-size: 1.1rem; font-weight: 700; color: #fbbf24;">PII Column Detected</div>
                <div style="font-size: 0.85rem; color: #94a3b8;">This column is flagged as containing Personally Identifiable Information. Extra care required &mdash; consult your DPO before making changes.</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Report card
    report_title = "📊 Impact Analysis Report" if st.session_state.tool_log else "💬 Atlas Response"
    st.markdown(f"""
    <div style="
        background: rgba(30, 41, 59, 0.5);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 12px;
        padding: 1.5rem 2rem;
        margin-bottom: 1.5rem;
        backdrop-filter: blur(8px);
    ">
        <h2 style="
            font-size: 1.5rem;
            font-weight: 600;
            background: linear-gradient(135deg, #a78bfa 0%, #6366f1 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.3rem;
        ">{report_title}</h2>
        <p style="color: #64748b; font-size: 0.85rem; margin: 0;">Generated by Atlas &bull; Gemini-powered reasoning</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(st.session_state.analysis_report)

    # --- Feature 3: Download Report ---
    if st.session_state.tool_log:
        _download_content = st.session_state.analysis_report
        if sev:
            _download_content = f"**Severity: {sev['badge']}** — {sev['rationale']}\n\n" + _download_content
        st.download_button(
            label="📥 Download Report",
            data=_download_content,
            file_name=f"atlas_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
            mime="text/markdown",
        )

    # --- Feature 5: Stakeholder Notification Cards ---
    if st.session_state.tool_log and sev and sev.get("severity") != "INFO":
        # Pull the affected teams from the lineage data
        _notif_table = None
        _notif_column = None
        for entry in st.session_state.tool_log:
            if entry["tool"] == "summarize_impact":
                _notif_table = entry["args"].get("table", "")
                _notif_column = entry["args"].get("column", "")
                break

        if _notif_table and _notif_column:
            _impact_data = summarize_impact(_notif_table, _notif_column)
            _teams_seen = set()
            _notifications = []

            for asset in _impact_data.get("downstream_assets", []):
                team = asset.get("owner", "")
                if team and team not in _teams_seen:
                    _teams_seen.add(team)
                    contact = asset.get("owner_contact", {})
                    lead = contact.get("lead", "Team Lead")
                    email = contact.get("email", "")
                    slack_channel = contact.get("slack", "")
                    asset_name = asset.get("name", "")
                    criticality = asset.get("criticality", "tier_3")

                    # Build the notification message
                    msg = (
                        f"⚠️ *Schema Change Notice — {_notif_table}.{_notif_column}*\n\n"
                        f"Hi {lead},\n\n"
                        f"The data platform team is planning to deprecate the `{_notif_column}` column "
                        f"from `{_notif_table}`. Our analysis shows this impacts your asset "
                        f"*{asset_name}* ({criticality.replace('_', ' ').title()}).\n\n"
                        f"Severity: {sev['badge']}\n"
                        f"Required notice: {sev['notice_days']} days\n\n"
                        f"Please review and confirm whether your team has any dependencies "
                        f"that need migration before this change is applied.\n\n"
                        f"— Atlas (Data Change Intelligence Agent)"
                    )
                    _notifications.append({
                        "team": team,
                        "lead": lead,
                        "email": email,
                        "slack_channel": slack_channel,
                        "message": msg,
                        "asset_name": asset_name,
                        "criticality": criticality,
                    })

            if _notifications:
                st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 1.5rem 0;">', unsafe_allow_html=True)
                st.markdown("""
                <div style="
                    background: rgba(30, 41, 59, 0.5);
                    border: 1px solid rgba(255, 255, 255, 0.06);
                    border-radius: 12px;
                    padding: 1.2rem 1.5rem;
                    margin-bottom: 1rem;
                    backdrop-filter: blur(8px);
                ">
                    <h3 style="color: #a78bfa; margin: 0; font-size: 1.2rem;">📨 Stakeholder Notifications</h3>
                    <p style="color: #64748b; font-size: 0.8rem; margin: 0.3rem 0 0 0;">Send impact alerts to affected teams via Slack or Email</p>
                </div>
                """, unsafe_allow_html=True)

                for idx, notif in enumerate(_notifications):
                    tier_colors = {
                        "tier_1": "#fca5a5",
                        "tier_2": "#fdba74",
                        "tier_3": "#fde047",
                    }
                    tier_color = tier_colors.get(notif["criticality"], "#94a3b8")

                    st.markdown(f"""
                    <div style="
                        background: rgba(30, 41, 59, 0.4);
                        border: 1px solid rgba(255,255,255,0.08);
                        border-left: 3px solid {tier_color};
                        border-radius: 0 10px 10px 0;
                        padding: 1rem 1.3rem;
                        margin-bottom: 0.8rem;
                    ">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <div>
                                <strong style="color: #e2e8f0; font-size: 1rem;">{notif['team']}</strong>
                                <span style="color: #64748b; font-size: 0.85rem;"> · {notif['lead']}</span>
                            </div>
                            <span style="color: {tier_color}; font-size: 0.8rem; font-weight: 600;">{notif['criticality'].replace('_', ' ').upper()}</span>
                        </div>
                        <div style="color: #94a3b8; font-size: 0.82rem; margin-bottom: 0.3rem;">
                            Asset: <code style="color: #e2e8f0;">{notif['asset_name']}</code>
                            {' · Slack: <code style="color: #e2e8f0;">' + notif['slack_channel'] + '</code>' if notif['slack_channel'] else ''}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    with st.expander(f"📝 Preview message for {notif['team']}", expanded=False):
                        st.code(notif["message"], language=None)

                    col_slack, col_telegram, col_email = st.columns([1, 1, 1])

                    with col_slack:
                        if st.button(f"💬 Send to Slack", key=f"slack_{idx}", use_container_width=True):
                            if slack_webhook:
                                try:
                                    resp = http_requests.post(
                                        slack_webhook,
                                        json={"text": notif["message"]},
                                        timeout=10,
                                    )
                                    if resp.status_code == 200:
                                        st.success(f"✅ Sent to Slack!")
                                    else:
                                        st.error(f"Slack error: {resp.status_code} — {resp.text}")
                                except Exception as e:
                                    st.error(f"Failed: {e}")
                            else:
                                st.warning("⚙️ Add your Slack Webhook URL in the sidebar → Integrations")

                    with col_telegram:
                        if st.button(f"✈️ Send to Telegram", key=f"telegram_{idx}", use_container_width=True):
                            if telegram_bot_token and telegram_chat_id:
                                try:
                                    resp = http_requests.post(
                                        f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage",
                                        json={
                                            "chat_id": telegram_chat_id,
                                            "text": notif["message"]
                                        },
                                        timeout=10,
                                    )
                                    if resp.status_code == 200:
                                        st.success(f"✅ Sent to Telegram!")
                                    else:
                                        st.error(f"Telegram error: {resp.status_code} — {resp.text}")
                                except Exception as e:
                                    st.error(f"Failed: {e}")
                            else:
                                st.warning("⚙️ Add Telegram Bot Token and Chat ID in sidebar")

                    with col_email:
                        if notif["email"]:
                            _subject = quote(f"Schema Change Notice: {_notif_table}.{_notif_column}")
                            _body = quote(notif["message"])
                            _mailto = f"mailto:{notif['email']}?subject={_subject}&body={_body}"
                            st.markdown(
                                f'<a href="{_mailto}" target="_blank" style="'
                                f'display: inline-block; width: 100%; text-align: center;'
                                f'padding: 0.5rem 1rem; border-radius: 8px;'
                                f'background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);'
                                f'color: #e2e8f0; text-decoration: none; font-size: 0.9rem;'
                                f'transition: all 0.3s ease;'
                                f'">📧 Send Email</a>',
                                unsafe_allow_html=True,
                            )
                        else:
                            st.caption("No email on file")


    # --- Feature 4: Follow-up Chat ---
    if st.session_state.tool_log:
        st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 1rem 0;">', unsafe_allow_html=True)
        st.markdown("""
        <div style="
            background: rgba(30, 41, 59, 0.3);
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 10px;
            padding: 0.8rem 1.2rem;
            margin-bottom: 0.6rem;
        ">
            <span style="color: #94a3b8; font-size: 0.9rem;">💬 Have a follow-up question about this analysis? Ask below.</span>
        </div>
        """, unsafe_allow_html=True)

        # Show follow-up history
        for fu in st.session_state.followup_history:
            st.markdown(f"**You:** {fu['question']}")
            st.markdown(fu['answer'])
            st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.04); margin: 0.8rem 0;">', unsafe_allow_html=True)

        followup_q = st.text_input(
            "Follow-up question",
            placeholder='e.g., "Write a Jira ticket for this" or "Draft an email to the CFO"',
            key="followup_input",
            label_visibility="collapsed",
        )
        followup_send = st.button("💬 Ask Follow-up", key="followup_btn")

        if followup_send and followup_q.strip():
            with st.status("Atlas is thinking...", expanded=True) as fu_status:
                # Build conversation with full context: original analysis + all follow-ups
                fu_contents = list(st.session_state.analysis_contents)  # copy
                for fu in st.session_state.followup_history:
                    fu_contents.append(types.Content(role="user", parts=[types.Part(text=fu['question'])]))
                    fu_contents.append(types.Content(role="model", parts=[types.Part(text=fu['answer'])]))
                fu_contents.append(types.Content(role="user", parts=[types.Part(text=followup_q.strip())]))

                fu_answer, _ = run_agent(
                    contents=fu_contents,
                    tool_decls=ANALYSIS_TOOL_DECLS,
                    system_prompt=ANALYSIS_PROMPT,
                    status_container=fu_status,
                )
                fu_status.update(label="Done", state="complete")

            st.session_state.followup_history.append({
                "question": followup_q.strip(),
                "answer": fu_answer,
            })
            st.rerun()

    # Tool call trace and Approval gate only show if tools were actually used
    approved = False
    rejected = False
    if st.session_state.tool_log:
        with st.expander("🔧 View tool calls made during analysis"):
            for i, entry in enumerate(st.session_state.tool_log, 1):
                st.code(f"Step {i}: {entry['tool']}({json.dumps(entry['args'])})", language=None)

        # Approval gate
        st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 1.5rem 0;">', unsafe_allow_html=True)

        st.markdown("""
        <div style="
            background: rgba(99, 102, 241, 0.08);
            border: 1px solid rgba(99, 102, 241, 0.2);
            border-radius: 12px;
            padding: 1.2rem 1.5rem;
            margin-bottom: 1rem;
        ">
            <h3 style="color: #a78bfa; margin: 0 0 0.4rem 0; font-size: 1.2rem;">🛡️ Approval Gate</h3>
            <p style="color: #94a3b8; margin: 0; font-size: 0.9rem;">Review the analysis above carefully. Atlas will <strong style="color:#e2e8f0;">only execute</strong> after your explicit approval.</p>
        </div>
        """, unsafe_allow_html=True)

        col_approve, col_reject, col_spacer = st.columns([1, 1, 3])

        with col_approve:
            approved = st.button("✅ Approve Execution", type="primary", use_container_width=True)
        with col_reject:
            rejected = st.button("❌ Reject", use_container_width=True)

    if rejected:
        st.info("Execution cancelled. No changes were made.")
        st.session_state.analysis_report = None

    if approved:
        st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 1.5rem 0;">', unsafe_allow_html=True)

        st.markdown("""
        <div style="
            background: rgba(30, 41, 59, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 12px;
            padding: 1.2rem 1.5rem;
            margin-bottom: 1rem;
            backdrop-filter: blur(8px);
        ">
            <h3 style="color: #a78bfa; margin: 0; font-size: 1.2rem;">⚙️ Execution</h3>
        </div>
        """, unsafe_allow_html=True)

        with st.status("Executing approved plan...", expanded=True) as exec_status:
            # Demo cache: serve a pre-baked execution for rehearsed scenarios.
            # The cache invokes the real (offline) Fivetran mock tools, so the
            # change log below is genuine even with zero API quota.
            _cached_exec = check_execution_cache(st.session_state.user_request)
            if _cached_exec:
                exec_status.write("🟢 Demo mode — executing cached plan (no API quota used).")
                exec_result, exec_log = _cached_exec["result"], _cached_exec["tool_log"]
            else:
                exec_contents = [
                    types.Content(role="user", parts=[types.Part(text=(
                        f"Original request: {st.session_state.user_request}\n\n"
                        f"Analysis (approved by user):\n{st.session_state.analysis_report}\n\n"
                        f"User has APPROVED. Execute the deprecation now."
                    ))]),
                ]

                exec_result, exec_log = run_agent(
                    contents=exec_contents,
                    tool_decls=EXECUTION_TOOL_DECLS,
                    system_prompt=EXECUTION_PROMPT,
                    status_container=exec_status,
                )

            exec_status.update(label="Execution complete", state="complete")

        st.session_state.execution_done = True
        st.session_state.execution_result = exec_result
        st.session_state.tool_log.extend(exec_log)

        st.markdown(exec_result)

        # Change log
        st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 1.5rem 0;">', unsafe_allow_html=True)
        st.markdown("""
        <div style="
            background: rgba(30, 41, 59, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 12px;
            padding: 1.2rem 1.5rem;
            margin-bottom: 1rem;
            backdrop-filter: blur(8px);
        ">
            <h3 style="color: #a78bfa; margin: 0; font-size: 1.2rem;">📋 Change Log</h3>
        </div>
        """, unsafe_allow_html=True)
        changes = get_change_log()
        if changes:
            for entry in changes:
                st.markdown(f"""
                <div style="
                    background: rgba(34, 197, 94, 0.08);
                    border-left: 3px solid #22c55e;
                    border-radius: 0 8px 8px 0;
                    padding: 0.8rem 1rem;
                    margin-bottom: 0.6rem;
                ">
                    <strong style="color: #4ade80;">{entry['action']}</strong><br>
                    <span style="color: #94a3b8;">Target:</span> <code style="color: #e2e8f0;">{entry['target']}</code><br>
                    <span style="color: #94a3b8;">Change:</span> <span style="color: #e2e8f0;">{entry['change']}</span><br>
                    <span style="color: #94a3b8;">Time:</span> <span style="color: #64748b;">{entry['timestamp']}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No changes recorded.")


# ---------------------------------------------------------------------------
# Already executed state
# ---------------------------------------------------------------------------

if st.session_state.execution_done and st.session_state.execution_result:
    st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 1.5rem 0;">', unsafe_allow_html=True)

    # Report card header
    st.markdown("""
    <div style="
        background: rgba(30, 41, 59, 0.5);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 12px;
        padding: 1.5rem 2rem;
        margin-bottom: 1.5rem;
        backdrop-filter: blur(8px);
    ">
        <h2 style="
            font-size: 1.5rem;
            font-weight: 600;
            background: linear-gradient(135deg, #a78bfa 0%, #6366f1 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.3rem;
        ">📊 Impact Analysis Report</h2>
        <p style="color: #64748b; font-size: 0.85rem; margin: 0;">Generated by Atlas &bull; Gemini-powered reasoning</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown(st.session_state.analysis_report)

    st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 1.5rem 0;">', unsafe_allow_html=True)

    # Execution result card
    st.markdown("""
    <div style="
        background: rgba(34, 197, 94, 0.06);
        border: 1px solid rgba(34, 197, 94, 0.15);
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 1rem;
    ">
        <h3 style="color: #4ade80; margin: 0 0 0.3rem 0; font-size: 1.2rem;">✅ Execution Result</h3>
    </div>
    """, unsafe_allow_html=True)
    st.markdown(st.session_state.execution_result)

    st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 1.5rem 0;">', unsafe_allow_html=True)

    # Change log
    st.markdown("""
    <div style="
        background: rgba(30, 41, 59, 0.5);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 1rem;
        backdrop-filter: blur(8px);
    ">
        <h3 style="color: #a78bfa; margin: 0; font-size: 1.2rem;">📋 Change Log</h3>
    </div>
    """, unsafe_allow_html=True)
    changes = get_change_log()
    if changes:
        for entry in changes:
            st.markdown(f"""
            <div style="
                background: rgba(34, 197, 94, 0.08);
                border-left: 3px solid #22c55e;
                border-radius: 0 8px 8px 0;
                padding: 0.8rem 1rem;
                margin-bottom: 0.6rem;
            ">
                <strong style="color: #4ade80;">{entry['action']}</strong><br>
                <span style="color: #94a3b8;">Target:</span> <code style="color: #e2e8f0;">{entry['target']}</code><br>
                <span style="color: #94a3b8;">Change:</span> <span style="color: #e2e8f0;">{entry['change']}</span><br>
                <span style="color: #94a3b8;">Time:</span> <span style="color: #64748b;">{entry['timestamp']}</span>
            </div>
            """, unsafe_allow_html=True)

    with st.expander("🔧 Full tool call trace"):
        for i, entry in enumerate(st.session_state.tool_log, 1):
            st.code(f"Step {i}: {entry['tool']}({json.dumps(entry['args'])})", language=None)

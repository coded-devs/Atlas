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
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv

from lineage import summarize_impact, load_default, load_graph
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
You are Atlas, a data change intelligence agent.

Analyze the proposed schema change. Follow these steps:
1. Call list_connections to find the relevant connector.
2. Call get_connection_schema_config to confirm the column exists.
   -> IF the column or table does not exist in Fivetran, STOP and tell the user it cannot be found. Do not generate the rest of the report.
3. Call get_connection_details to check connector health.
4. Call summarize_impact to discover downstream dependencies.
   -> IF the column or table has no lineage data, state that there are zero known downstream dependencies.

Then produce a report with these sections (only if the column exists):
## Connection Info
One line: connector name, service, status, last sync.

## Column Status
Confirm the column exists and is synced.

## Impact Summary
One paragraph: what breaks, how many assets, highest criticality.

## Affected Assets
Bullet list: **name** (type) - owned by lead, team, tier (if none, state "No downstream dependencies").

## Recommended Deprecation Plan
Numbered steps with day offsets (if no dependencies, recommend an immediate drop).

## Stakeholder Messages
For each team, a Slack message (3-5 sentences). Technical for engineers, business for execs. (Skip if no dependencies).

Be direct. No fluff.
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
col_input, col_status = st.columns([3, 1])

with col_input:
    request = st.text_area(
        "What change do you want to make?",
        placeholder="e.g., I want to drop the customer_segment column from stripe.customers",
        height=80,
    )

with col_status:
    st.markdown("&nbsp;")  # spacing
    st.markdown("&nbsp;")
    analyze_clicked = st.button("Analyze Impact", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Phase 1: Analysis
# ---------------------------------------------------------------------------

if analyze_clicked and request.strip():
    st.session_state.analysis_report = None
    st.session_state.execution_done = False
    st.session_state.execution_result = None
    st.session_state.tool_log = []
    st.session_state.user_request = request.strip()

    st.divider()

    with st.status("Atlas is analyzing your change...", expanded=True) as status:
        contents = [
            types.Content(role="user", parts=[types.Part(text=request.strip())])
        ]

        report, tool_log = run_agent(
            contents=contents,
            tool_decls=ANALYSIS_TOOL_DECLS,
            system_prompt=ANALYSIS_PROMPT,
            status_container=status,
        )

        status.update(label="Analysis complete", state="complete")

    st.session_state.analysis_report = report
    st.session_state.analysis_contents = contents
    st.session_state.tool_log = tool_log


# ---------------------------------------------------------------------------
# Display analysis report
# ---------------------------------------------------------------------------

if st.session_state.analysis_report and not st.session_state.execution_done:
    st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 1.5rem 0;">', unsafe_allow_html=True)

    # Report card
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

    # Tool call trace
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

"""
pages/2_Audit_Dashboard.py — Audit dashboard for Atlas.

Shows every action Atlas has taken this session (from the Fivetran mock change
log): deprecations, renames, table disables, rollbacks, and verification syncs.
Includes summary metrics, action/connector filters, and a demo-reset button.

The change log is in-memory and shared across pages within one Streamlit server
run, so changes made on the Atlas Agent page appear here immediately.
"""

import sys
from pathlib import Path

import streamlit as st

# Make repo-root modules importable when Streamlit runs this file from pages/.
sys.path.append(str(Path(__file__).resolve().parent.parent))

from fivetran_tools import get_change_log, clear_change_log
from connector_health import humanize_timestamp

st.set_page_config(page_title="Atlas — Audit Dashboard", page_icon="📋", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap');
html, body, [class*="css"] { font-family: 'Outfit', sans-serif !important; }
.stApp { background-color: #0b0f19 !important; color: #e2e8f0 !important; }
</style>
""", unsafe_allow_html=True)

# Friendly labels + emoji for each action type.
ACTION_LABELS = {
    "modify_connection_column_config": "🟥 Column deprecated",
    "rename_column_config": "🟧 Column renamed",
    "disable_table_sync": "⬛ Table disabled",
    "rollback_column_config": "↩️ Rollback",
    "sync_connection": "🔄 Verification sync",
}

st.title("📋 Audit Dashboard")
st.caption("Every action Atlas has taken in this session.")

log = get_change_log()

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------

total_actions = len(log)
columns_deprecated = sum(1 for e in log if e.get("action") == "modify_connection_column_config")
tables_disabled = sum(1 for e in log if e.get("action") == "disable_table_sync")
renames = sum(1 for e in log if e.get("action") == "rename_column_config")
rollbacks = sum(1 for e in log if e.get("action") == "rollback_column_config")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Actions", total_actions)
m2.metric("Columns Deprecated", columns_deprecated)
m3.metric("Tables Disabled", tables_disabled)
m4.metric("Rollbacks", rollbacks)

st.divider()

if not log:
    st.info("No actions yet. Use **Atlas Agent** to make changes, then return here to see them logged.")
    st.page_link("pages/1_Atlas_Agent.py", label="Go to Atlas Agent", icon="🤖")
    st.stop()

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Filters")
    all_actions = sorted({e.get("action", "") for e in log})
    all_connectors = sorted({e.get("connection_id", "") for e in log})

    sel_actions = st.multiselect(
        "Action type",
        options=all_actions,
        default=all_actions,
        format_func=lambda a: ACTION_LABELS.get(a, a),
    )
    sel_connectors = st.multiselect(
        "Connector",
        options=all_connectors,
        default=all_connectors,
    )

    st.divider()
    if st.button("🗑️ Clear log (demo reset)", use_container_width=True):
        clear_change_log()
        st.rerun()

filtered = [
    e for e in log
    if e.get("action") in sel_actions and e.get("connection_id") in sel_connectors
]

# ---------------------------------------------------------------------------
# Action table (newest first)
# ---------------------------------------------------------------------------

st.subheader(f"Actions ({len(filtered)})")

if not filtered:
    st.warning("No actions match the current filters.")
    st.stop()

rows_html = [
    '<table style="width:100%; border-collapse:collapse; font-size:0.88rem;">',
    '<thead><tr>'
    + "".join(
        f'<th style="text-align:left; padding:8px 12px; color:#94a3b8; '
        f'border-bottom:1px solid rgba(255,255,255,0.12);">{h}</th>'
        for h in ["Timestamp", "Action", "Connector", "Target", "Change"]
    )
    + "</tr></thead><tbody>",
]

for e in reversed(filtered):
    label = ACTION_LABELS.get(e.get("action", ""), e.get("action", ""))
    ts = humanize_timestamp(e.get("timestamp", ""))
    cells = [
        ts,
        label,
        f'<code>{e.get("connection_id", "")}</code>',
        f'<code>{e.get("target", "")}</code>',
        e.get("change", ""),
    ]
    rows_html.append(
        '<tr>'
        + "".join(
            f'<td style="padding:7px 12px; color:#e2e8f0; '
            f'border-bottom:1px solid rgba(255,255,255,0.05);">{c}</td>'
            for c in cells
        )
        + "</tr>"
    )

rows_html.append("</tbody></table>")
st.markdown("".join(rows_html), unsafe_allow_html=True)

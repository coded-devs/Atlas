"""
app.py — Atlas landing / entry page (multi-page app).

This is the Streamlit entrypoint. The actual agent, audit dashboard, and
connector health views live in pages/. This page is a lightweight hub:
a short intro, navigation links to the three pages, and quick stats.

Run: streamlit run app.py
"""

import streamlit as st

from fivetran_tools import get_change_log
from connector_health import gather_connectors

st.set_page_config(
    page_title="Atlas - Data Change Intelligence",
    page_icon="🔍",
    layout="wide",
)

# Shared dark theme (kept in sync with the agent page for visual continuity).
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap');
html, body, [class*="css"] { font-family: 'Outfit', sans-serif !important; }
.stApp { background-color: #0b0f19 !important; color: #e2e8f0 !important; }
[data-testid="stSidebar"] {
    background: rgba(15, 23, 42, 0.4) !important;
    backdrop-filter: blur(12px) !important;
    border-right: 1px solid rgba(255,255,255,0.05);
}
[data-testid="stPageLink"] {
    background: rgba(30, 41, 59, 0.5) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 12px !important;
    padding: 0.4rem 0.6rem !important;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

st.markdown("""
<div style="padding: 2.5rem 0 1rem 0; text-align: left;">
    <h1 style="
        font-size: 3.2rem; font-weight: 600;
        background: linear-gradient(135deg, #a78bfa 0%, #818cf8 40%, #6366f1 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 0.3rem; letter-spacing: -0.02em;
    ">Atlas</h1>
    <p style="color: #94a3b8; font-size: 1.1rem; margin: 0; letter-spacing: 0.02em;">
        Data Change Intelligence Agent &mdash; Powered by
        <strong style="color:#a78bfa;">Gemini</strong> +
        <strong style="color:#818cf8;">Fivetran MCP</strong>
    </p>
</div>
<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 0.5rem 0 1.5rem 0;">
""", unsafe_allow_html=True)

st.markdown("""
Atlas helps data teams **safely deprecate, rename, or disable data columns and tables**
by analyzing downstream impact *before* a change is made — then drafting stakeholder
notifications, enforcing an approval gate, and logging every action.

Use the navigation below (or the sidebar) to get started.
""")


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

st.markdown("### Where do you want to go?")

nav1, nav2, nav3 = st.columns(3)

with nav1:
    st.markdown("#### 🤖 Atlas Agent")
    st.caption("Describe a schema change in plain English. Atlas analyzes impact, "
               "ranks severity, and executes on approval.")
    st.page_link("pages/1_Atlas_Agent.py", label="Open Atlas Agent", icon="🤖")

with nav2:
    st.markdown("#### 📋 Audit Dashboard")
    st.caption("Every action Atlas has taken this session — deprecations, renames, "
               "table disables, and rollbacks — with filters.")
    st.page_link("pages/2_Audit_Dashboard.py", label="Open Audit Dashboard", icon="📋")

with nav3:
    st.markdown("#### 🔌 Connector Health")
    st.caption("Live status of every Fivetran connector: sync state, last sync time, "
               "and tables synced.")
    st.page_link("pages/3_Connector_Health.py", label="Open Connector Health", icon="🔌")


# ---------------------------------------------------------------------------
# Quick stats
# ---------------------------------------------------------------------------

st.markdown('<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 2rem 0 1rem 0;">', unsafe_allow_html=True)

_log = get_change_log()
_exec_actions = {"modify_connection_column_config", "rename_column_config", "disable_table_sync"}
_changes = sum(1 for e in _log if e.get("action") in _exec_actions)
_rollbacks = sum(1 for e in _log if e.get("action") == "rollback_column_config")
_connectors = len(gather_connectors())

st.markdown("### Today at a glance")
s1, s2, s3 = st.columns(3)
s1.metric("Changes executed", _changes)
s2.metric("Rollbacks", _rollbacks)
s3.metric("Connectors monitored", _connectors)

st.caption(
    f"Today: **{_changes}** change(s) executed, **{_rollbacks}** rollback(s), "
    f"**{_connectors}** connector(s) monitored."
)

st.markdown("""
<div style="text-align: center; padding: 2rem 0 0.5rem 0;">
    <span style="color: #475569; font-size: 0.75rem;">Built for the</span><br>
    <span style="
        font-size: 0.85rem; font-weight: 600;
        background: linear-gradient(135deg, #a78bfa, #38bdf8);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    ">Google Cloud Rapid Agent Hackathon 2026</span>
</div>
""", unsafe_allow_html=True)

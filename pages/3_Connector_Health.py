"""
pages/3_Connector_Health.py — Connector health view for Atlas.

Shows every Fivetran connector as a status card: service icon, health dot,
humanized last-sync time, tables synced, and sync frequency. Includes a manual
Refresh button and an optional 30-second auto-refresh.
"""

import sys
from pathlib import Path

import streamlit as st

# Make repo-root modules importable when Streamlit runs this file from pages/.
sys.path.append(str(Path(__file__).resolve().parent.parent))

from connector_health import gather_connectors, health_totals

st.set_page_config(page_title="Atlas — Connector Health", page_icon="🔌", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap');
html, body, [class*="css"] { font-family: 'Outfit', sans-serif !important; }
.stApp { background-color: #0b0f19 !important; color: #e2e8f0 !important; }
</style>
""", unsafe_allow_html=True)

top_left, top_right = st.columns([4, 1])
with top_left:
    st.title("🔌 Connector Health")
    st.caption("Live status of every Fivetran connector in the account.")
with top_right:
    st.markdown("&nbsp;")
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

# Optional auto-refresh. A meta-refresh tag re-runs the whole page every 30s
# without blocking the script (Streamlit has no built-in non-blocking timer and
# we add no new dependencies). Off by default so it never disrupts a demo.
auto = st.toggle("Auto-refresh every 30s", value=False)
if auto:
    st.markdown('<meta http-equiv="refresh" content="30">', unsafe_allow_html=True)

connectors = gather_connectors()
totals = health_totals(connectors)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Connectors", totals["total"])
m2.metric("Healthy", totals["healthy"])
m3.metric("Warnings", totals["warning"])
m4.metric("Errors", totals["error"])

st.divider()

if not connectors:
    st.info("No connectors found.")
    st.stop()

# Two cards per row.
for i in range(0, len(connectors), 2):
    cols = st.columns(2)
    for col, conn in zip(cols, connectors[i:i + 2]):
        with col:
            with st.container(border=True):
                freq = conn.get("sync_frequency")
                freq_str = f"every {freq} min" if freq else "—"
                st.markdown(f"""
                <div style="display:flex; align-items:center; gap:0.6rem; margin-bottom:0.4rem;">
                    <span style="font-size:1.8rem;">{conn['icon']}</span>
                    <span style="font-size:1.2rem; font-weight:600; color:#e2e8f0; text-transform:capitalize;">
                        {conn['service']}
                    </span>
                    <span style="margin-left:auto; font-size:0.95rem;">
                        {conn['dot']} <span style="color:{conn['color']}; font-weight:600; text-transform:capitalize;">{conn['level']}</span>
                    </span>
                </div>
                <div style="color:#94a3b8; font-size:0.85rem; line-height:1.8;">
                    <code style="color:#cbd5e1;">{conn['id']}</code><br>
                    🕒 Last sync: <strong style="color:#e2e8f0;">{conn['succeeded_human']}</strong><br>
                    🗂️ Tables synced: <strong style="color:#e2e8f0;">{conn['tables_count']}</strong><br>
                    ⏱️ Sync frequency: <strong style="color:#e2e8f0;">{freq_str}</strong>
                </div>
                """, unsafe_allow_html=True)

st.caption("Connector data is served by the simulated Fivetran MCP tools (offline, no API quota).")

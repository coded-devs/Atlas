"""
connector_health.py — Pure helpers for connector health views.

Shared by the inline health check on the Atlas Agent page and the dedicated
Connector Health page. Contains NO Streamlit rendering — just data gathering
and formatting, so it stays testable and reusable.

Health data comes from the simulated Fivetran MCP tools in fivetran_tools.py.
"""

from datetime import datetime, timezone

from fivetran_tools import (
    list_connections,
    get_connection_details,
    get_connection_schema_config,
)

# Service → emoji icon for the health cards.
SERVICE_ICONS = {
    "stripe": "💳",
    "hubspot": "🎯",
    "salesforce": "☁️",
    "zendesk": "🎫",
}
DEFAULT_ICON = "🔌"


def humanize_timestamp(iso_str: str) -> str:
    """Turn an ISO timestamp into a relative string like '12 minutes ago'.

    Defensive about the fixture's quirk of appending 'Z' even when isoformat()
    already produced a '+00:00' offset.
    """
    if not iso_str:
        return "never"
    s = iso_str.strip()
    if s.endswith("+00:00Z"):
        s = s[:-1]
    elif s.endswith("Z") and "+" not in s:
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return iso_str
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    secs = int((datetime.now(tz=timezone.utc) - dt).total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs} second{'s' if secs != 1 else ''} ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs} hour{'s' if hrs != 1 else ''} ago"
    days = hrs // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def status_level(status: dict) -> str:
    """Classify a connection's status as 'healthy', 'warning', or 'error'."""
    if not isinstance(status, dict):
        return "warning"
    if status.get("failed_at"):
        return "error"
    if status.get("warnings"):
        return "warning"
    if status.get("setup_state") != "connected":
        return "warning"
    if status.get("update_state") not in (None, "on_schedule", "delayed", "rescheduled"):
        # unknown update states are surfaced as a warning, not silently healthy
        pass
    return "healthy"


# Color + dot for each health level (used by both views).
LEVEL_COLORS = {
    "healthy": ("#22c55e", "🟢"),
    "warning": ("#eab308", "🟡"),
    "error":   ("#ef4444", "🔴"),
}


def _count_tables(connection_id: str) -> int:
    """How many tables a connection currently syncs (across all schemas)."""
    cfg = get_connection_schema_config(connection_id)
    if cfg.get("code") != "Success":
        return 0
    total = 0
    for schema in cfg["data"].get("schemas", {}).values():
        total += len(schema.get("tables", {}))
    return total


def gather_connectors() -> list:
    """Return a list of connector health summaries.

    Each entry: {id, service, icon, level, dot, color, status, sync_frequency,
                 succeeded_at, succeeded_human, failed_at, tables_count}.
    """
    out = []
    listing = list_connections()
    items = listing.get("data", {}).get("items", []) if listing.get("code") == "Success" else []

    for item in items:
        conn_id = item["id"]
        details = get_connection_details(conn_id)
        status = details["data"]["status"] if details.get("code") == "Success" else {}
        level = status_level(status)
        color, dot = LEVEL_COLORS[level]
        service = item.get("service", "unknown")
        succeeded_at = status.get("succeeded_at") or item.get("succeeded_at")

        out.append({
            "id": conn_id,
            "service": service,
            "icon": SERVICE_ICONS.get(service, DEFAULT_ICON),
            "level": level,
            "dot": dot,
            "color": color,
            "status": status,
            "sync_frequency": item.get("sync_frequency"),
            "succeeded_at": succeeded_at,
            "succeeded_human": humanize_timestamp(succeeded_at),
            "failed_at": status.get("failed_at"),
            "tables_count": _count_tables(conn_id),
        })
    return out


def health_totals(connectors: list) -> dict:
    """Aggregate counts for the metric cards."""
    return {
        "total": len(connectors),
        "healthy": sum(1 for c in connectors if c["level"] == "healthy"),
        "warning": sum(1 for c in connectors if c["level"] == "warning"),
        "error": sum(1 for c in connectors if c["level"] == "error"),
    }


# Quick self-test — run `python connector_health.py`.
if __name__ == "__main__":
    conns = gather_connectors()
    print(f"=== connector_health.py self-test ===\n{len(conns)} connectors\n")
    for c in conns:
        print(f"{c['dot']} {c['icon']} {c['service']:12} {c['id']:22} "
              f"{c['level']:8} tables={c['tables_count']} last_sync={c['succeeded_human']}")
    print("\nTotals:", health_totals(conns))

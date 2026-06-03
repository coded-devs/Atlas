"""
lineage.py — The mock lineage layer for Atlas.

Atlas treats these functions as tools (just like Fivetran MCP tools).
They answer "what depends on this column?" and "who owns it?" — the gap
Fivetran cannot fill on its own.

In production, these queries would hit Looker, Tableau, dbt, Hex, etc.
For the hackathon demo, they read from a curated JSON file.
"""

import json
from pathlib import Path

# The active lineage graph. Functions below always read from this module-level
# global, so swapping it at runtime (load_graph / load_default) instantly
# changes what every query sees — no need to touch the functions themselves.
_LINEAGE_PATH = Path(__file__).parent / "lineage.json"
_GRAPH = {}


def load_graph(data: dict) -> dict:
    """
    Replace the active lineage graph at runtime.

    Args:
        data: a lineage dict in the same shape as lineage.json
              (top-level "tables", "owners", "criticality_levels" keys).

    Returns:
        The graph that is now active.
    """
    global _GRAPH
    _GRAPH = data
    return _GRAPH


def load_default() -> dict:
    """Load the bundled lineage.json and make it the active graph."""
    with open(_LINEAGE_PATH) as f:
        return load_graph(json.load(f))


# Load the default graph once at import time so the demo works out of the box.
load_default()


def find_downstream(table: str, column: str) -> dict:
    """
    Return everything that depends on a given column.

    Args:
        table: fully-qualified table name like "stripe.customers"
        column: column name like "customer_segment"

    Returns:
        A dict with the column's metadata + a list of downstream assets.
        Returns an empty result if the column or table is unknown.
    """
    table_info = _GRAPH["tables"].get(table)
    if not table_info:
        return {
            "found": False,
            "reason": f"Table '{table}' not in lineage graph",
            "downstream": []
        }

    column_info = table_info["columns"].get(column)
    if not column_info:
        return {
            "found": False,
            "reason": f"Column '{column}' not found in '{table}'",
            "downstream": []
        }

    return {
        "found": True,
        "table": table,
        "column": column,
        "description": column_info["description"],
        "is_pii": column_info["is_pii"],
        "table_criticality": table_info["criticality"],
        "downstream": column_info["downstream"],
        "downstream_count": len(column_info["downstream"])
    }


def get_owner(team_name: str) -> dict:
    """Return contact details for a team."""
    owner = _GRAPH["owners"].get(team_name)
    if not owner:
        return {"found": False, "team": team_name}
    return {"found": True, "team": team_name, **owner}


def get_deprecation_policy(criticality: str) -> dict:
    """Return the deprecation policy for a given criticality tier."""
    policy = _GRAPH["criticality_levels"].get(criticality)
    if not policy:
        return {"found": False, "criticality": criticality}
    return {"found": True, "criticality": criticality, **policy}


def summarize_impact(table: str, column: str) -> dict:
    """
    Higher-level helper: combines lineage + ownership + policy
    into one structured impact report. Atlas will call this when
    a user proposes a change.
    """
    downstream = find_downstream(table, column)
    if not downstream["found"]:
        return downstream

    # Enrich each downstream asset with full owner contact info
    enriched = []
    for asset in downstream["downstream"]:
        owner_info = get_owner(asset["owner"])
        enriched.append({**asset, "owner_contact": owner_info})

    # Pick the strictest criticality of any downstream asset
    tiers = [a["criticality"] for a in downstream["downstream"]] or ["tier_3"]
    tier_priority = {"tier_1": 1, "tier_2": 2, "tier_3": 3}
    strictest = min(tiers, key=lambda t: tier_priority.get(t, 99))

    policy = get_deprecation_policy(strictest)

    return {
        "table": table,
        "column": column,
        "description": downstream["description"],
        "is_pii": downstream["is_pii"],
        "downstream_assets": enriched,
        "downstream_count": downstream["downstream_count"],
        "highest_criticality": strictest,
        "recommended_deprecation_days": policy.get("deprecation_notice_days", 7),
        "policy_note": policy.get("description", "")
    }


# Quick self-test — run `python lineage.py` to verify the file works
if __name__ == "__main__":
    print("=== Testing lineage.py ===\n")

    print("1. Find downstream for stripe.customers.customer_segment:")
    result = find_downstream("stripe.customers", "customer_segment")
    print(json.dumps(result, indent=2))

    print("\n2. Get owner for sales-leadership team:")
    print(json.dumps(get_owner("sales-leadership"), indent=2))

    print("\n3. Full impact summary for dropping customer_segment:")
    summary = summarize_impact("stripe.customers", "customer_segment")
    print(json.dumps(summary, indent=2))

    print("\n4. Testing unknown column (should fail gracefully):")
    print(json.dumps(find_downstream("stripe.customers", "fake_column"), indent=2))

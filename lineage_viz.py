"""
lineage_viz.py — Build a Graphviz DOT graph of a column's downstream lineage.

Atlas renders this in the Streamlit UI (via st.graphviz_chart) so a user can
*see* the blast radius of a proposed schema change, not just read it. The flow
is left-to-right:

    Fivetran Connector -> schema.table -> target column -> downstream assets -> owners

The DOT string is rendered client-side by Streamlit (viz.js), so no system
Graphviz binary is required — it works on Streamlit Community Cloud as-is.

build_lineage_graph(table, column) returns the DOT string, or None if the
column does not exist in the lineage graph.
"""

import re

from lineage import find_downstream, get_owner
from fivetran_tools import _find_connection_by_table


# Fill colour + node shape per downstream asset type.
_TYPE_STYLES = {
    "dbt_model":        ("rectangle", "#4CAF50"),  # green
    "dashboard":        ("rectangle", "#FF9800"),  # orange
    "ml_feature":       ("rectangle", "#9C27B0"),  # purple
    "scheduled_report": ("rectangle", "#F44336"),  # red
}
_TYPE_FALLBACK = ("rectangle", "#607D8B")  # blue-gray for any unknown type


def _esc(value) -> str:
    """Escape a value for safe inclusion inside a DOT double-quoted label."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _safe_id(value: str) -> str:
    """Turn an arbitrary string (e.g. a team slug) into a valid DOT node id."""
    return re.sub(r"[^0-9a-zA-Z_]", "_", str(value))


def _tier_label(criticality: str) -> str:
    """'tier_2' -> '2' so labels read 'Tier 2' rather than 'Tier tier_2'."""
    return str(criticality).replace("tier_", "")


def build_lineage_graph(table: str, column: str):
    """Return a Graphviz DOT string visualising the downstream impact of
    changing ``table.column``.

    Args:
        table:  fully-qualified table name, e.g. "stripe.customers".
        column: column name, e.g. "customer_segment".

    Returns:
        A DOT string, or None if the column is not found in the lineage graph.
    """
    info = find_downstream(table, column)
    if not info.get("found"):
        return None

    # Resolve the Fivetran connector that lands this schema, for the L1 node.
    schema_name = table.split(".")[0]
    conn = _find_connection_by_table(schema_name)
    service = conn["service"] if conn else schema_name

    lines = [
        "digraph lineage {",
        "    rankdir=LR;",
        '    fontname="Helvetica";',
        '    bgcolor="transparent";',
        '    node [style=filled, fontname="Helvetica", fontcolor="white"];',
        '    edge [color="#666666"];',
        "",
        # Level 1 — Fivetran connector
        f'    connector [shape=box3d, fillcolor="#2196F3", color="#2196F3", '
        f'label="{_esc(service)} Connector"];',
        # Level 2 — table
        f'    tbl [shape=rectangle, fillcolor="#37474F", color="#37474F", '
        f'label="{_esc(table)}"];',
        # Level 3 — target column being changed
        f'    col [shape=octagon, fillcolor="#F44336", color="#F44336", '
        f'label="{_esc(column)} [DEPRECATING]"];',
        "",
        "    connector -> tbl;",
        "    tbl -> col;",
    ]

    downstream = info.get("downstream", [])

    if not downstream:
        # Zero downstream — single reassuring green node.
        lines.append(
            '    safe [shape=circle, fillcolor="#4CAF50", color="#4CAF50", '
            'label="No dependencies — Safe to drop"];'
        )
        lines.append("    col -> safe;")
    else:
        owners_seen = set()
        for i, asset in enumerate(downstream):
            a_type = asset.get("type", "asset")
            shape, fillcolor = _TYPE_STYLES.get(a_type, _TYPE_FALLBACK)
            name = asset.get("name", "asset")
            tier = _tier_label(asset.get("criticality", "tier_3"))

            asset_id = f"asset_{i}"
            label = f"{_esc(name)}\\n({_esc(a_type)})\\nTier {tier}"
            lines.append(
                f'    {asset_id} [shape={shape}, fillcolor="{fillcolor}", '
                f'color="{fillcolor}", label="{label}"];'
            )
            lines.append(f"    col -> {asset_id};")

            # Level 5 — owner node (deduped so shared owners merge).
            team = asset.get("owner", "")
            if team:
                owner_id = f"owner_{_safe_id(team)}"
                if team not in owners_seen:
                    owners_seen.add(team)
                    owner_info = get_owner(team)
                    lead = owner_info.get("lead", "") if owner_info.get("found") else ""
                    owner_label = f"{_esc(team)}\\n{_esc(lead)}"
                    lines.append(
                        f'    {owner_id} [shape=ellipse, fillcolor="#78909C", '
                        f'color="#78909C", label="{owner_label}"];'
                    )
                lines.append(f"    {asset_id} -> {owner_id};")

    lines.append("}")
    return "\n".join(lines)


# Quick self-test — run `python lineage_viz.py` to verify DOT generation.
if __name__ == "__main__":
    print("=== lineage_viz.py self-test ===\n")

    print("1. customer_segment (full graph, 5 downstream):")
    dot = build_lineage_graph("stripe.customers", "customer_segment")
    print(dot)

    print("\n2. lead_source_legacy (zero downstream — safe to drop):")
    print(build_lineage_graph("hubspot.deals", "lead_source_legacy"))

    print("\n3. discount_code (column not found -> None):")
    print(build_lineage_graph("stripe.customers", "discount_code"))

"""
schema_diff.py — Before/after schema preview for a proposed change.

Given a target table/column and an operation (drop, rename, or disable_table),
produces two parallel column lists — "before" and "after" — that the UI renders
side by side so the user can see exactly what the change does before approving.

Pure functions only (no Streamlit): build_schema_diff() returns the data, and
render_diff_table_html() turns a side into a styled HTML table string that the
app drops into st.markdown.
"""

from lineage import get_table_columns

# Per-cell background colors keyed by (side, highlight, operation).
_GREEN = "#1B5E20"   # target column, "before" side
_RED = "#B71C1C"     # dropped column, "after" side
_ORANGE = "#F57C00"  # renamed column, "after" side


def _columns_for_table(scan_result, table: str) -> list:
    """Return [(name, type), ...] for a table.

    Prefers the live database scan (which carries real types). Falls back to
    the active lineage graph's column list (types unknown) when no scan is
    available — e.g. the user is on demo lineage.
    """
    if scan_result and not scan_result.get("error"):
        info = scan_result.get("tables", {}).get(table)
        if info:
            return [(c.get("name", ""), (c.get("type") or "")) for c in info.get("columns", [])]
    return [(name, "") for name in get_table_columns(table)]


def build_schema_diff(scan_result, table: str, column: str, operation: str, new_name: str = None):
    """Build the before/after column lists for a proposed change.

    Args:
        scan_result: a db_scanner scan dict, or None to fall back to lineage.
        table: the target table.
        column: the target column (ignored for disable_table).
        operation: "drop", "rename", or "disable_table".
        new_name: the new column name (rename only).

    Returns:
        (before, after) — each a list of {"name", "type", "highlight"} dicts,
        where highlight is "none", "target", or "changed".
    """
    op = (operation or "drop").lower()
    cols = _columns_for_table(scan_result, table)

    before, after = [], []
    for name, typ in cols:
        if op == "disable_table":
            # Whole table goes away: every column is the target before, changed after.
            before.append({"name": name, "type": typ, "highlight": "target"})
            after.append({"name": name, "type": typ, "highlight": "changed"})
            continue

        is_target = (name == column)
        if not is_target:
            before.append({"name": name, "type": typ, "highlight": "none"})
            after.append({"name": name, "type": typ, "highlight": "none"})
            continue

        before.append({"name": name, "type": typ, "highlight": "target"})
        if op == "rename":
            after.append({"name": new_name or f"{name}_new", "type": typ, "highlight": "changed"})
        else:  # drop / deprecate
            after.append({"name": name, "type": typ, "highlight": "changed"})

    return before, after


def _row_style(side: str, highlight: str, operation: str) -> str:
    """Inline CSS for one row, based on side + highlight + operation."""
    op = (operation or "drop").lower()
    if highlight == "target":
        # Green on the "before" side; on the "after" side a target only appears
        # for disable_table (handled as 'changed'), so green is before-only.
        return f"background:{_GREEN}; color:#e8f5e9;"
    if highlight == "changed":
        if op == "rename":
            return f"background:{_ORANGE}; color:#fff3e0;"
        if op == "disable_table":
            return "background:rgba(100,116,139,0.18); color:#64748b; text-decoration:line-through;"
        # drop / deprecate
        return f"background:{_RED}; color:#ffebee; text-decoration:line-through;"
    return "color:#cbd5e1;"


def render_diff_table_html(rows: list, side: str, operation: str) -> str:
    """Render one side (before/after) of the diff as an HTML table string."""
    header_label = "Before" if side == "before" else "After"
    out = [
        '<table style="width:100%; border-collapse:collapse; font-size:0.85rem; '
        'font-family:monospace;">',
        f'<thead><tr>'
        f'<th style="text-align:left; padding:6px 10px; color:#94a3b8; '
        f'border-bottom:1px solid rgba(255,255,255,0.1);">{header_label} — column</th>'
        f'<th style="text-align:left; padding:6px 10px; color:#94a3b8; '
        f'border-bottom:1px solid rgba(255,255,255,0.1);">type</th>'
        f'</tr></thead><tbody>',
    ]
    for r in rows:
        style = _row_style(side, r.get("highlight", "none"), operation)
        typ = r.get("type") or "—"
        out.append(
            f'<tr style="{style}">'
            f'<td style="padding:5px 10px; border-bottom:1px solid rgba(255,255,255,0.05);">{r["name"]}</td>'
            f'<td style="padding:5px 10px; border-bottom:1px solid rgba(255,255,255,0.05);">{typ}</td>'
            f'</tr>'
        )
    out.append("</tbody></table>")
    return "".join(out)


# Quick self-test — run `python schema_diff.py`.
if __name__ == "__main__":
    import lineage
    lineage.load_default()

    print("=== schema_diff.py self-test ===\n")
    for op, col, new in [
        ("drop", "customer_segment", None),
        ("rename", "customer_segment", "segment_label"),
        ("disable_table", None, None),
    ]:
        before, after = build_schema_diff(None, "stripe.customers", col, op, new)
        print(f"{op}: before={[ (r['name'], r['highlight']) for r in before ]}")
        print(f"{op}: after ={[ (r['name'], r['highlight']) for r in after ]}\n")

    # Render check
    b, a = build_schema_diff(None, "stripe.customers", "customer_segment", "rename", "segment_label")
    html = render_diff_table_html(a, "after", "rename")
    print("rename after-table contains new name + orange:",
          "segment_label" in html and _ORANGE in html)

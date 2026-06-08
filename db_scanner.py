"""
db_scanner.py — Database Auto-Discovery Scanner for Atlas.

Instead of uploading a hand-written JSON/CSV lineage file, a user can upload a
real SQLite database and Atlas discovers its schema automatically: every table,
its columns (name, type, nullability, primary keys), and the foreign-key
relationships that wire the tables together.

This module is pure discovery + display. It does NOT build a lineage graph —
that inference step (Gemini-powered) comes later. Uses only the stdlib `sqlite3`
module, so it adds no new pip dependency.
"""

import os
import sqlite3
import tempfile


def scan_sqlite(file_bytes: bytes) -> dict:
    """
    Scan an uploaded SQLite database and return its discovered schema.

    Args:
        file_bytes: the raw bytes of a .db / .sqlite file.

    Returns:
        A dict shaped like:
        {
          "tables": {
            "table_name": {
              "columns": [
                {"name": "id", "type": "INTEGER", "notnull": True, "primary_key": True},
                ...
              ],
              "foreign_keys": [
                {"from_column": "customer_id", "to_table": "customers", "to_column": "id"},
                ...
              ]
            }
          },
          "table_count": int,
          "column_count": int,
          "fk_count": int
        }
        On failure, returns {"error": "..."}.
    """
    # sqlite3 needs a real file on disk, so write the uploaded bytes to a temp
    # file, open it read-only, then clean up.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # All user tables (skip SQLite's internal sqlite_* bookkeeping tables).
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        table_names = [row["name"] for row in cursor.fetchall()]

        tables = {}
        column_count = 0
        fk_count = 0

        for table in table_names:
            # PRAGMA doesn't accept bound parameters for the table name, but
            # these names come straight from sqlite_master so they're trusted.
            cursor.execute(f'PRAGMA table_info("{table}")')
            columns = []
            for col in cursor.fetchall():
                columns.append({
                    "name": col["name"],
                    "type": (col["type"] or "").upper(),
                    "notnull": bool(col["notnull"]),
                    "primary_key": bool(col["pk"]),
                })
            column_count += len(columns)

            cursor.execute(f'PRAGMA foreign_key_list("{table}")')
            foreign_keys = []
            for fk in cursor.fetchall():
                foreign_keys.append({
                    "from_column": fk["from"],
                    "to_table": fk["table"],
                    "to_column": fk["to"],
                })
            fk_count += len(foreign_keys)

            tables[table] = {
                "columns": columns,
                "foreign_keys": foreign_keys,
            }

        conn.close()

        return {
            "tables": tables,
            "table_count": len(tables),
            "column_count": column_count,
            "fk_count": fk_count,
        }

    except sqlite3.DatabaseError as e:
        return {"error": f"Not a valid SQLite database: {e}"}
    except Exception as e:
        return {"error": f"Could not scan database: {e}"}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def scan_postgres(connection_string: str) -> dict:
    """
    Placeholder for PostgreSQL discovery.

    Not implemented yet — a live Postgres scan needs the `psycopg2` driver,
    which is not in requirements.txt. This stub marks the intended direction:
    point Atlas at a warehouse connection string and discover it directly.
    """
    return {
        "error": "PostgreSQL support coming soon. Use SQLite upload for now."
    }


def build_discovery_report(scan_result: dict) -> str:
    """
    Turn a scan result into a formatted markdown summary.

    Returns a one-line headline ("Discovered X tables, Y columns, Z foreign
    key relationships") followed by a markdown table listing each table with
    its column count and foreign-key count.
    """
    if not scan_result or "error" in scan_result:
        return f"**Scan failed:** {scan_result.get('error', 'unknown error') if scan_result else 'no result'}"

    table_count = scan_result.get("table_count", 0)
    column_count = scan_result.get("column_count", 0)
    fk_count = scan_result.get("fk_count", 0)

    lines = [
        f"**Discovered {table_count} table(s), {column_count} column(s), "
        f"{fk_count} foreign key relationship(s).**",
        "",
        "| Table | Columns | Foreign keys |",
        "| --- | --- | --- |",
    ]

    for name, info in scan_result.get("tables", {}).items():
        n_cols = len(info.get("columns", []))
        n_fks = len(info.get("foreign_keys", []))
        lines.append(f"| `{name}` | {n_cols} | {n_fks} |")

    return "\n".join(lines)


# Quick self-test — run `python db_scanner.py` to verify the file works.
if __name__ == "__main__":
    import json

    print("=== Testing db_scanner.py ===\n")

    demo_path = os.path.join(os.path.dirname(__file__), "demo_warehouse.db")
    if os.path.exists(demo_path):
        with open(demo_path, "rb") as f:
            result = scan_sqlite(f.read())
        print("1. Scanned demo_warehouse.db:")
        print(json.dumps(result, indent=2))
        print("\n2. Discovery report:\n")
        print(build_discovery_report(result))
    else:
        print("demo_warehouse.db not found — run `python create_demo_db.py` first.")

    print("\n3. Postgres placeholder:")
    print(json.dumps(scan_postgres("postgres://localhost/db"), indent=2))

    print("\n4. Bad bytes (should error gracefully):")
    print(json.dumps(scan_sqlite(b"this is not a database"), indent=2))

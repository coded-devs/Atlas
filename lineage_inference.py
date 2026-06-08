"""
lineage_inference.py — AI-powered lineage inference for Atlas.

After db_scanner.py discovers a database's raw schema (tables, columns, foreign
keys), this module asks Gemini to INFER the downstream lineage: for each column,
what dashboards / dbt models / ML features / reports likely depend on it, who
owns them, how PII-sensitive the column is, and how business-critical it is.

The output is a lineage dict in the exact shape of lineage.json, so the rest of
Atlas (severity ranking, impact analysis, stakeholder cards) runs on it
unchanged via lineage.load_graph().

The model only produces the `tables` block. We synthesize `owners` and
`criticality_levels` deterministically from a fixed team directory so they
always validate, regardless of what the model returns.
"""

import json
import re

from google.genai import types

from gemini_client import smart_generate


# ---------------------------------------------------------------------------
# Fixed reference data — kept out of the model's hands so it always validates.
# ---------------------------------------------------------------------------

# The seven teams Gemini is allowed to assign as owners. Anything it returns
# outside this set is remapped to "analytics" during normalization.
TEAM_DIRECTORY = {
    "finance":     {"slack": "#finance-data",  "email": "finance@example.com",     "lead": "Sarah Okonkwo"},
    "marketing":   {"slack": "#marketing-ops", "email": "marketing@example.com",   "lead": "Tomás Vega"},
    "analytics":   {"slack": "#analytics",     "email": "analytics@example.com",   "lead": "Marcus Chen"},
    "sales":       {"slack": "#sales",         "email": "sales@example.com",       "lead": "James Reilly"},
    "ml-platform": {"slack": "#ml-platform",   "email": "ml-platform@example.com", "lead": "Daniel Adeyemi"},
    "growth":      {"slack": "#growth",        "email": "growth@example.com",      "lead": "Aiko Tanaka"},
    "cfo-office":  {"slack": "#cfo-direct",    "email": "cfo-office@example.com",  "lead": "Robert Kim"},
}

_ALLOWED_TEAMS = set(TEAM_DIRECTORY)
_ALLOWED_TIERS = {"tier_1", "tier_2", "tier_3"}
_ALLOWED_ASSET_TYPES = {"dbt_model", "dashboard", "ml_feature", "scheduled_report"}

CRITICALITY_LEVELS = {
    "tier_1": {"description": "Business-critical. Used by execs or revenue-impacting systems. Requires 2-week deprecation notice minimum.", "deprecation_notice_days": 14},
    "tier_2": {"description": "Important but recoverable. Team-level analytics. Requires 1-week notice.", "deprecation_notice_days": 7},
    "tier_3": {"description": "Internal exploration. Minimal notice required.", "deprecation_notice_days": 2},
}

# Threshold above which we warn the user that inference may be slow/incomplete.
LARGE_SCHEMA_TABLE_LIMIT = 50

# A compact slice of lineage.json used as a few-shot example so Gemini learns
# the exact output shape it must produce.
_FEWSHOT_EXAMPLE = """{
  "tables": {
    "stripe.customers": {
      "criticality": "tier_1",
      "columns": {
        "id": {
          "description": "Unique customer ID, primary key",
          "is_pii": false,
          "downstream": [
            { "type": "dbt_model", "name": "mart_customers", "owner": "analytics", "criticality": "tier_1" },
            { "type": "dashboard", "name": "Executive Revenue Dashboard", "owner": "cfo-office", "criticality": "tier_1" }
          ]
        },
        "email": {
          "description": "Customer email address",
          "is_pii": true,
          "downstream": [
            { "type": "scheduled_report", "name": "Weekly Marketing Send List", "owner": "marketing", "criticality": "tier_2" }
          ]
        }
      }
    }
  }
}"""


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _format_schema_for_prompt(scan_result: dict) -> str:
    """Render the scanned schema as a readable block for the prompt."""
    lines = []
    for table, info in scan_result.get("tables", {}).items():
        lines.append(f"Table: {table}")
        for col in info.get("columns", []):
            flags = []
            if col.get("primary_key"):
                flags.append("PRIMARY KEY")
            if col.get("notnull"):
                flags.append("NOT NULL")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"  - {col['name']} ({col.get('type') or 'ANY'}){suffix}")
        for fk in info.get("foreign_keys", []):
            lines.append(
                f"  FK: {fk['from_column']} -> {fk['to_table']}.{fk['to_column']}"
            )
        lines.append("")
    return "\n".join(lines).strip()


def _build_prompt(scan_result: dict, feedback: str = "") -> str:
    """Assemble the full inference prompt."""
    schema_block = _format_schema_for_prompt(scan_result)
    teams = ", ".join(sorted(_ALLOWED_TEAMS))

    feedback_block = ""
    if feedback.strip():
        feedback_block = (
            f"\n\nADDITIONAL USER GUIDANCE (apply this when inferring):\n{feedback.strip()}\n"
        )

    return f"""You are a senior data architect. Below is a database schema discovered by an automated scanner. Infer the likely DOWNSTREAM LINEAGE for every column — the dashboards, dbt models, ML features, and scheduled reports that would realistically depend on each column in a modern data stack.

For EACH column, infer:
- description: one concise line describing the column.
- is_pii: true if the column likely holds Personally Identifiable Information, else false.
- downstream: a list of likely downstream assets. Each asset has:
    - type: one of "dbt_model", "dashboard", "ml_feature", "scheduled_report"
    - name: a realistic asset name
    - owner: one of these teams ONLY: {teams}
    - criticality: one of "tier_1", "tier_2", "tier_3"
  A column may have zero downstream assets (e.g. an obscure internal field) — use an empty list.
- Also give each TABLE a "criticality" (tier_1/2/3) reflecting the strictest column.

Common patterns to apply:
- email/phone/name/address columns are PII (is_pii=true).
- customer_id, user_id, and segment columns likely feed dashboards.
- amount/revenue/mrr/price columns are tier_1 financial data.
- created_at/updated_at/timestamp columns are typically tier_3.
- ML feature columns are tier_2.
- Primary keys and foreign keys are higher tier (they wire core entities together).

OUTPUT FORMAT — respond with JSON ONLY, no prose, wrapped in a ```json code fence. Produce a top-level "tables" object. Match this exact structure:

```json
{_FEWSHOT_EXAMPLE}
```

Use the EXACT table names from the schema below as the keys (do not rename them).{feedback_block}

SCHEMA TO ANALYZE:
{schema_block}
"""


# ---------------------------------------------------------------------------
# JSON extraction + normalization
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response.

    Handles ```json fences, bare ``` fences, and raw JSON. Raises ValueError
    if no parseable JSON object is found.
    """
    if not text:
        raise ValueError("Empty response from model.")

    # Prefer a fenced block if present.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None

    if candidate is None:
        # Fall back to the first {...} span in the text.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in model response.")
        candidate = text[start:end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model returned invalid JSON: {e}")


def _normalize(tables_block: dict) -> dict:
    """Coerce a model-produced tables block into a clean lineage dict.

    Remaps unknown teams to 'analytics' and unknown tiers to 'tier_3', drops
    malformed assets, and assembles owners + criticality_levels deterministically.
    """
    clean_tables = {}
    used_teams = set()

    for table, info in (tables_block or {}).items():
        if not isinstance(info, dict):
            continue
        columns_in = info.get("columns", {})
        if not isinstance(columns_in, dict):
            columns_in = {}

        clean_cols = {}
        for col_name, col in columns_in.items():
            if not isinstance(col, dict):
                continue
            downstream_clean = []
            for asset in col.get("downstream", []) or []:
                if not isinstance(asset, dict) or not asset.get("name"):
                    continue
                team = asset.get("owner", "analytics")
                if team not in _ALLOWED_TEAMS:
                    team = "analytics"
                used_teams.add(team)
                tier = asset.get("criticality", "tier_3")
                if tier not in _ALLOWED_TIERS:
                    tier = "tier_3"
                atype = asset.get("type", "dbt_model")
                if atype not in _ALLOWED_ASSET_TYPES:
                    atype = "dbt_model"
                downstream_clean.append({
                    "type": atype,
                    "name": str(asset["name"]),
                    "owner": team,
                    "criticality": tier,
                })

            clean_cols[col_name] = {
                "description": str(col.get("description", "")),
                "is_pii": bool(col.get("is_pii", False)),
                "downstream": downstream_clean,
            }

        # Table criticality = strictest among its assets, or the model's hint.
        tiers = [a["criticality"] for c in clean_cols.values() for a in c["downstream"]]
        tier_priority = {"tier_1": 1, "tier_2": 2, "tier_3": 3}
        if tiers:
            table_crit = min(tiers, key=lambda t: tier_priority.get(t, 99))
        else:
            table_crit = info.get("criticality", "tier_3")
            if table_crit not in _ALLOWED_TIERS:
                table_crit = "tier_3"

        clean_tables[table] = {
            "criticality": table_crit,
            "team_owner": "data-platform",
            "columns": clean_cols,
        }

    owners = {team: TEAM_DIRECTORY[team] for team in sorted(used_teams)}

    return {
        "tables": clean_tables,
        "owners": owners,
        "criticality_levels": CRITICALITY_LEVELS,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def infer_lineage_from_schema(scan_result: dict, gemini_client, feedback: str = "", on_status=None) -> dict:
    """Infer a lineage graph from a scanned database schema using Gemini.

    Args:
        scan_result: output of db_scanner.scan_sqlite().
        gemini_client: a google.genai Client (routed through smart_generate).
        feedback: optional free-text hint to steer a re-inference.
        on_status: optional callback(str) for progress (passed to smart_generate).

    Returns:
        A lineage dict in lineage.json shape: {tables, owners, criticality_levels}.
        On failure, returns {"error": "..."} so the UI can offer a retry.
    """
    if not scan_result or "error" in scan_result:
        return {"error": "Cannot infer lineage — the schema scan failed or is empty."}
    if not scan_result.get("tables"):
        return {"error": "No tables found in the scanned schema."}

    prompt = _build_prompt(scan_result, feedback=feedback)
    config = types.GenerateContentConfig(
        system_instruction="You are a precise data-lineage inference engine. You only ever respond with JSON.",
    )

    try:
        response = smart_generate(gemini_client, prompt, config, on_status=on_status)
    except Exception as e:
        return {"error": f"Gemini call failed: {e}"}

    if not response.candidates:
        return {"error": "Gemini returned no response."}

    parts = response.candidates[0].content.parts or []
    text = "".join(getattr(p, "text", "") or "" for p in parts).strip()

    try:
        parsed = _extract_json(text)
    except ValueError as e:
        return {"error": str(e)}

    # The model may return either {tables: {...}} or a bare tables object.
    tables_block = parsed.get("tables", parsed) if isinstance(parsed, dict) else {}
    lineage = _normalize(tables_block)

    is_valid, errors = validate_inferred_lineage(lineage)
    if not is_valid:
        return {"error": "Inferred lineage failed validation: " + "; ".join(errors)}

    return lineage


def validate_inferred_lineage(lineage_dict: dict) -> tuple:
    """Validate that a lineage dict matches the lineage.json schema.

    Returns:
        (is_valid: bool, errors: list[str])
    """
    errors = []

    if not isinstance(lineage_dict, dict):
        return False, ["Lineage is not a dict."]

    if "error" in lineage_dict:
        return False, [str(lineage_dict["error"])]

    tables = lineage_dict.get("tables")
    if not isinstance(tables, dict):
        return False, ["Missing or invalid 'tables' object."]
    if not tables:
        errors.append("No tables in lineage.")

    for table, info in tables.items():
        if not isinstance(info, dict):
            errors.append(f"Table '{table}' is not an object.")
            continue
        columns = info.get("columns")
        if not isinstance(columns, dict):
            errors.append(f"Table '{table}' missing 'columns' object.")
            continue
        for col_name, col in columns.items():
            if not isinstance(col, dict):
                errors.append(f"Column '{table}.{col_name}' is not an object.")
                continue
            if "is_pii" not in col:
                errors.append(f"Column '{table}.{col_name}' missing 'is_pii'.")
            downstream = col.get("downstream")
            if not isinstance(downstream, list):
                errors.append(f"Column '{table}.{col_name}' missing 'downstream' list.")
                continue
            for asset in downstream:
                if not isinstance(asset, dict):
                    errors.append(f"Asset in '{table}.{col_name}' is not an object.")
                    continue
                for key in ("type", "name", "owner", "criticality"):
                    if key not in asset:
                        errors.append(f"Asset in '{table}.{col_name}' missing '{key}'.")

    if not isinstance(lineage_dict.get("owners"), dict):
        errors.append("Missing or invalid 'owners' object.")
    if not isinstance(lineage_dict.get("criticality_levels"), dict):
        errors.append("Missing or invalid 'criticality_levels' object.")

    return (len(errors) == 0), errors


# Quick self-test — run `python lineage_inference.py` to verify parsing/validation
# without spending API quota.
if __name__ == "__main__":
    print("=== lineage_inference.py self-test ===\n")

    # 1. Validation of a good structure.
    good = _normalize({
        "stripe_customers": {
            "criticality": "tier_1",
            "columns": {
                "email": {"description": "email", "is_pii": True, "downstream": [
                    {"type": "dashboard", "name": "X", "owner": "marketing", "criticality": "tier_2"},
                ]},
            },
        }
    })
    ok, errs = validate_inferred_lineage(good)
    print(f"1. Normalized + validated good lineage: valid={ok}, errors={errs}")
    print(f"   owners synthesized: {list(good['owners'])}")

    # 2. JSON extraction from a fenced response.
    fenced = 'Here is the lineage:\n```json\n{"tables": {"t": {"columns": {}}}}\n```\nDone.'
    print(f"\n2. Extracted from fence: {_extract_json(fenced)}")

    # 3. Normalization remaps unknown team/tier.
    normed = _normalize({
        "t": {"columns": {"c": {"description": "d", "is_pii": False, "downstream": [
            {"type": "weird_type", "name": "A", "owner": "nonexistent-team", "criticality": "tier_9"},
        ]}}}
    })
    asset = normed["tables"]["t"]["columns"]["c"]["downstream"][0]
    print(f"\n3. Remapped asset: {asset}")
    assert asset["owner"] == "analytics" and asset["criticality"] == "tier_3" and asset["type"] == "dbt_model"

    # 4. Bad JSON.
    try:
        _extract_json("no json here")
    except ValueError as e:
        print(f"\n4. Bad JSON correctly rejected: {e}")

    # 5. Invalid structure fails validation.
    ok, errs = validate_inferred_lineage({"tables": {"t": {"columns": {"c": {"downstream": "nope"}}}}})
    print(f"\n5. Invalid structure: valid={ok}, errors={errs}")

    print("\nAll self-tests passed.")

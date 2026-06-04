"""
demo_cache.py — Pre-baked responses for the three canonical demo scenarios.

WHY THIS EXISTS
---------------
Atlas's analysis prose is generated live by Gemini. During a hackathon demo
that is a single point of failure: if the free-tier quota is exhausted (or the
network is flaky) at the wrong moment, the live demo dies. This module is the
safety net.

Before app.py calls the live model, it asks this module whether the request
matches one of the three rehearsed scenarios. If so, we return a pre-written
report + a synthetic tool_log and SKIP Gemini entirely. The demo then works
with zero API quota.

IMPORTANT — the rest of the UI stays fully dynamic even on a cache hit:
the severity badge, PII flag, stakeholder cards and follow-up logic in app.py
are all driven off the returned `tool_log` + the deterministic lineage layer
(lineage.json), not off the model. So a cached run renders identically to a
live run; only the prose text is pre-baked.

The cached prose is embedded as string constants (not read from reports/) on
purpose: reports/ is gitignored and not shipped to Streamlit Cloud, so the
cache must be self-contained to survive deployment.

Scenarios:
  1. Drop customer_segment from stripe.customers   -> CRITICAL impact report
  2. Drop lead_source_legacy from hubspot.deals     -> zero-impact "safe" report
  3. Drop discount_code from stripe.customers        -> "column not found" report
"""

# ---------------------------------------------------------------------------
# Cached report prose
# ---------------------------------------------------------------------------

_CUSTOMER_SEGMENT_REPORT = """## Connection Info
`stripe_main_001` (service: stripe) — status **connected**, last sync succeeded. Pipeline is healthy, so this analysis is based on live schema state.

## Column Status
The column `customer_segment` in `stripe.customers` exists and is currently enabled for sync.

## Impact Summary
Dropping `customer_segment` from `stripe.customers` will impact **5 downstream assets** spanning a dbt model, two dashboards, an ML feature, and a scheduled board report. The highest criticality among them is **Tier 1** — this column feeds executive- and revenue-facing systems, so removing it without notice risks breaking business-critical reporting.

## Affected Assets
- **mart_customer_segments** (dbt_model) — owned by Marcus Chen, analytics-team, tier_2
- **Revenue by Segment** (dashboard) — owned by James Reilly, sales-leadership, tier_1
- **Segment Retention Cohorts** (dashboard) — owned by Aiko Tanaka, growth-team, tier_2
- **churn_predictor_v3** (ml_feature) — owned by Daniel Adeyemi, ml-platform, tier_2
- **Monthly Board Deck — Segment Revenue** (scheduled_report) — owned by Robert Kim, cfo-office, tier_1

## Recommended Deprecation Plan
1. **Day 0:** Announce the deprecation to all five affected teams and confirm receipt from the Tier 1 owners (sales-leadership, cfo-office).
2. **Day 0–7:** Analytics, growth, and ML Platform teams remove their dependencies on `customer_segment`.
3. **Day 7–14:** Sales Leadership and CFO Office migrate the "Revenue by Segment" dashboard and "Monthly Board Deck — Segment Revenue" report off the column.
4. **Day 14:** Soft-deprecate `customer_segment` by disabling its sync, then trigger a verification sync.

## Stakeholder Messages

### #analytics
Hi analytics-team — `customer_segment` in `stripe.customers` is scheduled for deprecation in 14 days. Your dbt model `mart_customer_segments` depends on it. Please update the model to drop this dependency by Day 7 so your pipelines keep building cleanly.

### #sales-leads
Hi sales-leadership — the Tier 1 "Revenue by Segment" dashboard relies on `customer_segment` in `stripe.customers`, which will be deprecated in 14 days. Please coordinate with your data team to update the dashboard by Day 14 so executive reporting is uninterrupted.

### #growth
Hi growth-team — your "Segment Retention Cohorts" dashboard uses `customer_segment` from `stripe.customers`. This column will be deprecated in 14 days; please update the dashboard by Day 7 to avoid gaps in your cohort analysis.

### #ml-platform
Hi ml-platform — `churn_predictor_v3` uses `customer_segment` as a feature. The column will be deprecated in 14 days. Please update your feature pipeline by Day 7 so model training and scoring are unaffected.

### #cfo-direct
Hi cfo-office — the Tier 1 "Monthly Board Deck — Segment Revenue" report depends on `customer_segment` in `stripe.customers`, which will be deprecated in 14 days. Please ensure the report is updated by Day 14 to protect board-level financial reporting.
"""

_LEAD_SOURCE_REPORT = """## Connection Info
`hubspot_crm_002` (service: hubspot) — status **connected**, last sync succeeded. Pipeline is healthy.

## Column Status
The column `lead_source_legacy` in `hubspot.deals` exists and is currently enabled for sync. It is flagged as deprecated (replaced by `hubspot.contacts.acquisition_channel`).

## Impact Summary
Dropping `lead_source_legacy` from `hubspot.deals` has **zero downstream impact**. No dbt models, dashboards, scheduled reports, or ML features depend on this column, so it is safe to remove.

## Affected Assets
No downstream dependencies found — this column is safe to drop immediately.

## Recommended Deprecation Plan
Safe for immediate removal. No stakeholder notice period is required.
1. **Day 0:** Soft-deprecate `lead_source_legacy` by disabling its sync, then trigger a verification sync.
"""

_DISCOUNT_CODE_REPORT = """## Connection Info
`stripe_main_001` (service: stripe) — status **connected**, last sync succeeded.

## Column Status
The column `discount_code` was **not found** in the `stripe.customers` table. I checked the live Fivetran schema configuration and this column is not currently synced (and has no lineage record).

## Impact Summary
There is nothing to analyze or deprecate — `discount_code` does not exist in `stripe.customers`. Please double-check the column name, or confirm it lives in a different table or connection.
"""

_CUSTOMER_SEGMENT_EXECUTION = """## Execution Complete
- **Column:** `stripe.customers.customer_segment`
- **Action:** `modify_connection_column_config` — `enabled` set to `false` (soft-deprecated)
- **Verification:** `sync_connection` triggered, status `sync_triggered`
- **What happens next:** the column stops being written to the warehouse on the next sync. Existing data already in the warehouse is preserved, so this is fully reversible by re-enabling the column.
"""

_LEAD_SOURCE_EXECUTION = """## Execution Complete
- **Column:** `hubspot.deals.lead_source_legacy`
- **Action:** `modify_connection_column_config` — `enabled` set to `false` (soft-deprecated)
- **Verification:** `sync_connection` triggered, status `sync_triggered`
- **What happens next:** the column stops syncing on the next run. No downstream assets were affected, so no migration was required.
"""


# ---------------------------------------------------------------------------
# Synthetic tool logs — mirror what the live agent would have called.
# The `summarize_impact` entry is what lets app.py rebuild the severity badge,
# PII flag and stakeholder cards deterministically from lineage.json.
# ---------------------------------------------------------------------------

def _discovery_log(connection_id: str) -> list:
    """The discovery tool calls every analysis starts with."""
    return [
        {"tool": "list_connections", "args": {}},
        {"tool": "get_connection_schema_config", "args": {"connection_id": connection_id}},
    ]


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------

def _norm(request: str) -> str:
    """Lowercase and treat spaces/underscores as interchangeable so that
    'customer segment' matches the same scenario as 'customer_segment'."""
    return (request or "").lower().replace(" ", "_")


def _mentions(request: str, *needles: str) -> bool:
    """True only if every needle appears in the normalized request."""
    r = _norm(request)
    return all(_norm(n) in r for n in needles)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_analysis_cache(request: str):
    """Return a pre-baked analysis for a known demo scenario, or None.

    On a hit, app.py should display the report and skip the live Gemini call,
    letting the demo run with zero API quota.

    Args:
        request: the raw user request string.

    Returns:
        dict with keys:
            "report"   — markdown report string
            "tool_log" — list of {"tool", "args"} dicts (drives the severity
                         badge, PII flag and stakeholder cards in app.py)
        or None on a cache miss (caller should fall back to live Gemini).
    """
    # Scenario 1: business-critical drop.
    if _mentions(request, "customer_segment", "stripe"):
        return {
            "report": _CUSTOMER_SEGMENT_REPORT,
            "tool_log": _discovery_log("stripe_main_001") + [
                {"tool": "summarize_impact",
                 "args": {"table": "stripe.customers", "column": "customer_segment"}},
            ],
        }

    # Scenario 2: zero-impact, safe to drop.
    if _mentions(request, "lead_source_legacy", "hubspot"):
        return {
            "report": _LEAD_SOURCE_REPORT,
            "tool_log": _discovery_log("hubspot_crm_002") + [
                {"tool": "summarize_impact",
                 "args": {"table": "hubspot.deals", "column": "lead_source_legacy"}},
            ],
        }

    # Scenario 3: column does not exist. No summarize_impact entry on purpose,
    # so app.py shows no severity badge — there is nothing to rank.
    if _mentions(request, "discount_code", "stripe"):
        return {
            "report": _DISCOUNT_CODE_REPORT,
            "tool_log": _discovery_log("stripe_main_001"),
        }

    return None


def check_execution_cache(request: str):
    """Return a pre-baked execution result for a known demo scenario, or None.

    On a hit we ALSO invoke the real (offline, deterministic) Fivetran mock
    tools so that the live change log populates exactly as it would in a real
    run — get_change_log() in app.py then shows genuine, timestamped entries.
    No network or API quota is used.

    Args:
        request: the original user request string.

    Returns:
        dict with keys:
            "result"     — markdown execution-result string
            "change_log" — the change log entries produced by this execution
            "tool_log"   — list of {"tool", "args"} dicts for the trace
        or None on a cache miss (caller should fall back to live Gemini).
    """
    # Imported lazily so importing this module never drags in fivetran_tools
    # unless an execution is actually requested.
    from fivetran_tools import (
        modify_connection_column_config,
        sync_connection,
        get_change_log,
    )

    target = None
    result_text = None

    if _mentions(request, "customer_segment", "stripe"):
        target = ("stripe_main_001", "stripe", "customers", "customer_segment")
        result_text = _CUSTOMER_SEGMENT_EXECUTION
    elif _mentions(request, "lead_source_legacy", "hubspot"):
        target = ("hubspot_crm_002", "hubspot", "deals", "lead_source_legacy")
        result_text = _LEAD_SOURCE_EXECUTION

    if not target:
        return None

    conn_id, schema, table, column = target

    # Actually apply the change against the mock so the change log is real.
    modify_connection_column_config(
        connection_id=conn_id,
        schema_name=schema,
        table_name=table,
        column_name=column,
        enabled=False,
    )
    sync_connection(conn_id)

    return {
        "result": result_text,
        "change_log": get_change_log(),
        "tool_log": [
            {"tool": "modify_connection_column_config",
             "args": {"connection_id": conn_id, "schema_name": schema,
                      "table_name": table, "column_name": column, "enabled": False}},
            {"tool": "sync_connection", "args": {"connection_id": conn_id}},
        ],
    }


# Quick self-test — run `python demo_cache.py` to verify the cache works.
if __name__ == "__main__":
    import json

    print("=== demo_cache.py self-test ===\n")

    for label, req in [
        ("Scenario 1 (customer_segment)", "Drop customer_segment from stripe.customers"),
        ("Scenario 2 (lead_source_legacy)", "Is it safe to drop lead_source_legacy from hubspot.deals?"),
        ("Scenario 3 (discount_code)", "Remove the discount_code column from stripe.customers"),
        ("Cache miss", "Drop user_email from salesforce.leads"),
    ]:
        hit = check_analysis_cache(req)
        status = "HIT" if hit else "miss (falls back to live Gemini)"
        print(f"{label}: analysis {status}")
        if hit:
            print(f"    tool_log: {json.dumps(hit['tool_log'])}")

    print("\nExecution cache for customer_segment:")
    exec_hit = check_execution_cache("Drop customer_segment from stripe.customers")
    print(json.dumps(exec_hit["change_log"], indent=2))

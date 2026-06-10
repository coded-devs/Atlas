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

_RENAME_SEGMENT_REPORT = """## Connection Info
`stripe_main_001` (service: stripe) — status **connected**, last sync succeeded. Pipeline is healthy.

## Column Status
The column `customer_segment` in `stripe.customers` exists and is currently enabled for sync. You want to rename it to `segment_label`.

## Impact Summary
Renaming `customer_segment` to `segment_label` has the **same downstream blast radius as a drop** — every asset that references the old name breaks until it is updated. This impacts **5 downstream assets** spanning a dbt model, two dashboards, an ML feature, and a scheduled board report. The highest criticality is **Tier 1**, so the rename must be coordinated with the affected teams before it lands.

## Affected Assets
- **mart_customer_segments** (dbt_model) — owned by Marcus Chen, analytics-team, tier_2
- **Revenue by Segment** (dashboard) — owned by James Reilly, sales-leadership, tier_1
- **Segment Retention Cohorts** (dashboard) — owned by Aiko Tanaka, growth-team, tier_2
- **churn_predictor_v3** (ml_feature) — owned by Daniel Adeyemi, ml-platform, tier_2
- **Monthly Board Deck — Segment Revenue** (scheduled_report) — owned by Robert Kim, cfo-office, tier_1

## Recommended Rename Plan
1. **Day 0:** Announce the rename (`customer_segment` → `segment_label`) to all five affected teams.
2. **Day 0–7:** Analytics, growth, and ML Platform teams update their references to `segment_label`.
3. **Day 7–14:** Sales Leadership and CFO Office update the "Revenue by Segment" dashboard and "Monthly Board Deck" report to the new name.
4. **Day 14:** Apply the rename via Fivetran, then trigger a verification sync.

## Stakeholder Messages

### #analytics
Hi analytics-team — `customer_segment` in `stripe.customers` is being renamed to `segment_label` in 14 days. Your dbt model `mart_customer_segments` references it; please update to the new name by Day 7 so your pipelines keep building.

### #sales-leads
Hi sales-leadership — the Tier 1 "Revenue by Segment" dashboard references `customer_segment`, which is being renamed to `segment_label` in 14 days. Please update the dashboard by Day 14 so executive reporting is uninterrupted.

### #growth
Hi growth-team — your "Segment Retention Cohorts" dashboard uses `customer_segment`. It is being renamed to `segment_label` in 14 days; please update by Day 7.

### #ml-platform
Hi ml-platform — `churn_predictor_v3` uses `customer_segment` as a feature. It is being renamed to `segment_label` in 14 days. Please update your feature pipeline by Day 7.

### #cfo-direct
Hi cfo-office — the Tier 1 "Monthly Board Deck — Segment Revenue" report references `customer_segment`, being renamed to `segment_label` in 14 days. Please update by Day 14 to protect board-level reporting.
"""

_DISABLE_CUSTOMERS_REPORT = """## Connection Info
`stripe_main_001` (service: stripe) — status **connected**, last sync succeeded. Pipeline is healthy.

## Table Status
The table `stripe.customers` exists and is currently enabled for sync. **Affected: 4 columns, 10 downstream assets.**

## Impact Summary
Disabling sync for the entire `stripe.customers` table stops every column from syncing at once. Aggregated across all 4 columns, this breaks **10 unique downstream assets**, including Tier 1 revenue dashboards, finance dbt models, and the executive board report. This is the largest possible change to this connector — the highest criticality is **Tier 1**, requiring a 2-week notice.

## Affected Assets
- **mart_customers** (dbt_model) — owned by Marcus Chen, analytics-team, tier_1
- **fct_revenue** (dbt_model) — owned by Sarah Okonkwo, finance-analytics, tier_1
- **Executive Revenue Dashboard** (dashboard) — owned by Robert Kim, cfo-office, tier_1
- **Weekly Marketing Send List** (scheduled_report) — owned by Tomás Vega, marketing-ops, tier_2
- **mart_customer_segments** (dbt_model) — owned by Marcus Chen, analytics-team, tier_2
- **Revenue by Segment** (dashboard) — owned by James Reilly, sales-leadership, tier_1
- **Segment Retention Cohorts** (dashboard) — owned by Aiko Tanaka, growth-team, tier_2
- **churn_predictor_v3** (ml_feature) — owned by Daniel Adeyemi, ml-platform, tier_2
- **Monthly Board Deck — Segment Revenue** (scheduled_report) — owned by Robert Kim, cfo-office, tier_1
- **Cohort Analysis** (dashboard) — owned by Aiko Tanaka, growth-team, tier_2

## Recommended Disable Plan
1. **Day 0:** Announce the table disable to all affected teams; confirm receipt from Tier 1 owners (analytics, finance, cfo-office, sales-leadership).
2. **Day 0–7:** Teams migrate or freeze every dependency on `stripe.customers`.
3. **Day 7–14:** Tier 1 dashboards and reports are migrated off the table.
4. **Day 14:** Disable sync for `stripe.customers`, then trigger a verification sync.

## Stakeholder Messages

### #analytics
Hi analytics-team — we plan to disable sync for the entire `stripe.customers` table in 14 days. Your models `mart_customers` and `mart_customer_segments` depend on it. Please migrate or freeze these by Day 7.

### #finance-data
Hi finance-analytics — disabling `stripe.customers` will break `fct_revenue` (Tier 1). Please plan a migration before Day 14.

### #cfo-direct
Hi cfo-office — the Tier 1 "Executive Revenue Dashboard" and "Monthly Board Deck — Segment Revenue" both depend on `stripe.customers`, which we plan to disable in 14 days. Please ensure these are migrated by Day 14.

### #sales-leads
Hi sales-leadership — the Tier 1 "Revenue by Segment" dashboard depends on `stripe.customers`. We plan to disable this table in 14 days; please update by Day 14.

### #growth
Hi growth-team — "Segment Retention Cohorts" and "Cohort Analysis" both depend on `stripe.customers`. Please migrate off it by Day 7.

### #ml-platform
Hi ml-platform — `churn_predictor_v3` depends on `stripe.customers`. The table will be disabled in 14 days; please update your feature pipeline by Day 7.

### #marketing-ops
Hi marketing-ops — the "Weekly Marketing Send List" depends on `stripe.customers`. Please find an alternative source before Day 7.
"""

_CUSTOMER_SEGMENT_EXECUTION = """## Execution Complete
- **Column:** `stripe.customers.customer_segment`
- **Action:** `modify_connection_column_config` — `enabled` set to `false` (soft-deprecated)
- **Verification:** `sync_connection` triggered, status `sync_triggered`
- **What happens next:** the column stops being written to the warehouse on the next sync. Existing data already in the warehouse is preserved, so this is fully reversible by re-enabling the column.
"""

_RENAME_SEGMENT_EXECUTION = """## Execution Complete
- **Column:** `stripe.customers.customer_segment`
- **Action:** `rename_column_config` — renamed to `segment_label`
- **Verification:** `sync_connection` triggered, status `sync_triggered`
- **What happens next:** the column now lands in the warehouse as `segment_label`. Downstream assets must reference the new name; existing data is preserved.
"""

_DISABLE_CUSTOMERS_EXECUTION = """## Execution Complete
- **Table:** `stripe.customers`
- **Action:** `disable_table_sync` — table `enabled` set to `false`
- **Verification:** `sync_connection` triggered, status `sync_triggered`
- **What happens next:** every column in `stripe.customers` stops syncing on the next run. Data already in the warehouse is preserved; re-enable the table to resume syncing.
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
    _r = _norm(request)

    # Scenario 4: RENAME a column. Checked before the drop scenario so the
    # rename wording wins (it also mentions customer_segment + stripe).
    if "rename" in _r and "customer_segment" in _r:
        return {
            "report": _RENAME_SEGMENT_REPORT,
            "tool_log": _discovery_log("stripe_main_001") + [
                {"tool": "summarize_impact",
                 "args": {"table": "stripe.customers", "column": "customer_segment"}},
            ],
        }

    # Scenario 5: DISABLE an entire table. Uses summarize_table_impact so
    # app.py ranks it with calculate_table_risk and renders the table diff.
    if ("disable" in _r or "stop_syncing" in _r) and "customers" in _r and "customer_segment" not in _r:
        return {
            "report": _DISABLE_CUSTOMERS_REPORT,
            "tool_log": _discovery_log("stripe_main_001") + [
                {"tool": "summarize_table_impact",
                 "args": {"table": "stripe.customers"}},
            ],
        }

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


# ---------------------------------------------------------------------------
# Cached AI-inferred lineage for the bundled demo_warehouse.db
# ---------------------------------------------------------------------------
#
# When a user uploads demo_warehouse.db and clicks "Auto-Discover Lineage with
# AI", app.py first checks here. On a hit we return this pre-baked inference
# instantly — zero Gemini calls — so the Day-6 inference flow demos reliably
# even with exhausted quota. The structure matches lineage.json exactly
# (load_graph() accepts it directly), and the team names match the
# lineage_inference.TEAM_DIRECTORY so owners resolve cleanly.

_DEMO_DB_TEAMS = {
    "finance":     {"slack": "#finance-data",  "email": "finance@example.com",     "lead": "Sarah Okonkwo"},
    "marketing":   {"slack": "#marketing-ops", "email": "marketing@example.com",   "lead": "Tomás Vega"},
    "analytics":   {"slack": "#analytics",     "email": "analytics@example.com",   "lead": "Marcus Chen"},
    "sales":       {"slack": "#sales",         "email": "sales@example.com",       "lead": "James Reilly"},
    "ml-platform": {"slack": "#ml-platform",   "email": "ml-platform@example.com", "lead": "Daniel Adeyemi"},
    "growth":      {"slack": "#growth",        "email": "growth@example.com",      "lead": "Aiko Tanaka"},
    "cfo-office":  {"slack": "#cfo-direct",    "email": "cfo-office@example.com",  "lead": "Robert Kim"},
}

_DEMO_DB_CRITICALITY = {
    "tier_1": {"description": "Business-critical. Used by execs or revenue-impacting systems. Requires 2-week deprecation notice minimum.", "deprecation_notice_days": 14},
    "tier_2": {"description": "Important but recoverable. Team-level analytics. Requires 1-week notice.", "deprecation_notice_days": 7},
    "tier_3": {"description": "Internal exploration. Minimal notice required.", "deprecation_notice_days": 2},
}


def _col(description, is_pii, downstream):
    return {"description": description, "is_pii": is_pii, "downstream": downstream}


def _asset(atype, name, owner, criticality):
    return {"type": atype, "name": name, "owner": owner, "criticality": criticality}


_DEMO_DB_LINEAGE = {
    "tables": {
        "stripe_customers": {
            "criticality": "tier_1",
            "team_owner": "data-platform",
            "columns": {
                "id": _col("Unique customer ID, primary key", False, [
                    _asset("dbt_model", "mart_customers", "analytics", "tier_1"),
                    _asset("dashboard", "Executive Revenue Dashboard", "cfo-office", "tier_1"),
                ]),
                "email": _col("Customer email address", True, [
                    _asset("scheduled_report", "Weekly Marketing Send List", "marketing", "tier_2"),
                ]),
                "customer_segment": _col("Marketing-assigned segment label", False, [
                    _asset("dbt_model", "mart_customer_segments", "analytics", "tier_2"),
                    _asset("dashboard", "Revenue by Segment", "sales", "tier_1"),
                    _asset("ml_feature", "churn_predictor_v3", "ml-platform", "tier_2"),
                ]),
                "name": _col("Customer full name", True, [
                    _asset("dbt_model", "mart_customers", "analytics", "tier_2"),
                ]),
                "created_at": _col("When the customer signed up", False, [
                    _asset("dashboard", "Cohort Analysis", "growth", "tier_3"),
                ]),
                "is_active": _col("Whether the customer account is active", False, [
                    _asset("dashboard", "Active Accounts Overview", "growth", "tier_3"),
                ]),
            },
        },
        "stripe_subscriptions": {
            "criticality": "tier_1",
            "team_owner": "data-platform",
            "columns": {
                "id": _col("Subscription ID, primary key", False, [
                    _asset("dbt_model", "fct_subscriptions", "finance", "tier_1"),
                ]),
                "customer_id": _col("FK to stripe_customers.id", False, [
                    _asset("dbt_model", "fct_subscriptions", "finance", "tier_1"),
                    _asset("dashboard", "MRR Dashboard", "cfo-office", "tier_1"),
                ]),
                "plan_name": _col("Subscription plan tier name", False, [
                    _asset("dashboard", "Plan Distribution", "growth", "tier_2"),
                ]),
                "status": _col("Subscription status (active/canceled/past_due)", False, [
                    _asset("dashboard", "Churn Dashboard", "growth", "tier_1"),
                ]),
                "mrr": _col("Monthly recurring revenue for the subscription", False, [
                    _asset("dbt_model", "fct_mrr", "finance", "tier_1"),
                    _asset("dashboard", "MRR Dashboard", "cfo-office", "tier_1"),
                ]),
                "started_at": _col("When the subscription started", False, [
                    _asset("dbt_model", "fct_subscriptions", "finance", "tier_3"),
                ]),
            },
        },
        "stripe_invoices": {
            "criticality": "tier_1",
            "team_owner": "data-platform",
            "columns": {
                "id": _col("Invoice ID, primary key", False, [
                    _asset("dbt_model", "fct_invoices", "finance", "tier_1"),
                ]),
                "customer_id": _col("FK to stripe_customers.id", False, [
                    _asset("dbt_model", "fct_invoices", "finance", "tier_1"),
                ]),
                "subscription_id": _col("FK to stripe_subscriptions.id", False, [
                    _asset("dbt_model", "fct_invoices", "finance", "tier_1"),
                ]),
                "amount": _col("Invoice amount in USD", False, [
                    _asset("dbt_model", "fct_revenue", "finance", "tier_1"),
                    _asset("dashboard", "Executive Revenue Dashboard", "cfo-office", "tier_1"),
                ]),
                "status": _col("Invoice status (paid/open/void)", False, [
                    _asset("dashboard", "Billing Health", "finance", "tier_2"),
                ]),
                "created_at": _col("When the invoice was created", False, [
                    _asset("dbt_model", "fct_invoices", "finance", "tier_3"),
                ]),
            },
        },
        "hubspot_deals": {
            "criticality": "tier_1",
            "team_owner": "data-platform",
            "columns": {
                "deal_id": _col("HubSpot deal ID, primary key", False, [
                    _asset("dbt_model", "mart_sales_pipeline", "sales", "tier_2"),
                ]),
                "company_name": _col("Company associated with the deal", False, [
                    _asset("dashboard", "Sales Pipeline Health", "sales", "tier_2"),
                ]),
                "amount": _col("Deal value in USD", False, [
                    _asset("dbt_model", "mart_sales_pipeline", "sales", "tier_1"),
                    _asset("dashboard", "Sales Pipeline Health", "sales", "tier_1"),
                ]),
                "deal_stage": _col("Stage in the sales funnel", False, [
                    _asset("dashboard", "Sales Pipeline Health", "sales", "tier_1"),
                ]),
                "lead_source": _col("Where the lead originated", False, [
                    _asset("dashboard", "Lead Source Attribution", "marketing", "tier_2"),
                    _asset("ml_feature", "lead_score_v2", "ml-platform", "tier_2"),
                ]),
                "owner_email": _col("Sales rep who owns the deal", True, [
                    _asset("dashboard", "Rep Performance", "sales", "tier_2"),
                ]),
            },
        },
        "hubspot_contacts": {
            "criticality": "tier_2",
            "team_owner": "data-platform",
            "columns": {
                "contact_id": _col("HubSpot contact ID, primary key", False, [
                    _asset("dbt_model", "mart_contacts", "marketing", "tier_2"),
                ]),
                "email": _col("Contact email address", True, [
                    _asset("scheduled_report", "Weekly Marketing Send List", "marketing", "tier_2"),
                ]),
                "first_name": _col("Contact first name", True, []),
                "last_name": _col("Contact last name", True, []),
                "lifecycle_stage": _col("Marketing lifecycle stage", False, [
                    _asset("dashboard", "Funnel Conversion", "marketing", "tier_2"),
                ]),
            },
        },
        "analytics_mrr_by_segment": {
            "criticality": "tier_1",
            "team_owner": "data-platform",
            "columns": {
                "id": _col("Row ID, primary key", False, []),
                "month": _col("Reporting month", False, [
                    _asset("dashboard", "MRR by Segment", "cfo-office", "tier_1"),
                ]),
                "segment": _col("Customer segment", False, [
                    _asset("dashboard", "MRR by Segment", "cfo-office", "tier_1"),
                ]),
                "total_mrr": _col("Total MRR for the segment/month", False, [
                    _asset("dashboard", "MRR by Segment", "cfo-office", "tier_1"),
                    _asset("scheduled_report", "Monthly Board Deck — Segment Revenue", "cfo-office", "tier_1"),
                ]),
                "customer_count": _col("Number of customers in the segment", False, [
                    _asset("dashboard", "MRR by Segment", "cfo-office", "tier_2"),
                ]),
            },
        },
    },
    "owners": _DEMO_DB_TEAMS,
    "criticality_levels": _DEMO_DB_CRITICALITY,
}


def check_inference_cache(scan_result: dict):
    """Return a pre-baked inferred lineage for the bundled demo_warehouse.db.

    We fingerprint the scan by its set of table names. The demo database has a
    distinctive set of six tables, so an exact match means the user uploaded
    (or loaded) demo_warehouse.db and we can serve the cached inference with
    zero API quota.

    Args:
        scan_result: output of db_scanner.scan_sqlite().

    Returns:
        A lineage dict (lineage.json shape) on a hit, or None on a miss
        (caller should fall back to live Gemini inference).
    """
    if not scan_result or "error" in scan_result:
        return None
    scanned = set(scan_result.get("tables", {}).keys())
    expected = set(_DEMO_DB_LINEAGE["tables"].keys())
    if scanned == expected:
        return _DEMO_DB_LINEAGE
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
        rename_column_config,
        disable_table_sync,
        sync_connection,
        get_change_log,
    )

    _r = _norm(request)

    # RENAME a column — checked first (also mentions customer_segment).
    if "rename" in _r and "customer_segment" in _r:
        rename_column_config(
            connection_id="stripe_main_001", schema_name="stripe",
            table_name="customers", column_name="customer_segment",
            new_column_name="segment_label",
        )
        sync_connection("stripe_main_001")
        return {
            "result": _RENAME_SEGMENT_EXECUTION,
            "change_log": get_change_log(),
            "tool_log": [
                {"tool": "rename_column_config",
                 "args": {"connection_id": "stripe_main_001", "schema_name": "stripe",
                          "table_name": "customers", "column_name": "customer_segment",
                          "new_column_name": "segment_label"}},
                {"tool": "sync_connection", "args": {"connection_id": "stripe_main_001"}},
            ],
        }

    # DISABLE an entire table.
    if ("disable" in _r or "stop_syncing" in _r) and "customers" in _r and "customer_segment" not in _r:
        disable_table_sync(
            connection_id="stripe_main_001", schema_name="stripe", table_name="customers",
        )
        sync_connection("stripe_main_001")
        return {
            "result": _DISABLE_CUSTOMERS_EXECUTION,
            "change_log": get_change_log(),
            "tool_log": [
                {"tool": "disable_table_sync",
                 "args": {"connection_id": "stripe_main_001", "schema_name": "stripe",
                          "table_name": "customers"}},
                {"tool": "sync_connection", "args": {"connection_id": "stripe_main_001"}},
            ],
        }

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

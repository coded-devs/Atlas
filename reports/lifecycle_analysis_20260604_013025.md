# Atlas Lifecycle Report

**Generated:** 2026-06-04 01:30:25

**Request:** I want to drop the customer_segment column from stripe.customers. Tell me what will break and how to deprecate it safely.

---

## Connection Info
stripe_main_001, stripe, connected, 2026-06-03T12:18:09.341576+00:00Z

## Column Status
The column `customer_segment` in `stripe.customers` exists and is currently enabled for sync.

## Impact Summary
Deprecating the `customer_segment` column will impact 5 downstream assets. This includes a dbt model, two Looker dashboards, an ML feature, and a critical scheduled report. The highest criticality identified among these assets is Tier 1, indicating business-critical dependencies used by executives or revenue-impacting systems.

## Affected Assets
*   **mart_customer_segments** (dbt_model) - owned by Marcus Chen, analytics-team, tier_2
*   **Revenue by Segment** (dashboard) - owned by James Reilly, sales-leadership, tier_1
*   **Segment Retention Cohorts** (dashboard) - owned by Aiko Tanaka, growth-team, tier_2
*   **churn_predictor_v3** (ml_feature) - owned by Daniel Adeyemi, ml-platform, tier_2
*   **Monthly Board Deck — Segment Revenue** (scheduled_report) - owned by Robert Kim, cfo-office, tier_1

## Recommended Deprecation Plan
1.  **Day 0**: Announce deprecation to all affected teams and stakeholders.
2.  **Day 0-14**: Affected teams update or remove dependencies on `stripe.customers.customer_segment`.
3.  **Day 14**: Deprecate `stripe.customers.customer_segment` by disabling its sync.

## Stakeholder Messages

### #analytics
@Marcus Chen and Analytics Team: Please be aware that the `customer_segment` column in `stripe.customers` is scheduled for deprecation in 14 days. Your dbt model, `mart_customer_segments`, currently depends on this column. Please plan to update your model to remove this dependency before the deprecation date to avoid any disruptions.

### #sales-leads
@James Reilly and Sales Leadership: The `Revenue by Segment` dashboard, which is a Tier 1 asset, relies on the `customer_segment` column in `stripe.customers`. This column will be deprecated in 14 days. Please work with your data team to assess the impact and ensure any necessary adjustments are made to maintain continuity of your reporting.

### #growth
@Aiko Tanaka and Growth Team: The `Segment Retention Cohorts` dashboard uses the `customer_segment` column from `stripe.customers`. This column will be deprecated in 14 days. Please take the necessary steps to update your dashboards and avoid any interruption to your analysis.

### #ml-platform
@Daniel Adeyemi and ML Platform Team: The `churn_predictor_v3` ML feature has a dependency on the `customer_segment` column in `stripe.customers`. This column will be deprecated in 14 days. Please plan for the necessary modifications to your feature to mitigate any potential impact on the churn predictor.

### #cfo-direct
@Robert Kim and CFO Office: The `Monthly Board Deck — Segment Revenue` report, a Tier 1 asset, relies on the `customer_segment` column in `stripe.customers`. This column is scheduled for deprecation in 14 days. Please coordinate with your data team to ensure business continuity and address any reporting adjustments required.

## Execution Preview
`modify_connection_column_config(connection_id='stripe_main_001', schema_name='stripe', table_name='customers', column_name='customer_segment', enabled=false)`

Awaiting your approval to execute.
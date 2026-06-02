# Atlas Report - Scenario 1

**Generated:** 2026-06-03 06:15:44

**Request:** I want to drop the customer_segment column from stripe.customers. Tell me what will break and how to deprecate it safely.

---

## Impact Summary
The proposed change to drop the `customer_segment` column from the `stripe.customers` table will impact 5 downstream assets. This column is business-critical and used by executive and revenue-impacting systems, meaning the highest criticality consequence is disruption to tier_1 dashboards and scheduled reports.

## Affected Assets
- **mart_customer_segments** (dbt_model) - owned by Marcus Chen, analytics-team, criticality tier_2
- **Revenue by Segment** (dashboard) - owned by James Reilly, sales-leadership, criticality tier_1
- **Segment Retention Cohorts** (dashboard) - owned by Aiko Tanaka, growth-team, criticality tier_2
- **churn_predictor_v3** (ml_feature) - owned by Daniel Adeyemi, ml-platform, criticality tier_2
- **Monthly Board Deck â€” Segment Revenue** (scheduled_report) - owned by Robert Kim, cfo-office, criticality tier_1

## Recommended Deprecation Plan
1. **Day 0:** Communicate deprecation plan to all stakeholders.
2. **Day 7:** Analytics team updates `mart_customer_segments` to remove reliance on `customer_segment`. Growth team updates "Segment Retention Cohorts" dashboard. ML Platform team updates `churn_predictor_v3`.
3. **Day 14:** Sales Leadership and CFO office update "Revenue by Segment" dashboard and "Monthly Board Deck â€” Segment Revenue" scheduled report. The `customer_segment` column can be dropped from `stripe.customers`.

## Stakeholder Messages

### #analytics
Hi analytics-team, please note that the `customer_segment` column in `stripe.customers` will be deprecated in 14 days. Our records show that `mart_customer_segments` depends on this column. Please update your dbt models by Day 7 to remove this dependency and ensure continuity of your data pipelines.

### #sales-leads
Hi sales-leadership, the `customer_segment` column in `stripe.customers` will be deprecated in 14 days. Your "Revenue by Segment" dashboard relies on this column. Please plan to update the dashboard by Day 14 to prevent any disruption to your reporting.

### #growth
Hi growth-team, the `customer_segment` column in `stripe.customers` will be deprecated in 14 days. Your "Segment Retention Cohorts" dashboard depends on this column. Please update your dashboard by Day 7 to remove this dependency.

### #ml-platform
Hi ml-platform, the `customer_segment` column in `stripe.customers` will be deprecated in 14 days. Our records indicate that `churn_predictor_v3` uses this column as a feature. Please update your feature engineering by Day 7 to remove this dependency.

### #cfo-direct
Hi cfo-office, the `customer_segment` column in `stripe.customers` will be deprecated in 14 days. The "Monthly Board Deck â€” Segment Revenue" scheduled report uses this column. Please ensure the report is updated by Day 14 to avoid any impact on your financial reporting.
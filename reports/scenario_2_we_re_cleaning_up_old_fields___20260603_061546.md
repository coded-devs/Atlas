# Atlas Report - Scenario 2

**Generated:** 2026-06-03 06:15:46

**Request:** We're cleaning up old fields. Is it safe to drop lead_source_legacy from hubspot.deals?

---

The `lead_source_legacy` column in `hubspot.deals` has zero downstream impact. It is safe to proceed with dropping this column.

## Impact Summary
The proposed change is to drop the `lead_source_legacy` column from the `hubspot.deals` table. This column is deprecated and has no downstream dependencies, meaning its removal will not affect any dbt models, dashboards, scheduled reports, or ML features.

## Affected Assets
None.

## Recommended Deprecation Plan
This column has no downstream impact. You can proceed with the deprecation with a short notice period.

*   **Day 0**: Drop the `lead_source_legacy` column from `hubspot.deals`.
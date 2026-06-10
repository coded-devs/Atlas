# CLAUDE.md — Project Context for Atlas

> Claude Code reads this file automatically. It is the single source of truth
> about the project. Do not guess or assume — if it's not in this file or in
> the actual codebase, ask.

## What This Project Is

Atlas is a **Data Change Intelligence Agent** — an AI-powered tool that helps
data engineers safely deprecate, rename, or disable data columns by analyzing
downstream impact before making changes.

**Hackathon:** Google Cloud Rapid Agent Hackathon (deadline June 11, 2026)
**Track:** Fivetran partner track ($5,000 first place)
**Deployed:** https://atlas-fivetran.streamlit.app/
**Repo:** GitHub (public, MIT license)

## Architecture

```
User Request (natural language)
    ↓
Streamlit multi-page UI (app.py entry → pages/1_Atlas_Agent.py)
    ↓
Gemini LLM (via google-genai SDK)
    ↓ (function calling)
┌────────────────────────────────────┐
│           Tool Layer               │
│                                    │
│  Fivetran MCP Tools    Lineage     │
│  (fivetran_tools.py)   Engine      │
│                        (lineage.py)│
│  6 tools matching      4 query     │
│  official fivetran/    functions    │
│  fivetran-mcp server              │
└────────────────────────────────────┘
    ↓
Deterministic Semantic Ranker (severity calculation)
    ↓
Human Approval Gate (approve/reject in UI)
    ↓
Execution (modify column config → trigger sync)
    ↓
Change Log (timestamped proof of actions)
    ↓
Multi-channel Notifications (Slack, Telegram, Email)
```

## File Map (AUTHORITATIVE — do not invent files)

### Core Agent (multi-page Streamlit app)
- `app.py` — Streamlit ENTRYPOINT / landing page. Brief intro, three
  `st.page_link` buttons to the pages below, and quick stats (changes
  executed, rollbacks, connectors monitored) pulled from the change log.
  Run with `streamlit run app.py`. Holds NO agent logic anymore.
- `pages/1_Atlas_Agent.py` — THE agent UI (formerly app.py). All analysis/
  execution/approval logic, data-source picker, DB scan + AI lineage
  inference, severity badge, dependency graph, schema diff, stakeholder
  notifications, follow-up chat, rollback. Lives in `pages/`, so it loads
  repo-root files via `Path(__file__).resolve().parent.parent`.
- `pages/2_Audit_Dashboard.py` — Action history from
  `fivetran_tools.get_change_log()`. 4 metric cards (Total Actions, Columns
  Deprecated, Tables Disabled, Rollbacks), a styled HTML table (Timestamp |
  Action | Connector | Target | Change), sidebar filters (action type,
  connector), and a "Clear log" demo-reset button.
- `pages/3_Connector_Health.py` — Per-connector status cards (service icon,
  health dot, humanized last-sync, tables synced, sync frequency), 4 summary
  metrics, manual Refresh button, and an optional 30s auto-refresh
  (HTML meta-refresh, off by default).
- `atlas.py` — Terminal/CLI version of the agent. Same logic, no UI.
- `gemini_client.py` — Smart model fallback. `smart_generate()` tries
  models in MODEL_CHAIN order, catches 429/503/404, auto-switches.
  Both the agent page and atlas.py import from here.
- `connector_health.py` — Pure (no-Streamlit) helpers shared by the inline
  health check (agent page) and the Connector Health page:
  `gather_connectors()`, `health_totals()`, `humanize_timestamp()`,
  `status_level()`. Reads the simulated Fivetran tools.
- `schema_diff.py` — Before/after schema preview. `build_schema_diff(scan_or_None,
  table, column, operation, new_name)` returns two column lists with
  `highlight` ∈ {none, target, changed}; `render_diff_table_html(rows, side,
  operation)` returns a styled HTML table. Falls back to the active lineage
  graph's columns when no DB scan is present. Operations: drop, rename,
  disable_table.

### Data Layer
- `lineage.py` — Mock downstream lineage engine.
  Functions: `load_graph()`, `load_default()`, `find_downstream()`,
  `get_owner()`, `get_deprecation_policy()`, `summarize_impact()`,
  `calculate_semantic_risk()` (column severity), and the table-level pair
  `summarize_table_impact()` / `calculate_table_risk()` (aggregate impact +
  severity for disabling a whole table), plus `get_table_columns()`.
  Module-level `_GRAPH` global swappable at runtime.
- `lineage.json` — Seeded demo data. 3 tables:
  - `stripe.customers` (columns: id, email, customer_segment, created_at)
  - `stripe.subscriptions` (columns: id, customer_id, status, plan_name)
  - `hubspot.deals` (columns: deal_id, amount, deal_stage, lead_source_legacy)
  Each column has downstream assets (dbt_model, dashboard, ml_feature,
  scheduled_report) with owner teams and criticality tiers (tier_1/2/3).
  Owners section maps team names to slack/email/lead.

### Fivetran Integration
- `fivetran_tools.py` — Simulated Fivetran MCP tools. Same tool names
  and response shapes as the official `fivetran/fivetran-mcp` server.py.
  In-memory fixture with four connections:
  - `stripe_main_001` (service: stripe, schema: stripe)
  - `hubspot_crm_002` (service: hubspot, schema: hubspot)
  - `salesforce_crm_003` (service: salesforce, schema: salesforce)
  - `zendesk_support_004` (service: zendesk, schema: zendesk)
  Tools: `list_connections()`, `get_connection_details()`,
  `get_connection_state()`, `get_connection_schema_config()`,
  `modify_connection_column_config()` (drop/deprecate),
  `rename_column_config()` (rename), `disable_table_sync()` (disable table),
  `rollback_column_config()` (undo), `sync_connection()`,
  `get_change_log()`, `clear_change_log()`.
  Changes mutate the in-memory fixture and are tracked in `_FIXTURE["change_log"]`
  (actions: modify_connection_column_config, rename_column_config,
  disable_table_sync, rollback_column_config, sync_connection).
  Response envelope: `{"code": "Success", "data": {...}}` or `{"code": "Error", "message": "..."}`.

### Database Auto-Discovery
- `db_scanner.py` — SQLite schema discovery (stdlib `sqlite3`, no new dep).
  Functions: `scan_sqlite(file_bytes)`, `scan_postgres(connection_string)`
  (placeholder stub — returns "coming soon"), `build_discovery_report(scan_result)`.
  `scan_sqlite` returns `{"tables": {name: {columns, foreign_keys}}, "table_count",
  "column_count", "fk_count"}`. Discovery only — does NOT build a lineage graph
  (that's the Gemini-inference step, planned next).
- `create_demo_db.py` — Generates `demo_warehouse.db` (run `python create_demo_db.py`).
  6 tables: stripe_customers, stripe_subscriptions, stripe_invoices,
  hubspot_deals, hubspot_contacts, analytics_mrr_by_segment. Coherent data
  with matching ids across tables.
- `demo_warehouse.db` — Bundled SQLite demo warehouse (generated, ships with repo).
- `lineage_inference.py` — AI-powered lineage inference (Day 6). Takes a
  `db_scanner` scan result and asks Gemini (via `smart_generate`) to infer
  downstream lineage for every column, returning a dict in lineage.json shape.
  Functions: `infer_lineage_from_schema(scan_result, gemini_client, feedback="")`,
  `validate_inferred_lineage(lineage_dict) -> (bool, errors)`. Owners and
  criticality_levels are synthesized deterministically from `TEAM_DIRECTORY`
  (7 allowed teams); the model only produces the `tables` block, which is
  normalized (unknown teams→analytics, unknown tiers→tier_3). On any failure
  returns `{"error": ...}`. app.py renders the result in an editable
  `st.data_editor` review panel before the user accepts it via `load_graph()`.
  `demo_cache.check_inference_cache()` serves a pre-baked inference for
  `demo_warehouse.db` (matched by table-name set) so the demo uses zero quota.

### Caching & Resilience
- `demo_cache.py` — Pre-cached responses for 3 demo scenarios so the app
  works with ZERO Gemini API quota. Functions: `check_analysis_cache()`,
  `check_execution_cache()`, `check_inference_cache()`. Fuzzy matches on
  keywords in the request (or table-name set for inference).
  Cached scenarios:
  1. "customer_segment" + "stripe" → full CRITICAL report
  2. "lead_source_legacy" + "hubspot" → zero-impact INFO report
  3. "discount_code" + "stripe" → column not found
  4. `demo_warehouse.db` table set → full inferred lineage (6 tables)

### Config
- `.env` — Contains `GEMINI_API_KEY=...` (NEVER committed, gitignored)
- `.gitignore` — Covers: .env, __pycache__/, *.pyc, .venv/, reports/, test_upload.*
- `requirements.txt` — streamlit, google-genai, python-dotenv, requests
- `.streamlit/config.toml` — Theme config only
- `LICENSE` — MIT

### Static Assets
- `screenshots/` — UI screenshots for README (5 images)
- `README.md` — Project documentation with architecture diagram, screenshots,
  setup instructions, Fivetran integration explanation

## Key Design Decisions (DO NOT CHANGE without asking)

1. **Fivetran tools are simulated, not live.** We don't have Fivetran API
   credentials. The tools match the real MCP interface exactly. This is
   intentional and disclosed in the README. Do not try to add real API calls.

2. **Two-phase agent loop.** Analysis uses read-only tools. Execution uses
   write tools. Write tools are NEVER available during analysis. This is a
   safety architecture, not a convenience choice. Do not merge the phases.

3. **Deterministic severity ranking.** The severity badge (CRITICAL/HIGH/
   WARNING/INFO) is calculated by Python code, NOT by Gemini. This is
   intentional — hybrid AI where the LLM cannot hallucinate severity.
   Do not move severity calculation into the LLM prompt.

4. **Demo cache returns real tool_log entries.** The cached scenarios
   include tool_log data so the UI renders identically to live runs
   (severity badges, notification cards, etc.).

5. **Model fallback chain.** gemini_client.py tries multiple models.
   If you add models to MODEL_CHAIN, only add valid text-generation
   Gemini models (not TTS, not Gemma, not Imagen).

6. **Notifications are user-configured at runtime.** Slack webhook,
   Telegram bot token, and chat ID are entered in the sidebar by the
   user. They are NOT stored in .env or environment variables.

## Conventions

- **Python style:** Simple, readable. The developer is intermediate-level.
  No metaclasses, no decorators beyond basics, no async complexity.
- **Imports:** Use google.genai (NOT the deprecated google.generativeai).
- **Git commits:** Descriptive messages. Push to `main` branch.
- **Git config:** Commit as `yusufsaheed2012` / `codeddevs.team@gmail.com`
- **Testing:** Each .py file has an `if __name__ == "__main__":` self-test.
  Run `python <file>.py` to verify.
- **No new dependencies** without explicit approval. Everything should work
  with what's in requirements.txt.

## Common Pitfalls (things that have gone wrong before)

1. **datetime.utcnow()** is deprecated in Python 3.14. Use
   `datetime.now(tz=timezone.utc)` instead.
2. **Streamlit reruns the entire script** on every interaction. Use
   `st.session_state` for persistence across reruns.
3. **Free-tier Gemini has 20 RPD per model.** The fallback chain handles
   this, but test sparingly. Demo cache exists for a reason.
4. **Streamlit Cloud needs secrets configured separately.** The .env file
   doesn't exist there. GEMINI_API_KEY must be set in the Streamlit Cloud
   dashboard under Settings → Secrets.
5. **Line endings:** Windows CRLF vs Unix LF. Git handles this but you'll
   see warnings. Ignore them.
6. **graphviz** — if adding visual graphs, use `st.graphviz_chart()` which
   is built into Streamlit. Do NOT add graphviz as a pip dependency unless
   Streamlit's built-in doesn't work. Check Streamlit docs first.

## The Three Demo Scenarios

These are the canonical test cases. Any new feature MUST work for all three:

1. **CRITICAL:** "Drop customer_segment from stripe.customers"
   → 5 downstream assets, 2 tier-1, severity CRITICAL, 14-day notice,
   5 stakeholder messages, full execution lifecycle

2. **SAFE:** "Drop lead_source_legacy from hubspot.deals"
   → 0 downstream assets, severity INFO, immediate drop OK,
   no stakeholder notifications

3. **NOT FOUND:** "Drop discount_code from stripe.customers"
   → Column not in lineage graph, no analysis, no execution

## What We're Building Next

Features in priority order (may already be done by the time you read this):
- Visual lineage graph (Graphviz dependency diagram)
- Rollback capability (undo a deprecation)
- More change types (rename column, disable table sync)
- Schema diff preview (before/after comparison)
- Audit dashboard (multi-page app with action history)
- Business impact estimator (risk quantification)

## Hackathon Judging Criteria

Each 25% of total score:
1. **Technological Implementation** — quality of Gemini + Fivetran integration
2. **Design** — UX polish and visual quality
3. **Potential Impact** — scale of problem solved
4. **Quality of the Idea** — creativity and originality

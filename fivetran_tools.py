"""
fivetran_tools.py — Simulated Fivetran MCP tools for the Atlas demo.

These functions match the EXACT tool names and response shapes from the
official Fivetran MCP server (github.com/fivetran/fivetran-mcp).

In the demo, Atlas calls these functions instead of the live MCP. The interface
is identical, so swapping to the real MCP is a one-line import change once
Fivetran trial credentials are available.

Tool coverage:
  - list_connections          (discover what pipelines exist)
  - get_connection_details    (sync health, schedule, status)
  - get_connection_state      (current sync state)
  - get_connection_schema_config  (which tables/columns are synced)
  - modify_connection_column_config  (soft-deprecate a column)
  - sync_connection           (trigger verification sync)

This is enough for Atlas's full lifecycle: discover -> analyze ->
plan -> approve -> execute -> verify.
"""

from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# In-memory fixture — simulates a small Fivetran account with three connectors
# ---------------------------------------------------------------------------

_NOW = datetime.now(tz=timezone.utc)

_FIXTURE = {
    "connections": {
        "stripe_main_001": {
            "id": "stripe_main_001",
            "service": "stripe",
            "schema": "stripe",
            "group_id": "group_prod_42",
            "paused": False,
            "sync_frequency": 60,
            "status": {
                "setup_state": "connected",
                "sync_state": "scheduled",
                "update_state": "on_schedule",
                "is_historical_sync": False,
                "tasks": [],
                "warnings": [],
                "succeeded_at": (_NOW - timedelta(minutes=12)).isoformat() + "Z",
                "failed_at": None,
            },
            "schemas": {
                "stripe": {
                    "name_in_destination": "stripe",
                    "enabled": True,
                    "tables": {
                        "customers": {
                            "name_in_destination": "customers",
                            "enabled": True,
                            "sync_mode": "SOFT_DELETE",
                            "columns": {
                                "id":               {"name_in_destination": "id",               "enabled": True,  "hashed": False, "is_primary_key": True},
                                "email":            {"name_in_destination": "email",            "enabled": True,  "hashed": False, "is_primary_key": False},
                                "customer_segment": {"name_in_destination": "customer_segment", "enabled": True,  "hashed": False, "is_primary_key": False},
                                "created_at":       {"name_in_destination": "created_at",       "enabled": True,  "hashed": False, "is_primary_key": False},
                            },
                        },
                        "subscriptions": {
                            "name_in_destination": "subscriptions",
                            "enabled": True,
                            "sync_mode": "SOFT_DELETE",
                            "columns": {
                                "id":          {"name_in_destination": "id",          "enabled": True,  "hashed": False, "is_primary_key": True},
                                "customer_id": {"name_in_destination": "customer_id", "enabled": True,  "hashed": False, "is_primary_key": False},
                                "status":      {"name_in_destination": "status",      "enabled": True,  "hashed": False, "is_primary_key": False},
                                "plan_name":   {"name_in_destination": "plan_name",   "enabled": True,  "hashed": False, "is_primary_key": False},
                            },
                        },
                    },
                },
            },
        },
        "hubspot_crm_002": {
            "id": "hubspot_crm_002",
            "service": "hubspot",
            "schema": "hubspot",
            "group_id": "group_prod_42",
            "paused": False,
            "sync_frequency": 360,
            "status": {
                "setup_state": "connected",
                "sync_state": "scheduled",
                "update_state": "on_schedule",
                "is_historical_sync": False,
                "tasks": [],
                "warnings": [],
                "succeeded_at": (_NOW - timedelta(hours=2)).isoformat() + "Z",
                "failed_at": None,
            },
            "schemas": {
                "hubspot": {
                    "name_in_destination": "hubspot",
                    "enabled": True,
                    "tables": {
                        "deals": {
                            "name_in_destination": "deals",
                            "enabled": True,
                            "sync_mode": "SOFT_DELETE",
                            "columns": {
                                "deal_id":            {"name_in_destination": "deal_id",            "enabled": True,  "hashed": False, "is_primary_key": True},
                                "amount":             {"name_in_destination": "amount",             "enabled": True,  "hashed": False, "is_primary_key": False},
                                "deal_stage":         {"name_in_destination": "deal_stage",         "enabled": True,  "hashed": False, "is_primary_key": False},
                                "lead_source_legacy": {"name_in_destination": "lead_source_legacy", "enabled": True,  "hashed": False, "is_primary_key": False},
                            },
                        },
                    },
                },
            },
        },
        "salesforce_crm_003": {
            "id": "salesforce_crm_003",
            "service": "salesforce",
            "schema": "salesforce",
            "group_id": "group_prod_42",
            "paused": False,
            "sync_frequency": 60,
            "status": {
                "setup_state": "connected",
                "sync_state": "scheduled",
                "update_state": "on_schedule",
                "is_historical_sync": False,
                "tasks": [],
                "warnings": [],
                "succeeded_at": (_NOW - timedelta(minutes=5)).isoformat() + "Z",
                "failed_at": None,
            },
            "schemas": {
                "salesforce": {
                    "name_in_destination": "salesforce",
                    "enabled": True,
                    "tables": {
                        "opportunities": {
                            "name_in_destination": "opportunities",
                            "enabled": True,
                            "sync_mode": "SOFT_DELETE",
                            "columns": {
                                "id":             {"name_in_destination": "id",             "enabled": True,  "hashed": False, "is_primary_key": True},
                                "amount":         {"name_in_destination": "amount",         "enabled": True,  "hashed": False, "is_primary_key": False},
                                "stage_name":     {"name_in_destination": "stage_name",     "enabled": True,  "hashed": False, "is_primary_key": False},
                                "forecast_category": {"name_in_destination": "forecast_category", "enabled": True,  "hashed": False, "is_primary_key": False},
                            },
                        },
                    },
                },
            },
        },
        "zendesk_support_004": {
            "id": "zendesk_support_004",
            "service": "zendesk",
            "schema": "zendesk",
            "group_id": "group_prod_42",
            "paused": False,
            "sync_frequency": 15,
            "status": {
                "setup_state": "connected",
                "sync_state": "scheduled",
                "update_state": "on_schedule",
                "is_historical_sync": False,
                "tasks": [],
                "warnings": [],
                "succeeded_at": (_NOW - timedelta(minutes=2)).isoformat() + "Z",
                "failed_at": None,
            },
            "schemas": {
                "zendesk": {
                    "name_in_destination": "zendesk",
                    "enabled": True,
                    "tables": {
                        "tickets": {
                            "name_in_destination": "tickets",
                            "enabled": True,
                            "sync_mode": "SOFT_DELETE",
                            "columns": {
                                "id":             {"name_in_destination": "id",             "enabled": True,  "hashed": False, "is_primary_key": True},
                                "subject":        {"name_in_destination": "subject",        "enabled": True,  "hashed": False, "is_primary_key": False},
                                "status":         {"name_in_destination": "status",         "enabled": True,  "hashed": False, "is_primary_key": False},
                                "priority":       {"name_in_destination": "priority",       "enabled": True,  "hashed": False, "is_primary_key": False},
                                "custom_nps_score": {"name_in_destination": "custom_nps_score", "enabled": True,  "hashed": False, "is_primary_key": False},
                            },
                        },
                    },
                },
            },
        },
    },
    # Track changes Atlas makes during the session (so the demo can prove execution worked)
    "change_log": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _success(data: dict) -> dict:
    """Wrap a payload in Fivetran's standard envelope."""
    return {"code": "Success", "data": data}


def _error(message: str) -> dict:
    return {"code": "Error", "message": message}


def _find_connection_by_table(schema_name: str) -> dict | None:
    """Helper: which connection owns this destination schema?"""
    for conn in _FIXTURE["connections"].values():
        if schema_name in conn["schemas"]:
            return conn
    return None


# ---------------------------------------------------------------------------
# Tools — names and shapes match the official Fivetran MCP server
# ---------------------------------------------------------------------------

def list_connections() -> dict:
    """List all Fivetran connections in the account.

    Real endpoint: GET /v1/connections
    """
    items = []
    for conn in _FIXTURE["connections"].values():
        items.append({
            "id": conn["id"],
            "service": conn["service"],
            "schema": conn["schema"],
            "group_id": conn["group_id"],
            "paused": conn["paused"],
            "sync_frequency": conn["sync_frequency"],
            "succeeded_at": conn["status"]["succeeded_at"],
            "failed_at": conn["status"]["failed_at"],
        })
    return _success({"items": items, "_total_items": len(items)})


def get_connection_details(connection_id: str) -> dict:
    """Get full configuration and status for a connection.

    Real endpoint: GET /v1/connections/{connection_id}
    """
    conn = _FIXTURE["connections"].get(connection_id)
    if not conn:
        return _error(f"Connection '{connection_id}' not found")

    return _success({
        "id": conn["id"],
        "service": conn["service"],
        "schema": conn["schema"],
        "group_id": conn["group_id"],
        "paused": conn["paused"],
        "sync_frequency": conn["sync_frequency"],
        "status": conn["status"],
    })


def get_connection_state(connection_id: str) -> dict:
    """Get the current sync state of a connection.

    Real endpoint: GET /v1/connections/{connection_id}/state
    """
    conn = _FIXTURE["connections"].get(connection_id)
    if not conn:
        return _error(f"Connection '{connection_id}' not found")

    return _success({
        "id": conn["id"],
        "sync_state": conn["status"]["sync_state"],
        "update_state": conn["status"]["update_state"],
        "succeeded_at": conn["status"]["succeeded_at"],
        "failed_at": conn["status"]["failed_at"],
    })


def get_connection_schema_config(connection_id: str) -> dict:
    """Get the schema configuration — which schemas, tables, columns are synced.

    Real endpoint: GET /v1/connections/{connection_id}/schemas
    """
    conn = _FIXTURE["connections"].get(connection_id)
    if not conn:
        return _error(f"Connection '{connection_id}' not found")

    return _success({
        "schema_change_handling": "ALLOW_ALL",
        "schemas": conn["schemas"],
    })


def modify_connection_column_config(
    connection_id: str,
    schema_name: str,
    table_name: str,
    column_name: str,
    enabled: bool,
) -> dict:
    """Update a column's sync configuration. Setting enabled=False soft-deprecates
    the column — it stops being written to the warehouse on the next sync,
    but the column itself is not deleted from the destination.

    Real endpoint: PATCH /v1/connections/{connection_id}/schemas/{schema}/tables/{table}/columns/{column}
    """
    conn = _FIXTURE["connections"].get(connection_id)
    if not conn:
        return _error(f"Connection '{connection_id}' not found")

    schema = conn["schemas"].get(schema_name)
    if not schema:
        return _error(f"Schema '{schema_name}' not found in connection")

    table = schema["tables"].get(table_name)
    if not table:
        return _error(f"Table '{table_name}' not found in schema '{schema_name}'")

    column = table["columns"].get(column_name)
    if not column:
        return _error(f"Column '{column_name}' not found in table '{table_name}'")

    # Apply the change
    old_value = column["enabled"]
    column["enabled"] = enabled

    # Log it (so the demo can prove the change happened)
    _FIXTURE["change_log"].append({
        "timestamp": datetime.now(tz=timezone.utc).isoformat() + "Z",
        "action": "modify_connection_column_config",
        "connection_id": connection_id,
        "target": f"{schema_name}.{table_name}.{column_name}",
        "change": f"enabled: {old_value} -> {enabled}",
    })

    return _success({
        "connection_id": connection_id,
        "schema": schema_name,
        "table": table_name,
        "column": column_name,
        "enabled": enabled,
        "applied_at": datetime.now(tz=timezone.utc).isoformat() + "Z",
    })


def rollback_column_config(
    connection_id: str,
    schema_name: str,
    table_name: str,
    column_name: str,
) -> dict:
    """Undo a soft-deprecation by re-enabling a column (sets enabled=True).

    This is the inverse of modify_connection_column_config(enabled=False). It
    logs a distinct "rollback_column_config" action so the change log clearly
    shows the reversal — proof that Atlas can safely undo a change.

    Real endpoint: PATCH /v1/connections/{connection_id}/schemas/{schema}/tables/{table}/columns/{column}
    """
    conn = _FIXTURE["connections"].get(connection_id)
    if not conn:
        return _error(f"Connection '{connection_id}' not found")

    schema = conn["schemas"].get(schema_name)
    if not schema:
        return _error(f"Schema '{schema_name}' not found in connection")

    table = schema["tables"].get(table_name)
    if not table:
        return _error(f"Table '{table_name}' not found in schema '{schema_name}'")

    column = table["columns"].get(column_name)
    if not column:
        return _error(f"Column '{column_name}' not found in table '{table_name}'")

    # Re-enable the column.
    old_value = column["enabled"]
    column["enabled"] = True

    _FIXTURE["change_log"].append({
        "timestamp": datetime.now(tz=timezone.utc).isoformat() + "Z",
        "action": "rollback_column_config",
        "connection_id": connection_id,
        "target": f"{schema_name}.{table_name}.{column_name}",
        "change": f"enabled: {old_value} -> True",
    })

    return _success({
        "connection_id": connection_id,
        "schema": schema_name,
        "table": table_name,
        "column": column_name,
        "enabled": True,
        "rolled_back_at": datetime.now(tz=timezone.utc).isoformat() + "Z",
    })


def sync_connection(connection_id: str) -> dict:
    """Trigger a sync for a connection. Used after a schema change to verify
    everything still works end-to-end.

    Real endpoint: POST /v1/connections/{connection_id}/sync
    """
    conn = _FIXTURE["connections"].get(connection_id)
    if not conn:
        return _error(f"Connection '{connection_id}' not found")

    # Simulate a successful sync trigger
    _FIXTURE["change_log"].append({
        "timestamp": datetime.now(tz=timezone.utc).isoformat() + "Z",
        "action": "sync_connection",
        "connection_id": connection_id,
        "target": connection_id,
        "change": "triggered manual sync",
    })

    return _success({
        "connection_id": connection_id,
        "status": "sync_triggered",
        "message": "Sync has been queued and will start shortly.",
    })


# ---------------------------------------------------------------------------
# Demo helper — useful for the video and for self-testing
# ---------------------------------------------------------------------------

def get_change_log() -> list:
    """Return all changes Atlas has made in this session. Not a real Fivetran
    endpoint — exists so the demo can prove the execution actually happened.
    """
    return list(_FIXTURE["change_log"])


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    print("=== fivetran_tools.py self-test ===\n")

    print("1. list_connections():")
    print(json.dumps(list_connections(), indent=2))

    print("\n2. get_connection_details('stripe_main_001'):")
    print(json.dumps(get_connection_details("stripe_main_001"), indent=2))

    print("\n3. get_connection_schema_config('stripe_main_001'):")
    schema = get_connection_schema_config("stripe_main_001")
    # Print just the table names to keep output readable
    tables = list(schema["data"]["schemas"]["stripe"]["tables"].keys())
    print(f"   Tables synced: {tables}")

    print("\n4. modify_connection_column_config — soft-deprecate customer_segment:")
    result = modify_connection_column_config(
        connection_id="stripe_main_001",
        schema_name="stripe",
        table_name="customers",
        column_name="customer_segment",
        enabled=False,
    )
    print(json.dumps(result, indent=2))

    print("\n5. sync_connection('stripe_main_001'):")
    print(json.dumps(sync_connection("stripe_main_001"), indent=2))

    print("\n6. rollback_column_config — re-enable customer_segment (undo step 4):")

    def _enabled(col):
        return (_FIXTURE["connections"]["stripe_main_001"]["schemas"]["stripe"]
                ["tables"]["customers"]["columns"][col]["enabled"])

    print(f"   enabled before rollback: {_enabled('customer_segment')}  (was True, set to False in step 4)")
    rollback = rollback_column_config(
        connection_id="stripe_main_001",
        schema_name="stripe",
        table_name="customers",
        column_name="customer_segment",
    )
    print(json.dumps(rollback, indent=2))
    print(f"   enabled after rollback:  {_enabled('customer_segment')}")
    print("   -> full lifecycle observed: True -> False (modify) -> True (rollback)")

    print("\n7. Change log (proves modify, sync, and rollback all happened):")
    print(json.dumps(get_change_log(), indent=2))

    print("\n8. Error handling — bad connection ID:")
    print(json.dumps(get_connection_details("does_not_exist"), indent=2))

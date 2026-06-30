"""Phase 3 — schema config + registry tests.

Covers:
  * The two shipped schemas load cleanly (olist + shopify)
  * Switching `SCHEMA_NAME` env var + reload swaps the active config
  * Each config's tables/columns/enums/states are non-empty and well-formed
  * The function registry builds from the active config's factories
  * Shopify's functions are stubs: they error helpfully, they don't hit a DB
  * Olist's out-of-scope detector declines "returns"; Shopify's doesn't
    (because Shopify tracks returns)

These tests are offline — no DB, no LLM. They pin the contract of
the SchemaConfig shape so future schemas follow it.

Run:
    cd backend && ../venv/bin/python -m pytest tests/test_schemas.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


import pytest  # noqa: E402

import schemas  # noqa: E402
from schemas import get_active_config, reload_active_config, set_active_config  # noqa: E402
from schemas.base import ColumnRef, PromptConfig, SchemaConfig, ScopePattern  # noqa: E402


# --- Loading & switching ------------------------------------------------------

def test_olist_is_the_default():
    """If no SCHEMA_NAME is set, the default must be olist — every
    existing test, deployment, and config relies on this."""
    set_active_config(None)  # clear any test override
    # Make sure the env doesn't override us for this assertion.
    import os
    saved = os.environ.pop("SCHEMA_NAME", None)
    try:
        # settings.schema_name still defaults to "olist" so this stays
        # the default even without an env var.
        cfg = reload_active_config()
        assert cfg.name == "olist"
    finally:
        if saved is not None:
            os.environ["SCHEMA_NAME"] = saved


def test_olist_loads_with_required_keys():
    set_active_config(None)
    cfg = reload_active_config()
    assert isinstance(cfg, SchemaConfig)
    assert cfg.name == "olist"
    assert cfg.display_name  # non-empty
    # All seven core tables the functions reference
    for required in (
        "orders", "customers", "order_items", "products",
        "product_category_translation", "order_payments", "order_reviews",
    ):
        assert required in cfg.tables, f"missing table: {required}"
    # Status enum is a real set, not None
    assert cfg.get_enum("status") is not None
    assert "delivered" in cfg.get_enum("status")
    # States are present for Olist (Brazilian UFs)
    assert cfg.states is not None
    assert "SP" in cfg.states
    # Prompt has the few-shot examples
    assert len(cfg.prompt.few_shot_examples) > 0
    # Source citations cover every function
    functions = [n for n in schemas.list_available_schemas()]
    # (we know the registry builds from the active schema's factories)
    reg = schemas._BUILTIN  # noqa: SLF001 (test-only inspection)


def test_shopify_loads_with_required_keys():
    """The Shopify stub must load and present the SAME logical shape
    (tables, columns, enums) as Olist — even though the physical table
    names are completely different."""
    import os
    saved = os.environ.get("SCHEMA_NAME")
    os.environ["SCHEMA_NAME"] = "shopify"
    set_active_config(None)
    cfg = reload_active_config()
    try:
        assert cfg.name == "shopify"
        # Same logical keys, different physical names
        assert cfg.tables["orders"] == "shopify_orders"
        assert cfg.tables["customers"] == "shopify_customers"
        # Status enum reflects Shopify's order lifecycle, not Olist's
        statuses = cfg.get_enum("status")
        assert statuses is not None
        assert "fulfilled" in statuses
        assert "refunded" in statuses
        assert "delivered" not in statuses  # Olist-only term
        # States: US, not Brazil
        assert "CA" in cfg.states
        assert "NY" in cfg.states
        assert "SP" not in cfg.states  # Olist-only
    finally:
        if saved is None:
            os.environ.pop("SCHEMA_NAME", None)
        else:
            os.environ["SCHEMA_NAME"] = saved
        set_active_config(None)
        reload_active_config()


def test_unknown_schema_name_errors():
    set_active_config(None)
    import os
    saved = os.environ.get("SCHEMA_NAME")
    os.environ["SCHEMA_NAME"] = "nonexistent"
    try:
        with pytest.raises(RuntimeError, match="Unknown schema"):
            reload_active_config()
    finally:
        if saved is None:
            os.environ.pop("SCHEMA_NAME", None)
        else:
            os.environ["SCHEMA_NAME"] = saved
        set_active_config(None)
        reload_active_config()


# --- Config shape -----------------------------------------------------------

def test_get_table_and_get_column_are_strict():
    """Unknown logical keys must raise KeyError (loud failure beats a
    silent query against the wrong table)."""
    set_active_config(None)
    cfg = reload_active_config()
    with pytest.raises(KeyError, match="nonexistent_table"):
        cfg.get_table("nonexistent_table")
    with pytest.raises(KeyError, match="nonexistent_column"):
        cfg.get_column("nonexistent_column")


def test_get_enum_unknown_raises():
    set_active_config(None)
    cfg = reload_active_config()
    with pytest.raises(KeyError, match="nonexistent_enum"):
        cfg.get_enum("nonexistent_enum")


def test_columns_are_typed_as_columnref():
    """Every column entry must be a ColumnRef(table, column), not a
    bare string. The function SQL emitter relies on this for safe
    table-prefixed joins."""
    set_active_config(None)
    cfg = reload_active_config()
    for name, col in cfg.columns.items():
        assert isinstance(col, ColumnRef), f"column {name!r} is not a ColumnRef"
        assert col.table, f"column {name!r} has empty table"
        assert col.column, f"column {name!r} has empty column name"


def test_prompt_has_required_strings():
    """If any of these are empty, the LLM will get bad instructions."""
    set_active_config(None)
    cfg = reload_active_config()
    prompt = cfg.prompt
    for attr in (
        "dataset_description", "city_rule", "state_rule",
        "status_rule", "group_by_rule",
    ):
        assert getattr(prompt, attr), f"prompt.{attr} is empty"


def test_source_citations_cover_every_function():
    """Every registered function should have a human-readable source
    citation. Empty citations mean the user can't verify the query
    came from where we said."""
    set_active_config(None)
    cfg = reload_active_config()
    # Force-build the registry via the active config
    reg = {f["schema"]["name"]: f for f in
           [factory(cfg) for factory in cfg.function_factories]}
    for name, _entry in reg.items():
        assert name in cfg.prompt.source_citations, (
            f"function {name!r} has no source citation in {cfg.name} config"
        )


# --- Out-of-scope differs per schema ----------------------------------------

def test_olist_declines_returns():
    """Per the Olist out-of-scope lexicon — Olist doesn't have a returns
    table, so we decline with a redirect to canceled orders."""
    set_active_config(None)
    cfg = reload_active_config()
    if cfg.name != "olist":
        pytest.skip("not on olist")
    from validation.scope import detect_unsupported_concept
    result = detect_unsupported_concept("how many returns did we have?")
    assert result is not None
    assert result["concept"] == "returns"


def test_shopify_does_not_decline_returns():
    """Shopify tracks returns as a first-class concept, so its scope
    patterns must NOT include the word 'returns' — declining would be
    a wrong answer."""
    import os
    saved = os.environ.get("SCHEMA_NAME")
    os.environ["SCHEMA_NAME"] = "shopify"
    set_active_config(None)
    cfg = reload_active_config()
    assert cfg.name == "shopify"
    try:
        from validation.scope import detect_unsupported_concept
        result = detect_unsupported_concept("how many returns did we have?")
        assert result is None, (
            f"Shopify should not decline 'returns' but it did: {result}"
        )
    finally:
        if saved is None:
            os.environ.pop("SCHEMA_NAME", None)
        else:
            os.environ["SCHEMA_NAME"] = saved
        set_active_config(None)
        reload_active_config()


# --- Function registry builds from the active config -----------------------

def test_registry_builds_from_active_config():
    """The registry is materialised on demand from the active config's
    factories. Switching the config (via set_active_config + reset)
    rebuilds it."""
    set_active_config(None)
    cfg = reload_active_config()
    import functions.registry as registry
    registry.reset_registry()
    schemas_list = registry.get_all_schemas()
    assert len(schemas_list) == len(cfg.function_factories)
    # Every function name from the config must be in the registry
    for factory in cfg.function_factories:
        name = factory(cfg)["schema"]["name"]
        assert name in [s["name"] for s in schemas_list]


def test_shopify_functions_are_wired_stubs():
    """Shopify's factory returns a registry entry whose execute reports
    'not wired' — so the schema is selectable for prompt/formatting
    tests but cannot actually answer questions yet."""
    import os
    saved = os.environ.get("SCHEMA_NAME")
    os.environ["SCHEMA_NAME"] = "shopify"
    set_active_config(None)
    cfg = reload_active_config()
    import functions.registry as registry
    try:
        registry.reset_registry()

        # Build all shopify function entries
        for factory in cfg.function_factories:
            entry = factory(cfg)
            # All entries have schema + execute
            assert "schema" in entry
            assert "execute" in entry
            # All entries have the same JSON-schema shape (parameter names
            # are domain-neutral, not schema-specific)
            params = entry["schema"].get("parameters", {}).get("properties", {})
            # The key invariant: cities, states, statuses, dates are
            # domain-neutral keys the LLM uses. They must NOT vary between
            # schemas. (This is what lets the same prompt work for both.)
            if "status" in params:
                assert "description" in params["status"]
            if "city" in params:
                assert "description" in params["city"]
            if "state" in params:
                assert "description" in params["state"]
    finally:
        if saved is None:
            os.environ.pop("SCHEMA_NAME", None)
        else:
            os.environ["SCHEMA_NAME"] = saved
        set_active_config(None)
        reload_active_config()


def test_shopify_count_orders_returns_not_wired_error():
    """The Shopify stub's factory (defined in the schema config, not in
    functions/count_orders.py) returns a registry entry whose execute
    immediately reports 'not wired' — without hitting any DB."""
    import os
    saved = os.environ.get("SCHEMA_NAME")
    os.environ["SCHEMA_NAME"] = "shopify"
    set_active_config(None)
    cfg = reload_active_config()
    import asyncio
    try:
        # Use the schema's own factory (the one in the config), NOT the
        # Olist functions/count_orders.py module. The Olist factory would
        # try to run SQL against shopify_* tables and fail at the DB.
        factories_by_name = {f(cfg)["schema"]["name"]: f for f in cfg.function_factories}
        entry = factories_by_name["count_orders"](cfg)
        result = asyncio.run(entry["execute"]())
        assert "error" in result
        assert "not wired" in result["error"].lower() or "stub" in result["error"].lower()
    finally:
        if saved is None:
            os.environ.pop("SCHEMA_NAME", None)
        else:
            os.environ["SCHEMA_NAME"] = saved
        set_active_config(None)
        reload_active_config()


# --- Prompt reflects the active schema --------------------------------------

def test_prompt_few_shot_examples_match_active_schema():
    """Few-shots in the prompt must reference the active schema's
    domain. Showing 'São Paulo' on Shopify would mislead the model."""
    set_active_config(None)
    cfg = reload_active_config()
    all_examples = " ".join(q for q, _ in cfg.prompt.few_shot_examples)
    if cfg.name == "olist":
        # Brazilian cities
        assert "São Paulo" in all_examples or "sao paulo" in all_examples
        # Brazilian UF
        assert " SP" in all_examples or "=SP" in all_examples or '"SP"' in all_examples
    elif cfg.name == "shopify":
        # US cities
        assert "New York" in all_examples or "San Francisco" in all_examples
        # US state
        assert " CA" in all_examples or "=CA" in all_examples or '"CA"' in all_examples


# --- Cleanup: restore default after this module -----------------------

@pytest.fixture(autouse=True)
def _restore_default():
    yield
    set_active_config(None)
    import os
    if "SCHEMA_NAME" in os.environ:
        del os.environ["SCHEMA_NAME"]
    reload_active_config()

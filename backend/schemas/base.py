"""SchemaConfig — the contract every per-schema config must implement.

A SchemaConfig is a frozen dataclass that describes everything in the
backend that varies between schemas: table names, column references,
enum values, geographic state codes, the out-of-scope lexicon, the
system-prompt text and few-shot examples, the source-citation strings,
and the function factory list.

Every place in the backend that hardcoded a value specific to one
schema now reads from the active config. The result: a new customer DB
is onboarded by writing one config module under `schemas/<name>/config.py`
and setting `SCHEMA=<name>` in the environment.

Design notes
------------

* Why a dataclass and not a dict?  Type-checked attribute access, frozen
  instances make the active config a global singleton that's safe to
  pass around, and `dataclasses.replace` lets tests do per-test overrides
  without rebuilding the whole object.

* Why expose `display_name`?  The system prompt and the
  `result.formatted_answer` reference the schema by name ("this dataset
  doesn't track X" — but in WHICH dataset?). A single string here keeps
  every error message and prompt consistent.

* Why are columns a `ColumnRef` rather than a bare string?  Some columns
  are in different tables depending on the schema. `customer_city` lives
  in `olist_customers_dataset` in Olist and in `shopify_addresses` in
  Shopify (hypothetically). The `ColumnRef` lets the SQL builder emit
  the right JOIN without the function code caring.

* Why is the system prompt in the config?  Two reasons. (1) The
  few-shot examples must reference the right entity names for the active
  schema — "São Paulo" doesn't help on Shopify. (2) The status/state
  rules are domain-specific ("Brazilian UF codes" vs "US state
  abbreviations"). One config, one prompt, zero string surgery at
  runtime.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class ColumnRef:
    """A logical column reference: which table, which column on it."""
    table: str           # key into SchemaConfig.tables
    column: str          # physical column name on that table


@dataclass(frozen=True)
class ScopePattern:
    """An out-of-scope concept the schema can't answer, with a friendly
    explanation that names a *nearest* signal the schema DOES have.

    Per the project thesis: when a user asks about a concept the schema
    doesn't track, we decline honestly rather than mapping to a proxy
    and returning a confidently-wrong number.
    """
    pattern: str          # regex; word-boundaried
    concept: str          # human-readable label
    suggestion: str       # what the schema DOES have instead


@dataclass(frozen=True)
class PromptConfig:
    """The schema-specific parts of the LLM system prompt.

    The orchestrator's prompt builder takes one of these and weaves it
    into the final prompt alongside the tool schemas (which are also
    config-derived). The text fragments here should be:
      * short — the LLM's effective context is small
      * domain-flavoured — examples should match the active schema's
        entity names (Portuguese cities for Olist, US cities for Shopify)
      * consistent with `enums` and `states` — the model is told the
        exact values it may emit
    """
    dataset_description: str            # one-sentence description shown to the LLM
    city_rule: str                      # how to normalize city names
    state_rule: str                     # which state codes are valid + shape
    status_rule: str                    # which status values are valid
    group_by_rule: str                  # the group_by enum
    few_shot_examples: tuple[tuple[str, str], ...]   # (question, expected JSON) pairs
    source_citations: dict[str, str]   # tool name -> human-readable source


# A function factory takes the active SchemaConfig and returns a
# {"schema": <JSON Schema dict>, "execute": <async callable>} entry —
# the same shape the current `FUNCTIONS` registry uses. Per-schema
# function implementations live in functions/*.py and become factories
# (functions take a config, close over it, and return the registry entry).
FunctionFactory = Callable[["SchemaConfig"], dict]


@dataclass(frozen=True)
class SchemaConfig:
    """The single source of truth for what makes a schema this schema.

    The active config is selected at startup from `SCHEMA` env var and
    exposed as `schemas.active_config`. The rest of the backend reads
    from there. Nothing in here is mutable at runtime — config swaps
    require a process restart.
    """
    name: str                                       # e.g. "olist", "shopify"
    display_name: str                               # e.g. "Olist Brazilian e-commerce"

    # Logical -> physical table names.  e.g. {"orders": "olist_orders_dataset"}
    tables: dict[str, str]

    # Logical column -> which table + physical column.  e.g.
    # {"order_status": ColumnRef("orders", "order_status")}
    columns: dict[str, ColumnRef]

    # Allowed enum values, keyed by the SAME logical name the function
    # JSON schemas expose (e.g. "status" -> {"delivered", "shipped", ...}).
    # A key with value None means "no enum, the column is freeform text".
    enums: dict[str, Optional[frozenset[str]]]

    # Geographic state codes for this schema (None if it has no state
    # dimension at all, e.g. a single-country schema where "city" is
    # granular enough). The detectors only scan for state tokens when
    # this is set.
    states: Optional[frozenset[str]] = None

    # Out-of-scope concepts to decline. Order matters only for the
    # *first* match (we stop at the first hit per question).
    scope: tuple[ScopePattern, ...] = ()

    # Schema-specific prompt text + few-shots + source citations.
    prompt: PromptConfig = field(default_factory=PromptConfig)

    # Function factories: called at startup to materialize the
    # schema-aware function registry. Each factory closes over the
    # active config (so the function body never has to thread it
    # through the call chain).
    function_factories: tuple[FunctionFactory, ...] = ()

    def get_table(self, logical: str) -> str:
        """Return the physical table name for a logical key, or raise
        KeyError if the active schema doesn't define that logical
        table. Used by functions and the SQL builder."""
        try:
            return self.tables[logical]
        except KeyError as e:
            raise KeyError(
                f"Schema {self.name!r} has no table {logical!r} "
                "(missing in the config)"
            ) from e

    def get_column(self, logical: str) -> ColumnRef:
        try:
            return self.columns[logical]
        except KeyError as e:
            raise KeyError(
                f"Schema {self.name!r} has no column {logical!r} "
                "(missing in the config)"
            ) from e

    def get_enum(self, logical: str) -> Optional[frozenset[str]]:
        """Return the allowed values for an enum, or None if the
        schema marks this column as freeform."""
        if logical not in self.enums:
            raise KeyError(
                f"Schema {self.name!r} has no enum {logical!r} "
                "(missing in the config)"
            )
        return self.enums[logical]

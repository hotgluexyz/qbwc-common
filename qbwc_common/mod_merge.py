"""Schema-driven filtering for *Mod payload merge from queried *Ret records."""

from __future__ import annotations

from typing import Any

import xmlschema

_MOD_ELEMENT_NAMES_CACHE: dict[str, frozenset[str]] = {}


def _find_schema_element(schema: xmlschema.XMLSchema, element_name: str) -> Any:
    """Return the XSD element matching element_name by local name."""
    element = schema.elements.get(element_name)
    if element is not None:
        return element
    for key, candidate in schema.elements.items():
        if str(key).endswith(element_name):
            return candidate
    raise ValueError(f"XSD element not found: {element_name}")


def _get_element_child_names(schema: xmlschema.XMLSchema, element_name: str) -> frozenset[str]:
    """Return direct child element names for an XSD element, expanding groups."""
    element = _find_schema_element(schema, element_name)
    content = element.type.content
    if not hasattr(content, "iter_elements"):
        return frozenset()
    return frozenset(child.name for child in content.iter_elements())


def get_mod_element_names(
    schema: xmlschema.XMLSchema,
    mod_element_name: str,
) -> frozenset[str]:
    """Return cached top-level child names allowed on a *Mod XSD element."""
    cached = _MOD_ELEMENT_NAMES_CACHE.get(mod_element_name)
    if cached is not None:
        return cached
    allowed = _get_element_child_names(schema, mod_element_name)
    _MOD_ELEMENT_NAMES_CACHE[mod_element_name] = allowed
    return allowed


def get_ret_only_field_names(
    schema: xmlschema.XMLSchema,
    ret_element_name: str,
    mod_element_name: str,
) -> frozenset[str]:
    """Return top-level *Ret fields that are not defined on the matching *Mod element."""
    ret_names = _get_element_child_names(schema, ret_element_name)
    mod_names = get_mod_element_names(schema, mod_element_name)
    return frozenset(ret_names - mod_names)


def filter_dict_for_mod(
    payload: dict[str, Any],
    allowed: frozenset[str],
) -> dict[str, Any]:
    """Keep only top-level keys that belong on a *Mod payload."""
    return {key: value for key, value in payload.items() if key in allowed}

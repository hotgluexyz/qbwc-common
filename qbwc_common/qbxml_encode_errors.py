"""Human-readable messages for qbXML encode validation failures."""

from __future__ import annotations

import re

from xmlschema.validators.exceptions import XMLSchemaValidationError

MAX_LENGTH_FACET_RE = re.compile(r"value=(\d+)")
MISSING_FIELD_RE = re.compile(
    r"Unexpected child with tag '(\w+)' at position \d+\. Tag '(\w+)' expected\."
)
INCOMPLETE_FIELD_RE = re.compile(r"Tag '(\w+)' expected\.$")
UNKNOWN_FIELD_RE = re.compile(
    r"'(\w+)' does not match any declared element of the model group"
)
WRONG_TYPE_RE = re.compile(r"(\S+) is not an instance of <class '(\w+)'>")

REASON_NO_BOOL_ENCODE = "no type suitable for encoding the object"
REASON_SIMPLE_TYPE_CHILD = "a simpleType element can't have child elements"


def format_encode_validation_error(exc: XMLSchemaValidationError) -> str:
    """Build a short user-facing message from an xmlschema encode validation error."""
    field = exc.elem.tag if exc.elem is not None else None
    reason = exc.reason or str(exc)
    validator_name = type(exc.validator).__name__ if exc.validator is not None else ""

    if validator_name == "XsdMaxLengthFacet":
        limit_match = MAX_LENGTH_FACET_RE.search(str(exc.validator))
        limit = limit_match.group(1) if limit_match else None
        label = field or "field"
        if limit:
            return (
                f"qbXML validation error on {label}: "
                f"exceeds max length of {limit} characters"
            )

    missing_match = MISSING_FIELD_RE.search(reason)
    if missing_match:
        got, expected = missing_match.groups()
        return (
            f"qbXML validation error: missing required field '{expected}' "
            f"(got '{got}' at that position)"
        )

    if "is not complete" in reason:
        incomplete_match = INCOMPLETE_FIELD_RE.search(reason)
        if incomplete_match:
            return (
                f"qbXML validation error: missing required field "
                f"'{incomplete_match.group(1)}'"
            )

    unknown_match = UNKNOWN_FIELD_RE.search(reason)
    if unknown_match:
        return f"qbXML validation error: unknown field '{unknown_match.group(1)}'"

    wrong_type_match = WRONG_TYPE_RE.search(reason)
    if wrong_type_match:
        value, typ = wrong_type_match.groups()
        parent = field or "field"
        return f"qbXML validation error on {parent}: value {value!r} must be a {typ}"

    if reason == REASON_NO_BOOL_ENCODE and field:
        return f"qbXML validation error on {field}: value is not a valid boolean"

    if reason.startswith(REASON_SIMPLE_TYPE_CHILD):
        parent = field or "field"
        return f"qbXML validation error on {parent}: expected a string value, got an object"

    if field:
        return f"qbXML validation error on {field}: {reason}"
    return f"qbXML validation error: {reason}"

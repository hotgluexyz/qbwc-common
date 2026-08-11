"""QBXML encode, decode and response parsing helpers."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import xmlschema

from qbwc_common.exceptions import QBXMLEncodeError, QBXMLDecodeError
from qbwc_common.qbxml_encode_errors import format_encode_validation_error

QBD_XML_SCHEMAS_FILE = Path(__file__).parent / "qbd_xml_schemas" / "qbxmlops130.xsd"
QBXML_HEADER = '<?xml version="1.0" encoding="utf-8"?><?qbxml version="13.0"?>\n'

ON_ERROR_STOP = "stopOnError"
ON_ERROR_CONTINUE = "continueOnError"

# xmlschema decode mode for QBXML responses. strict matches tap-qbwc; skip tolerates
# partial *Ret payloads from QuickBooks write responses.
DEFAULT_DECODE_VALIDATION = "strict"


@functools.cache
def load_qbd_xml_schemas() -> xmlschema.XMLSchema:
    """Load and validate the bundled Intuit qbXML 13.0 operations schema set.

    Parsed schemas are cached for the process lifetime because the XSD bundle is
    immutable and expensive to load.
    """
    schema = xmlschema.XMLSchema(QBD_XML_SCHEMAS_FILE)
    if schema.validity != "valid":
        raise ValueError(f"QBD XML schemas are not valid: {schema.validity}")
    return schema


def merge_request_elements(requests: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge a list of single-key request dicts into one QBXMLMsgsRq body."""
    merged: dict[str, Any] = {}
    for request in requests:
        for key, value in request.items():
            if key in merged:
                existing = merged[key]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    merged[key] = [existing, value]
            else:
                merged[key] = value
    return merged


def encode_requests(
    request_data: dict[str, Any] | list[dict[str, Any]],
    schema: xmlschema.XMLSchema,
    on_error: str = ON_ERROR_STOP,
) -> str:
    """Validate and serialise request element(s) into a qbXML string."""
    if isinstance(request_data, list):
        body = merge_request_elements(request_data)
    else:
        body = request_data

    payload_dict = {
        "QBXMLMsgsRq": {
            "@onError": on_error,
            **body,
        }
    }

    try:
        xml_element = schema.encode(payload_dict, path="QBXML", unordered=True)
        xml_string = xmlschema.etree_tostring(xml_element, encoding="utf-8")
        return f"{QBXML_HEADER}\n{xml_string.decode('utf-8')}"
    except xmlschema.XMLSchemaValidationError as exc:
        message = format_encode_validation_error(exc)
        field = exc.elem.tag if exc.elem is not None else None
        raise QBXMLEncodeError(message, field=field, details=exc.reason) from exc


def decode_response(
    response_xml: str,
    schema: xmlschema.XMLSchema,
    validation: str = DEFAULT_DECODE_VALIDATION,
) -> dict[str, Any]:
    """Decode a qbXML response string and return the QBXMLMsgsRs body."""
    try:
        response_dict = schema.decode(response_xml, validation=validation)
        return response_dict["QBXMLMsgsRs"]
    except xmlschema.XMLSchemaValidationError as exc:
        raise QBXMLDecodeError(f"Response XML to dictionary conversion failed: {exc}") from exc
    except (KeyError, TypeError) as exc:
        raise QBXMLDecodeError(f"Unexpected response structure: {exc}") from exc


def normalize_rs_list(qbxml_msgs_rs: dict[str, Any], rs_element: str) -> list[dict[str, Any]]:
    """Normalise a *Rs element to a list (xmlschema returns a dict when there is one)."""
    elements = qbxml_msgs_rs.get(rs_element)
    if elements is None:
        return []
    if isinstance(elements, dict):
        return [elements]
    return elements


def _find_ret_entity(rs_element: dict[str, Any]) -> tuple[str | None, Any]:
    """Return the *Ret child key and value from a single *Rs element."""
    for key, value in rs_element.items():
        if key.startswith("@"):
            continue
        if key.endswith("Ret"):
            return key, value
    return None, None


def parse_rs_element(rs_element: dict[str, Any]) -> dict[str, Any]:
    """Extract status fields and the returned entity from one *Rs element."""
    entity_key, entity = _find_ret_entity(rs_element)
    if isinstance(entity, list) and entity:
        entity = entity[0]

    return {
        "request_id": rs_element.get("@requestID", ""),
        "status_code": rs_element.get("@statusCode"),
        "status_severity": rs_element.get("@statusSeverity"),
        "status_message": rs_element.get("@statusMessage"),
        "entity_key": entity_key,
        "entity": entity,
    }

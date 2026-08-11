# qbwc-common

Shared Python library for QuickBooks Desktop Web Connector (QBWC) used by [`tap-qbwc`](https://github.com/hotgluexyz/tap-qbwc) and [`target-qbwc`](https://github.com/hotgluexyz/target-qbwc).

Repository: [github.com/hotgluexyz/qbwc-common](https://github.com/hotgluexyz/qbwc-common)

It centralises transport to the QBWC SOAP service, the bundled Intuit qbXML 13.0 XSD set, and the encode/decode helpers both connectors build on.

## What's included

| Module | Responsibility |
|---|---|
| `client.py` | `QBWCClient`: authenticate, enqueue qbXML, long-poll for responses |
| `qbxml.py` | Encode requests and decode responses against the XSD; `merge_request_elements`, `normalize_rs_list`, `parse_rs_element` |
| `mod_merge.py` | XSD-driven filtering for `*Mod` payloads (`get_mod_element_names`, `filter_dict_for_mod`, `get_ret_only_field_names`) |
| `qbxml_encode_errors.py` | User-facing messages for XSD encode validation failures (`format_encode_validation_error`) |
| `config.py` | Shared config contract, defaults, and sandbox/production base URLs |
| `exceptions.py` | `QBWC*` transport errors and `QBXML*` encode/decode errors |
| `qbd_xml_schemas/` | Bundled `qbxmlops130.xsd` and dependencies (qbXML 13.0) |

Public exports live in `qbwc_common.__init__`. Import from `qbwc_common` in connector code.

## Installation

```bash
git clone https://github.com/hotgluexyz/qbwc-common.git
cd qbwc-common
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Connectors declare a dependency on this package. For local work on both repos, clone `qbwc-common` as a sibling directory and install it before the tap or target.

## Configuration

Shared keys consumed by `QBWCClient` (connectors may add their own settings on top):

| Key | Required | Default | Description |
|---|---|---|---|
| `token` | yes | | Base64 connector token for the QBWC SOAP service |
| `request_timeout` | no | `1200` | Seconds a QBWC request may take before timeout |
| `is_sandbox` | no | `false` | Use `qbwc-qa.hotglue.xyz` instead of `qbwc.hotglue.com` |
| `qbwc_is_alive_timeout` | no | `3600` | Timeout for the optional `HostQueryRq` liveness check |

Example:

```json
{
  "token": "your_base64_connector_token",
  "is_sandbox": true,
  "request_timeout": 1200
}
```

## Usage

### Client and qbXML round-trip

```python
from qbwc_common import QBWCClient, load_qbd_xml_schemas

schemas = load_qbd_xml_schemas()
client = QBWCClient(config, schemas, logger=my_logger)
client.create_session()
client.check_qbwc_is_alive()  # optional HostQueryRq ping
response = client.make_request({"HostQueryRq": {}})
```

`make_request` encodes dict-shaped request elements, sends them through QBWC, and returns the decoded `QBXMLMsgsRs` body. Use `send_qbxml` when you already have a qbXML string.

### Batched writes

Pass a list of single-key request dicts. Set `on_error="continueOnError"` so one failed record does not abort the batch. Give each record a `@requestID` attribute; QuickBooks echoes it on the matching `*Rs`.

For write responses with partial `*Ret` payloads, pass `decode_validation="skip"` (the tap defaults to strict decode on reads).

```python
from qbwc_common import ON_ERROR_CONTINUE

requests = [
    {
        "CustomerAddRq": {
            "@requestID": "0",
            "CustomerAdd": {"Name": "Customer A", "CompanyName": "A Co"},
        }
    },
    {
        "CustomerAddRq": {
            "@requestID": "1",
            "CustomerAdd": {"Name": "Customer B", "CompanyName": "B Co"},
        }
    },
]
response = client.make_request(
    requests,
    on_error=ON_ERROR_CONTINUE,
    decode_validation="skip",
)
```

### Mod payload merge

After a query returns a `*Ret` record, strip read-only fields before overlaying incoming changes onto a `*Mod` payload:

```python
from qbwc_common import filter_dict_for_mod, get_mod_element_names

allowed = get_mod_element_names(schemas, "CustomerMod")
incoming = filter_dict_for_mod(payload, allowed)
merged = {**existing_ret, **incoming}
merged["ListID"] = existing_ret["ListID"]
merged["EditSequence"] = existing_ret["EditSequence"]
```

`get_ret_only_field_names` returns `*Ret` fields that are not valid on the matching `*Mod` element.

### Response parsing

```python
from qbwc_common import normalize_rs_list, parse_rs_element

for rs in normalize_rs_list(response, "CustomerAddRs"):
    parsed = parse_rs_element(rs)
    # parsed: request_id, status_code, status_message, entity_key, entity
```

## Development

```bash
tox
```

Or run tools directly:

```bash
.venv/bin/ruff check .
.venv/bin/pytest tests/
```

Related repos:

- [`tap-qbwc`](https://github.com/hotgluexyz/tap-qbwc): Singer tap for reading from QuickBooks Desktop via QBWC
- [`target-qbwc`](https://github.com/hotgluexyz/target-qbwc): Singer target for writing QuickBooks-shaped records via QBWC

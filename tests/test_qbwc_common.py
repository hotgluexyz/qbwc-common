"""Unit tests for qbwc-common."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from qbwc_common import (
    QBWCClient,
    QBWCAuthenticationError,
    QBWCEnqueueError,
    QBWCNotAuthenticatedError,
    QBWCQueueFullError,
    QBWCRequestError,
    QBWCRequestTimeoutError,
    QBWCUnknownPollStatusError,
    QBXMLDecodeError,
    QBXMLEncodeError,
    QBXMLStatusError,
    decode_response,
    encode_requests,
    load_qbd_xml_schemas,
    normalize_config,
    normalize_rs_list,
    parse_rs_element,
    resolve_base_url,
    SANDBOX_BASE_URL,
    PRODUCTION_BASE_URL,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_QBWC_IS_ALIVE_TIMEOUT,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SCHEMA = load_qbd_xml_schemas()


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def _mock_response(status_code: int, json_data: dict | None = None, text: str = ""):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if json_data is not None:
        response.json.return_value = json_data
    return response


class TestConfig:
    """Shared config contract."""

    def test_normalize_config_applies_defaults(self):
        """Missing optional keys receive package defaults."""
        normalized = normalize_config({"token": "abc"})
        assert normalized["request_timeout"] == DEFAULT_REQUEST_TIMEOUT
        assert normalized["qbwc_is_alive_timeout"] == DEFAULT_QBWC_IS_ALIVE_TIMEOUT
        assert normalized["is_sandbox"] is False
        assert normalized["token"] == "abc"

    def test_normalize_config_requires_token(self):
        """Missing token raises ValueError."""
        with pytest.raises(ValueError, match="token"):
            normalize_config({})

    def test_resolve_base_url(self):
        """Sandbox flag selects the QA SOAP service host."""
        assert resolve_base_url(False) == PRODUCTION_BASE_URL
        assert resolve_base_url(True) == SANDBOX_BASE_URL


class TestLoadQbdXmlSchemas:
    """Bundled qbXML schema loading."""

    def test_load_qbd_xml_schemas_parses_once_and_reuses_result(self):
        """Repeated loads parse the XSD once and return the cached XMLSchema."""
        load_qbd_xml_schemas.cache_clear()
        try:
            mock_schema = MagicMock()
            mock_schema.validity = "valid"
            with patch(
                "qbwc_common.qbxml.xmlschema.XMLSchema",
                return_value=mock_schema,
            ) as mock_ctor:
                first = load_qbd_xml_schemas()
                second = load_qbd_xml_schemas()

            assert mock_ctor.call_count == 1
            assert first is second is mock_schema
            assert load_qbd_xml_schemas.cache_info().hits == 1
        finally:
            load_qbd_xml_schemas.cache_clear()
            load_qbd_xml_schemas()


class TestEncodeRequests:
    """QBXML encode behaviour."""

    def test_single_request_stop_on_error(self):
        """Single request encodes with stopOnError and no requestID."""
        xml = encode_requests(
            {"AccountAddRq": {"AccountAdd": {"Name": "Test", "AccountType": "Income"}}},
            SCHEMA,
        )
        assert "stopOnError" in xml
        assert "AccountAddRq" in xml
        assert "requestID" not in xml

    def test_single_request_with_request_id(self):
        """requestID attribute is set on the request element."""
        xml = encode_requests(
            {
                "CustomerAddRq": {
                    "@requestID": "ext-1",
                    "CustomerAdd": {"Name": "HG-TEST", "CompanyName": "Test Co"},
                }
            },
            SCHEMA,
            on_error="continueOnError",
        )
        assert "continueOnError" in xml
        assert "ext-1" in xml

    def test_batch_request_structure(self):
        """Batch of sibling requests encodes with continueOnError and per-record requestIDs."""
        requests = [
            {
                "CustomerAddRq": {
                    "@requestID": "ext-ok-1",
                    "CustomerAdd": {"Name": "HG-BATCH-1", "CompanyName": "One"},
                }
            },
            {
                "CustomerAddRq": {
                    "@requestID": "ext-ok-2",
                    "CustomerAdd": {"Name": "HG-BATCH-2", "CompanyName": "Two"},
                }
            },
        ]
        xml = encode_requests(requests, SCHEMA, on_error="continueOnError")
        assert "continueOnError" in xml
        assert xml.count("<CustomerAddRq") == 2
        assert "ext-ok-1" in xml
        assert "ext-ok-2" in xml

    def test_invalid_payload_raises_encode_error(self):
        """Empty CustomerAdd fails XSD validation with a readable message."""
        with pytest.raises(QBXMLEncodeError, match="missing required field 'Name'") as exc_info:
            encode_requests({"CustomerAddRq": {"CustomerAdd": {}}}, SCHEMA)
        error = exc_info.value
        assert error.field == "CustomerAdd"
        assert "Name" in error.details


class TestEncodeValidationMessages:
    """Encode validation errors return short qbXML validation messages."""

    ENCODE_VALIDATION_CASES = {
        "length_Name": (
            {"CustomerAddRq": {"@requestID": "0", "CustomerAdd": {"Name": "A" * 50}}},
            "qbXML validation error on Name: exceeds max length of 41 characters",
            "Name",
        ),
        "length_CompanyName": (
            {
                "CustomerAddRq": {
                    "@requestID": "0",
                    "CustomerAdd": {"Name": "OK", "CompanyName": "A" * 50},
                }
            },
            "qbXML validation error on CompanyName: exceeds max length of 41 characters",
            "CompanyName",
        ),
        "missing_Name": (
            {"CustomerAddRq": {"@requestID": "0", "CustomerAdd": {"CompanyName": "No Name"}}},
            "qbXML validation error: missing required field 'Name' (got 'CompanyName' at that position)",
            "CustomerAdd",
        ),
        "unknown_field_Balance": (
            {
                "CustomerAddRq": {
                    "@requestID": "0",
                    "CustomerAdd": {"Name": "OK", "Balance": "not-a-number"},
                }
            },
            "qbXML validation error: unknown field 'Balance'",
            "Name",
        ),
        "invalid_type_IsActive": (
            {
                "CustomerAddRq": {
                    "@requestID": "0",
                    "CustomerAdd": {"Name": "OK", "IsActive": "maybe"},
                }
            },
            "qbXML validation error on IsActive: value is not a valid boolean",
            "IsActive",
        ),
        "extra_field": (
            {
                "CustomerAddRq": {
                    "@requestID": "0",
                    "CustomerAdd": {"Name": "OK", "TotallyFakeField": "x"},
                }
            },
            "qbXML validation error: unknown field 'TotallyFakeField'",
            "Name",
        ),
        "invalid_nested": (
            {
                "CustomerAddRq": {
                    "@requestID": "0",
                    "CustomerAdd": {"Name": "OK", "BillAddress": {"BadField": "x"}},
                }
            },
            "qbXML validation error: unknown field 'BadField'",
            "BillAddress",
        ),
        "invalid_ref_type": (
            {
                "CustomerAddRq": {
                    "@requestID": "0",
                    "CustomerAdd": {"Name": "OK", "ParentRef": {"ListID": 12345}},
                }
            },
            "qbXML validation error on ListID: value '12345' must be a str",
            "ListID",
        ),
        "wrong_structure": (
            {
                "CustomerAddRq": {
                    "@requestID": "0",
                    "CustomerAdd": {"Name": {"nested": "bad"}},
                }
            },
            "qbXML validation error on Name: expected a string value, got an object",
            "Name",
        ),
    }

    @pytest.mark.parametrize(
        ("request_data", "expected_message", "expected_field"),
        list(ENCODE_VALIDATION_CASES.values()),
        ids=list(ENCODE_VALIDATION_CASES.keys()),
    )
    def test_encode_validation_message(
        self, request_data, expected_message, expected_field
    ):
        """Known XSD failures return stable user-facing encode error messages."""
        with pytest.raises(QBXMLEncodeError) as exc_info:
            encode_requests(request_data, SCHEMA, on_error="continueOnError")
        error = exc_info.value
        assert str(error) == expected_message
        assert error.field == expected_field
        assert error.details


class TestDecodeResponses:
    """QBXML decode and *Rs parsing from committed fixtures."""

    def test_decode_strict_rejects_partial_customer_ret(self):
        """Write batch fixtures need validation=skip; strict fails like tap would."""
        with pytest.raises(QBXMLDecodeError):
            decode_response(_read_fixture("customer-batch-valid.response.xml"), SCHEMA)

    def test_decode_valid_batch_response_with_skip(self):
        """All five successful CustomerAddRs are parsed with ListIDs when using skip."""
        body = decode_response(
            _read_fixture("customer-batch-valid.response.xml"),
            SCHEMA,
            validation="skip",
        )
        records = normalize_rs_list(body, "CustomerAddRs")
        assert len(records) == 5

        parsed = [parse_rs_element(record) for record in records]
        assert all(item["status_code"] == 0 for item in parsed)
        assert [item["request_id"] for item in parsed] == [
            "ext-ok-1",
            "ext-ok-2",
            "ext-ok-3",
            "ext-ok-4",
            "ext-ok-5",
        ]
        assert parsed[0]["entity"]["ListID"] == "80002747-1785964187"

    def test_decode_mixed_batch_response(self):
        """Mixed batch yields per-record status including errors."""
        body = decode_response(
            _read_fixture("customer-batch-mixed.response.xml"),
            SCHEMA,
            validation="skip",
        )
        records = normalize_rs_list(body, "CustomerAddRs")
        assert len(records) == 5

        parsed = [parse_rs_element(record) for record in records]
        assert [item["request_id"] for item in parsed] == [
            "ext-mix-1",
            "ext-mix-2",
            "ext-mix-3",
            "ext-mix-4",
            "ext-mix-5",
        ]
        assert parsed[0]["status_code"] == 0
        assert parsed[0]["entity"]["ListID"] == "8000274C-1785964190"
        assert parsed[1]["status_code"] == 3100
        assert parsed[1]["entity"] is None
        assert parsed[2]["status_code"] == 3250
        assert parsed[3]["status_code"] == 3130
        assert parsed[3]["entity"] is None
        assert parsed[4]["status_code"] == 0
        assert parsed[4]["entity"]["ListID"] == "8000274D-1785964190"

    def test_decode_single_account_response_strict_default(self):
        """Strict default decode parses a single AccountAddRs fixture."""
        body = decode_response(_read_fixture("account-add.response.xml"), SCHEMA)
        records = normalize_rs_list(body, "AccountAddRs")
        assert len(records) == 1

        parsed = parse_rs_element(records[0])
        assert parsed["status_code"] == 0
        assert parsed["entity"]["ListID"] == "80000035-1785958998"
        assert parsed["entity_key"] == "AccountRet"


class TestNormalizeRsList:
    """normalize_rs_list handles missing, single, and repeated *Rs elements."""

    def test_missing_element_returns_empty_list(self):
        """Absent *Rs key is an empty list, not None."""
        assert normalize_rs_list({}, "CustomerAddRs") == []

    def test_single_dict_is_wrapped(self):
        """xmlschema returns a dict when there is one *Rs element."""
        assert normalize_rs_list({"CustomerAddRs": {"@statusCode": 0}}, "CustomerAddRs") == [
            {"@statusCode": 0}
        ]

    def test_list_is_returned_unchanged(self):
        """Repeated *Rs elements stay a list."""
        items = [{"@statusCode": 0}, {"@statusCode": 1}]
        assert normalize_rs_list({"CustomerAddRs": items}, "CustomerAddRs") == items


class TestParseRsElement:
    """parse_rs_element extracts status fields and optional *Ret payload."""

    def test_error_rs_has_no_entity(self):
        """A failed *Rs without *Ret leaves entity and entity_key unset."""
        parsed = parse_rs_element(
            {
                "@requestID": "1",
                "@statusCode": 3100,
                "@statusSeverity": "Error",
                "@statusMessage": "already in use",
            }
        )
        assert parsed["request_id"] == "1"
        assert parsed["status_code"] == 3100
        assert parsed["status_message"] == "already in use"
        assert parsed["entity_key"] is None
        assert parsed["entity"] is None


def _stub_completed_poll(mock_post, mock_get, response_fixture: str) -> None:
    """Queue a successful enqueue and a completed poll with the given fixture."""
    mock_post.return_value = _mock_response(200, {"request_id": "req-1"})
    mock_get.return_value = _mock_response(
        200,
        {
            "status": "completed",
            "response_payload": _read_fixture(response_fixture),
        },
    )


def _customer_add_batch(count: int) -> list[dict]:
    """Build count CustomerAddRq dicts with ext-ok-N request IDs."""
    return [
        {
            "CustomerAddRq": {
                "@requestID": f"ext-ok-{index}",
                "CustomerAdd": {
                    "Name": f"HG-BATCH-{index}",
                    "CompanyName": f"Co {index}",
                },
            }
        }
        for index in range(1, count + 1)
    ]


class TestQBWCClientPoll:
    """Poll loop behaviour with mocked HTTP."""

    def _make_client(self):
        return QBWCClient({"token": "test-token"}, SCHEMA)

    @patch("qbwc_common.client.requests.get")
    @patch("qbwc_common.client.requests.post")
    def test_make_request_round_trip(self, mock_post, mock_get):
        """make_request encodes, enqueues, polls and decodes in one call."""
        client = self._make_client()
        client.session_id = "sess-1"
        _stub_completed_poll(mock_post, mock_get, "account-add.response.xml")

        response = client.make_request(
            {
                "AccountAddRq": {
                    "AccountAdd": {
                        "Name": "HG-WRITE-TEST-0805",
                        "AccountType": "Income",
                        "Desc": "Created by target-qbwc write probe",
                    }
                }
            }
        )
        enqueue_payload = mock_post.call_args.kwargs["json"]["request_payload"]
        assert "AccountAddRq" in enqueue_payload
        assert "stopOnError" in enqueue_payload
        assert mock_post.call_args.kwargs["params"]["session_id"] == "sess-1"
        records = normalize_rs_list(response, "AccountAddRs")
        assert len(records) == 1
        assert parse_rs_element(records[0])["entity"]["Name"] == "HG-WRITE-TEST-0805"

    @patch("qbwc_common.client.requests.get")
    @patch("qbwc_common.client.requests.post")
    def test_send_qbxml_decode_validation_skip(self, mock_post, mock_get):
        """Client decode_validation=skip decodes partial write batch responses."""
        client = self._make_client()
        client.session_id = "sess-1"
        _stub_completed_poll(mock_post, mock_get, "customer-batch-valid.response.xml")

        batch_request_xml = encode_requests(
            _customer_add_batch(5),
            SCHEMA,
            on_error="continueOnError",
        )
        response = client.send_qbxml(batch_request_xml, decode_validation="skip")
        enqueue_payload = mock_post.call_args.kwargs["json"]["request_payload"]
        assert enqueue_payload == batch_request_xml
        assert "continueOnError" in enqueue_payload
        assert all(f"ext-ok-{index}" in enqueue_payload for index in range(1, 6))
        parsed = [
            parse_rs_element(record)
            for record in normalize_rs_list(response, "CustomerAddRs")
        ]
        assert [item["request_id"] for item in parsed] == [
            f"ext-ok-{index}" for index in range(1, 6)
        ]

    @patch("qbwc_common.client.requests.post")
    def test_enqueue_includes_completed_percentage(self, mock_post):
        """Enqueue payload includes completed_percentage when counters are set."""
        client = self._make_client()
        client.session_id = "sess-1"
        client.total_estimated_records_count = 100
        client.total_processed_records_count = 50
        mock_post.return_value = _mock_response(200, {"request_id": "req-1"})

        with patch.object(client, "_poll_request", return_value=_read_fixture("account-add.response.xml")):
            client.send_qbxml(_read_fixture("account-add.request.xml"))

        payload = mock_post.call_args.kwargs["json"]
        assert payload["completed_percentage"] == 50
        assert payload["request_payload"] == _read_fixture("account-add.request.xml")

    @patch("qbwc_common.client.requests.post")
    def test_enqueue_omits_completed_percentage_when_counters_are_zero(self, mock_post):
        """completed_percentage is omitted until both progress counters are set."""
        client = self._make_client()
        client.session_id = "sess-1"
        mock_post.return_value = _mock_response(200, {"request_id": "req-1"})

        with patch.object(
            client, "_poll_request", return_value=_read_fixture("account-add.response.xml")
        ):
            client.send_qbxml(_read_fixture("account-add.request.xml"))

        payload = mock_post.call_args.kwargs["json"]
        assert "completed_percentage" not in payload

    @patch("qbwc_common.client.requests.get")
    @patch("qbwc_common.client.requests.post")
    def test_poll_completed(self, mock_post, mock_get):
        """Completed poll returns decoded QBXMLMsgsRs body."""
        client = self._make_client()
        client.session_id = "sess-1"
        request_xml = _read_fixture("account-add.request.xml")
        _stub_completed_poll(mock_post, mock_get, "account-add.response.xml")

        response = client.send_qbxml(request_xml)
        assert mock_post.call_args.kwargs["json"]["request_payload"] == request_xml
        records = normalize_rs_list(response, "AccountAddRs")
        assert len(records) == 1
        assert parse_rs_element(records[0])["entity"]["Name"] == "HG-WRITE-TEST-0805"

    @patch("qbwc_common.client.requests.get")
    @patch("qbwc_common.client.requests.post")
    def test_poll_queued_then_completed(self, mock_post, mock_get):
        """Queued and in_progress statuses retry until completed."""
        client = self._make_client()
        client.session_id = "sess-1"

        mock_post.return_value = _mock_response(200, {"request_id": "req-1"})
        mock_get.side_effect = [
            _mock_response(200, {"status": "queued"}),
            _mock_response(200, {"status": "in_progress"}),
            _mock_response(
                200,
                {
                    "status": "completed",
                    "response_payload": _read_fixture("account-add.response.xml"),
                },
            ),
        ]

        response = client.send_qbxml(_read_fixture("account-add.request.xml"))
        assert normalize_rs_list(response, "AccountAddRs")
        assert mock_get.call_count == 3

    @patch("qbwc_common.client.requests.get")
    @patch("qbwc_common.client.requests.post")
    def test_poll_error_status(self, mock_post, mock_get):
        """Error poll status raises QBWCRequestError."""
        client = self._make_client()
        client.session_id = "sess-1"

        mock_post.return_value = _mock_response(200, {"request_id": "req-1"})
        mock_get.return_value = _mock_response(
            200,
            {"status": "error", "error_code": "E1", "error_message": "boom"},
        )

        with pytest.raises(QBWCRequestError, match="req-1") as exc_info:
            client.send_qbxml("<QBXML></QBXML>")
        assert "boom" in str(exc_info.value)
        assert "Request XML" not in str(exc_info.value)

    @patch("qbwc_common.client.requests.get")
    @patch("qbwc_common.client.requests.post")
    def test_poll_timeout_status(self, mock_post, mock_get):
        """Timeout poll status raises QBWCRequestTimeoutError."""
        client = self._make_client()
        client.session_id = "sess-1"

        mock_post.return_value = _mock_response(200, {"request_id": "req-1"})
        mock_get.return_value = _mock_response(200, {"status": "timeout"})

        with pytest.raises(QBWCRequestTimeoutError, match="req-1") as exc_info:
            client.send_qbxml("<QBXML></QBXML>", request_timeout=10)
        assert "10 seconds" in str(exc_info.value)
        assert "Request XML" not in str(exc_info.value)

    @patch("qbwc_common.client.requests.get")
    @patch("qbwc_common.client.requests.post")
    def test_poll_unknown_status(self, mock_post, mock_get):
        """Unknown poll status raises QBWCUnknownPollStatusError."""
        client = self._make_client()
        client.session_id = "sess-1"

        mock_post.return_value = _mock_response(200, {"request_id": "req-1"})
        mock_get.return_value = _mock_response(200, {"status": "weird"})

        with pytest.raises(QBWCUnknownPollStatusError, match="weird") as exc_info:
            client.send_qbxml("<QBXML></QBXML>")
        assert "req-1" in str(exc_info.value)
        assert "Request XML" not in str(exc_info.value)

    def test_send_without_session_raises(self):
        """Enqueue without create_session raises QBWCNotAuthenticatedError."""
        client = self._make_client()
        with pytest.raises(QBWCNotAuthenticatedError):
            client.send_qbxml("<QBXML></QBXML>")

    @patch("qbwc_common.client.requests.post")
    def test_enqueue_failure_raises(self, mock_post):
        """Non-200 enqueue response raises QBWCEnqueueError."""
        client = self._make_client()
        client.session_id = "sess-1"
        mock_post.return_value = _mock_response(500, text="server error")

        with pytest.raises(QBWCEnqueueError, match="500"):
            client.send_qbxml("<QBXML></QBXML>")

    @patch("qbwc_common.client.requests.post")
    def test_enqueue_missing_request_id_raises(self, mock_post):
        """HTTP 200 enqueue body without request_id raises QBWCEnqueueError."""
        client = self._make_client()
        client.session_id = "sess-1"
        mock_post.return_value = _mock_response(200, {})

        with pytest.raises(QBWCEnqueueError, match="request_id"):
            client.send_qbxml("<QBXML></QBXML>")

    @patch("qbwc_common.client.requests.post")
    def test_enqueue_queue_full_raises(self, mock_post):
        """HTTP 429 on enqueue raises QBWCQueueFullError without waiting on backoff."""
        client = self._make_client()
        client.session_id = "sess-1"
        mock_post.return_value = _mock_response(429, text="queue full")

        enqueue = QBWCClient._enqueue_request
        while hasattr(enqueue, "__wrapped__"):
            enqueue = enqueue.__wrapped__
        with patch.object(
            client,
            "_enqueue_request",
            lambda xml, timeout: enqueue(client, xml, timeout),
        ):
            with pytest.raises(QBWCQueueFullError, match="429"):
                client.send_qbxml("<QBXML></QBXML>")

    @patch.object(QBWCClient, "make_request")
    def test_check_qbwc_is_alive_qbxml_status_error(self, mock_make_request):
        """Non-zero HostQueryRs statusCode raises QBXMLStatusError."""
        client = self._make_client()
        mock_make_request.return_value = {
            "HostQueryRs": [{"@statusCode": 1, "@statusMessage": "QB unavailable"}],
        }

        with pytest.raises(QBXMLStatusError, match="QB unavailable"):
            client.check_qbwc_is_alive()

    @patch.object(QBWCClient, "make_request")
    def test_check_qbwc_is_alive_accepts_single_dict_rs(self, mock_make_request):
        """A single HostQueryRs dict (not a list) is treated as success when status is 0."""
        client = self._make_client()
        mock_make_request.return_value = {"HostQueryRs": {"@statusCode": 0}}

        client.check_qbwc_is_alive()

        mock_make_request.assert_called_once_with(
            {"HostQueryRq": {}}, client.qbwc_is_alive_timeout
        )

    @patch("qbwc_common.client.requests.post")
    def test_authenticate_stores_session_id(self, mock_post):
        """Successful authenticate stores the session id from the response body."""
        client = self._make_client()
        mock_post.return_value = _mock_response(
            200, {"session_id": "89ed16b4-44d8-4c37-ba4a-2ceb15ca304b"}
        )

        client.create_session()

        assert client.session_id == "89ed16b4-44d8-4c37-ba4a-2ceb15ca304b"
        auth_call = mock_post.call_args
        assert auth_call.args[0].endswith("/authenticate")
        assert auth_call.kwargs["headers"]["Authorization"] == "Bearer test-token"

    @patch("qbwc_common.client.requests.post")
    def test_authenticate_missing_session_id_raises(self, mock_post):
        """HTTP 200 authenticate body without session_id raises QBWCAuthenticationError."""
        client = self._make_client()
        mock_post.return_value = _mock_response(200, {})

        with pytest.raises(QBWCAuthenticationError, match="session_id"):
            client.create_session()

    @patch("qbwc_common.client.requests.post")
    def test_authenticate_failure_raises(self, mock_post):
        """Failed authenticate raises QBWCAuthenticationError."""
        client = self._make_client()
        mock_post.return_value = _mock_response(401, text="unauthorized")

        with pytest.raises(QBWCAuthenticationError, match="401"):
            client.create_session()

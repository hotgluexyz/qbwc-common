"""QBWC HTTP client for authenticate, enqueue and long-poll."""

from __future__ import annotations

import time
from logging import Logger
from typing import Any, Optional

import backoff
import requests
import xmlschema
from requests.exceptions import RequestException

from qbwc_common.config import normalize_config, resolve_base_url
from qbwc_common.exceptions import (
    QBWCAuthenticationError,
    QBWCEnqueueError,
    QBWCNotAuthenticatedError,
    QBWCQueueFullError,
    QBWCRequestError,
    QBWCRequestTimeoutError,
    QBWCUnknownPollStatusError,
    QBXMLStatusError,
)
from qbwc_common.qbxml import (
    DEFAULT_DECODE_VALIDATION,
    decode_response,
    encode_requests,
    ON_ERROR_STOP,
)

POLL_STATUSES_RETRY = frozenset({"queued", "in_progress"})


class QBWCClient:
    """Client for the QBWC SOAP service HTTP API."""

    def __init__(
        self,
        config: dict[str, Any],
        qbd_xml_schemas: xmlschema.XMLSchema,
        logger: Optional[Logger] = None,
    ):
        """Bind config, XSD schema and optional logger."""
        self.logger = logger
        self.config = normalize_config(config)
        self.session_id: str | None = None
        self.request_timeout = self.config["request_timeout"]
        self.qbwc_is_alive_timeout = self.config["qbwc_is_alive_timeout"]
        self.qbd_xml_schemas = qbd_xml_schemas
        self.base_url = resolve_base_url(self.config["is_sandbox"])
        self.total_estimated_records_count = 0
        self.total_processed_records_count = 0

    def _log_info(self, message: str) -> None:
        """Log at info level when a logger is configured."""
        if self.logger is not None:
            self.logger.info(message)

    def create_session(self) -> None:
        """Authenticate with the connector token and store the session id."""
        self._log_info("Creating QBWC client session")

        try:
            response = requests.post(
                f"{self.base_url}/authenticate",
                headers={"Authorization": f"Bearer {self.config['token']}"},
                timeout=30,
            )
        except RequestException as exc:
            raise QBWCAuthenticationError(f"Failed to authenticate: {exc}") from exc

        if response.status_code != 200:
            raise QBWCAuthenticationError(
                f"Failed to authenticate: {response.status_code} - {response.text}"
            )

        self.session_id = response.json()["session_id"]
        self._log_info(f"Created session id: {self.session_id}")

    def check_qbwc_is_alive(self) -> None:
        """Run HostQueryRq to verify QuickBooks is reachable through QBWC."""
        self._log_info("Pinging QBWC to check if it is alive")
        response = self.make_request({"HostQueryRq": {}}, self.qbwc_is_alive_timeout)
        host_query_records = response.get("HostQueryRs") or []
        if isinstance(host_query_records, dict):
            host_query_records = [host_query_records]
        host_query_data = host_query_records[0]
        if host_query_data.get("@statusCode") != 0:
            raise QBXMLStatusError(
                f"{host_query_data.get('@statusCode')} - "
                f"{host_query_data.get('@statusMessage')} - {host_query_data}"
            )

    @backoff.on_exception(
        backoff.expo,
        (RequestException, QBWCQueueFullError),
        max_time=60,
    )
    def _enqueue_request(self, request_xml: str, request_timeout: int) -> str:
        """POST send_qbwc_request and return the poll request id."""
        payload: dict[str, Any] = {
            "request_payload": request_xml,
            "request_timeout": request_timeout,
            "total_processed_records_count": self.total_processed_records_count,
            "total_estimated_records_count": self.total_estimated_records_count,
        }

        if self.total_estimated_records_count > 0 and self.total_processed_records_count > 0:
            payload["completed_percentage"] = int(
                self.total_processed_records_count / self.total_estimated_records_count * 100
            )

        response = requests.post(
            f"{self.base_url}/send_qbwc_request",
            params={"session_id": self.session_id},
            json=payload,
            timeout=30,
        )

        if response.status_code == 429:
            raise QBWCQueueFullError(f"{response.status_code} - {response.text}")
        if response.status_code != 200:
            raise QBWCEnqueueError(
                f"Failed to make request: {response.status_code} - {response.text}"
            )

        return response.json()["request_id"]

    @backoff.on_exception(backoff.expo, RequestException, max_time=60)
    def _make_poll_request(self, request_id: str) -> dict[str, Any]:
        """GET get_qbwc_response for one poll cycle."""
        response = requests.get(
            f"{self.base_url}/get_qbwc_response",
            params={"session_id": self.session_id, "request_id": request_id},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _poll_request(self, request_id: str, request_xml: str, request_timeout: int) -> str:
        """Long poll until the QBWC request completes or fails."""
        while True:
            self._log_info(f"Polling request {request_id} for the result")
            data = self._make_poll_request(request_id)
            status = data["status"]

            if status == "completed":
                self._log_info(f"Request {request_id} completed")
                return data["response_payload"]
            if status == "error":
                raise QBWCRequestError(
                    f"Request failed: {data.get('error_code')} - "
                    f"{data.get('error_message')} - Request XML: {request_xml}"
                )
            if status == "timeout":
                raise QBWCRequestTimeoutError(
                    f"Request timed out after {request_timeout} seconds - "
                    f"Request XML: {request_xml}"
                )
            if status in POLL_STATUSES_RETRY:
                self._log_info(f"Request {request_id} is '{status}'. Retrying in 1 second...")
                time.sleep(1)
                continue

            raise QBWCUnknownPollStatusError(
                f"Unknown response status: {status} - Response: {data} - "
                f"Request XML: {request_xml}"
            )

    def _require_session(self) -> None:
        """Raise when enqueue is attempted without an active session."""
        if not self.session_id:
            raise QBWCNotAuthenticatedError("Session ID not found. Please create a session first.")

    def send_qbxml(
        self,
        request_xml: str,
        request_timeout: Optional[int] = None,
        decode_validation: str = DEFAULT_DECODE_VALIDATION,
    ) -> dict[str, Any]:
        """Enqueue a pre-built qbXML string and return the decoded QBXMLMsgsRs body."""
        self._require_session()
        timeout = request_timeout or self.request_timeout
        request_id = self._enqueue_request(request_xml, timeout)
        response_xml = self._poll_request(request_id, request_xml, timeout)
        return decode_response(response_xml, self.qbd_xml_schemas, validation=decode_validation)

    def make_request(
        self,
        request_data: dict[str, Any] | list[dict[str, Any]],
        request_timeout: Optional[int] = None,
        on_error: str = ON_ERROR_STOP,
        decode_validation: str = DEFAULT_DECODE_VALIDATION,
    ) -> dict[str, Any]:
        """Encode request data, send it through QBWC and return the decoded response."""
        request_xml = encode_requests(request_data, self.qbd_xml_schemas, on_error=on_error)
        return self.send_qbxml(request_xml, request_timeout, decode_validation=decode_validation)

    def convert_request_data_to_xml(
        self,
        request_data: dict[str, Any] | list[dict[str, Any]],
        on_error: str = ON_ERROR_STOP,
    ) -> str:
        """Encode request data to qbXML (tap-compatible alias)."""
        return encode_requests(request_data, self.qbd_xml_schemas, on_error=on_error)

    def convert_response_xml_to_dict(
        self,
        response_xml: str,
        decode_validation: str = DEFAULT_DECODE_VALIDATION,
    ) -> dict[str, Any]:
        """Decode response XML to the QBXMLMsgsRs body (tap-compatible alias)."""
        return decode_response(
            response_xml, self.qbd_xml_schemas, validation=decode_validation
        )

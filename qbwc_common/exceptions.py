"""Typed exceptions for QBWC transport and QBXML handling."""


class QBWCError(Exception):
    """Base class for qbwc-common errors."""


class QBWCNotAuthenticatedError(QBWCError):
    """Raised when a request is made before session creation."""


class QBWCAuthenticationError(QBWCError):
    """Raised when authenticate fails against the SOAP service."""


class QBWCEnqueueError(QBWCError):
    """Raised when send_qbwc_request fails."""


class QBWCQueueFullError(QBWCEnqueueError):
    """Raised when the pending queue is full (HTTP 429)."""


class QBWCRequestError(QBWCError):
    """Raised when get_qbwc_response returns poll status error."""


class QBXMLStatusError(QBWCError):
    """Raised when a decoded *Rs element has a non-zero QuickBooks statusCode."""


class QBWCRequestTimeoutError(QBWCError):
    """Raised when QBWC reports a request timeout."""


class QBWCUnknownPollStatusError(QBWCError):
    """Raised when poll returns an unrecognized status."""


class QBXMLEncodeError(QBWCError):
    """Raised when request data fails XSD validation during encode."""

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        details: str | None = None,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.details = details


class QBXMLDecodeError(QBWCError):
    """Raised when response XML fails decode or validation."""

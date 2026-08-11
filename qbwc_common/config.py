"""Shared config contract, defaults and base URL resolution."""

from typing import Any

DEFAULT_REQUEST_TIMEOUT = 1200
DEFAULT_QBWC_IS_ALIVE_TIMEOUT = 3600
DEFAULT_IS_SANDBOX = False

PRODUCTION_BASE_URL = "https://qbwc.hotglue.com"
SANDBOX_BASE_URL = "https://qbwc-qa.hotglue.xyz"

REQUIRED_CONFIG_KEYS = ("token",)
OPTIONAL_CONFIG_KEYS = (
    "request_timeout",
    "is_sandbox",
    "qbwc_is_alive_timeout",
)


def resolve_base_url(is_sandbox: bool = DEFAULT_IS_SANDBOX) -> str:
    """Return the QBWC SOAP service base URL for the given environment."""
    return SANDBOX_BASE_URL if is_sandbox else PRODUCTION_BASE_URL


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Apply defaults and validate required keys for the shared config contract."""
    missing = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing:
        raise ValueError(f"Missing required config key(s): {', '.join(missing)}")

    return {
        **config,
        "request_timeout": config.get("request_timeout", DEFAULT_REQUEST_TIMEOUT),
        "qbwc_is_alive_timeout": config.get(
            "qbwc_is_alive_timeout", DEFAULT_QBWC_IS_ALIVE_TIMEOUT
        ),
        "is_sandbox": config.get("is_sandbox", DEFAULT_IS_SANDBOX),
    }

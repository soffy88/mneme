"""Fail-fast production configuration contracts.

This module is intentionally pure: validation reads an environment mapping and
never contacts a production service.  The application lifespan calls it before
opening the database so an unsafe deployment cannot start accidentally.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

DEFAULT_JWT_SECRET = "mneme-dev-secret-change-in-prod!"
PRODUCTION_NAMES = frozenset({"prod", "production"})
DEFAULT_SECRET_VALUES = frozenset({"", "your_key_here", "change-me", "changeme"})


class ProductionConfigError(RuntimeError):
    """Raised when production configuration would violate a safety invariant."""


@dataclass(frozen=True, slots=True)
class ProductionConfigReport:
    environment: str
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_local_url(value: str) -> bool:
    try:
        host = (urlparse(value).hostname or "").lower()
    except ValueError:
        return False
    return host in {"localhost", "127.0.0.1", "::1"}


def _production_errors(env: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    if _truthy(env.get("DEBUG")):
        errors.append("DEBUG must be false in production")
    if _truthy(env.get("DEMO_MODE")):
        errors.append("DEMO_MODE must be false in production")
    if _truthy(env.get("SYNTHETIC_ANALYTICS")):
        errors.append("synthetic analytics must be disabled in production")
    if _truthy(env.get("MNEME_ALLOW_MOCK_LLM")):
        errors.append("mock LLM is not permitted in production")

    secret = env.get("JWT_SECRET", "")
    if secret == DEFAULT_JWT_SECRET or secret.strip().lower() in DEFAULT_SECRET_VALUES:
        errors.append("JWT_SECRET must be a non-default production secret")
    elif len(secret) < 32:
        errors.append("JWT_SECRET must contain at least 32 characters")

    database_url = env.get("DATABASE_URL", "")
    database_name = database_url.rsplit("/", 1)[-1].split("?", 1)[0].lower()
    if database_name in {"mneme_test", "test", "testing"} or database_name.endswith("_test"):
        errors.append("production cannot use a test database")
    if database_url and _is_local_url(database_url):
        errors.append("production database cannot point to localhost")

    billing = env.get("BILLING_PROVIDER", "").strip().lower()
    if billing in {"fake", "test", "mock", "fakebillingprovider"}:
        errors.append("FakeBillingProvider is not permitted in production")

    auth = env.get("AUTH_TRANSPORT", "bearer").strip().lower()
    if auth == "cookie":
        if not _truthy(env.get("SESSION_COOKIE_SECURE")):
            errors.append("cookie sessions require Secure cookies")
        if not _truthy(env.get("SESSION_COOKIE_HTTPONLY", "true")):
            errors.append("cookie sessions require HttpOnly cookies")
        if env.get("SESSION_COOKIE_SAMESITE", "lax").lower() not in {"lax", "strict"}:
            errors.append("cookie sessions require SameSite=Lax or Strict")

    origins = env.get("CORS_ALLOW_ORIGINS", "")
    if "*" in {item.strip() for item in origins.split(",") if item.strip()}:
        errors.append("wildcard CORS is not permitted with credentialed production access")

    callback_keys = ("OAUTH_CALLBACK_URL", "AUTH_CALLBACK_URL", "FRONTEND_CALLBACK_URL")
    for key in callback_keys:
        if env.get(key) and _is_local_url(env[key]):
            errors.append(f"{key} cannot point to localhost in production")

    if env.get("AUTH_PROVIDER", "").strip().lower() in {"mock", "test", "fake"}:
        errors.append("mock authentication is not permitted in production")
    if env.get("SMS_PROVIDER", "mock").strip().lower() == "mock" and env.get("EMAIL_PROVIDER", "mock").strip().lower() == "mock":
        errors.append("at least one real SMS or email verification provider is required")
    if env.get("MINIO_ACCESS_KEY") == "minioadmin" or env.get("MINIO_SECRET_KEY") == "minioadmin":
        errors.append("default object-storage credentials are not permitted in production")
    return errors


def validate_production_config(
    environ: Mapping[str, str] | None = None,
    *,
    raise_on_error: bool = True,
) -> ProductionConfigReport:
    """Validate development/test/production settings without exposing secrets.

    Development and test are intentionally permissive because their providers
    and databases are local.  Production is fail-closed.  ``raise_on_error``
    is useful to launch tooling that needs to report all findings first.
    """

    env = os.environ if environ is None else environ
    environment = env.get("MNEME_ENV", "dev").strip().lower()
    errors = _production_errors(env) if environment in PRODUCTION_NAMES else []
    report = ProductionConfigReport(environment=environment, valid=not errors, errors=tuple(errors))
    if errors and raise_on_error:
        raise ProductionConfigError("production configuration rejected: " + "; ".join(errors))
    return report


def validate_session_contract(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return a redacted session contract for the operator/readiness surface."""

    env = os.environ if environ is None else environ
    transport = env.get("AUTH_TRANSPORT", "bearer").strip().lower()
    if transport != "cookie":
        return {"transport": transport, "secure": None, "http_only": None, "same_site": None, "valid": True}
    same_site = env.get("SESSION_COOKIE_SAMESITE", "lax").lower()
    secure = _truthy(env.get("SESSION_COOKIE_SECURE"))
    http_only = _truthy(env.get("SESSION_COOKIE_HTTPONLY", "true"))
    return {"transport": transport, "secure": secure, "http_only": http_only, "same_site": same_site, "valid": secure and http_only and same_site in {"lax", "strict"}}


__all__ = ["DEFAULT_JWT_SECRET", "ProductionConfigError", "ProductionConfigReport", "validate_production_config", "validate_session_contract"]

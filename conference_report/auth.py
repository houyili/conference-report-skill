from __future__ import annotations

import getpass
import os
from dataclasses import dataclass


SERVICE_NAME = "conference-report"
OPENAI_ACCOUNT = "openai_api_key"


@dataclass(frozen=True)
class CredentialStatus:
    provider: str
    available: bool
    source: str | None = None
    detail: str | None = None


def _keyring():
    try:
        import keyring
    except Exception:
        return None
    return keyring


def get_secret(provider: str) -> str | None:
    if provider != "openai":
        raise ValueError(f"Unsupported provider: {provider}")
    env_value = os.environ.get("OPENAI_API_KEY")
    if env_value:
        return env_value
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(SERVICE_NAME, OPENAI_ACCOUNT)
    except Exception:
        return None


def get_openai_api_key() -> str | None:
    return get_secret("openai")


def openai_client_kwargs() -> dict[str, str]:
    key = get_openai_api_key()
    return {"api_key": key} if key else {}


def credential_status(provider: str) -> CredentialStatus:
    if provider != "openai":
        raise ValueError(f"Unsupported provider: {provider}")
    if os.environ.get("OPENAI_API_KEY"):
        return CredentialStatus(provider=provider, available=True, source="OPENAI_API_KEY")
    kr = _keyring()
    if kr is None:
        return CredentialStatus(provider=provider, available=False, detail="Python package keyring is not installed.")
    try:
        value = kr.get_password(SERVICE_NAME, OPENAI_ACCOUNT)
    except Exception as exc:
        return CredentialStatus(provider=provider, available=False, source="keyring", detail=str(exc))
    return CredentialStatus(provider=provider, available=bool(value), source="keyring")


def set_secret_interactive(provider: str) -> None:
    if provider != "openai":
        raise ValueError(f"Unsupported provider: {provider}")
    kr = _keyring()
    if kr is None:
        raise SystemExit("Install the keyring package first: python -m pip install keyring")
    value = getpass.getpass("OpenAI API key: ").strip()
    if not value:
        raise SystemExit("No key entered; nothing was stored.")
    try:
        kr.set_password(SERVICE_NAME, OPENAI_ACCOUNT, value)
    except Exception as exc:
        raise SystemExit(f"Could not store key in the system credential store: {exc}") from exc
    print("Stored OpenAI API key in the system credential store.")


def delete_secret(provider: str) -> None:
    if provider != "openai":
        raise ValueError(f"Unsupported provider: {provider}")
    kr = _keyring()
    if kr is None:
        raise SystemExit("Install the keyring package first: python -m pip install keyring")
    try:
        kr.delete_password(SERVICE_NAME, OPENAI_ACCOUNT)
    except Exception as exc:
        raise SystemExit(f"Could not delete key from the system credential store: {exc}") from exc
    print("Deleted OpenAI API key from the system credential store.")

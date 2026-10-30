"""Bootstrap configuration: packaged defaults overridden by BATON_* environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from importlib import resources
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

ENV_PREFIX = "BATON_"
MIN_UI_KEY_LENGTH = 24
LOOPBACK_HOSTS = {"127.0.0.1", "::1"}


class ConfigError(Exception):
    """The configuration is missing a value or holds an invalid one."""


class Config(BaseModel):
    """Validated bootstrap configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    public_url: str
    auth_mode: Literal["key", "proxy"]
    ui_key: str | None
    spotify_client_id: str
    spotify_client_secret: str
    data_dir: str
    listen_host: str
    listen_port: int
    log_level: str
    trust_proxy_headers: bool
    proxy_user_header: str
    session_days: int
    spotify_api_url: str
    spotify_accounts_url: str
    settle_delay_ms: int
    throttle_max_failures: int
    throttle_window_seconds: int
    throttle_lockout_seconds: int
    recent_playlists_cache_seconds: int
    state_cache_seconds: float
    spotify_budget_30s: int
    spotify_budget_hour: int

    @field_validator("public_url")
    @classmethod
    def _check_public_url(cls, value: str) -> str:
        parts = urlsplit(value)
        loopback = parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS
        if parts.scheme != "https" and not loopback:
            raise ValueError("must be an https:// URL or an http://127.0.0.1 loopback URL")
        if not parts.hostname or parts.path.strip("/") or parts.query or parts.fragment:
            raise ValueError("must be a bare origin without path, query or fragment")
        return value.rstrip("/")

    @model_validator(mode="after")
    def _check_auth(self) -> Config:
        if self.auth_mode == "key" and (self.ui_key or "").strip() == "":
            raise ValueError("ui_key is required when auth_mode is key")
        if self.ui_key is not None and 0 < len(self.ui_key) < MIN_UI_KEY_LENGTH:
            raise ValueError(f"ui_key must be at least {MIN_UI_KEY_LENGTH} characters")
        return self

    @property
    def redirect_uri(self) -> str:
        """Spotify redirect URI, always derived from the configured public URL."""
        return f"{self.public_url}/auth/spotify/callback"

    @property
    def cookie_secure(self) -> bool:
        """Whether cookies carry the Secure attribute."""
        return self.public_url.startswith("https://")


def load_config(environ: Mapping[str, str] | None = None) -> Config:
    """Load the packaged defaults and apply BATON_* overrides from ``environ``."""
    env = os.environ if environ is None else environ
    text = resources.files("baton").joinpath("default_config.yaml").read_text("utf-8")
    values: dict[str, object] = yaml.safe_load(text)
    for key in values:
        override = env.get(f"{ENV_PREFIX}{key.upper()}")
        if override is not None and override != "":
            values[key] = override
    missing = [f"{ENV_PREFIX}{k.upper()}" for k, v in values.items() if v is None and k != "ui_key"]
    if missing:
        raise ConfigError(f"missing required configuration: {', '.join(missing)}")
    try:
        return Config(**values)  # type: ignore[arg-type]
    except ValidationError as exc:
        problems = "; ".join(
            f"{ENV_PREFIX}{'.'.join(str(p) for p in e['loc']).upper() or 'CONFIG'}: {e['msg']}"
            for e in exc.errors()
        )
        raise ConfigError(f"invalid configuration: {problems}") from None

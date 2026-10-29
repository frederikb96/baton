"""Spotify login: authorization-code flow with PKCE, refresh token storage, token refresh."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import httpx

from baton import errors
from baton.config import Config
from baton.db import SpotifyAuthRecord, Store

SCOPES = (
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-read-recently-played",
    "user-library-read",
    "user-library-modify",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
)
REFRESH_TOKEN_LIFETIME_SECONDS = 180 * 86400
EXPIRY_MARGIN_SECONDS = 60
LOGIN_TTL_SECONDS = 600
SECONDS_PER_DAY = 86400


class LoginRevoked(errors.ProviderError):
    """Spotify refused the refresh token itself (``invalid_grant``); only a new login helps."""

    def __init__(self) -> None:
        super().__init__(
            errors.SPOTIFY_AUTH, "Spotify login expired or revoked. Log in again on the web page."
        )


def pkce_pair() -> tuple[str, str]:
    """A PKCE (verifier, S256 challenge) pair."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class SpotifyAccounts:
    """Owns the Spotify login and hands out valid access tokens."""

    def __init__(
        self,
        config: Config,
        store: Store,
        client: httpx.AsyncClient,
        now: Callable[[], float],
    ) -> None:
        self._config = config
        self._store = store
        self._client = client
        self._now = now
        self._lock = asyncio.Lock()

    def start_login(self) -> tuple[str, str]:
        """Register a pending login; returns (state, authorize URL)."""
        state = secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        self._store.put_oauth_state(state, verifier, LOGIN_TTL_SECONDS)
        query = urlencode(
            {
                "client_id": self._config.spotify_client_id,
                "response_type": "code",
                "redirect_uri": self._config.redirect_uri,
                "scope": " ".join(SCOPES),
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            }
        )
        return state, f"{self._config.spotify_accounts_url}/authorize?{query}"

    async def finish_login(self, state: str, code: str) -> None:
        """Exchange the callback code for tokens; the state is single use."""
        verifier = self._store.pop_oauth_state(state)
        if verifier is None:
            raise errors.ProviderError(errors.BAD_REQUEST, "Login expired, start it again.")
        data = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._config.redirect_uri,
                "code_verifier": verifier,
            }
        )
        now = self._now()
        self._store.save_spotify_auth(
            SpotifyAuthRecord(
                refresh_token=data["refresh_token"],
                access_token=data["access_token"],
                access_expires_at=now + float(data.get("expires_in", 3600)),
                scope=data.get("scope"),
                authorized_at=now,
            )
        )

    async def access_token(self, *, force: bool = False) -> str:
        """A valid access token, refreshing it when it is about to expire."""
        record = self._store.get_spotify_auth()
        if record is None:
            raise errors.ProviderError(
                errors.SPOTIFY_AUTH, "Spotify is not linked. Log in on the web page."
            )
        if record.invalid_reason:
            raise errors.ProviderError(errors.SPOTIFY_AUTH, record.invalid_reason)
        if not force and self._fresh(record):
            assert record.access_token is not None
            return record.access_token
        async with self._lock:
            record = self._store.get_spotify_auth()
            if record is None:
                raise errors.ProviderError(
                    errors.SPOTIFY_AUTH, "Spotify is not linked. Log in on the web page."
                )
            if not force and self._fresh(record):
                assert record.access_token is not None
                return record.access_token
            return await self._refresh(record)

    def _fresh(self, record: SpotifyAuthRecord) -> bool:
        return (
            record.access_token is not None
            and record.access_expires_at is not None
            and record.access_expires_at - self._now() > EXPIRY_MARGIN_SECONDS
        )

    async def _refresh(self, record: SpotifyAuthRecord) -> str:
        try:
            data = await self._token_request(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": record.refresh_token,
                }
            )
        except errors.ProviderError as exc:
            if isinstance(exc, LoginRevoked):
                self._store.save_spotify_auth(
                    SpotifyAuthRecord(
                        record.refresh_token,
                        None,
                        None,
                        record.scope,
                        record.authorized_at,
                        invalid_reason=exc.message,
                    )
                )
            raise
        now = self._now()
        self._store.save_spotify_auth(
            SpotifyAuthRecord(
                refresh_token=data.get("refresh_token") or record.refresh_token,
                access_token=data["access_token"],
                access_expires_at=now + float(data.get("expires_in", 3600)),
                scope=data.get("scope") or record.scope,
                authorized_at=record.authorized_at,
            )
        )
        return str(data["access_token"])

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        credentials = f"{self._config.spotify_client_id}:{self._config.spotify_client_secret}"
        if form["grant_type"] == "authorization_code":
            form = {**form, "client_id": self._config.spotify_client_id}
        try:
            resp = await self._client.post(
                f"{self._config.spotify_accounts_url}/api/token",
                data=form,
                headers={
                    "Authorization": "Basic " + base64.b64encode(credentials.encode()).decode()
                },
                timeout=15,
            )
        except httpx.HTTPError:
            raise errors.ProviderError(
                errors.SPOTIFY_ERROR, "Spotify accounts service unreachable."
            ) from None
        if resp.status_code == 200:
            body: dict[str, Any] = resp.json()
            return body
        try:
            error = resp.json().get("error")
        except ValueError:
            error = None
        if resp.status_code == 400 and error == "invalid_grant":
            raise LoginRevoked
        if resp.status_code == 429:
            raise errors.ProviderError(
                errors.SPOTIFY_RATE_LIMITED, "Spotify is rate limiting requests."
            )
        if resp.status_code in (400, 401):
            raise errors.ProviderError(
                errors.SPOTIFY_ERROR,
                "Spotify rejected the token request. Check the client id and secret.",
            )
        raise errors.ProviderError(
            errors.SPOTIFY_ERROR, f"Spotify accounts service answered {resp.status_code}."
        )

    def disconnect(self) -> None:
        """Forget the stored login."""
        self._store.clear_spotify_auth()

    def status(self) -> dict[str, Any]:
        """Login state for the web page."""
        record = self._store.get_spotify_auth()
        if record is None:
            return {
                "linked": False,
                "valid": False,
                "expires_in_days": None,
                "authorized_at": None,
                "message": "Not linked.",
            }
        remaining = record.authorized_at + REFRESH_TOKEN_LIFETIME_SECONDS - self._now()
        valid = record.invalid_reason is None and remaining > 0
        message = record.invalid_reason or (None if valid else "Login expired, log in again.")
        return {
            "linked": True,
            "valid": valid,
            "expires_in_days": max(0, math.ceil(remaining / SECONDS_PER_DAY)),
            "authorized_at": record.authorized_at,
            "message": message,
        }

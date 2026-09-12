"""
BROKER AUTHENTICATION FLOWS
===========================
Each Indian broker uses a different login handshake. These helpers complete the
exchange and return a ready-to-use AuthSession. The actual secrets (api_secret,
TOTP) are supplied by the user and never logged.

Flow summary:
  Zerodha : redirect to kite login → request_token → POST /session/token (SHA256 checksum) → access_token
  Upstox  : redirect to OAuth → auth code → POST /login/authorization/token → access_token
  AngelOne: POST loginByPassword with clientcode + pin + TOTP → jwtToken + feedToken
  Dhan    : user pastes a long-lived access token (no handshake)
  Fyers   : redirect to auth → auth code → POST /validate-authcode (SHA256) → access_token
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

import httpx

from app.providers.base import AuthSession

logger = logging.getLogger(__name__)


# ── Zerodha ───────────────────────────────────────────────────────────────────

class ZerodhaAuth:
    @staticmethod
    def login_url(api_key: str) -> str:
        return f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"

    @staticmethod
    async def exchange(api_key: str, api_secret: str, request_token: str) -> AuthSession:
        checksum = hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.kite.trade/session/token",
                headers={"X-Kite-Version": "3"},
                data={"api_key": api_key, "request_token": request_token, "checksum": checksum},
            )
            r.raise_for_status()
            data = r.json()["data"]
        # Zerodha tokens expire at next day ~6am IST
        return AuthSession(
            provider_key="zerodha",
            access_token=data["access_token"],
            api_key=api_key,
            user_id=data.get("user_id"),
            expires_at=_next_6am_ist(),
        )


# ── Upstox ────────────────────────────────────────────────────────────────────

class UpstoxAuth:
    @staticmethod
    def login_url(api_key: str, redirect_uri: str) -> str:
        return (
            "https://api.upstox.com/v2/login/authorization/dialog"
            f"?response_type=code&client_id={api_key}&redirect_uri={redirect_uri}"
        )

    @staticmethod
    async def exchange(api_key: str, api_secret: str, code: str, redirect_uri: str) -> AuthSession:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.upstox.com/v2/login/authorization/token",
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                data={
                    "code": code, "client_id": api_key, "client_secret": api_secret,
                    "redirect_uri": redirect_uri, "grant_type": "authorization_code",
                },
            )
            r.raise_for_status()
            data = r.json()
        return AuthSession(
            provider_key="upstox",
            access_token=data["access_token"],
            api_key=api_key,
            user_id=data.get("user_id"),
            expires_at=_next_330am_ist(),    # Upstox tokens expire 3:30am IST
        )


# ── Angel One ─────────────────────────────────────────────────────────────────

class AngelOneAuth:
    @staticmethod
    async def login(api_key: str, client_code: str, pin: str, totp: str,
                    extras: Optional[Dict] = None) -> AuthSession:
        headers = {
            "Content-Type": "application/json", "Accept": "application/json",
            "X-UserType": "USER", "X-SourceID": "WEB",
            "X-ClientLocalIP": (extras or {}).get("local_ip", "127.0.0.1"),
            "X-ClientPublicIP": (extras or {}).get("public_ip", "127.0.0.1"),
            "X-MACAddress": (extras or {}).get("mac", "00:00:00:00:00:00"),
            "X-PrivateKey": api_key,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword",
                headers=headers,
                json={"clientcode": client_code, "password": pin, "totp": totp},
            )
            r.raise_for_status()
            data = r.json()
        if not data.get("status"):
            raise ValueError(f"Angel One login failed: {data.get('message')}")
        tokens = data["data"]
        return AuthSession(
            provider_key="angelone",
            access_token=tokens["jwtToken"],
            refresh_token=tokens.get("refreshToken"),
            feed_token=tokens.get("feedToken"),
            api_key=api_key,
            user_id=client_code,
            extras=extras or {},
            expires_at=datetime.utcnow() + timedelta(hours=12),
        )


# ── Dhan ──────────────────────────────────────────────────────────────────────

class DhanAuth:
    @staticmethod
    def make_session(access_token: str, client_id: str, extras: Optional[Dict] = None) -> AuthSession:
        # Dhan tokens are long-lived (set when generated in Dhan web console)
        return AuthSession(
            provider_key="dhan",
            access_token=access_token,
            user_id=client_id,
            extras=extras or {},
            expires_at=None,    # long-lived
        )


# ── Fyers ─────────────────────────────────────────────────────────────────────

class FyersAuth:
    @staticmethod
    def login_url(app_id: str, redirect_uri: str, state: str = "hcd") -> str:
        return (
            "https://api-t1.fyers.in/api/v3/generate-authcode"
            f"?client_id={app_id}&redirect_uri={redirect_uri}"
            f"&response_type=code&state={state}"
        )

    @staticmethod
    async def exchange(app_id: str, app_secret: str, auth_code: str) -> AuthSession:
        app_id_hash = hashlib.sha256(f"{app_id}:{app_secret}".encode()).hexdigest()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api-t1.fyers.in/api/v3/validate-authcode",
                json={"grant_type": "authorization_code", "appIdHash": app_id_hash, "code": auth_code},
            )
            r.raise_for_status()
            data = r.json()
        if data.get("s") != "ok":
            raise ValueError(f"Fyers auth failed: {data.get('message')}")
        return AuthSession(
            provider_key="fyers",
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            api_key=app_id,
            expires_at=_next_6am_ist(),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_6am_ist() -> datetime:
    """Most broker tokens die ~6am IST (00:30 UTC). Return that moment in UTC."""
    now = datetime.utcnow()
    target = now.replace(hour=0, minute=30, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target


def _next_330am_ist() -> datetime:
    """Upstox tokens expire 3:30am IST (22:00 UTC previous day)."""
    now = datetime.utcnow()
    target = now.replace(hour=22, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target

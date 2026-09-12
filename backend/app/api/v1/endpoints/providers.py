"""
PROVIDERS API
=============
Endpoints to discover providers, connect Indian brokers, and fetch market data
through the unified registry — Indian brokers and global sources side by side.

  GET  /providers                     list all providers + capabilities
  GET  /providers/indian              Indian brokers only
  GET  /providers/global              global sources only
  POST /providers/{key}/login-url     get a broker OAuth login URL
  POST /providers/{key}/connect       complete auth, store session
  GET  /providers/{key}/status        is this broker connected & token valid?
  POST /providers/fetch               fetch OHLCV through any provider (with fallback)
  DELETE /providers/{key}/disconnect  drop a stored broker session
"""
from typing import Optional, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.v1.endpoints.auth import get_current_user
from app.models.models import User
from app.providers.registry import ProviderRegistry
from app.providers.base import ProviderRegion, AuthSession
from app.providers.auth_flows import (
    ZerodhaAuth, UpstoxAuth, AngelOneAuth, DhanAuth, FyersAuth,
)

router = APIRouter()


# In-memory session store keyed by (user_id, provider).
# In production, encrypt and persist these in the DB or a secrets manager.
_SESSIONS: Dict[str, AuthSession] = {}


def _session_key(user_id, provider_key: str) -> str:
    return f"{user_id}:{provider_key}"


# ── List providers ────────────────────────────────────────────────────────────

@router.get("")
async def list_providers():
    return {"providers": [p.to_dict() for p in ProviderRegistry.list_providers()]}


@router.get("/indian")
async def list_indian():
    return {"providers": [p.to_dict() for p in ProviderRegistry.list_providers(ProviderRegion.INDIA)]}


@router.get("/global")
async def list_global():
    return {"providers": [p.to_dict() for p in ProviderRegistry.list_providers(ProviderRegion.GLOBAL)]}


# ── Login URL (OAuth brokers) ─────────────────────────────────────────────────

class LoginUrlRequest(BaseModel):
    api_key: str
    redirect_uri: Optional[str] = None


@router.post("/{provider_key}/login-url")
async def get_login_url(provider_key: str, body: LoginUrlRequest,
                        current_user: User = Depends(get_current_user)):
    if provider_key == "zerodha":
        return {"login_url": ZerodhaAuth.login_url(body.api_key)}
    if provider_key == "upstox":
        if not body.redirect_uri:
            raise HTTPException(400, "redirect_uri required for Upstox")
        return {"login_url": UpstoxAuth.login_url(body.api_key, body.redirect_uri)}
    if provider_key == "fyers":
        if not body.redirect_uri:
            raise HTTPException(400, "redirect_uri required for Fyers")
        return {"login_url": FyersAuth.login_url(body.api_key, body.redirect_uri)}
    raise HTTPException(400, f"{provider_key} does not use a redirect login flow")


# ── Connect (complete auth) ───────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    # Zerodha / Fyers
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    request_token: Optional[str] = None    # Zerodha
    auth_code: Optional[str] = None        # Upstox / Fyers
    redirect_uri: Optional[str] = None     # Upstox
    # Angel One
    client_code: Optional[str] = None
    pin: Optional[str] = None
    totp: Optional[str] = None
    # Dhan
    access_token: Optional[str] = None
    client_id: Optional[str] = None
    # shared extras (exchange, IPs, segment)
    extras: Optional[Dict] = None


@router.post("/{provider_key}/connect")
async def connect_provider(provider_key: str, body: ConnectRequest,
                           current_user: User = Depends(get_current_user)):
    """Complete the broker handshake and store the session for this user."""
    try:
        if provider_key == "zerodha":
            session = await ZerodhaAuth.exchange(body.api_key, body.api_secret, body.request_token)
        elif provider_key == "upstox":
            session = await UpstoxAuth.exchange(body.api_key, body.api_secret, body.auth_code, body.redirect_uri)
        elif provider_key == "angelone":
            session = await AngelOneAuth.login(body.api_key, body.client_code, body.pin, body.totp, body.extras)
        elif provider_key == "dhan":
            session = DhanAuth.make_session(body.access_token, body.client_id, body.extras)
        elif provider_key == "fyers":
            session = await FyersAuth.exchange(body.api_key, body.api_secret, body.auth_code)
        else:
            raise HTTPException(400, f"Unknown or non-broker provider: {provider_key}")
    except Exception as e:
        raise HTTPException(401, f"Connection failed: {e}")

    _SESSIONS[_session_key(current_user.id, provider_key)] = session
    return {
        "connected": True,
        "provider": provider_key,
        "user_id": session.user_id,
        "expires_at": session.expires_at.isoformat() if session.expires_at else None,
    }


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/{provider_key}/status")
async def provider_status(provider_key: str, current_user: User = Depends(get_current_user)):
    session = _SESSIONS.get(_session_key(current_user.id, provider_key))
    info = ProviderRegistry.get_info(provider_key)
    if not info:
        raise HTTPException(404, "Unknown provider")
    return {
        "provider": provider_key,
        "requires_auth": info.requires_auth,
        "connected": session is not None and not session.is_expired,
        "expired": session.is_expired if session else None,
        "expires_at": session.expires_at.isoformat() if session and session.expires_at else None,
    }


# ── Disconnect ────────────────────────────────────────────────────────────────

@router.delete("/{provider_key}/disconnect", status_code=204)
async def disconnect(provider_key: str, current_user: User = Depends(get_current_user)):
    _SESSIONS.pop(_session_key(current_user.id, provider_key), None)


# ── Fetch through any provider (with fallback) ────────────────────────────────

class FetchRequest(BaseModel):
    symbol: str
    interval: str = "1d"
    start: Optional[str] = None
    end: Optional[str] = None
    provider: Optional[str] = None         # None → auto-route
    enable_fallback: bool = True
    provider_kwargs: Optional[Dict] = None


@router.post("/fetch")
async def fetch_market_data(body: FetchRequest, current_user: User = Depends(get_current_user)):
    """
    Fetch OHLCV through the unified registry. If a broker is requested and the
    user has a stored session, it is used; otherwise we auto-route to a global
    source. Fallback keeps the request alive if the primary provider fails.
    """
    session = None
    if body.provider:
        session = _SESSIONS.get(_session_key(current_user.id, body.provider))

    try:
        result = await ProviderRegistry.get_ohlcv(
            symbol=body.symbol,
            interval=body.interval,
            start=body.start,
            end=body.end,
            provider_key=body.provider,
            session=session,
            enable_fallback=body.enable_fallback,
            provider_kwargs=body.provider_kwargs,
        )
    except Exception as e:
        raise HTTPException(502, f"Data fetch failed: {e}")

    df = result["data"]
    return {
        "symbol": body.symbol,
        "provider_used": result["provider"],
        "fell_back": result["fell_back"],
        "attempts": result["attempts"],
        "n_bars": len(df),
        "start": str(df.index[0]),
        "end": str(df.index[-1]),
        "preview": df.tail(50).reset_index().astype(str).to_dict(orient="records"),
    }

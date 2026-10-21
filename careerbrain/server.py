"""Explicit construction of the identity API; the caller owns the runtime config."""

from .api import IdentityAPI
from .auth import AuthService, GoogleVerifier
from .db import tenant_pool


def create_app(*, auth_conninfo: str, api_conninfo: str, web_client_id: str,
               presenter_client_ids: tuple[str, ...]) -> IdentityAPI:
    verifier = GoogleVerifier(web_client_id, presenter_client_ids)
    auth_pool = tenant_pool(auth_conninfo)
    try:
        api_pool = tenant_pool(api_conninfo)
        try:
            service = AuthService(auth_pool, api_pool, verifier)
            return IdentityAPI(service)
        except BaseException:
            api_pool.close()
            raise
    except BaseException:
        auth_pool.close()
        raise

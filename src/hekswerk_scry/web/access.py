"""Reaching the workbench from another device, through Cloudflare Access.

The workbench always listens on 127.0.0.1. A Cloudflare Tunnel (`cloudflared`, running on
this machine) can carry requests for one public name, such as scry.hekswerk.com, to it.
Cloudflare Access signs the person in first and adds a signed token to each request
(the `Cf-Access-Jwt-Assertion` header). The workbench answers a request for the public
name only when that token checks out:

- it is signed (RS256) by one of the Access team's published keys, checked here, not
  only by the tunnel;
- it is for this Access application (its audience tag), from this team, of type "app";
- it is current (not expired, not from the future, allowing 30 seconds of clock skew).

Requests addressed to any other name are refused, as before. The team's keys are fetched
from Cloudflare when first needed and again when a token names a key not seen yet (at most
once a minute). If they can't be fetched, requests for the public name are refused.

A process on this machine can still reach 127.0.0.1 directly; it could read the files
anyway. Standard library only.
"""

import base64
import binascii
import contextlib
import hashlib
import hmac
import json
import re
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeGuard

TOKEN_HEADER = "Cf-Access-Jwt-Assertion"
MAX_TOKEN_BYTES = 16_384
CLOCK_SKEW_SECONDS = 30
KEY_REFRESH_SECONDS = 60
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_TEAM = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_AUDIENCE = re.compile(r"^[0-9a-f]{64}$")
# DER prefix of a SHA-256 DigestInfo, for PKCS #1 v1.5 signatures (RFC 8017, section 9.2).
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")

KeyFetcher = Callable[[str], dict[str, Any]]


class AccessSetupError(ValueError):
    """The public-access settings are wrong. The message says how to fix them."""


def fetch_keys(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        data: dict[str, Any] = json.loads(response.read())
    return data


@dataclass
class PublicAccess:
    """One public name, admitted only with a valid Cloudflare Access token."""

    host: str
    team: str
    audience: str
    fetch: KeyFetcher = fetch_keys
    clock: Callable[[], float] = time.time
    _keys: dict[str, tuple[int, int]] = field(default_factory=dict)
    _fetched_at: float = -1e18
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.host = self.host.strip().casefold()
        if not _HOSTNAME.match(self.host):
            raise AccessSetupError(
                f"'{self.host}' isn't a host name. Give the public name alone, such as "
                "scry.hekswerk.com (no https://, no port, no path).")
        if not _TEAM.match(self.team):
            raise AccessSetupError(
                f"'{self.team}' isn't a Cloudflare Access team name. It is the first part of "
                "your team domain: for raspy-salad-878a.cloudflareaccess.com, give "
                "raspy-salad-878a.")
        if not _AUDIENCE.match(self.audience):
            raise AccessSetupError(
                "The Access audience must be the application's AUD tag: 64 hexadecimal "
                "characters, from Zero Trust > Access > Applications > (the app) > Overview.")

    @property
    def issuer(self) -> str:
        return f"https://{self.team}.cloudflareaccess.com"

    @property
    def keys_url(self) -> str:
        return f"{self.issuer}/cdn-cgi/access/certs"

    def refusal(self, tokens: list[str]) -> str | None:
        """Why a request for the public name must be refused, or None to answer it."""
        if len(tokens) != 1:
            return "Sign in through Cloudflare Access to use this address."
        reason = self._check(tokens[0])
        if reason is not None:
            return (f"Your Cloudflare Access sign-in couldn't be checked ({reason}). "
                    "Sign in again and retry.")
        return None

    def _check(self, token: str) -> str | None:
        if len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
            return "token too long"
        parts = token.split(".")
        if len(parts) != 3 or not all(parts):
            return "not a token"
        header, claims = _json_part(parts[0]), _json_part(parts[1])
        signature = _base64url(parts[2])
        if header is None or claims is None or signature is None:
            return "not a token"
        if header.get("alg") != "RS256" or header.get("typ", "JWT") != "JWT":
            return "unexpected kind of signature"
        kid = header.get("kid")
        if not isinstance(kid, str) or not 1 <= len(kid) <= 256:
            return "no signing key named"
        key = self._key(kid)
        if key is None:
            return "signed by a key this team doesn't publish"
        signed = f"{parts[0]}.{parts[1]}".encode("ascii")
        if not rs256_valid(key, signed, signature):
            return "signature doesn't match"
        audience = claims.get("aud")
        audiences = [audience] if isinstance(audience, str) else audience
        if not isinstance(audiences, list) or self.audience not in audiences:
            return "token is for another application"
        if claims.get("iss") != self.issuer:
            return "token is from another team"
        if claims.get("type") != "app":
            return "not an application token"
        now = self.clock()
        expires, not_before = claims.get("exp"), claims.get("nbf")
        if not _whole_number(expires) or expires <= now - CLOCK_SKEW_SECONDS:
            return "sign-in expired"
        if not _whole_number(not_before) or not_before > now + CLOCK_SKEW_SECONDS:
            return "token isn't valid yet"
        return None

    def _key(self, kid: str) -> tuple[int, int] | None:
        with self._lock:
            if kid not in self._keys and self.clock() - self._fetched_at >= KEY_REFRESH_SECONDS:
                self._fetched_at = self.clock()
                # If the keys can't be fetched, keep what we had: an unknown key stays unknown.
                with contextlib.suppress(OSError, ValueError):
                    self._keys = _rsa_keys(self.fetch(self.keys_url))
            return self._keys.get(kid)


def rs256_valid(key: tuple[int, int], message: bytes, signature: bytes) -> bool:
    """RSASSA-PKCS1-v1_5 with SHA-256: rebuild the expected block and compare (RFC 8017)."""
    n, e = key
    size = (n.bit_length() + 7) // 8
    if len(signature) != size:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    block = pow(s, e, n).to_bytes(size, "big")
    digest = _SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    padding = size - len(digest) - 3
    if padding < 8:
        return False
    expected = b"\x00\x01" + b"\xff" * padding + b"\x00" + digest
    return hmac.compare_digest(block, expected)


def _rsa_keys(data: dict[str, Any]) -> dict[str, tuple[int, int]]:
    keys: dict[str, tuple[int, int]] = {}
    for jwk in data.get("keys", []):
        if not isinstance(jwk, dict) or jwk.get("kty") != "RSA":
            continue
        kid, n, e = jwk.get("kid"), _base64url(jwk.get("n")), _base64url(jwk.get("e"))
        if isinstance(kid, str) and n and e:
            keys[kid] = (int.from_bytes(n, "big"), int.from_bytes(e, "big"))
    if not keys:
        raise ValueError("Cloudflare published no RSA keys for this team.")
    return keys


def _base64url(text: Any) -> bytes | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        return None


def _json_part(text: str) -> dict[str, Any] | None:
    raw = _base64url(text)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _whole_number(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)

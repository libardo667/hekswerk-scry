"""The workbench's public name: answered only with a valid Cloudflare Access sign-in.

The signing key is a throwaway made with `openssl genrsa` (tests/fixtures/access_test_key.json),
together with a signature OpenSSL made, so the signature check is held to an independent
implementation rather than only to itself.
"""

import base64
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from hekswerk_scry.web.access import (
    KEY_REFRESH_SECONDS,
    AccessSetupError,
    PublicAccess,
    rs256_valid,
)

KEY = json.loads((Path(__file__).parent / "fixtures" / "access_test_key.json").read_text())
N, E, D = int(KEY["n"], 16), KEY["e"], int(KEY["d"], 16)
SIZE = (N.bit_length() + 7) // 8
AUDIENCE = "a" * 64
TEAM = "raspy-salad-878a"
NOW = 1_800_000_000


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign(message: bytes, d: int = D, n: int = N) -> bytes:
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420")
    digest = digest_info + hashlib.sha256(message).digest()
    block = b"\x00\x01" + b"\xff" * (SIZE - len(digest) - 3) + b"\x00" + digest
    return pow(int.from_bytes(block, "big"), d, n).to_bytes(SIZE, "big")


def token(header: dict[str, Any] | None = None, claims: dict[str, Any] | None = None,
          *, d: int = D) -> str:
    header = {"alg": "RS256", "kid": "key-1", "typ": "JWT", **(header or {})}
    claims = {"aud": [AUDIENCE], "iss": f"https://{TEAM}.cloudflareaccess.com", "type": "app",
              "exp": NOW + 3600, "nbf": NOW - 60, "iat": NOW - 60, "sub": "person",
              **(claims or {})}
    signed = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims).encode())}"
    return f"{signed}.{b64(sign(signed.encode(), d))}"


class Keys:
    """Stands in for Cloudflare's key list, counting how often it's asked."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failing = False

    def __call__(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        if self.failing:
            raise OSError("no network")
        return {"keys": [{"kty": "RSA", "kid": "key-1", "alg": "RS256",
                          "n": b64(N.to_bytes(SIZE, "big")), "e": b64(E.to_bytes(3, "big"))}]}


class Clock:
    def __init__(self) -> None:
        self.now = float(NOW)

    def __call__(self) -> float:
        return self.now


def public_access() -> tuple[PublicAccess, Keys, Clock]:
    keys, clock = Keys(), Clock()
    return PublicAccess("scry.hekswerk.com", TEAM, AUDIENCE, fetch=keys, clock=clock), keys, clock


class TestSignature(unittest.TestCase):
    def test_an_openssl_signature_is_accepted_and_ours_is_the_same(self) -> None:
        message = KEY["message"].encode()
        theirs = base64.b64decode(KEY["openssl_signature"])
        self.assertTrue(rs256_valid((N, E), message, theirs))
        self.assertEqual(sign(message), theirs)

    def test_any_changed_byte_breaks_it(self) -> None:
        message = KEY["message"].encode()
        good = base64.b64decode(KEY["openssl_signature"])
        for i in range(0, SIZE, 7):
            bad = bytearray(good)
            bad[i] ^= 0x01
            self.assertFalse(rs256_valid((N, E), message, bytes(bad)), i)
        for i in range(len(message)):
            bad_message = bytearray(message)
            bad_message[i] ^= 0x01
            self.assertFalse(rs256_valid((N, E), bytes(bad_message), good), i)
        self.assertFalse(rs256_valid((N, E), message, good[1:]))

    def test_the_whole_block_must_be_right_not_just_its_end(self) -> None:
        # Real signatures (made with the private key) over blocks that end in the right
        # digest but are padded wrongly. Accepting these is how lenient checks get fooled.
        message = KEY["message"].encode()
        digest = bytes.fromhex("3031300d060960864801650304020105000420") + \
            hashlib.sha256(message).digest()
        fill = SIZE - len(digest) - 3
        for block in (b"\x00\x02" + b"\xff" * fill + b"\x00" + digest,
                      b"\x00\x01" + b"\xff" * (fill - 1) + b"\x00\x00" + digest,
                      b"\x00\x01" + b"\xfe" + b"\xff" * (fill - 1) + b"\x00" + digest):
            signature = pow(int.from_bytes(block, "big"), D, N).to_bytes(SIZE, "big")
            self.assertFalse(rs256_valid((N, E), message, signature))


class TestPublicAccess(unittest.TestCase):
    def test_a_good_sign_in_is_answered(self) -> None:
        access, keys, _ = public_access()
        self.assertIsNone(access.refusal([token()]))
        self.assertEqual(keys.calls, [f"https://{TEAM}.cloudflareaccess.com/cdn-cgi/access/certs"])

    def test_everything_else_is_refused(self) -> None:
        other_key = D + 2  # signs with a different private exponent
        good = token()
        unsigned = good.rsplit(".", 1)[0] + "." + b64(b"\x00" * SIZE)
        cases: list[tuple[str, list[str]]] = [
            ("no token", []),
            ("two tokens", [good, good]),
            ("not a token", ["hello"]),
            ("signature replaced", [unsigned]),
            ("signed by another key", [token(d=other_key)]),
            ("claims changed after signing", [good.split(".")[0] + "." +
                                              b64(json.dumps({"aud": [AUDIENCE]}).encode()) +
                                              "." + good.split(".")[2]]),
            ("another application", [token(claims={"aud": ["b" * 64]})]),
            ("another team", [token(claims={"iss": "https://other.cloudflareaccess.com"})]),
            ("not an app token", [token(claims={"type": "org"})]),
            ("expired", [token(claims={"exp": NOW - 31})]),
            ("not valid yet", [token(claims={"nbf": NOW + 31})]),
            ("expiry not a number", [token(claims={"exp": "soon"})]),
            ("no signature algorithm", [token(header={"alg": "none"})]),
            ("other algorithm", [token(header={"alg": "HS256"})]),
            ("unknown key", [token(header={"kid": "key-2"})]),
            ("no key named", [token(header={"kid": ""})]),
        ]
        for name, tokens in cases:
            with self.subTest(name):
                access, _, _ = public_access()
                self.assertIsNotNone(access.refusal(tokens))

    def test_clock_skew_of_thirty_seconds_is_allowed(self) -> None:
        access, _, _ = public_access()
        self.assertIsNone(access.refusal([token(claims={"exp": NOW - 29, "nbf": NOW + 29})]))

    def test_keys_are_fetched_again_for_a_new_key_at_most_once_a_minute(self) -> None:
        access, keys, clock = public_access()
        self.assertIsNone(access.refusal([token()]))
        for _ in range(5):
            self.assertIsNotNone(access.refusal([token(header={"kid": "key-2"})]))
        self.assertEqual(len(keys.calls), 1)
        clock.now += KEY_REFRESH_SECONDS
        access.refusal([token(header={"kid": "key-2"})])
        self.assertEqual(len(keys.calls), 2)
        self.assertIsNone(access.refusal([token()]))  # known keys need no fetch
        self.assertEqual(len(keys.calls), 2)

    def test_no_keys_means_no_entry(self) -> None:
        access, keys, _ = public_access()
        keys.failing = True
        self.assertIsNotNone(access.refusal([token()]))

    def test_settings_are_checked(self) -> None:
        for host, team, audience in [
            ("https://scry.hekswerk.com", TEAM, AUDIENCE),
            ("scry.hekswerk.com:443", TEAM, AUDIENCE),
            ("scry.hekswerk.com", "raspy-salad-878a.cloudflareaccess.com", AUDIENCE),
            ("scry.hekswerk.com", TEAM, "not-an-aud-tag"),
        ]:
            with self.subTest((host, team, audience)), self.assertRaises(AccessSetupError):
                PublicAccess(host, team, audience)
        self.assertEqual(PublicAccess("Scry.Hekswerk.com", TEAM, AUDIENCE).host,
                         "scry.hekswerk.com")


if __name__ == "__main__":
    unittest.main()

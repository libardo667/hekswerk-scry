"""Downloading DeepMind's published AlphaProof proofs from IMO 2024.

The archive is published alongside DeepMind's IMO 2024 solutions page. It is not stored
in this repository (it carries no license), so Scry downloads it on request and checks it
against a fixed fingerprint before using it. Only the three Lean files edited to compile
on public Lean and Mathlib are extracted.
"""

import hashlib
import urllib.request
import zipfile
from pathlib import Path

from hekswerk_scry.lean.workspace import LeanWorkspace

ARCHIVE_URL = (
    "https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/"
    "imo-2024-solutions/static/alphaproof-outputs.zip"
)
ARCHIVE_SHA256 = "a1c83ea22a1b9cf0b1fbf339b4041355c97bfe47b25753322ae19d328568cd51"
PROOFS = {
    "AlphaProof/P1.lean": "imo_2024_p1",
    "AlphaProof/P2.lean": "imo_2024_p2",
    "AlphaProof/P6.lean": "imo_2024_p6",
}
FOLDER = Path("fetched") / "alphaproof"


class AlphaProofFetchError(RuntimeError):
    """The archive couldn't be downloaded, or it isn't the expected file."""


def fetch_alphaproof(workspace: LeanWorkspace, *, timeout: float = 120) -> dict[Path, str]:
    """Download and extract the proofs. Returns each file's path and its theorem's name."""
    target = workspace.root / FOLDER
    target.mkdir(parents=True, exist_ok=True)
    archive = target / "alphaproof-outputs.zip"
    if not archive.is_file() or _sha256(archive) != ARCHIVE_SHA256:
        try:
            with urllib.request.urlopen(ARCHIVE_URL, timeout=timeout) as response:
                data = response.read()
        except OSError as exc:
            raise AlphaProofFetchError(
                f"Couldn't download the AlphaProof archive from {ARCHIVE_URL}: {exc}"
            ) from exc
        if hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
            raise AlphaProofFetchError(
                "The downloaded AlphaProof archive is not the expected file (its fingerprint "
                "doesn't match), so it was not used."
            )
        archive.write_bytes(data)
    extracted: dict[Path, str] = {}
    with zipfile.ZipFile(archive) as bundle:
        for member, theorem in PROOFS.items():
            path = target / Path(member).name
            path.write_bytes(bundle.read(member))
            extracted[path] = theorem
    return extracted


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

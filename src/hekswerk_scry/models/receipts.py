"""Receipts: a record of one check."""

from dataclasses import dataclass
from typing import Any, Self

from hekswerk_scry.core.enums import CheckKind
from hekswerk_scry.core.hashing import fingerprint_data


@dataclass(frozen=True)
class LeanRunEvidence:
    """What actually happened when Lean ran: the command, how it ended, and its output.

    Every Lean receipt carries one, so anyone reading a receipt can see the run it came
    from. Only code that has just run Lean creates these (`lean/runner.py` for proofs,
    `lean/statement.py` for statements), in a new process or the kept-running one.
    """

    command: tuple[str, ...]
    exit_code: int | None
    timed_out: bool
    output_sha256: str
    seconds: float

    def __post_init__(self) -> None:
        if not self.command or len(self.output_sha256) != 64:
            raise ValueError(
                "Lean run evidence needs the command that ran and its output's SHA-256."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "output_sha256": self.output_sha256,
            "seconds": round(self.seconds, 3),
        }


@dataclass(frozen=True)
class Receipt:
    """A record of one check: what was checked, by which checker, and the result.

    A receipt is a record, not a permission slip. Nothing in Scry applies a change
    because a receipt says it passed; changes are re-checked at the moment they are
    applied. That way a hand-made or out-of-date receipt can't unlock anything.

    A receipt that says it came from Lean can only be made with `from_lean_run`, which
    requires the evidence of an actual Lean run; `create` refuses to make one.
    """

    receipt_id: str
    checked_by: CheckKind
    subject: str
    subject_fingerprint: str
    passed: bool
    summary: str
    lean_run: LeanRunEvidence | None = None

    @classmethod
    def create(
        cls,
        *,
        checked_by: CheckKind,
        subject: str,
        subject_fingerprint: str,
        passed: bool,
        summary: str,
    ) -> Self:
        if checked_by is CheckKind.LEAN:
            raise ValueError(
                "A receipt can only say it came from Lean if it carries the evidence of an "
                "actual Lean run. Use Receipt.from_lean_run."
            )
        return cls._make(checked_by, subject, subject_fingerprint, passed, summary, None)

    @classmethod
    def from_lean_run(
        cls,
        evidence: LeanRunEvidence,
        *,
        subject: str,
        subject_fingerprint: str,
        passed: bool,
        summary: str,
    ) -> Self:
        return cls._make(CheckKind.LEAN, subject, subject_fingerprint, passed, summary, evidence)

    @classmethod
    def _make(
        cls,
        checked_by: CheckKind,
        subject: str,
        subject_fingerprint: str,
        passed: bool,
        summary: str,
        lean_run: LeanRunEvidence | None,
    ) -> Self:
        receipt_id = fingerprint_data(
            {
                "checked_by": checked_by.value,
                "subject": subject,
                "subject_fingerprint": subject_fingerprint,
                "passed": passed,
                "summary": summary,
                "lean_run": lean_run.to_dict() if lean_run else None,
            }
        )
        return cls(
            receipt_id=receipt_id,
            checked_by=checked_by,
            subject=subject,
            subject_fingerprint=subject_fingerprint,
            passed=passed,
            summary=summary,
            lean_run=lean_run,
        )

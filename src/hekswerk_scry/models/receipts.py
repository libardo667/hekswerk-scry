"""Receipts: a record of one check."""

from dataclasses import dataclass
from typing import Self

from hekswerk_scry.core.enums import CheckKind
from hekswerk_scry.core.hashing import fingerprint_data


@dataclass(frozen=True)
class Receipt:
    """A record of one check: what was checked, by which checker, and the result.

    A receipt is a record, not a permission slip. Nothing in Scry applies a change
    because a receipt says it passed; changes are re-checked at the moment they are
    applied. That way a hand-made or out-of-date receipt can't unlock anything.
    """

    receipt_id: str
    checked_by: CheckKind
    subject: str
    subject_fingerprint: str
    passed: bool
    summary: str

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
        receipt_id = fingerprint_data(
            {
                "checked_by": checked_by.value,
                "subject": subject,
                "subject_fingerprint": subject_fingerprint,
                "passed": passed,
                "summary": summary,
            }
        )
        return cls(
            receipt_id=receipt_id,
            checked_by=checked_by,
            subject=subject,
            subject_fingerprint=subject_fingerprint,
            passed=passed,
            summary=summary,
        )

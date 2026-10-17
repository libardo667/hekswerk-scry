"""The built-in checks: wiring, scanning, What-If tests, and Simplification cards."""

from hekswerk_scry.checker.cards import CardCheck, CardRejectedError, apply_card, check_card
from hekswerk_scry.checker.regions import RegionBoundary, region_boundary
from hekswerk_scry.checker.scanner import Chokepoint, Knot, MapScan, UnusedStep, scan_proof_map
from hekswerk_scry.checker.what_if import WIRING_WHAT_IF_CAVEAT, run_what_if
from hekswerk_scry.checker.wiring import StepVerdict, WiringProblem, WiringReport, check_wiring

__all__ = [
    "WIRING_WHAT_IF_CAVEAT",
    "CardCheck",
    "CardRejectedError",
    "Chokepoint",
    "Knot",
    "MapScan",
    "RegionBoundary",
    "StepVerdict",
    "UnusedStep",
    "WiringProblem",
    "WiringReport",
    "apply_card",
    "check_card",
    "check_wiring",
    "region_boundary",
    "run_what_if",
    "scan_proof_map",
]

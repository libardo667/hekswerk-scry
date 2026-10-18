"""Blocks the workbench folds when it draws a Lean map.

Two real maps (openai/math proofs; see tests/fixtures/maps/NOTICE.md) and a made-up one
where a "block" would let a route leave it and come back in.
"""

import random
import unittest
from pathlib import Path

from hekswerk_scry.files import load_proof_map
from hekswerk_scry.models import LeanRange, ProofMap, ProofStep, StepContract, StepViews
from hekswerk_scry.web.blocks import Block, foldable_blocks
from tests.helpers import make_map

MAPS = sorted((Path(__file__).parent / "fixtures" / "maps").glob("*.json"))


def folded(proof_map: ProofMap, blocks: list[Block], open_roots: set[str]) -> dict[str, str]:
    """What each step is drawn as: the outermost block around it that isn't open, or itself."""
    drawn = {step_id: step_id for step_id in proof_map.steps}
    for block in sorted(blocks, key=lambda b: len(b.members)):  # inner blocks first
        if block.root not in open_roots:
            for member in block.members:
                drawn[member] = f"block:{block.root}"
    return drawn


def has_cycle(edges: set[tuple[str, str]]) -> bool:
    nodes = {n for edge in edges for n in edge}
    incoming = {n: 0 for n in nodes}
    for _, b in edges:
        incoming[b] += 1
    ready = [n for n, k in incoming.items() if k == 0]
    done = 0
    while ready:
        n = ready.pop()
        done += 1
        for a, b in edges:
            if a == n:
                incoming[b] -= 1
                if incoming[b] == 0:
                    ready.append(b)
    return done != len(nodes)


def span(step: ProofStep) -> tuple[tuple[int, int], tuple[int, int]]:
    r = step.lean_range
    assert r is not None
    return (r.start_line, r.start_column), (r.end_line, r.end_column)


class TestRealMaps(unittest.TestCase):
    def setUp(self) -> None:
        self.maps = [load_proof_map(p) for p in MAPS]
        self.assertEqual(len(self.maps), 2)

    def test_there_are_blocks_and_folding_them_makes_the_drawing_smaller(self) -> None:
        for proof_map in self.maps:
            blocks = foldable_blocks(proof_map)
            self.assertGreaterEqual(len(blocks), 8)
            shown = set(folded(proof_map, blocks, set()).values())
            self.assertLess(len(shown), len(proof_map.steps) * 0.7)

    def test_a_block_is_its_root_s_why_steps_and_what_is_written_inside_it(self) -> None:
        for proof_map in self.maps:
            steps = proof_map.steps
            for block in foldable_blocks(proof_map):
                with self.subTest(block.root):
                    self.assertNotIn(block.root, block.members)
                    (start, end) = span(steps[block.root])
                    whys = {s for s, step in steps.items() if step.lean_introduced_by == block.root}
                    self.assertTrue(whys and whys <= set(block.members))
                    for member in block.members:
                        step = steps[member]
                        if step.lean_range is not None:
                            a, b = span(step)
                            self.assertTrue(start <= a and b <= end and (a, b) != (start, end))
                        else:
                            self.assertTrue(step.lean_introduced_by == block.root or
                                            step.lean_introduced_by in block.members)
                    # ... and everything written inside it is in it, with its "why" steps.
                    for step_id, step in steps.items():
                        if step_id != block.root and step.lean_range is not None:
                            a, b = span(step)
                            if start <= a and b <= end and (a, b) != (start, end):
                                self.assertIn(step_id, block.members)
                        if step.lean_introduced_by in block.members:
                            self.assertIn(step_id, block.members)
                    self.assertEqual(block.gives, tuple(steps[w].contract.proves for w in
                                                        sorted(whys, key=block.members.index)))
                    proven = {steps[m].contract.proves for m in block.members}
                    used = {f for m in block.members for f in steps[m].contract.assumes}
                    self.assertEqual(set(block.takes), used - proven)

    def test_nested_blocks_sit_wholly_inside_their_parent(self) -> None:
        for proof_map in self.maps:
            blocks = {b.root: b for b in foldable_blocks(proof_map)}
            for block in blocks.values():
                if block.parent is not None:
                    parent = blocks[block.parent]
                    self.assertIn(block.root, parent.members)
                    self.assertLess(set(block.members), set(parent.members))

    def test_folding_any_blocks_never_draws_arrows_in_a_circle(self) -> None:
        rng = random.Random(11)
        for proof_map in self.maps:
            blocks = foldable_blocks(proof_map)
            roots = [b.root for b in blocks]
            for trial in range(300):
                open_roots = {r for r in roots if rng.random() < 0.5} if trial else set()
                drawn = folded(proof_map, blocks, open_roots)
                edges = {(drawn[d], drawn[s]) for s, step in proof_map.steps.items()
                         for d in step.depends_on if drawn[d] != drawn[s]}
                self.assertFalse(has_cycle(edges), (proof_map.map_id, sorted(open_roots)))


class TestMadeUpMap(unittest.TestCase):
    def test_a_block_a_route_could_leave_and_reenter_is_not_offered(self) -> None:
        # `have h` (lines 1-5) proves h from its inner step and from x, written outside it,
        # which uses the inner step. Folded, the box would both feed x and be fed by it.
        def step(step_id: str, deps: tuple[str, ...] = (),
                 lines: tuple[int, int] | None = None, why_of: str | None = None) -> ProofStep:
            return ProofStep(
                step_id=step_id, title=step_id,
                contract=StepContract(assumes=tuple(f"f-{d}" for d in deps),
                                      proves=f"f-{step_id}"),
                views=StepViews(), depends_on=deps,
                lean_range=LeanRange(lines[0], 2, lines[1], 9) if lines else None,
                lean_introduced_by=why_of)

        steps = [
            step("goal", ("have",), (1, 9)),
            step("have", ("next",), (1, 5)),
            step("have-why1", ("inner", "x"), why_of="have"),
            step("inner", (), (2, 2)),
            step("x", ("inner",), (7, 7)),
            step("next", ("have-why1",), (8, 8)),
        ]
        self.assertEqual(foldable_blocks(make_map(steps, "goal")), [])
        steps[4] = step("x", (), (7, 7))  # without the route back in
        [block] = foldable_blocks(make_map(steps, "goal"))
        self.assertEqual(set(block.members), {"have-why1", "inner"})
        self.assertEqual(block.takes, ("f-x",))

if __name__ == "__main__":
    unittest.main()

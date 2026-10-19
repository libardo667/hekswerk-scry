"""Reading and writing proof maps and outlines as JSON files.

The format is deliberately strict: missing fields, unknown fields, and wrong types are
all rejected with a message saying what to fix, so a typo never goes unnoticed.
Files hold content only. There is no field for "this step was checked": statuses are
always worked out fresh by a checker.
"""

import json
from pathlib import Path
from typing import Any

from hekswerk_scry.models.outline import Outline, OutlineError, OutlinePart, UnusedHypothesis
from hekswerk_scry.models.proof_map import (
    LeanRange,
    LeanSource,
    ProofMap,
    ProofStep,
    StepContract,
    StepViews,
    SwapRecord,
)

FORMAT_NAME = "hekswerk-scry/proof-map"
FORMAT_VERSION = 1

_MAP_REQUIRED = frozenset(
    {"format", "version", "map_id", "title", "starting_facts", "goal", "goal_step_id", "steps"}
)
_MAP_OPTIONAL = frozenset({"archived_steps", "history", "lean_source"})
_STEP_REQUIRED = frozenset({"id", "title", "assumes", "proves"})
_STEP_OPTIONAL = frozenset(
    {"depends_on", "views", "lean_range", "lean_value_range", "lean_introduced_by"}
)
_LEAN_SOURCE_KEYS = frozenset({"file", "theorem", "file_sha256"})
_LEAN_RANGE_KEYS = frozenset({"start_line", "start_column", "end_line", "end_column"})
_VIEW_KEYS = frozenset({"plain_english", "math", "code"})
_HISTORY_KEYS = frozenset(
    {"card_id", "card_title", "removed_step_ids", "added_step_ids", "receipt_id"}
)
_HISTORY_OPTIONAL = frozenset({"lean_before", "lean_after"})

OUTLINE_FORMAT = "hekswerk-scry/outline"
OUTLINE_SUFFIX = ".outline.json"  # how the workbench recognises an outline file
OUTLINE_VERSION = 1
_OUTLINE_KEYS = frozenset({"format", "version", "result", "project", "lean_version",
                           "file_sha256", "axioms", "parts"})
_PART_KEYS = frozenset({"id", "name", "kind", "private", "module", "file", "start_line",
                        "end_line", "doc", "statement", "source", "statement_uses", "body_uses",
                        "unused_hypotheses"})
_HYPOTHESIS_KEYS = frozenset({"name", "statement"})


class MapFileError(ValueError):
    """A proof map file could not be read. The message says what to fix."""


def load_proof_map(path: Path) -> ProofMap:
    """Read a proof map from a JSON file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MapFileError(f"Couldn't open '{path}': {exc.strerror}.") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MapFileError(
            f"'{path}' is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}."
        ) from exc
    return proof_map_from_dict(data, source=str(path))


def save_proof_map(proof_map: ProofMap, path: Path) -> None:
    """Write a proof map to a JSON file."""
    text = json.dumps(proof_map_to_dict(proof_map), indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def proof_map_to_dict(proof_map: ProofMap) -> dict[str, Any]:
    data: dict[str, Any] = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "map_id": proof_map.map_id,
        "title": proof_map.title,
        "starting_facts": list(proof_map.starting_facts),
        "goal": proof_map.goal,
        "goal_step_id": proof_map.goal_step_id,
        "steps": [_step_to_dict(step) for step in proof_map.steps.values()],
    }
    if proof_map.archived_steps:
        data["archived_steps"] = [_step_to_dict(s) for s in proof_map.archived_steps.values()]
    if proof_map.history:
        data["history"] = [
            {key: value for key, value in record.to_dict().items() if value is not None}
            for record in proof_map.history
        ]
    if proof_map.lean_source:
        data["lean_source"] = proof_map.lean_source.to_dict()
    return data


def proof_map_from_dict(data: object, source: str = "The proof map") -> ProofMap:
    """Build a proof map from parsed JSON, rejecting anything malformed."""
    top = _object(data, source)
    _check_keys(top, source, _MAP_REQUIRED, _MAP_OPTIONAL)
    if top["format"] != FORMAT_NAME or top["version"] != FORMAT_VERSION:
        raise MapFileError(
            f"{source} says it is format {top['format']!r} version {top['version']!r}. "
            f"This version of Scry reads format '{FORMAT_NAME}' version {FORMAT_VERSION}."
        )
    steps = _steps(top["steps"], f"{source}, 'steps'")
    archived = _steps(top.get("archived_steps", []), f"{source}, 'archived_steps'")
    history = tuple(
        _history_record(raw, f"{source}, history entry {index + 1}")
        for index, raw in enumerate(_list(top.get("history", []), f"{source}, 'history'"))
    )
    try:
        return ProofMap(
            map_id=_text(top["map_id"], f"{source}, 'map_id'"),
            title=_text(top["title"], f"{source}, 'title'"),
            starting_facts=_text_list(top["starting_facts"], f"{source}, 'starting_facts'"),
            goal=_text(top["goal"], f"{source}, 'goal'"),
            goal_step_id=_text(top["goal_step_id"], f"{source}, 'goal_step_id'"),
            steps=steps,
            archived_steps=archived,
            history=history,
            lean_source=_lean_source(top.get("lean_source"), f"{source}, 'lean_source'"),
        )
    except MapFileError:
        raise
    except ValueError as exc:
        raise MapFileError(f"{source}: {exc}") from exc


def _step_to_dict(step: ProofStep) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": step.step_id,
        "title": step.title,
        "assumes": list(step.contract.assumes),
        "proves": step.contract.proves,
    }
    if step.depends_on:
        data["depends_on"] = list(step.depends_on)
    views = {key: value for key, value in step.views.to_dict().items() if value is not None}
    if views:
        data["views"] = views
    if step.lean_range:
        data["lean_range"] = step.lean_range.to_dict()
    if step.lean_value_range:
        data["lean_value_range"] = step.lean_value_range.to_dict()
    if step.lean_introduced_by:
        data["lean_introduced_by"] = step.lean_introduced_by
    return data


def _steps(raw: object, where: str) -> dict[str, ProofStep]:
    steps: dict[str, ProofStep] = {}
    for index, raw_step in enumerate(_list(raw, where)):
        step = _step(raw_step, f"{where}, step {index + 1}")
        if step.step_id in steps:
            raise MapFileError(f"{where}: the step ID '{step.step_id}' is used more than once.")
        steps[step.step_id] = step
    return steps


def _step(raw: object, where: str) -> ProofStep:
    obj = _object(raw, where)
    _check_keys(obj, where, _STEP_REQUIRED, _STEP_OPTIONAL)
    views_raw = _object(obj.get("views", {}), f"{where}, 'views'")
    _check_keys(views_raw, f"{where}, 'views'", frozenset(), _VIEW_KEYS)
    try:
        return ProofStep(
            step_id=_text(obj["id"], f"{where}, 'id'"),
            title=_text(obj["title"], f"{where}, 'title'"),
            contract=StepContract(
                assumes=_text_list(obj["assumes"], f"{where}, 'assumes'"),
                proves=_text(obj["proves"], f"{where}, 'proves'"),
            ),
            views=StepViews(
                **{
                    key: _text(value, f"{where}, views '{key}'")
                    for key, value in views_raw.items()
                }
            ),
            depends_on=_text_list(obj.get("depends_on", []), f"{where}, 'depends_on'"),
            lean_range=_lean_range(obj.get("lean_range"), f"{where}, 'lean_range'"),
            lean_value_range=_lean_range(
                obj.get("lean_value_range"), f"{where}, 'lean_value_range'"
            ),
            lean_introduced_by=(
                _text(obj["lean_introduced_by"], f"{where}, 'lean_introduced_by'")
                if "lean_introduced_by" in obj
                else None
            ),
        )
    except MapFileError:
        raise
    except ValueError as exc:
        raise MapFileError(f"{where}: {exc}") from exc


def _history_record(raw: object, where: str) -> SwapRecord:
    obj = _object(raw, where)
    _check_keys(obj, where, _HISTORY_KEYS, _HISTORY_OPTIONAL)
    return SwapRecord(
        card_id=_text(obj["card_id"], f"{where}, 'card_id'"),
        card_title=_text(obj["card_title"], f"{where}, 'card_title'"),
        removed_step_ids=_text_list(obj["removed_step_ids"], f"{where}, 'removed_step_ids'"),
        added_step_ids=_text_list(obj["added_step_ids"], f"{where}, 'added_step_ids'"),
        receipt_id=_text(obj["receipt_id"], f"{where}, 'receipt_id'"),
        lean_before=_lean_source(obj.get("lean_before"), f"{where}, 'lean_before'"),
        lean_after=_lean_source(obj.get("lean_after"), f"{where}, 'lean_after'"),
    )


def _lean_source(raw: object, where: str) -> LeanSource | None:
    if raw is None:
        return None
    obj = _object(raw, where)
    _check_keys(obj, where, _LEAN_SOURCE_KEYS, frozenset({"project"}))
    return LeanSource(
        file=_text(obj["file"], f"{where}, 'file'"),
        theorem=_text(obj["theorem"], f"{where}, 'theorem'"),
        file_sha256=_text(obj["file_sha256"], f"{where}, 'file_sha256'"),
        project=_text(obj["project"], f"{where}, 'project'") if "project" in obj else None,
    )


def _lean_range(raw: object, where: str) -> LeanRange | None:
    if raw is None:
        return None
    obj = _object(raw, where)
    _check_keys(obj, where, _LEAN_RANGE_KEYS, frozenset())
    numbers = {key: _whole_number(obj[key], f"{where}, '{key}'") for key in _LEAN_RANGE_KEYS}
    return LeanRange(**numbers)


def _whole_number(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MapFileError(f"{where} should be a whole number.")
    return value


def _object(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MapFileError(f"{where} should be a JSON object ({{...}}).")
    return value


def _list(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise MapFileError(f"{where} should be a list ([...]).")
    return value


def _text(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise MapFileError(f"{where} should be text in quotes.")
    return value


def _text_list(value: object, where: str) -> tuple[str, ...]:
    return tuple(
        _text(item, f"{where}, item {index + 1}") for index, item in enumerate(_list(value, where))
    )


def _check_keys(
    obj: dict[str, Any], where: str, required: frozenset[str], optional: frozenset[str]
) -> None:
    missing = sorted(required - obj.keys())
    if missing:
        raise MapFileError(f"{where} is missing: {', '.join(missing)}.")
    unknown = sorted(obj.keys() - required - optional)
    if unknown:
        raise MapFileError(
            f"{where} has field(s) Scry doesn't recognise: {', '.join(unknown)}. "
            "(Unknown fields are rejected so that typos don't go unnoticed.)"
        )


# --- outlines --------------------------------------------------------------------------


def load_outline(path: Path) -> Outline:
    """Read an outline from a JSON file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MapFileError(f"Couldn't open '{path}': {exc.strerror}.") from exc
    except json.JSONDecodeError as exc:
        raise MapFileError(
            f"'{path}' is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}."
        ) from exc
    return outline_from_dict(data, source=str(path))


def save_outline(outline: Outline, path: Path) -> None:
    text = json.dumps(outline_to_dict(outline), indent=1, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def outline_to_dict(outline: Outline) -> dict[str, Any]:
    return {
        "format": OUTLINE_FORMAT, "version": OUTLINE_VERSION, "result": outline.result,
        "project": outline.project, "lean_version": outline.lean_version,
        "file_sha256": dict(outline.file_sha256), "axioms": list(outline.axioms),
        "parts": [{
            "id": p.part_id, "name": p.name, "kind": p.kind, "private": p.private,
            "module": p.module, "file": p.file, "start_line": p.start_line,
            "end_line": p.end_line, "doc": p.doc, "statement": p.statement, "source": p.source,
            "statement_uses": list(p.statement_uses), "body_uses": list(p.body_uses),
            "unused_hypotheses": [{"name": h.name, "statement": h.statement}
                                  for h in p.unused_hypotheses],
        } for p in outline.parts.values()],
    }


def outline_from_dict(data: object, source: str = "The outline") -> Outline:
    """Build an outline from parsed JSON, rejecting anything malformed."""
    top = _object(data, source)
    _check_keys(top, source, _OUTLINE_KEYS, frozenset())
    if top["format"] != OUTLINE_FORMAT or top["version"] != OUTLINE_VERSION:
        raise MapFileError(
            f"{source} says it is format {top['format']!r} version {top['version']!r}. "
            f"This version of Scry reads outlines in format '{OUTLINE_FORMAT}' version "
            f"{OUTLINE_VERSION}."
        )
    hashes = _object(top["file_sha256"], f"{source}, 'file_sha256'")
    parts: dict[str, OutlinePart] = {}
    for index, raw in enumerate(_list(top["parts"], f"{source}, 'parts'")):
        part = _part(raw, f"{source}, part {index + 1}")
        if part.part_id in parts:
            raise MapFileError(f"{source}: the part '{part.part_id}' is listed more than once.")
        parts[part.part_id] = part
    try:
        return Outline(
            result=_text(top["result"], f"{source}, 'result'"),
            project=_text(top["project"], f"{source}, 'project'"),
            lean_version=_text(top["lean_version"], f"{source}, 'lean_version'"),
            file_sha256={_text(k, f"{source}, 'file_sha256'"): _text(v, f"{source}, "
                         f"'file_sha256' of '{k}'") for k, v in hashes.items()},
            axioms=_text_list(top["axioms"], f"{source}, 'axioms'"),
            parts=parts,
        )
    except OutlineError as exc:
        raise MapFileError(f"{source}: {exc}") from exc


def _part(raw: object, where: str) -> OutlinePart:
    obj = _object(raw, where)
    _check_keys(obj, where, _PART_KEYS, frozenset())
    hypotheses = []
    for index, h in enumerate(_list(obj["unused_hypotheses"], f"{where}, 'unused_hypotheses'")):
        h_where = f"{where}, unused hypothesis {index + 1}"
        h_obj = _object(h, h_where)
        _check_keys(h_obj, h_where, _HYPOTHESIS_KEYS, frozenset())
        hypotheses.append(UnusedHypothesis(_maybe_text(h_obj["name"], f"{h_where}, 'name'"),
                                           _text(h_obj["statement"], f"{h_where}, 'statement'")))
    private = obj["private"]
    if not isinstance(private, bool):
        raise MapFileError(f"{where}, 'private' should be true or false.")
    return OutlinePart(
        part_id=_text(obj["id"], f"{where}, 'id'"),
        name=_text(obj["name"], f"{where}, 'name'"),
        kind=_text(obj["kind"], f"{where}, 'kind'"),
        private=private,
        module=_maybe_text(obj["module"], f"{where}, 'module'"),
        file=_maybe_text(obj["file"], f"{where}, 'file'"),
        start_line=_maybe_number(obj["start_line"], f"{where}, 'start_line'"),
        end_line=_maybe_number(obj["end_line"], f"{where}, 'end_line'"),
        doc=_maybe_text(obj["doc"], f"{where}, 'doc'"),
        statement=_text(obj["statement"], f"{where}, 'statement'"),
        source=_maybe_text(obj["source"], f"{where}, 'source'"),
        statement_uses=_text_list(obj["statement_uses"], f"{where}, 'statement_uses'"),
        body_uses=_text_list(obj["body_uses"], f"{where}, 'body_uses'"),
        unused_hypotheses=tuple(hypotheses),
    )


def _maybe_text(value: object, where: str) -> str | None:
    return None if value is None else _text(value, where)


def _maybe_number(value: object, where: str) -> int | None:
    return None if value is None else _whole_number(value, where)

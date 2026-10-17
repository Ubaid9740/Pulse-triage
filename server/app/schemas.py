"""Validates JSON against the shared schemas in shared/schemas (the contract with the app and dashboard)."""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


class Schemas:
    def __init__(self, shared_dir: Path):
        root = shared_dir / "schemas"
        docs: dict[str, dict] = {}
        for path in sorted(root.rglob("*.schema.json")):
            name = path.relative_to(root).as_posix().removesuffix(".schema.json")
            docs[name] = json.loads(path.read_text(encoding="utf-8"))
        registry = Registry().with_resources(
            (doc["$id"], Resource.from_contents(doc)) for doc in docs.values())
        self._validators = {
            name: Draft202012Validator(doc, registry=registry) for name, doc in docs.items()}

    @property
    def names(self) -> list[str]:
        return sorted(self._validators)

    def errors(self, name: str, instance) -> list[str]:
        """All validation errors as short readable strings; empty when valid."""
        validator = self._validators[name]
        out = []
        for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.path)):
            where = "/".join(str(p) for p in err.path) or "(root)"
            out.append(f"{where}: {err.message}")
        return out

    def check(self, name: str, instance) -> None:
        problems = self.errors(name, instance)
        if problems:
            raise ValueError(f"{name}: " + "; ".join(problems[:3]))

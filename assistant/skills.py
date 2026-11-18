"""SKILL.md loader – YAML front matter + Markdown body.

Progressive disclosure: at startup only the name and description are loaded
(catalog); the full body goes into the prompt only when the skill runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass
class Skill:
    name: str
    description: str
    allowed_tools: list[str]
    required_tools: list[str]
    output_model: str
    path: Path

    @property
    def body(self) -> str:
        return _split(self.path.read_text(encoding="utf-8"))[1]


def _split(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("SKILL.md must start with a YAML front matter.")
    _, header, body = text.split("---", 2)
    return yaml.safe_load(header) or {}, body.strip()


def load_skill(path: Path) -> Skill:
    meta, _ = _split(path.read_text(encoding="utf-8"))
    for key in ("name", "description", "allowed-tools", "output-model"):
        if key not in meta:
            raise ValueError(f"{path}: missing front matter field: {key}")
    return Skill(
        name=meta["name"],
        description=" ".join(str(meta["description"]).split()),
        allowed_tools=list(meta["allowed-tools"]),
        required_tools=list(meta.get("required-tools", [])),
        output_model=meta["output-model"],
        path=path,
    )


def load_catalog(directory: Path = SKILLS_DIR) -> dict[str, Skill]:
    return {s.name: s for s in (load_skill(p) for p in sorted(directory.glob("*/SKILL.md")))}

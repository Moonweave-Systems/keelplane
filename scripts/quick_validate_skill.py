#!/usr/bin/env python3
"""Repo-local skill package validator.

This intentionally covers the small release-gate surface needed by this skill
without depending on the host Codex installation or PyYAML.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


ALLOWED_FRONTMATTER_KEYS = {"name", "description", "license", "allowed-tools", "metadata"}
REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "agents/openai.yaml",
    "docs/github-research.md",
    "docs/fixture-smoke/v0-smoke.md",
    "docs/spec.md",
    "references/workflow-patterns.md",
    "references/workflow-plan-schema.md",
    "scripts/check_release_text.py",
]
MAX_SKILL_NAME_LENGTH = 64


class ValidationError(ValueError):
    """Raised when the skill package is invalid."""


def parse_simple_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        raise ValidationError("No YAML frontmatter found")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        raise ValidationError("Invalid frontmatter format")
    result: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise ValidationError(f"Unsupported frontmatter line: {line}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        if key in result:
            raise ValidationError(f"Duplicate frontmatter key: {key}")
        result[key] = value.strip().strip("\"'")
    return result


def parse_simple_agent_yaml(text: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    current_section = ""
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            if not line.endswith(":"):
                raise ValidationError(f"Unsupported agents/openai.yaml line: {line}")
            current_section = line[:-1].strip()
            if current_section in result:
                raise ValidationError(f"Duplicate agents/openai.yaml section: {current_section}")
            result[current_section] = {}
            continue
        if not current_section:
            raise ValidationError("agents/openai.yaml key appears before a section")
        stripped = line.strip()
        if ":" not in stripped:
            raise ValidationError(f"Unsupported agents/openai.yaml line: {line}")
        key, value = stripped.split(":", 1)
        result[current_section][key.strip()] = value.strip().strip("\"'")
    return result


def title_from_skill_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-"))


def validate_skill(root: Path) -> None:
    for rel_path in REQUIRED_FILES:
        path = root / rel_path
        if not path.exists():
            raise ValidationError(f"Required file missing: {rel_path}")
        if not path.is_file():
            raise ValidationError(f"Required path is not a file: {rel_path}")

    frontmatter = parse_simple_frontmatter((root / "SKILL.md").read_text())
    extra = sorted(set(frontmatter) - ALLOWED_FRONTMATTER_KEYS)
    if extra:
        raise ValidationError(f"Unexpected SKILL.md frontmatter keys: {extra}")
    for key in ["name", "description"]:
        if key not in frontmatter:
            raise ValidationError(f"Missing SKILL.md frontmatter key: {key}")
        if not isinstance(frontmatter[key], str) or not frontmatter[key].strip():
            raise ValidationError(f"SKILL.md frontmatter key is empty: {key}")

    name = frontmatter["name"].strip()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValidationError("Skill name must be hyphen-case")
    if len(name) > MAX_SKILL_NAME_LENGTH:
        raise ValidationError(f"Skill name is too long: {len(name)}")

    description = frontmatter["description"].strip()
    if len(description.split()) < 10:
        raise ValidationError("Skill description is too short to route reliably")

    agent_config = parse_simple_agent_yaml((root / "agents" / "openai.yaml").read_text())
    interface = agent_config.get("interface")
    if not interface:
        raise ValidationError("agents/openai.yaml missing interface section")
    display_name = interface.get("display_name", "")
    if display_name != title_from_skill_name(name):
        raise ValidationError("agents/openai.yaml display_name does not match skill name")
    default_prompt = interface.get("default_prompt", "")
    if f"${name}" not in default_prompt:
        raise ValidationError("agents/openai.yaml default_prompt must reference the skill")
    short_description = interface.get("short_description", "")
    for term in ["workflow", "design"]:
        if term not in short_description.lower():
            raise ValidationError("agents/openai.yaml short_description does not match skill purpose")


def self_test() -> None:
    good = "---\nname: sample-skill\ndescription: This sample skill has enough words to route a realistic request.\n---\n"
    frontmatter = parse_simple_frontmatter(good)
    if frontmatter["name"] != "sample-skill":
        raise ValidationError("self-test failed: frontmatter parse mismatch")
    try:
        parse_simple_frontmatter("name: missing-boundary\n")
    except ValidationError:
        pass
    else:
        raise ValidationError("self-test failed: missing boundary passed")
    agent_config = parse_simple_agent_yaml('interface:\n  display_name: "Sample Skill"\n')
    if agent_config["interface"]["display_name"] != "Sample Skill":
        raise ValidationError("self-test failed: agent yaml parse mismatch")
    print("quick skill validator self-test: pass")


def main() -> int:
    root = Path(".")
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        self_test()
        return 0
    if len(sys.argv) > 1:
        root = Path(sys.argv[1])
    try:
        validate_skill(root)
    except ValidationError as exc:
        print(f"quick_validate_skill: {exc}", file=sys.stderr)
        return 1
    print("Skill is valid!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

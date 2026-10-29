"""The configuration document and the code agree on the environment variables."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ENV_NAME = re.compile(r"\bBATON_[A-Z0-9_]+\b")


def config_env_names() -> set[str]:
    text = resources.files("baton").joinpath("default_config.yaml").read_text("utf-8")
    return {f"BATON_{key.upper()}" for key in yaml.safe_load(text)}


def documented_env_names() -> set[str]:
    return set(ENV_NAME.findall((ROOT / "docs" / "server.md").read_text("utf-8")))


def test_every_variable_the_code_reads_is_documented_and_the_reverse() -> None:
    assert config_env_names() == documented_env_names()


def test_the_code_reads_the_environment_only_through_the_config_loader() -> None:
    source = ROOT / "server" / "baton"
    offenders = [
        path.name
        for path in source.rglob("*.py")
        if path.name != "config.py"
        and ("os.environ" in path.read_text("utf-8") or "getenv" in path.read_text("utf-8"))
    ]
    assert offenders == []


def test_the_compose_example_only_mentions_documented_variables() -> None:
    text = (ROOT / "server" / "compose.example.yaml").read_text("utf-8")
    assert set(ENV_NAME.findall(text)) <= documented_env_names()

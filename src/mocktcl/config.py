"""Optional configuration from ``mocktcl.toml`` or ``[tool.mocktcl]`` in ``pyproject.toml``."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

KEYS = {
    "tests_dir": str,
    "cov": list,
    "cov_omit": list,
    "cov_report": list,
    "cov_conditions": bool,
    "fail_under": (int, float),
    "tclsh": str,
    "jobs": int,
    "timeout": (int, float),
    "float_zero_tolerance": (int, float),
}


class ConfigError(ValueError):
    pass


def load(root: Path) -> dict[str, Any]:
    own = root / "mocktcl.toml"
    if own.is_file():
        data = _read(own)
        section = data.get("mocktcl", data)
        source = own
    else:
        pyproject = root / "pyproject.toml"
        if not pyproject.is_file():
            return {}
        section = _read(pyproject).get("tool", {}).get("mocktcl", {})
        source = pyproject
    config: dict[str, Any] = {}
    for key, value in section.items():
        key = key.replace("-", "_")
        if key not in KEYS:
            raise ConfigError(f"{source}: unknown option '{key}'")
        if isinstance(value, str) and KEYS[key] is list:
            value = [value]
        if not isinstance(value, KEYS[key]):
            raise ConfigError(f"{source}: option '{key}' has the wrong type")
        config[key] = value
    return config


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e

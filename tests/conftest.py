from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from mocktcl.cli import main

TCLSH = shutil.which("tclsh") or shutil.which("tclsh8.6")

requires_tcl = pytest.mark.skipif(TCLSH is None, reason="tclsh not installed")


def write_files(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return root


def tcl_eval(script: str) -> str:
    """Run a script under tclsh and return its stdout (stripped)."""
    proc = subprocess.run([TCLSH], input=script.encode(), capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode()
    return proc.stdout.decode().strip()


@pytest.fixture
def project(tmp_path):
    def make(files: dict[str, str]) -> Path:
        return write_files(tmp_path, files)

    return make


@pytest.fixture
def run_cli(capsys, monkeypatch):
    def run(root: Path, *args: str) -> tuple[int, str]:
        monkeypatch.setenv("NO_COLOR", "1")
        code = main(["--root", str(root), "--tclsh", TCLSH, *args])
        out = capsys.readouterr()
        return code, out.out + out.err

    return run

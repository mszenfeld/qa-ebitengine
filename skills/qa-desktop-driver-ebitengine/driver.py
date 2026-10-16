#!/usr/bin/env python3
# _go_mod_entries and ebitengine_requirement are copied from AppVerk's av-marketplace qa plugin (MIT License); see NOTICE.
"""qa-ebitengine: the Ebitengine desktop driver for the qa plugin (QA desktop driver contract 1).

The qa engine runs every phase with cwd and ``PWD`` set to the repository root:

- ``check --repo R`` prints one JSON object: ``{"result": null}`` when the
  repository can run under Ebitengine's ``exp/vmhost``, ``tool-missing`` (``go``)
  or ``unsupported`` with the reason otherwise.
- ``prepare --repo R --cache C`` builds the host once per run as the virtual
  package ``./.qa-ebitengine-host`` inside the project's module
  (``go build -overlay``), so host and app share one Ebitengine version.
- ``build --repo R --cache C --package P --out G`` builds the app with
  ``-tags ebitenginevmguest``.
- ``run --repo R --cache C --guest G --steps S --out A --width W --height H
  --deadline N -- <args…>`` executes the host from the repository root; the
  host starts the app, drives it and writes ``A/result.json``.

Python 3.11+ standard library only.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterator
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

EBITENGINE_MODULE = "github.com/hajimehoshi/ebiten/v2"
EBITENGINE_MINIMUM = (2, 10, 5)
HOST_DIR = ".qa-ebitengine-host"
HOST_SOURCE = Path(__file__).resolve().parent / "host" / "main.go"


def _go_mod_entries(text: str) -> Iterator[tuple[str, list[str]]]:
    """Yield ``(verb, fields)`` for every directive line, inside or outside ``verb (…)`` blocks."""
    block: str | None = None
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if block is not None:
            if line == ")":
                block = None
            else:
                yield block, line.split()
            continue
        verb, *rest = line.split(None, 1)
        if rest == ["("]:
            block = verb
        elif rest:
            yield verb, rest[0].split()


def ebitengine_requirement(repo: Path) -> str | None:
    """``None`` when the root module may run under ``exp/vmhost``, else the ``unsupported`` detail.

    Reads ``go.mod`` as text only: no ``go`` command, module cache or network.
    """
    try:
        text = (repo / "go.mod").read_text()
    except FileNotFoundError:
        return "no go.mod at the repository root"
    except (OSError, UnicodeError):
        return "go.mod is not readable"
    version: str | None = None
    replaced = False
    for verb, fields in _go_mod_entries(text):
        if not fields or fields[0].strip('"') != EBITENGINE_MODULE:
            continue
        if verb == "replace":
            replaced = True
        elif verb == "require" and len(fields) >= 2:
            version = fields[1]
    if version is None:
        return f"go.mod does not require {EBITENGINE_MODULE}"
    if replaced:
        return None
    parsed = re.match(r"v(\d+)\.(\d+)\.(\d+)", version)
    if parsed and tuple(int(part) for part in parsed.groups()) >= EBITENGINE_MINIMUM:
        return None
    minimum = ".".join(str(part) for part in EBITENGINE_MINIMUM)
    return f"go.mod requires {EBITENGINE_MODULE} {version}; qa-ebitengine supports v{minimum} or later"


def _absolute(value: str) -> Path:
    """An absolute path without resolving symlinks, so the host receives the paths the engine gave."""
    return Path(os.path.abspath(value))


def _go(arguments: list[str], repo: Path) -> int:
    go = shutil.which("go")
    if go is None:
        print("go not found", file=sys.stderr)
        return 1
    return subprocess.run([go, *arguments], cwd=repo, env={**os.environ, "PWD": str(repo)}, stdin=subprocess.DEVNULL, check=False).returncode


def check(repo: Path) -> int:
    if shutil.which("go") is None:
        answer: dict[str, object] = {"result": "tool-missing", "detail": "go"}
    else:
        requirement = ebitengine_requirement(repo)
        answer = {"result": None} if requirement is None else {"result": "unsupported", "detail": requirement}
    print(json.dumps(answer))
    return 0


def prepare(repo: Path, cache: Path) -> int:
    if os.path.lexists(repo / HOST_DIR):
        print(f"reserved directory {HOST_DIR} exists", file=sys.stderr)
        return 1
    if shutil.which("go") is None:
        print("go not found", file=sys.stderr)
        return 1
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    overlay = cache / "overlay.json"
    overlay.write_text(json.dumps({"Replace": {str(repo / HOST_DIR / "main.go"): str(HOST_SOURCE)}}) + "\n")
    return _go(["build", "-overlay", str(overlay), "-o", str(cache / "host"), f"./{HOST_DIR}"], repo)


def build(repo: Path, package: str, out: Path) -> int:
    return _go(["build", "-tags", "ebitenginevmguest", "-o", str(out), package], repo)


def run(repo: Path, cache: Path, options: argparse.Namespace, extra: list[str]) -> int:
    host = cache / "host"
    if not (host.is_file() and os.access(host, os.X_OK)):
        print("host binary missing: run prepare first", file=sys.stderr)
        return 1
    argv = [
        str(host), "-guest", str(_absolute(options.guest)), "-script", str(_absolute(options.steps)),
        "-out", str(_absolute(options.out)), "-w", str(options.width), "-h", str(options.height),
        "-deadline", f"{options.deadline}s", "--", *extra,
    ]
    # The host starts the app in its own working directory, and apps load files relative to it.
    os.chdir(repo)
    os.execve(str(host), argv, {**os.environ, "PWD": str(repo)})
    return 1  # unreachable: execve replaces this process or raises


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="driver.py", description="qa-ebitengine desktop driver (contract 1)")
    phases = root.add_subparsers(dest="phase", required=True)
    for name, options in (
        ("check", ()),
        ("prepare", ("--cache",)),
        ("build", ("--cache", "--package", "--out")),
        ("run", ("--cache", "--guest", "--steps", "--out")),
    ):
        phase = phases.add_parser(name)
        phase.add_argument("--repo", required=True)
        for option in options:
            phase.add_argument(option, required=True)
        if name == "run":
            for option in ("--width", "--height", "--deadline"):
                phase.add_argument(option, required=True, type=int)
    return root


def main(argv: list[str]) -> int:
    extra: list[str] = []
    if "--" in argv:
        split = argv.index("--")
        argv, extra = argv[:split], argv[split + 1:]
    options = parser().parse_args(argv)
    if extra and options.phase != "run":
        parser().error("arguments after -- are accepted by run only")
    repo = Path(options.repo).resolve()
    if options.phase == "check":
        return check(repo)
    cache = _absolute(options.cache)
    if options.phase == "prepare":
        return prepare(repo, cache)
    if options.phase == "build":
        return build(repo, options.package, _absolute(options.out))
    return run(repo, cache, options, extra)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

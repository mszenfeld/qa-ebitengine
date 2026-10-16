"""driver.py phases against a fake ``go`` and a fake host; needs neither Go nor a display.

Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

DRIVER = Path(__file__).resolve().parents[1] / "skills/qa-desktop-driver-ebitengine/driver.py"
HOST_SOURCE = DRIVER.parent / "host/main.go"
GO_MOD = "module example.com/game\n\ngo 1.25\n\nrequire github.com/hajimehoshi/ebiten/v2 v2.10.5\n"
FAKE_GO = '''#!{python}
import json, os, sys
state = os.environ["FAKE_DIR"]
args = sys.argv[1:]
with open(os.path.join(state, "go.jsonl"), "a") as log:
    log.write(json.dumps({{"argv": args, "cwd": os.getcwd(), "pwd": os.environ.get("PWD")}}) + "\\n")
if "-o" in args:
    with open(args[args.index("-o") + 1], "w") as out:
        out.write("built")
code_file = os.path.join(state, "go-exit")
sys.exit(int(open(code_file).read()) if os.path.exists(code_file) else 0)
'''
FAKE_HOST = '''#!{python}
import json, os, sys
with open(os.path.join(os.environ["FAKE_DIR"], "host.json"), "w") as log:
    json.dump({{"argv": sys.argv[1:], "cwd": os.getcwd(), "pwd": os.environ.get("PWD")}}, log)
'''


class DriverTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "repo"
        self.cache = self.root / "cache"
        self.fake = self.root / "fake"
        self.bin = self.root / "bin"
        self.empty = self.root / "empty-bin"
        for directory in (self.repo, self.cache, self.fake, self.bin, self.empty):
            directory.mkdir()
        go = self.bin / "go"
        go.write_text(FAKE_GO.format(python=sys.executable))
        go.chmod(0o755)
        (self.repo / "go.mod").write_text(GO_MOD)
        self.env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "FAKE_DIR": str(self.fake)}

    def driver(self, *args: str, cwd: Path | None = None, path: Path | None = None, **env: str) -> subprocess.CompletedProcess[str]:
        environment = {**self.env, **env}
        if path is not None:
            environment["PATH"] = str(path)
        return subprocess.run([sys.executable, str(DRIVER), *args], cwd=cwd or self.root, env=environment,
                              capture_output=True, text=True, check=False)

    def check(self, go_mod: str | None = None, **env: str) -> dict[str, object]:
        if go_mod is not None:
            (self.repo / "go.mod").write_text(go_mod)
        result = self.driver("check", "--repo", str(self.repo), **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def go_calls(self) -> list[dict[str, object]]:
        path = self.fake / "go.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_check_without_go_reports_the_missing_tool(self) -> None:
        result = self.driver("check", "--repo", str(self.repo), path=self.empty)
        self.assertEqual((result.returncode, json.loads(result.stdout)), (0, {"result": "tool-missing", "detail": "go"}))

    def test_check_accepts_supported_modules_without_a_module_cache_or_vendor_state(self) -> None:
        self.assertEqual(self.check(), {"result": None})
        self.assertEqual(self.check(GOMODCACHE=str(self.root / "empty-cache")), {"result": None})
        (self.repo / "vendor/github.com/hajimehoshi/ebiten/v2").mkdir(parents=True)
        self.assertEqual(self.check(), {"result": None})
        self.assertEqual(self.check("module m\n\nrequire (\n\tgithub.com/hajimehoshi/ebiten/v2 v2.11.0-alpha.1 // indirect\n)\n"), {"result": None})
        self.assertEqual(self.check("module m\nrequire github.com/hajimehoshi/ebiten/v2 v2.9.0\nreplace github.com/hajimehoshi/ebiten/v2 => ../ebiten\n"),
                         {"result": None})
        self.assertEqual(self.go_calls(), [])

    def test_check_names_why_a_module_is_unsupported(self) -> None:
        (self.repo / "go.mod").unlink()
        self.assertEqual(self.check(), {"result": "unsupported", "detail": "no go.mod at the repository root"})
        self.assertEqual(self.check("module m\n\nrequire github.com/hajimehoshi/ebiten v1.12.12\n"),
                         {"result": "unsupported", "detail": "go.mod does not require github.com/hajimehoshi/ebiten/v2"})
        self.assertEqual(self.check("module m\n\nrequire github.com/hajimehoshi/ebiten/v2 v2.9.0\n"), {
            "result": "unsupported",
            "detail": "go.mod requires github.com/hajimehoshi/ebiten/v2 v2.9.0; qa-ebitengine supports v2.10.5 or later"})

    def test_prepare_refuses_a_reserved_directory_without_calling_go(self) -> None:
        (self.repo / ".qa-ebitengine-host").mkdir()
        result = self.driver("prepare", "--repo", str(self.repo), "--cache", str(self.cache))
        self.assertEqual((result.returncode, result.stderr.strip()), (1, "reserved directory .qa-ebitengine-host exists"))
        self.assertEqual(self.go_calls(), [])

    def test_prepare_builds_the_host_through_an_overlay_inside_the_repository(self) -> None:
        result = self.driver("prepare", "--repo", str(self.repo), "--cache", str(self.cache))
        self.assertEqual(result.returncode, 0, result.stderr)
        overlay = json.loads((self.cache / "overlay.json").read_text())
        self.assertEqual(overlay, {"Replace": {str(self.repo / ".qa-ebitengine-host/main.go"): str(HOST_SOURCE)}})
        self.assertTrue(HOST_SOURCE.is_file())
        [call] = self.go_calls()
        self.assertEqual(call["argv"], ["build", "-overlay", str(self.cache / "overlay.json"), "-o", str(self.cache / "host"), "./.qa-ebitengine-host"])
        self.assertEqual((call["cwd"], call["pwd"]), (str(self.repo), str(self.repo)))
        (self.fake / "go-exit").write_text("3")
        self.assertEqual(self.driver("prepare", "--repo", str(self.repo), "--cache", str(self.cache)).returncode, 3)

    def test_build_compiles_the_package_as_a_vmhost_guest(self) -> None:
        guest = self.root / "out/guest"
        guest.parent.mkdir()
        args = ("build", "--repo", str(self.repo), "--cache", str(self.cache), "--package", "./cmd/game", "--out", str(guest))
        result = self.driver(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        [call] = self.go_calls()
        self.assertEqual(call["argv"], ["build", "-tags", "ebitenginevmguest", "-o", str(guest), "./cmd/game"])
        self.assertEqual((call["cwd"], call["pwd"]), (str(self.repo), str(self.repo)))
        (self.fake / "go-exit").write_text("2")
        self.assertEqual(self.driver(*args).returncode, 2)

    def run_args(self, repo: Path) -> list[str]:
        return ["run", "--repo", str(repo), "--cache", str(self.cache), "--guest", str(self.root / "guest"),
                "--steps", str(self.root / "steps.json"), "--out", str(self.root / "out"), "--width", "960", "--height", "540",
                "--deadline", "135", "--", "-debug", "-seed", "42"]

    def test_run_without_a_prepared_host_fails(self) -> None:
        result = self.driver(*self.run_args(self.repo))
        self.assertEqual((result.returncode, result.stderr.strip()), (1, "host binary missing: run prepare first"))

    def test_run_executes_the_host_from_the_resolved_repository(self) -> None:
        host = self.cache / "host"
        host.write_text(FAKE_HOST.format(python=sys.executable))
        host.chmod(0o755)
        link = self.root / "repo-link"
        link.symlink_to(self.repo)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        result = self.driver(*self.run_args(link), cwd=elsewhere)
        self.assertEqual(result.returncode, 0, result.stderr)
        recorded = json.loads((self.fake / "host.json").read_text())
        self.assertEqual(recorded["argv"], [
            "-guest", str(self.root / "guest"), "-script", str(self.root / "steps.json"), "-out", str(self.root / "out"),
            "-w", "960", "-h", "540", "-deadline", "135s", "--", "-debug", "-seed", "42"])
        self.assertEqual((recorded["cwd"], recorded["pwd"]), (str(self.repo), str(self.repo)))


if __name__ == "__main__":
    unittest.main()

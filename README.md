# qa-ebitengine

The Ebitengine desktop driver for the [`qa` plugin](https://github.com/AppVerk/av-marketplace/blob/master/docs/plugins/qa.md) of av-marketplace (QA desktop driver contract 1). With it installed, `/qa:run` tests Ebitengine games through DESKTOP scenarios: the game runs headless in the background, the tester injects keys, text and mouse input tick by tick and judges PNG frames and the game's log. No window takes focus, no OS input is sent and no screen is captured.

The plugin ships one skill, `qa-desktop-driver-ebitengine`, which holds the driver manifest `qa-desktop-driver.json`, the driver `driver.py`, the headless host `host/main.go` and the guide `SKILL.md` that qa's planner, config-author and tester read.

## Requirements

- `qa` 3.1.0 or later.
- Go on `PATH`.
- A root `go.mod` that requires `github.com/hajimehoshi/ebiten/v2` v2.10.5 or later (a `replace` of that module is accepted).
- Python 3.11 or later, which qa needs as well.
- A graphics session: a normal macOS login, or X11/EGL on Linux.
- No `.qa-ebitengine-host` directory at the repository root.

## Install

In Claude Code:

```text
/plugin install qa-ebitengine@av-marketplace
```

This installs `qa` with it as a dependency.

In OMP:

```sh
omp plugin install qa@av-marketplace qa-ebitengine@av-marketplace
```

`/qa:run` and `/qa:create-plan` detect the installed driver, pass its guide to planning and configuration, and register it for each run. Configure an app under `[qa.desktop.<name>]` with `driver = "ebitengine"`; the qa documentation describes the table.

## How it works

The qa engine runs `driver.py` for each phase of the contract, from the repository root:

1. `check` reads `go.mod` as text and reports a missing `go` or an unsupported module.
2. `prepare` builds the host once per run with `go build -overlay` as the virtual package `./.qa-ebitengine-host` inside the project's module, so host and game always share one Ebitengine version. Nothing is written to the repository.
3. `build` compiles the game's package with `-tags ebitenginevmguest`.
4. `run` executes the host, which starts the game with `EBITENGINE_VM_ENDPOINT` set and drives it from a hidden, unfocused window through Ebitengine's `exp/vmhost`. The host writes `result.json`, one PNG per shot and the game's output.

Keys are W3C `KeyboardEvent.code` values; `KeyA`…`KeyZ` map to Ebitengine's letter keys. `SKILL.md` explains how window coordinates map to the game's `Layout` coordinates.

## Limits

- `exp/vmhost` is experimental: a newer Ebitengine release can break the host build, which qa reports as `NEED_INFO kind=tool`.
- No audio assertions.
- Code that reads the wall clock sees real time between ticks.

## Development

```sh
python3 -m unittest discover -s tests -v
cd skills/qa-desktop-driver-ebitengine/host && gofmt -l . && go vet ./... && go build ./...
```

CI (`.github/workflows/ci.yml`) runs the driver tests on Python 3.11 (Ubuntu) and checks, vets and builds the host on macOS. A release tag `v<version>` matches `version` in `.claude-plugin/plugin.json` and in `qa-desktop-driver.json`; the av-marketplace catalog pins the tag and its commit.

## License

Apache License 2.0; see [LICENSE](LICENSE). `host/main.go` is derived from Ebitengine's `run-ebitengine-app-headless` driver template (Apache License 2.0), and two functions in `driver.py` are copied from av-marketplace under the MIT License. [NOTICE](NOTICE) holds both attributions.

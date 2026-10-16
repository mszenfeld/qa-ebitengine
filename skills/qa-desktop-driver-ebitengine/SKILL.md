---
name: qa-desktop-driver-ebitengine
description: "QA desktop driver for Ebitengine (v2.10.5 or later) games, used by the qa plugin's /qa:run and /qa:create-plan: gives the driver manifest path and how to recognise, configure, plan and script an Ebitengine app tested headless in the background."
---

# QA desktop driver: Ebitengine

## Paths

Driver: ebitengine (contract 1)
Driver manifest: ${CLAUDE_SKILL_DIR}/qa-desktop-driver.json
Driver guide: ${CLAUDE_SKILL_DIR}/SKILL.md

In OMP these placeholders stay unexpanded: resolve the paths with realpath skill://qa-desktop-driver-ebitengine/qa-desktop-driver.json and realpath skill://qa-desktop-driver-ebitengine/SKILL.md.

## Requirements

- Go on `PATH`.
- A root `go.mod` that requires `github.com/hajimehoshi/ebiten/v2` v2.10.5 or later. A `replace` of that module is accepted whatever the required version.
- A graphics session: a normal macOS login, or X11/EGL on Linux.
- No real `.qa-ebitengine-host` directory at the repository root; the driver uses that name for its virtual host package.

## Recognising an app

An Ebitengine app is a main package that this driver can run when all of these hold:

- the root `go.mod` has a `require` line for `github.com/hajimehoshi/ebiten/v2`;
- the package's code calls `ebiten.RunGame` or `ebiten.RunGameWithOptions`;
- its directory relative to the repository root is the app's `package`: `.` for the root, otherwise `./<dir>` (for example `./cmd/game`).

## Proposing configuration

For qa's config-author:

- Propose one `[qa.desktop.<name>]` table per recognised app, with `driver = "ebitengine"` and `package` as found above (omit it for `.`).
- `args` holds only flags that the documented run command (README, Makefile) always passes. Never put per-scenario values such as seeds there; scenarios pass those through their own `**Args:**`.
- Set `screen = [W, H]` only when the repository documents a window size the app needs; the default is 960×540.
- Put a TOML comment above the table that cites the `go.mod` require line, the `ebiten.RunGame` (or `RunGameWithOptions`) line and the run-command line, each as `path:line`.
- Never run `go`, the driver or the app while proposing.

## Planning

- A tick is one `Update` call. Ebitengine runs 60 ticks per second unless the app calls `ebiten.SetTPS`; the run result's `tps` reports the rate, and -1 means `ebiten.SyncWithFPS` (ticks follow rendered frames).
- Scenarios that move or click cite, in Preconditions, the logical size the game's `Layout` method returns (`path:line`), and give positions in those Layout coordinates.
- The app log is the process's stdout and stderr.
- Features behind a debug flag (for example an in-game console) need that flag in the configured app's `args`.

## Coordinates

Script coordinates are window pixels of the configured `screen` W×H. Ebitengine scales the `Layout` size LW×LH into that window:

- s = min(W/LW, H/LH)
- ox = (W − LW·s)/2, oy = (H − LH·s)/2
- window x = ox + gx·s, window y = oy + gy·s for a Layout point (gx, gy)

Example: a 1920×1080 Layout in the default 960×540 window gives x = gx/2 and y = gy/2. A PNG pixel (px, py) is the window point (px/scale, py/scale), with `scale` from the run result.

## Keys

Keys are W3C `KeyboardEvent.code` values. `KeyA`…`KeyZ` map to Ebitengine's letter keys `A`…`Z`; every other code goes to `ebiten.Key.UnmarshalText` unchanged, so Ebitengine's key names that follow W3C (`Digit1`, `ArrowUp`, `Enter`, `Backquote`, `ShiftLeft`, `F1`, …) work as written. An unknown name gives `invalid-script` naming the step.

## How it works

- `prepare` builds the host once per run with `go build -overlay` as the virtual package `./.qa-ebitengine-host` inside the project's module, so host and app always share one Ebitengine version. Nothing is written to the repository.
- `build` compiles the app's package with `-tags ebitenginevmguest`.
- `run` executes the host from the repository root. The host starts the app with `EBITENGINE_VM_ENDPOINT` set and drives it from a hidden, unfocused window through Ebitengine's `exp/vmhost`: input is injected tick by tick inside the app, and shots are frames the host composites, not screen captures.
- An app that ends itself through `ebiten.Termination` while the steps run is reported as `guest-exited` with `exit_code` 0 and detail `guest terminated itself`; a panic, a non-zero exit or an exit before connecting is any other `guest-exited`.

## Limits

- `exp/vmhost` is experimental: a newer Ebitengine release can break the host build, which qa reports as `NEED_INFO kind=tool`.
- No audio assertions.
- Code that reads the wall clock sees real time between ticks, not tick time.

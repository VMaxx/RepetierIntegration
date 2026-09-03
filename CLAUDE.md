# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **RepetierIntegration** (273 symbols, 575 relationships, 12 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/RepetierIntegration/context` | Codebase overview, check index freshness |
| `gitnexus://repo/RepetierIntegration/clusters` | All functional areas |
| `gitnexus://repo/RepetierIntegration/processes` | All execution flows |
| `gitnexus://repo/RepetierIntegration/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

## Project overview

RepetierIntegration is a Cura plugin (Python + QML) that adds network printing and print monitoring support for [Repetier-Server](https://www.repetier-server.com/). It is a fork/adaptation of Cura's built-in OctoPrint plugin, reworked to talk to the Repetier-Server HTTP API instead of OctoPrint's. It is installed as a plugin under `[Cura installation]/plugins/RepetierIntegration` — there is no separate build step, package manager, or test suite; it runs inside a live Cura/Uranium application process.

There is no linter, formatter, or automated test suite configured in this repo. Verify changes by running the plugin inside an actual Cura installation (copy/symlink this folder into Cura's `plugins/RepetierIntegration` directory, or the config folder's `plugins/` dir) and exercising the "Connect Repetier" machine action and print/monitor flow manually. Check the Cura log (Help → Show Configuration Folder → `cura.log`) for `Logger.log` output when debugging — the code logs extensively at the `"d"` (debug) and `"w"` (warning) levels.

## Architecture

The plugin registers two Cura extension points from `__init__.py`:

- **`output_device`** → `RepetierOutputDevicePlugin` (`RepetierOutputDevicePlugin.py`) — discovers Repetier-Server instances (via Zeroconf/Bonjour and manually-added instances stored in Cura preferences under `Repetier/manual_instances`), and creates/destroys `RepetierOutputDevice` instances as printers come and go. It watches `globalContainerStackChanged` to activate the output device that matches the currently selected printer.
- **`machine_action`** → `DiscoverRepetierAction` (`DiscoverRepetierAction.py`, backed by `DiscoverRepetierAction.qml`) — the "Connect Repetier" wizard UI shown in Manage Printers. Handles server discovery list, fetching the printer/slug list and model groups from a Repetier-Server instance, requesting/polling for an API key (or accepting a manually entered one), and validating the key against `printer/api/{slug}?a=getPrinterConfig`. Accepted API keys are cached in Cura preferences (`Repetier/keys_cache`, base64-encoded JSON) so they don't need re-entry per machine.

Core runtime class:

- **`RepetierOutputDevice`** (`RepetierOutputDevice.py`) extends Cura's `NetworkedPrinterOutputDevice`. This is where the actual printer connection lives: polling printer/job status from the Repetier-Server REST API, uploading G-code (as a `QHttpMultiPart` request) and triggering print start, and driving Cura's print-monitor UI (`qml/MonitorItem.qml`, `RepetierComponents.qml`) via `PrinterOutputModel`/`PrintJobOutputModel`. `UnifiedConnectionState` exists to paper over a `ConnectionState` enum casing change between Cura 4.0 beta1 and beta2 — keep both branches if touching connection-state handling.

Supporting modules:

- **`NetworkMJPGImage.py`** — a `QQuickPaintedItem` registered as a QML type (`RepetierIntegration.NetworkMJPGImage`) that streams and paints an MJPEG webcam feed, including flip/rotate handling driven by the webcam orientation settings fetched during discovery.
- **`NetworkReplyTimeout.py`** — small `QTimer` wrapper that aborts a `QNetworkReply` if it takes too long, used to bound blocking network calls in the discovery/API-key flow.

QML files (`RepetierComponents.qml`, `DiscoverRepetierAction.qml`, `qml/MonitorItem.qml`) are the UI counterparts driven by `pyqtProperty`/`pyqtSlot`/`pyqtSignal` members on `DiscoverRepetierAction` and `RepetierOutputDevice` — when changing a Python-side property/signal name, grep the corresponding `.qml` file for its usage since there's no compiler to catch a mismatch.

## Key conventions and gotchas

- **Preferences namespace**: all Cura preference keys use the `Repetier/` prefix (`Repetier/manual_instances`, `Repetier/keys_cache`). Per-machine metadata keys use the `repetier_` prefix (`repetier_id`, `repetier_api_key`, `repetier_show_camera`).
- **Zeroconf `properties` dict**: instance properties passed around (`addInstance`, `addManualInstance`) use `bytes` keys and values (e.g. `b"path"`, `b"repetier_id"`) to mirror what the real `zeroconf` library hands back for discovered (non-manual) instances — preserve this shape when adding new properties.
- **SDK version compatibility**: `plugin.json` declares `supported_sdk_versions` for Cura 5.0 through 8.0 (`minimum_cura_version: 5.0`). `RepetierOutputDevice.py`'s `UnifiedConnectionState` class is an example of the defensive `try`/`except AttributeError` pattern used to support multiple Cura/Uranium API shapes — follow the same pattern rather than assuming a single SDK version's API surface.
- **Renaming a printer breaks the plugin** (documented in README): the plugin's connection state matching relies on the machine's Cura ID, and Cura has a known bug where renaming loses that association.
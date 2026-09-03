# Changelog

### v5.2 - connection setup bugfixes (Mick Mifsud)

- **Flaky first-time connection setup.** `RepetierOutputDevicePlugin` decided whether to push
  the API key into a live connection by comparing the Repetier server instance's own name
  against Cura's auto-generated machine container `id` — two unrelated values that only matched
  by coincidence. This is why setup required repeatedly deleting/re-adding the printer profile.
  Fixed by persisting an explicit `repetier_instance_id` link on the machine when "Connect" is
  clicked, and matching on that. Existing (accidentally-working) profiles are migrated
  automatically on first reconnect (legacy id-match still honored as a fallback, then
  self-heals by backfilling the new metadata).
- **API key never validating on new profiles**, leaving "Connect" permanently disabled. The
  wizard's "RepetierID" and "API Key" fields were reading Cura container metadata keyed by the
  *Repetier server instance's name* instead of the *active machine's id* — essentially never a
  valid lookup for a fresh profile. Fixed to read the printer slug directly off the selected
  instance and the API key from the active machine.
- Same root-cause bug (server-instance identity vs. machine id) was also present in the
  instance-list "linked instance" bolding (`font.italic` was comparing against a nonexistent
  `.key` property and the wrong metadata field) and in the "Edit" button's pre-fill logic for
  the manual-instance dialog. Both fixed to use the same reliable source.
- **"Get Printers" button required multiple clicks**, and appeared to "cache" against the IP.
  `getPrinterList()` fires an async network request but the QML read the result synchronously
  right after calling it — always one click behind. Added a `printersChanged` signal (properly
  notified when the response actually lands) and an `isFetchingPrinters` busy flag; the button
  now disables while in flight and the dropdown populates reliably on the first response.
  Re-fetching now also preserves the current selection if it's still present in the new list.
- **`UnboundLocalError` crash silently breaking printer status polling** whenever a `stateList`
  response omitted `numExtruder` (seen with a real printer profile) — `printer_state` was only
  assigned inside a conditional branch but used unconditionally afterward. The `except:` handler
  for this case then also crashed on `printer.activePrintJob` being `None`. Both fixed.
- A second, identical `AttributeError` landmine in the `listPrinter` response handler
  (`self._key` was never defined anywhere — should have been `self._repetier_id`).
- **"Store G-code on the printer SD card" checkbox silently did nothing** — the setting was
  read back with a case-mismatched metadata key (`Repetier_store_sd` vs. the stored
  `repetier_store_sd`), so it always evaluated to the default (off).
  Fixed to use the matching, correctly-cased key.
- Unguarded `location_url` dereference in the upload-finished handler — would crash if Repetier
  ever omits the `Location` header on a successful auto-print upload. Added a guard with a
  clear error message instead.
- Missing `QSslConfiguration`/`QSslSocket` imports and PyQt6 enum-scoping issues
  (`FollowRedirectsAttribute`, `VerifyNone`) in `DiscoverRepetierAction._createRequest()` —
  currently unreachable dead code (not wired to any UI button) but would have crashed
  immediately if ever invoked.
- Duplicate `connectionStateChanged` signal connections stacking up on every reconnect attempt,
  causing repeated/duplicated `addOutputDevice`/`removeOutputDevice` calls during setup. Now
  disconnects before reconnecting.
- `RepetierOutputDevice.connect()` had no idempotency guard, so rapid successive calls (e.g.
  from `setInstanceId()` and `setApiKey()` each triggering a reconnect) restarted the poll timer
  and re-issued a burst of duplicate HTTP requests. Now a no-op while already
  connecting/connected.
- Invalid API key (HTTP 401) left the connection silently stuck in "Connecting" with no visible
  error state. Now surfaces a proper `Error` state and recovers to `Connected` automatically on
  the next successful poll once the key is corrected.

### Changed

- Instance list now bolds (moderate weight, not full bold) the Repetier instance currently
  linked to the active printer, and shows a "currently linked" label when it's selected.
- "Connect" is disabled while viewing the already-linked instance and enables as soon as a
  different instance is selected.
- Group dropdown ("Store print job and print") now renders Repetier-Server's `#` (default/
  ungrouped bucket) as "(Default)" instead of the raw symbol, and defaults to the first
  available group instead of leaving no selection.
- `manualPrinterDialog.onAccepted` no longer writes `repetier_id` metadata onto whichever
  machine happens to be active just from adding/editing a server entry in the list — that link
  is only ever made via the explicit "Connect" action now.

### Removed

- Dead code: `NetworkReplyTimeout.py` (never instantiated) and all references to it.
- `config.jpg`, `webcam.jpg`, and `Cura 4.1 testing doc.rtf.zip` — stale screenshots/testing doc
  from the Cura 4.1 era, superseded by the current README instructions.
- README's "must match the Instance Name" workaround note — no longer applicable now that
  linking is explicit rather than name-coincidence-based.

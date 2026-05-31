# Proposal: folder-sharing-link

## Intent

After the RPA finishes cleaning each OneDrive folder, automatically create a
sharing link on that folder so the resulting (now-empty) structure is shared
under controlled conditions:

- **Scope**: "Cualquier persona" (Anyone — no sign-in required)
- **Expiration**: today + 9 days, in `DD/MM/YYYY` format
- **Password**: the same password that the Excel report assigns to that folder

**Why now**: The clean + report pipeline already produces a per-folder password
in the Excel report (step 5), but those passwords are not applied anywhere — they
are documentation only. This change closes the loop: the password printed in the
report becomes the real sharing-link password, so the report is an actionable
artifact instead of a disconnected record. Sharing right after cleaning also
means the folder is locked down the moment it becomes empty, with no manual step.

**Success looks like**: For every folder in `folders.json["clean"]`, after a real
(non-dry-run) execution, the folder has an "Anyone" sharing link with an
expiration of today + 9 days and a password that exactly matches the one shown
for that folder in the generated Excel report. Failures in the sharing step are
logged and surfaced in the summary but never abort the run.

## Scope

### In scope

- New `rpa/sharer.py` module: `share_folder(page, folder_path, password, expiry_date)`
  plus a `ShareStats` aggregate for the summary.
- Pre-generating per-folder passwords **before** the clean loop so the same value
  is used for both sharing (step 4) and the report (step 5).
- New `SHARE_SELECTORS` and `SHARE_EXPIRY_DAYS = 9` in `config.py`.
- Threading the pre-generated passwords into `reporter.build_report_rows()` via an
  optional `passwords` argument (backward compatible).
- Wiring in `main.py`: pre-generate passwords, invoke the sharer after each
  folder clean, pass the same map to the reporter.
- Non-fatal error handling for the sharing step (same contract as `run_report()`).
- Unit tests for the pure helpers in `tests/test_sharer.py` (date formatting,
  password-to-folder mapping, stats aggregation).

### Out of scope

- Changing the deletion (DFS) logic in `cleaner.py`.
- Changing password **generation** strategy — we reuse the existing reporter
  password logic, only moving WHEN it runs.
- Removing or rotating existing sharing links, or detecting links created by a
  prior run (idempotency of sharing is not addressed in this change).
- Sharing folders that are NOT in the clean list.
- New TUI event categories beyond what the existing Observer/`RPACallbacks`
  pattern already supports (a sharing summary line is fine; a new live panel is
  out of scope).
- Configurable scope/expiration via CLI flags — values are fixed constants for
  this change.

## Approach

### Pre-generate passwords (core architectural decision)

The tension: the reporter generates passwords at **report time (step 5)**, but
sharing must happen **after each clean (step 4)**, and both must use the *same*
password per folder.

**Decision**: Lift password generation to a single point **before** the clean
loop. Build a `passwords: dict[str, str]` keyed by folder base name, then:

1. Use it during sharing in step 4 (one lookup per cleaned folder).
2. Pass the same map into `reporter.build_report_rows(..., passwords=...)` in
   step 5 so the report renders the exact values that were applied.

This makes the password the single source of truth flowing downstream, instead of
two independent generators that would inevitably diverge.

**Key mapping**: a clean path like `"pruebas/archivos_1"` maps to its base name
`"archivos_1"`, which is the report row key. The mapping helper is pure and unit
tested so the "share password == report password" invariant is verifiable without
a browser.

**Backward compatibility**: `build_report_rows()` takes `passwords` as an
optional argument (`dict[str, str] | None`). When `None`, it falls back to its
current internal generation, so existing callers and tests are unaffected.

### Non-fatal sharing design

Sharing is best-effort and must NOT abort the run, mirroring the existing
`run_report()` contract:

- Each folder's sharing attempt is wrapped so a failure logs the error, records
  it in `ShareStats`, and continues to the next folder.
- A sharing failure never changes the process exit code on its own.
- The final summary reports sharing outcomes (succeeded / failed / skipped) the
  same way report generation is surfaced today.

This keeps the deletion guarantee intact: the primary job (cleaning) already
succeeded by the time we attempt to share, so a flaky sharing dialog must not
mask a successful clean.

### Sharing UI flow (per folder)

Observed flow to encode in `share_folder()`:

1. Select the folder checkbox.
2. Click the "Compartir" toolbar button.
3. Wait for the "Configuración de vínculos" dialog.
4. Ensure the "Cualquier persona" radio is selected.
5. Fill the expiry date input (`DD/MM/AAAA`).
6. Fill the password input.
7. Click "Aplicar".

Selectors follow the project convention (`config.py → SELECTORS`): prefer
`data-automationid` (Microsoft testing contract, locale-stable), with text /
`aria-label` fallbacks only where no automation id is available.

**Delete-safety note**: unlike delete, sharing is idempotent enough to retry
within a single attempt — but per ADR-7 conventions we keep the sharing action
itself out of `@with_retry` unless live probing shows it is safe, and instead
rely on the non-fatal per-folder boundary.

## Files affected

| File | Change |
|------|--------|
| `onedrive_rpa/rpa/sharer.py` | **NEW**. `share_folder(page, folder_path, password, expiry_date)` drives the sharing dialog; `ShareStats` aggregates outcomes for the summary. |
| `onedrive_rpa/config.py` | Add `SHARE_SELECTORS` (dialog, radio, date input, password input, apply button) and `SHARE_EXPIRY_DAYS = 9`. |
| `onedrive_rpa/rpa/reporter.py` | `build_report_rows()` accepts optional `passwords: dict[str, str] \| None`; uses provided values when present, else generates as today. |
| `onedrive_rpa/main.py` | Pre-generate passwords before the clean loop; after each `cleaner.clean(...)` call `share_folder(...)` with the folder's password and computed expiry; pass the same map to `run_report()`/`build_report_rows()`; include sharing stats in the summary. |
| `tests/test_sharer.py` | **NEW**. Unit tests for pure helpers: expiry-date formatting (today + 9 days, `DD/MM/YYYY`), clean-path → base-name → report-key mapping, `ShareStats` aggregation. |

Estimated net size: ~200–250 lines. Single PR, under the 400-line budget.

## Risks

- **HIGH — Sharing dialog selectors unknown**. The "Configuración de vínculos"
  dialog, the "Cualquier persona" radio, the date input, password input, and
  "Aplicar" button selectors have not been confirmed against a live session.
  - *Mitigation*: Probe selectors in a live authenticated session during
    implementation; centralize all of them in `config.py → SHARE_SELECTORS`;
    prefer `data-automationid`; provide text/aria fallbacks; gate behind the
    non-fatal boundary so a wrong selector degrades to a logged failure rather
    than a crash. Validate end-to-end with a single real folder before enabling
    for the full list.

- **MEDIUM — Date locale / format mismatch**. The input may expect `DD/MM/AAAA`
  with locale-specific separators or parsing.
  - *Mitigation*: Format strictly as `DD/MM/YYYY`; unit test the formatter;
    verify acceptance in the live probe.

- **MEDIUM — Password ↔ report-key mismatch**. If the clean path → base name →
  report row key mapping is wrong, the applied password won't match the report.
  - *Mitigation*: Pure, unit-tested mapping helper; single source of truth for
    passwords (pre-generated map) consumed by both sharing and reporting.

- **LOW — Folder still selected / stale DOM after clean**. OneDrive's list is
  virtualized and may be stale right after the delete loop.
  - *Mitigation*: Re-list / re-locate the folder by name before selecting its
    checkbox, consistent with the existing post-mutation re-list pattern.

## Success criteria

1. After a real run, every folder in `folders.json["clean"]` has an "Anyone"
   sharing link.
2. Each link's expiration equals today + 9 days, rendered `DD/MM/YYYY`.
3. Each link's password exactly matches the password shown for that folder in the
   generated Excel report (verified by the shared password map and unit tests).
4. A sharing failure on one folder is logged, recorded in `ShareStats`, surfaced
   in the summary, and does NOT abort the run or change the exit code.
5. `tests/test_sharer.py` passes: expiry formatting, path→key mapping, and stats
   aggregation are all covered.
6. `reporter.build_report_rows()` remains backward compatible (works with and
   without the `passwords` argument).

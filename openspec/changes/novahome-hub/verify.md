# Verify Report: novahome-hub

**Date**: 2026-05-21  
**Verifier**: sdd-verify (claude-sonnet-4-6)  
**Mode**: Standard (strict_tdd: false)  
**Artifact store**: hybrid (engram + openspec)

---

## Completeness Table

| Phase | Tasks | Marked Complete | Code Present |
|-------|-------|-----------------|--------------|
| 1 — Scaffold | 4 | 4 | ✓ |
| 2 — UI Primitives | 2 | 2 | ✓ |
| 3 — Placeholders | 2 | 2 | ✓ |
| 4 — Azulito Dep Checks | 2 | 2 | ✓ |
| 5 — Env Wizard | 1 | 1 | ✓ |
| 6 — Azulito Orchestrator | 2 | 2 | ✓ |
| 7 — Entry Point | 1 | 1 | ✓ |
| 8 — Smoke Test (manual) | 8 | 0 | N/A |

**Core tasks (T1–T7)**: 14/14 marked complete, all confirmed in code.  
**Manual smoke tests (T8)**: 0/8 marked complete (expected — these are manual verification items).

---

## Build / Import Evidence

```
python3 -c "import novahome; import novahome.ui.banner; import novahome.ui.checks;
            import novahome.modules.azulito; import novahome.modules.novahld;
            import novahome.modules.aditai"
→ Exit 0, all imports OK
```

No test suite is configured (standard mode, no test runner). Import validation is the only executable evidence available.

---

## Spec Compliance Matrix

| Requirement | Scenario | Status | Evidence |
|-------------|----------|--------|----------|
| Branded Launch Screen | Normal launch — banner before menu | PASS | `render_banner()` called first in `main()` |
| Arrow-Key Menu — 3 options | User selects azulito | PASS | `questionary.select` with 4 choices; lazy import into `azulito.run()` |
| Arrow-Key Menu — 3 options | User selects novahld | PARTIAL | `novahld.run()` called; panel rendered; but NO return-to-menu |
| Arrow-Key Menu — 3 options | User selects aditai | PARTIAL | `aditai.run()` called; panel rendered; but NO return-to-menu |
| Graceful Ctrl+C | Ctrl+C at main menu | PASS | `try/except KeyboardInterrupt` → `print + sys.exit(130)` |
| Placeholder Return-to-Menu | Return after placeholder | FAIL | `main()` has no `while` loop; process exits after module returns |
| Sequential Dep Checks | All checks pass | PASS | 5 checks run unconditionally in `run_all_checks()` |
| Sequential Dep Checks | One or more fail | PASS | `all_passed` gate controls menu; Iniciar absent when any fail |
| Sequential Dep Checks | Chromium not installed | PARTIAL | Hint text is correct; but ADR-3a string-match fallback NOT implemented |
| Sequential Dep Checks | .env missing or incomplete | PASS | `ENV_PATH.exists()` + `dotenv_values` + key presence check |
| Env Wizard | .env exists with all values | PASS | `questionary.text(default=existing.get(KEY))` pre-fills username + sharepoint |
| Env Wizard | User skips field (has prior value) | FAIL | Empty submit triggers global re-prompt, NOT retain-existing; violates merge/patch AC-7 |
| Env Wizard | Empty submit, no prior value | PASS | Strip check catches it; error message + re-loop |
| Env Wizard | Successful save | PASS | `ENV_PATH.write_text(...)` with correct `REPO_ROOT / "onedrive_rpa" / ".env"` path |
| Subprocess Launch | RPA exits code 0 | PASS | `sys.exit(launch_rpa())` propagates returncode |
| Subprocess Launch | RPA exits non-zero | PASS | `sys.exit(launch_rpa())` propagates verbatim |
| Subprocess Launch | Ctrl+C during subprocess | PASS | `sys.exit(launch_rpa())` — KeyboardInterrupt exits at OS level with 130 |

---

## ADR Compliance

| ADR | Requirement | Status | Notes |
|-----|-------------|--------|-------|
| ADR-1 | `subprocess.run([...], cwd=REPO_ROOT)` | PASS | Line 196–199 in azulito.py |
| ADR-2 | `dotenv_values` read + `questionary.password()` always blank | PASS | Lines 135–155; password always blank |
| ADR-2 | Merge/patch: empty = keep existing | FAIL | Rejects empty with re-prompt instead of retaining prior value |
| ADR-3 | All 5 checks unconditional in `run_all_checks()` | PASS | All 5 results always appended |
| ADR-3 | Check 3: `importlib.util.find_spec("playwright")` | WARNING | Implementation uses `subprocess.run(["python3", "-c", "import playwright"])` — functionally equivalent but deviates from spec method |
| ADR-3a | Chromium: `returncode==0 AND "is already installed" in stdout+stderr` | WARNING | Implementation checks only `returncode==0`; string-match fallback missing; may produce false negatives across Playwright versions |
| ADR-4 | Lazy imports inside menu branches | PASS | All module imports are inside `if/elif` branches or function bodies |
| ADR-5 | No `Rich.Live` anywhere in `novahome/` | PASS | Confirmed by full scan |
| ADR-6 | `questionary>=2.0,<3.0` in root `requirements.txt` | WARNING | Implemented as `questionary>=2.0` (no upper bound `<3.0`); diverges from design spec |

---

## Design Coherence

| Design Element | Status | Notes |
|----------------|--------|-------|
| Module structure matches design diagram | PASS | All 6 files created as specified |
| `REPO_ROOT` resolved at import time | PASS | Module-level constant in azulito.py |
| `ENV_PATH = REPO_ROOT / "onedrive_rpa" / ".env"` | PASS | Exact path confirmed |
| No imports of `onedrive_rpa.*` | PASS | Confirmed across all novahome/ files |
| Hub-and-spoke subprocess boundary | PASS | RPA invoked only via `subprocess.run` |
| Interface contracts (`run() -> None` for all modules) | PASS | All three tool modules export `run()` |
| `configure_env()` pre-existing key preservation | FAIL | Full rewrite drops keys not in REQUIRED_KEYS; design ADR-2 says "managed file" but spec AC-6 says "pre-existing keys not managed by the wizard are preserved" |

---

## Issues

### CRITICAL

**C-1: No return-to-menu loop in `main()`**  
- Spec: "novahld and aditai MUST return the user to the main menu after displaying their panel. The main menu is RE-RENDERED and the user can make another selection."  
- Acceptance criterion AC-2 is violated.  
- Root cause: `main()` has no `while True` loop. After any module's `run()` returns, `main()` returns and the process exits cleanly.  
- Affects: novahld, aditai, and azulito's "Configurar/Volver" path all silently terminate the hub.  
- Fix: wrap the `questionary.select(...)` dispatch block in a `while True` loop; `break` on "Salir" or `choice is None`.

**C-2: Env wizard merge/patch strategy (AC-7) not implemented**  
- Spec scenario: "Given wizard is prompting for a var that already has a value, when user submits empty, THEN existing value is retained."  
- Implementation: empty input triggers a global re-prompt loop (`continue`) — it does NOT retain the existing value.  
- This contradicts AC-7 merge/patch. The correct fix: `resolved_username = username.strip() or existing.get("ONEDRIVE_USERNAME", "")`, then validate the resolved value rather than the raw input.  
- File: `novahome/modules/azulito.py`, function `configure_env()`.

**C-3: `configure_env()` drops pre-existing .env keys not in REQUIRED_KEYS**  
- Spec AC-6: "pre-existing keys not managed by the wizard are preserved."  
- Implementation writes exactly 3 KEY=value lines, discarding any other keys that exist in the file (e.g., future additions, comments-as-keys, etc.).  
- Fix: read all existing keys via `dotenv_values`, merge with wizard output, write all keys back.

### WARNING

**W-1: ADR-3 playwright check method deviates from spec**  
- Spec and ADR-3 specify `importlib.util.find_spec("playwright")` (in-process, no subprocess).  
- Implementation uses `subprocess.run(["python3", "-c", "import playwright"])`.  
- Functionally equivalent in most cases, but: (a) slower (spawns a process), (b) may check the wrong interpreter if `python3` resolves differently from the running venv.  
- Severity: WARNING (not spec-breaking in practice, but explicitly contradicts ADR-3).

**W-2: ADR-3a chromium string-match fallback missing**  
- ADR-3a requires: `returncode == 0 AND "is already installed" in combined stdout+stderr`.  
- Implementation checks only `returncode == 0`.  
- Risk: Playwright has inconsistently used exit codes across versions; the string check is the documented fallback.  
- File: `novahome/modules/azulito.py`, check #4 in `run_all_checks()`.

**W-3: `questionary` version upper bound missing in requirements.txt**  
- Design ADR-6 specifies `questionary>=2.0,<3.0`.  
- `requirements.txt` has `questionary>=2.0` with no upper bound.  
- Risk: a future major-version questionary release could break the hub silently.

### SUGGESTION

**S-1: `novahld` and `aditai` modules have no `questionary.press_any_key_to_continue()` pause**  
- Design ADR-5 mentions: "Coming-soon: single Panel, then `questionary.press_any_key()`, return to menu."  
- The panels render and immediately return, which means (once C-1 is fixed and the loop exists) the panel will flash briefly before the menu re-renders.  
- This is cosmetic but degrades UX.

**S-2: Banner's `render_banner()` signature deviates from design contract**  
- Design interface contract: `render_banner(console: Console) -> None`.  
- Implementation: `render_banner() -> None` (uses a module-level `_console`).  
- This is internally consistent but makes the function harder to test (no Console injection). Low risk for current scope.

---

## AC Checklist

| AC | Description | Status |
|----|-------------|--------|
| AC-1 | Banner + 3-option menu on launch | PASS |
| AC-2 | novahld/aditai show "coming soon" and return to menu | FAIL |
| AC-3 | Ctrl+C exits 130, no traceback | PASS |
| AC-4 | Exactly 5 dep check rows in Rich panel | PASS |
| AC-5 | Failing check hides Iniciar | PASS |
| AC-6 | Env wizard reads .env, shows defaults, writes to exact path | PARTIAL (path correct; pre-existing keys dropped — C-3) |
| AC-7 | Wizard merge/patch: empty retains prior; missing required re-prompts | FAIL |
| AC-8 | Iniciar launches `onedrive_rpa/main.py --mode manual`, cwd=REPO_ROOT | PASS |
| AC-9 | novahome exits with subprocess exit code verbatim | PASS |
| AC-10 | Zero files inside `onedrive_rpa/` modified | PASS |

---

## Final Verdict

**FAIL**

**3 CRITICAL / 3 WARNING / 2 SUGGESTION**

Blocking issues: C-1 (no return-to-menu loop), C-2 (merge/patch not implemented), C-3 (pre-existing .env keys dropped). These are not cosmetic — they contradict explicit spec requirements (AC-2, AC-7, AC-6) and the design's stated merge strategy.

Recommended next action: `sdd-apply` (corrective pass targeting C-1, C-2, C-3), then re-run `sdd-verify`.

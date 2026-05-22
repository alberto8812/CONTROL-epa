# Tasks: novahome-hub

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 280–360 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | All novahome-hub files | PR 1 | New package only; zero onedrive_rpa/ changes |

---

## Phase 1: Foundation / Scaffold

- [ ] 1.1 Create `novahome/__init__.py` — empty file; makes novahome a package.  
  Acceptance: `python -c "import novahome"` exits 0 from repo root.

- [ ] 1.2 Create `novahome/modules/__init__.py` — empty file.  
  Acceptance: file exists; no import errors.

- [ ] 1.3 Create `novahome/ui/__init__.py` — empty file.  
  Acceptance: file exists; no import errors.

- [ ] 1.4 Create repo-root `requirements.txt` with `questionary>=2.0,<3.0` and `-r onedrive_rpa/requirements.txt` (ADR-6).  
  Acceptance: `pip install -r requirements.txt` installs questionary and all RPA deps without error.

---

## Phase 2: Core — UI Primitives

- [ ] 2.1 Create `novahome/ui/banner.py` — implement `render(console: Console) -> None`.  
  Renders a Rich `Panel` with styled `Text` title "NovaHome", version, tagline. No ASCII art (ADR-5).  
  Acceptance: calling `render(Console())` prints a non-empty Panel to stdout without raising.

- [ ] 2.2 Create `novahome/ui/checks.py` — implement `@dataclass(frozen=True) CheckResult(name, ok, hint)` and `render(console, results) -> None`.  
  Renders a Rich `Table` (Check / Status cols) inside a Panel titled "Verificación de entorno". OK = green, FAIL = red + dim hint (ADR-5).  
  Acceptance: `render(Console(), [CheckResult("python3", True, None), CheckResult("pip", False, "hint")])` prints table; FAIL row shows hint.

---

## Phase 3: Core — Module Placeholders

- [ ] 3.1 Create `novahome/modules/novahld.py` — implement `run() -> None`.  
  Shows a single Rich `Panel` "coming soon", then `questionary.press_any_key_to_continue()`, then returns (does NOT call `sys.exit`).  
  Acceptance: calling `run()` returns control to caller; process does not exit.

- [ ] 3.2 Create `novahome/modules/aditai.py` — same pattern as 3.1.  
  Acceptance: same as 3.1.

---

## Phase 4: Core — Azulito Dep Checks

- [ ] 4.1 Create `novahome/modules/azulito.py` — module-level constants only:  
  `REPO_ROOT = Path(__file__).resolve().parents[2]`, `ENV_PATH = REPO_ROOT / "onedrive_rpa" / ".env"`, `REQUIRED_ENV_KEYS = ("ONEDRIVE_USERNAME", "ONEDRIVE_PASSWORD", "SHAREPOINT_PERSONAL_PATH")`.  
  Acceptance: importing the module sets all three constants without side effects.

- [ ] 4.2 Add `run_all_checks() -> list[CheckResult]` to `azulito.py`.  
  Implements all 5 checks unconditionally (ADR-3): `shutil.which("python3")`, `shutil.which("pip")`, `importlib.util.find_spec("playwright")`, Chromium via `subprocess.run([sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"], ...)` matching `"is already installed"` (ADR-3a), `.env` present + all 3 keys non-empty. Each check wrapped in try/except. Returns exactly 5 `CheckResult` objects.  
  Acceptance: function returns list of length 5 in all environments; never raises.

---

## Phase 5: Core — Azulito Env Wizard

- [ ] 5.1 Add `env_wizard() -> None` to `azulito.py`.  
  Reads `ENV_PATH` via `dotenv_values` (ADR-2); prompts `ONEDRIVE_USERNAME` and `SHAREPOINT_PERSONAL_PATH` with existing values as questionary `default=`; prompts `ONEDRIVE_PASSWORD` with `questionary.password()` (no default); empty submission retains existing value; empty submission when no prior value re-prompts with required-field error. Writes all 3 keys as `KEY=VALUE` lines to `ENV_PATH` (full rewrite). Shows confirmation panel on success; red error panel on FS error.  
  Acceptance (manual): running wizard with an existing `.env` retains unchanged fields; ONEDRIVE_PASSWORD is masked; file is rewritten with all 3 keys.

---

## Phase 6: Core — Azulito Orchestrator and Launch

- [ ] 6.1 Add `launch_rpa() -> int` to `azulito.py`.  
  Calls `subprocess.run(["python3", "onedrive_rpa/main.py", "--mode", "manual"], cwd=REPO_ROOT)`. Returns `CompletedProcess.returncode`. Catches `KeyboardInterrupt` → prints dim "Cancelado", returns 130 (ADR-1).  
  Acceptance: function signature correct; `KeyboardInterrupt` handled; no traceback on Ctrl+C.

- [ ] 6.2 Add `run() -> None` to `azulito.py` — orchestrates the full flow:  
  (1) call `run_all_checks()`, (2) call `ui.checks.render()`, (3) if all OK offer `["Iniciar", "Configurar variables de entorno", "Volver"]`; if any FAIL offer only `["Configurar variables de entorno", "Volver"]`. `Iniciar` → `launch_rpa()` → print exit code panel → return. `Configurar` → `env_wizard()` → re-run checks → re-render panel → offer menu again. `Volver` → return. `KeyboardInterrupt` caught: print "Cancelado", return.  
  Acceptance: `Iniciar` is unreachable when any check fails (spec AC-5); menu loops correctly; returns to caller.

---

## Phase 7: Entry Point

- [ ] 7.1 Create `novahome/main.py` — implement `main() -> int`.  
  (1) `ui.banner.render(console)`, (2) `questionary.select` with 3 options (novahld / azulito / aditai) (ADR-4: lazy imports inside each branch), (3) dispatch to `module.run()`, (4) loop back to menu, (5) `KeyboardInterrupt` at menu → print "Hasta luego", exit 130. Outer try/except on module dispatch → red panel, return to menu (never crash hub). `if __name__ == "__main__": sys.exit(main())`.  
  Acceptance (AC-1, AC-2, AC-3): banner visible on launch; novahld/aditai return to menu; Ctrl+C exits 130 with no traceback.

---

## Phase 8: Integration Smoke Test (manual)

- [ ] 8.1 Run `pip install -r requirements.txt` from repo root — must succeed.  
  Acceptance: no install errors.

- [ ] 8.2 Run `python novahome/main.py` from repo root — banner and 3-option menu appear.  
  Acceptance: AC-1 satisfied.

- [ ] 8.3 Select `novahld` → "coming soon" panel → any key → back at main menu. Repeat for `aditai`.  
  Acceptance: AC-2 satisfied.

- [ ] 8.4 Press Ctrl+C at main menu → friendly message, exit code 130, no traceback.  
  Acceptance: AC-3 satisfied.

- [ ] 8.5 Select `azulito` → dep check panel renders with exactly 5 rows.  
  Acceptance: AC-4 satisfied.

- [ ] 8.6 If any check FAIL → `Iniciar` absent from menu; `Configurar` available.  
  Acceptance: AC-5 satisfied.

- [ ] 8.7 Run env wizard → existing values as defaults, password masked, file rewritten.  
  Acceptance: AC-6, AC-7 satisfied.

- [ ] 8.8 Verify zero files under `onedrive_rpa/` were modified.  
  Acceptance: AC-10 satisfied.

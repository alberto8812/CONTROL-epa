# Proposal: NovaHome Hub

## Intent

The repository currently exposes a single tool (`onedrive_rpa/`) reached by typing a long `python main.py --mode ...` command from inside a subfolder. There is no unified entry point, no dependency validation, no friendly env configuration, and no room to host the upcoming sibling tools (novahld, aditai) without polluting the RPA's layered architecture. NovaHome solves this by adding a branded top-level shell hub that routes the user into the right subproject, validates its environment, and launches it as an isolated subprocess.

## Scope

### In Scope
- New `novahome/` package at repo root (entry: `python novahome/main.py`)
- `novahome/main.py`: Rich banner + arrow-key menu (questionary) routing to 3 modules
- `novahome/modules/azulito.py`: 5 dependency checks + env wizard + subprocess launch of `onedrive_rpa/main.py`
- `novahome/modules/novahld.py` and `novahome/modules/aditai.py`: "coming soon" placeholders
- `novahome/ui/banner.py`: Rich-rendered NovaHome banner
- `novahome/ui/checks.py`: Rich panel rendering dep check status (OK / FAIL with hint)
- Env wizard: merge/patch strategy against `onedrive_rpa/.env` (defaults from existing values, mask `ONEDRIVE_PASSWORD`)
- Add `questionary` to dependencies (root-level `requirements.txt`)

### Out of Scope
- Actual implementations of novahld and aditai (placeholders only)
- `pyproject.toml` or installable CLI entry point
- Any modification to files inside `onedrive_rpa/` (zero changes to existing RPA)
- Refactoring `onedrive_rpa` to be importable — it stays a subprocess boundary

## Capabilities

### New Capabilities
- `novahome-shell`: Top-level hub with branded banner and arrow-key menu routing to subproject modules
- `azulito-launcher`: Dependency validation, interactive env wizard, and subprocess launch of the OneDrive RPA

### Modified Capabilities
- None — `onedrive_rpa/` is not touched

## Approach

`novahome/main.py` renders the banner, then questionary presents a 3-option menu (azulito / novahld / aditai) and dispatches to `novahome/modules/<name>.py`. The azulito module runs 5 sequential dependency checks (python3, pip, playwright package, chromium browser, `onedrive_rpa/.env` with the 3 required vars) and renders results in a Rich panel. If all pass, the user picks `Iniciar` or `Configurar`. The env wizard reads the existing `.env`, shows current values as defaults (password masked), and writes back to the exact same path. Launch uses `subprocess.run(["python3", "onedrive_rpa/main.py", "--mode", "manual"], cwd=repo_root)` to preserve the existing layered separation — the RPA is never imported.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `novahome/` | New | Hub package: main.py, modules/, ui/ |
| `requirements.txt` (repo root) | New | Adds `questionary`, re-exports onedrive_rpa deps |
| `onedrive_rpa/` | Untouched | Zero changes; invoked only via subprocess |
| `onedrive_rpa/.env` | Read/Written | By env wizard only; hardcoded path preserved |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `config.py` hardcodes `.env` path as `Path(__file__).parent / ".env"` | High | Wizard ALWAYS writes to `onedrive_rpa/.env` exactly; covered by a test |
| Subprocess cwd drifts and breaks relative paths in the RPA | Medium | Pass `cwd=<repo_root>` explicitly and call with explicit `onedrive_rpa/main.py` path |
| questionary + Rich Live coexistence conflict | Low | Not exercised in this change (no Live during menu); documented as future constraint |
| Chromium check false-negative on first install | Medium | Check parses `playwright install --dry-run` output; on FAIL show exact remediation command |

## Rollback Plan

Delete `novahome/` and the root-level `requirements.txt`. `onedrive_rpa/` is untouched, so reverting restores the previous workflow with zero side effects. No data migration, no env mutation outside what the user explicitly approved in the wizard.

## Dependencies

- `questionary >= 2.0` (new)
- Existing: Rich 13.7.1, Loguru, Playwright 1.44.0, Click, python-dotenv

## Success Criteria

- [ ] `python novahome/main.py` from repo root opens the NovaHome menu
- [ ] Selecting azulito runs 5 dep checks and renders a Rich status panel
- [ ] Env wizard reads existing `onedrive_rpa/.env`, prompts with defaults, masks password, and writes back to the same path
- [ ] `Iniciar` launches the OneDrive RPA as a subprocess and exits with the RPA's exit code
- [ ] novahld and aditai show a "coming soon" panel and return to the menu
- [ ] Zero files modified inside `onedrive_rpa/`

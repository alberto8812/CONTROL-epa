# Spec: novahome-hub

## Capabilities Covered

| Capability | Type | Domain |
|---|---|---|
| `novahome-shell` | New | Top-level hub: banner + menu routing |
| `azulito-launcher` | New | Dep checks, env wizard, subprocess launch |

---

## Capability: novahome-shell

### Purpose

Top-level entry point that presents a branded NovaHome banner and routes the user to one of three subproject modules via an arrow-key menu.

---

### Requirement: Branded Launch Screen

The system MUST display a NovaHome branded banner before presenting any menu. The banner MUST be rendered via Rich and MUST be visible on every launch without requiring any flag.

#### Scenario: Normal launch

- GIVEN the user runs `python novahome/main.py` from the repo root
- WHEN the process starts
- THEN a Rich-rendered NovaHome banner is printed to stdout before the menu appears

---

### Requirement: Arrow-Key Menu with Three Options

The system MUST present exactly three options — `novahld`, `azulito`, `aditai` — navigable via arrow keys. Selection MUST dispatch to the corresponding module.

#### Scenario: User selects azulito

- GIVEN the main menu is displayed
- WHEN the user navigates to `azulito` and confirms
- THEN the azulito launcher module executes

#### Scenario: User selects novahld

- GIVEN the main menu is displayed
- WHEN the user selects `novahld`
- THEN a "coming soon" panel is rendered and control returns to the main menu

#### Scenario: User selects aditai

- GIVEN the main menu is displayed
- WHEN the user selects `aditai`
- THEN a "coming soon" panel is rendered and control returns to the main menu

---

### Requirement: Graceful Ctrl+C Handling

The system MUST intercept `KeyboardInterrupt` at the main menu level and exit with code 130 after printing a friendly farewell message. It MUST NOT print a raw traceback.

#### Scenario: Ctrl+C at the main menu

- GIVEN the main menu is displayed
- WHEN the user presses Ctrl+C
- THEN a friendly message is printed
- AND the process exits with code 130
- AND no Python traceback appears on stdout or stderr

---

### Requirement: Placeholder Module Return-to-Menu

novahld and aditai MUST return the user to the main menu after displaying their "coming soon" panel. They MUST NOT exit the process.

#### Scenario: Return to menu after placeholder

- GIVEN the user selected novahld or aditai
- WHEN the "coming soon" panel is dismissed
- THEN the main menu is re-rendered and the user can make another selection

---

## Capability: azulito-launcher

### Purpose

Validates all runtime dependencies for the OneDrive RPA, allows interactive configuration of required env vars, and launches the RPA as an isolated subprocess.

---

### Requirement: Sequential Dependency Checks

The system MUST run exactly five dependency checks in order before offering any launch action:

| # | Check | Method |
|---|---|---|
| 1 | `python3` available | `shutil.which("python3")` |
| 2 | `pip` available | `shutil.which("pip")` |
| 3 | `playwright` package importable | `importlib.util.find_spec("playwright")` |
| 4 | Chromium browser installed | parse `playwright install --dry-run` output |
| 5 | `onedrive_rpa/.env` present with all 3 vars non-empty | file read + key presence |

#### Scenario: All checks pass

- GIVEN the user enters the azulito module
- WHEN all five checks succeed
- THEN a Rich panel is rendered showing OK status for each check
- AND two options are offered: `Iniciar` and `Configurar variables de entorno`

#### Scenario: One or more checks fail

- GIVEN the user enters the azulito module
- WHEN at least one check fails
- THEN a Rich panel renders FAIL status for each failing check with the remediation command
- AND only the `Configurar variables de entorno` option is offered
- AND `Iniciar` MUST NOT be reachable

#### Scenario: Chromium not installed

- GIVEN check 4 fails
- WHEN the panel renders
- THEN the remediation hint shown is `playwright install chromium`

#### Scenario: .env missing or incomplete

- GIVEN check 5 fails because `onedrive_rpa/.env` does not exist or is missing at least one of the three required vars
- WHEN the panel renders
- THEN the FAIL entry identifies which vars are absent or empty

---

### Requirement: Env Wizard — Read, Prompt, Write

The env wizard MUST read the current `onedrive_rpa/.env` (if it exists), display existing non-password values as defaults, mask `ONEDRIVE_PASSWORD` input, validate all three vars are non-empty before saving, and write back to the exact path `onedrive_rpa/.env`.

The three required vars are: `ONEDRIVE_USERNAME`, `ONEDRIVE_PASSWORD`, `SHAREPOINT_PERSONAL_PATH`.

#### Scenario: .env already exists with all values

- GIVEN `onedrive_rpa/.env` exists with all three vars set
- WHEN the wizard opens
- THEN `ONEDRIVE_USERNAME` and `SHAREPOINT_PERSONAL_PATH` prompts show current values as defaults
- AND `ONEDRIVE_PASSWORD` prompt uses password masking and shows no existing value

#### Scenario: User skips a field (submits empty)

- GIVEN the wizard is prompting for a var that already has a value
- WHEN the user submits an empty input
- THEN the existing value is retained (merge/patch strategy)

#### Scenario: User submits empty value for a var that had no prior value

- GIVEN the wizard is prompting for a var with no prior value
- WHEN the user submits an empty input
- THEN the wizard rejects the submission, informs the user the field is required, and re-prompts

#### Scenario: Successful save

- GIVEN all three vars have non-empty resolved values
- WHEN the wizard writes `onedrive_rpa/.env`
- THEN the file is written to exactly `onedrive_rpa/.env` relative to the repo root
- AND a confirmation message is shown to the user
- AND pre-existing keys not managed by the wizard are preserved

---

### Requirement: Subprocess Launch via Iniciar

The system MUST launch `onedrive_rpa/main.py` as a subprocess with `--mode manual` when the user selects `Iniciar`. The subprocess MUST run with `cwd` set to the repo root. The novahome process MUST exit with the same exit code returned by the subprocess.

#### Scenario: RPA exits cleanly (code 0)

- GIVEN all dependency checks pass and the user selects `Iniciar`
- WHEN the subprocess finishes with exit code 0
- THEN novahome exits with code 0

#### Scenario: RPA exits with non-zero code

- GIVEN the user selected `Iniciar`
- WHEN the subprocess exits with code 3 (session expired)
- THEN novahome exits with code 3

#### Scenario: Ctrl+C during subprocess execution

- GIVEN the RPA subprocess is running
- WHEN the user presses Ctrl+C
- THEN `KeyboardInterrupt` is caught by the novahome wrapper
- AND novahome exits with code 130
- AND no raw traceback is printed

---

## Out of Scope

- Real implementations of `novahld` and `aditai`
- `pyproject.toml` or installable CLI entry point
- Any modification to files inside `onedrive_rpa/`
- Importing `onedrive_rpa` as a Python package (subprocess boundary is preserved)
- `--mode auto` or `--mode headless` launch options from the hub

---

## Acceptance Criteria Summary

| # | Criterion |
|---|---|
| AC-1 | `python novahome/main.py` from repo root shows the NovaHome banner and 3-option menu |
| AC-2 | novahld and aditai show "coming soon" and return to menu without exiting |
| AC-3 | Ctrl+C at any menu level exits with code 130 and no traceback |
| AC-4 | Azulito renders exactly 5 dep check results in a Rich panel |
| AC-5 | A failing check shows the remediation command; `Iniciar` is not offered |
| AC-6 | Env wizard reads existing `onedrive_rpa/.env`, shows defaults (password masked), validates, and writes back to the same path |
| AC-7 | Wizard merge/patch: empty submission retains existing value; missing required var is re-prompted |
| AC-8 | `Iniciar` launches `onedrive_rpa/main.py --mode manual` as subprocess with repo-root cwd |
| AC-9 | novahome exits with the subprocess exit code verbatim |
| AC-10 | Zero files inside `onedrive_rpa/` are modified by this change |

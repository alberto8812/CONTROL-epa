# Design: NovaHome Hub

> Technical design for the `novahome-hub` change. The HOW, at architectural level.
> Implementation steps belong in `tasks.md` — this document covers structure,
> contracts, decisions, and rationale only.

## 1. Architectural Approach

### Pattern: Hub-and-Spoke with Subprocess Boundary

NovaHome is a **shell/hub** that does NOT import its sibling tools. Each tool
(`onedrive_rpa`, future `novahld`, future `aditai`) is an isolated executable
behind a subprocess boundary. The hub only knows three things about each tool:

1. Where its entry point lives on disk
2. What command launches it
3. What environment it expects (validated via dep checks)

This is deliberate. It preserves three properties:

- **Layered separation**: `onedrive_rpa` keeps its strict `auth/rpa/config`
  layering. The hub does not become a transitive dependency of the RPA.
- **Independent lifecycles**: each tool can use a different Python interpreter,
  conflicting packages, or even a different language in the future. Subprocess
  is the lowest-common-denominator contract.
- **Crash isolation**: an unhandled exception in the RPA cannot corrupt the
  hub's TUI state, because they live in different processes.

### Layering

```
novahome/
  main.py          presentation + routing (Rich + questionary)
  modules/         one file per tool — pure orchestration
  ui/              reusable Rich renderers (banner, dep-check panel)
```

The hub has only three architectural roles: **render**, **route**, **launch**.
It never reads user files (except `onedrive_rpa/.env` via the wizard), never
mutates state outside the wizard's exact target file, never imports anything
from `onedrive_rpa/`.

## 2. Module Structure and Responsibilities

| Module | Responsibility | Imports allowed |
|--------|---------------|-----------------|
| `novahome/__init__.py` | Package marker. Exports nothing. | — |
| `novahome/main.py` | Entry point. Render banner, show menu, dispatch to module. Catches `KeyboardInterrupt` for graceful exit. | `rich`, `questionary`, `novahome.ui.*`, `novahome.modules.*` (lazy) |
| `novahome/modules/__init__.py` | Package marker. | — |
| `novahome/modules/azulito.py` | OneDrive RPA launcher: 5 dep checks, env wizard, subprocess launch. | `rich`, `questionary`, `subprocess`, `dotenv`, `pathlib`, `shutil`, `importlib`, `novahome.ui.*` |
| `novahome/modules/novahld.py` | Placeholder "coming soon" panel + return. | `rich` |
| `novahome/modules/aditai.py` | Placeholder "coming soon" panel + return. | `rich` |
| `novahome/ui/__init__.py` | Package marker. | — |
| `novahome/ui/banner.py` | Render the NovaHome banner (Rich Panel with title, version, tagline). | `rich` |
| `novahome/ui/checks.py` | Render the dep-check results Table inside a Panel; format OK/FAIL/hint rows. | `rich` |

**Forbidden import**: nothing under `novahome/` may `import onedrive_rpa.*`.
The subprocess boundary is enforced by convention and verified in tests.

## 3. Data Flow

```
                    user runs `python novahome/main.py`
                                  │
                                  ▼
                ┌────────────────────────────────────┐
                │ novahome/main.py                   │
                │  1. ui.banner.render()             │
                │  2. questionary.select(modules)    │
                └────────────────┬───────────────────┘
                                 │ choice
       ┌─────────────────────────┼─────────────────────────┐
       ▼                         ▼                         ▼
 azulito.run()             novahld.run()              aditai.run()
       │                         │                         │
       │                         └─ panel "coming soon" ───┘
       │                              return to main loop
       ▼
 ┌──────────────────────────────────────────────┐
 │ azulito.run()                                │
 │  1. checks = run_all_checks()  ← all 5       │
 │  2. ui.checks.render(checks)                 │
 │  3. action = questionary.select(             │
 │        ["Iniciar", "Configurar", "Volver"])  │
 └────────┬─────────────────────┬────────────┬──┘
          │ Iniciar             │ Configurar │ Volver
          ▼                     ▼            ▼
   launch_rpa()            env_wizard()    return
          │                     │
          ▼                     ▼
 subprocess.run(           dotenv_values  + questionary prompts
   ["python3",             then full rewrite of
    "onedrive_rpa/         onedrive_rpa/.env
    main.py",              (KEY=VALUE lines)
    "--mode","manual"],
   cwd=REPO_ROOT
 )
          │
          ▼
 propagate exit code → return to main loop
```

`REPO_ROOT` is resolved once, at import time of each module that needs it:

```
REPO_ROOT = Path(__file__).resolve().parents[2]
# novahome/modules/azulito.py  → parents[2] = repo root
```

Resolution at import time is intentional: the hub's notion of "where am I"
becomes immutable for the lifetime of the process, independent of the user's
shell `cwd`. This is the contract the subprocess boundary depends on.

## 4. Design Decisions (ADR-style)

### ADR-1: Subprocess Contract for the RPA

**Decision.** The hub launches the RPA exclusively via:

```
subprocess.run(
    ["python3", "onedrive_rpa/main.py", "--mode", "manual"],
    cwd=REPO_ROOT,
)
```

where `REPO_ROOT = Path(__file__).resolve().parents[2]` evaluated in
`novahome/modules/azulito.py`.

**Rationale.** Three constraints must hold simultaneously:

1. The RPA's `config.py` resolves `.env` as `Path(__file__).parent / ".env"`,
   which is independent of `cwd`. Good — the wizard can write that exact path
   and the RPA will read it.
2. `onedrive_rpa/folders.json` and `onedrive_rpa/logs/` are accessed via
   relative paths inside the RPA. They depend on `cwd`. Passing
   `cwd=REPO_ROOT` and invoking as `onedrive_rpa/main.py` (NOT `cd onedrive_rpa
   && python main.py`) keeps these paths stable: the RPA still resolves
   `folders.json` relative to its own file via Click/Pathlib conventions in
   the codebase.
3. The user may invoke `python novahome/main.py` from any directory.
   Resolving `REPO_ROOT` at import time freezes it before any chdir could
   happen.

**Rejected alternatives.**

- *Import `onedrive_rpa.main` and call it directly.* Rejected: breaks the
  layered isolation, makes `questionary` and `rich` transitive deps of the
  RPA, and any uncaught RPA exception kills the hub.
- *`os.chdir(REPO_ROOT / "onedrive_rpa")` then `python main.py`.* Rejected:
  mutates global process state, fragile if the RPA itself chdir's, and
  hides the working directory contract from the call site.
- *Use `sys.executable` instead of `"python3"`.* Considered. Trade-off: more
  hermetic (uses the same interpreter) but breaks the user's expectation
  that the RPA runs in the project's chosen env. Defer: stick with
  `"python3"` for now; revisit if multi-env support is requested.

### ADR-2: Env Wizard — Merge-and-Rewrite Strategy

**Decision.** The wizard reads existing values via `dotenv_values(<path>)`,
prompts for each of the 3 required variables with the existing value shown as
the questionary `default=` (except `ONEDRIVE_PASSWORD`, which is always
prompted blank via `questionary.password()`), and then **fully rewrites**
`onedrive_rpa/.env` with exactly the 3 `KEY=VALUE` lines.

Target path:
```
ENV_PATH = REPO_ROOT / "onedrive_rpa" / ".env"
```

**Rationale.**

- *Why show existing values as defaults?* Lowers friction on re-runs — the
  user can press Enter to keep a value. Empty input means "keep existing".
- *Why mask the password unconditionally?* Even showing
  `"current: ********"` as a hint leaks length and signals presence in shell
  history if the terminal echoes the prompt. Safer to always ask blank;
  empty input keeps the existing value.
- *Why full rewrite instead of in-place patch?* The `.env` schema is fixed
  (3 keys). A clean rewrite eliminates stale keys, comments drifting out of
  sync, and ordering ambiguity. Cost: the user loses any custom comments
  they added — acceptable, this is a managed file.
- *Why the literal path `onedrive_rpa/.env`?* The RPA hardcodes
  `Path(__file__).parent / ".env"` in `config.py`. The wizard must write
  exactly that path; any other location is ignored by the RPA. This is the
  highest risk in the proposal and is captured here so future contributors
  don't "improve" it.

**Rejected alternatives.**

- *Use `python-dotenv`'s `set_key()` to patch in place.* Rejected: preserves
  comments but interacts poorly with quoting rules and can re-order keys
  unpredictably across versions.
- *Write to a temp file and atomic-rename.* Considered for safety. Deferred:
  the `.env` is small and a partial write on crash is recoverable by
  re-running the wizard. Add later if it bites us.

### ADR-3: Dependency Check Sequencing

**Decision.** All 5 checks run unconditionally, in order, and accumulate
into a list of `CheckResult` records. The Rich panel renders the full set
even if early checks fail.

The 5 checks:

| # | Check | Method | Remediation hint on FAIL |
|---|-------|--------|--------------------------|
| 1 | `python3` available | `shutil.which("python3") is not None` | `Install Python 3.x from python.org` |
| 2 | `pip` available | `shutil.which("pip")` or `subprocess.run([sys.executable, "-m", "pip", "--version"])` exit 0 | `Run: python3 -m ensurepip --upgrade` |
| 3 | `playwright` package importable | `importlib.util.find_spec("playwright") is not None` | `Run: pip install playwright==1.44.0` |
| 4 | Chromium installed for Playwright | See ADR-3a below | `Run: playwright install chromium` |
| 5 | `onedrive_rpa/.env` complete | File exists AND `dotenv_values()` contains `ONEDRIVE_USERNAME`, `ONEDRIVE_PASSWORD`, `LOG_LEVEL` (or whatever the RPA's `env.example` declares) AND all non-empty | `Select 'Configurar variables de entorno' below` |

**Rationale.** Failing fast on check 1 would hide the .env problem the user
also has. Showing the full picture lets the user fix everything in one pass.
Checks are cheap (no network) so cost is negligible.

### ADR-3a: Chromium Detection Method

**Decision.** Use:

```
result = subprocess.run(
    [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
    capture_output=True, text=True, timeout=15,
)
chromium_ok = (
    result.returncode == 0
    and "is already installed" in (result.stdout + result.stderr).lower()
)
```

with a string-match fallback because `--dry-run` exit codes have varied
across Playwright versions.

**Rationale.** The alternative — `from playwright.sync_api import
sync_playwright; p.chromium.executable_path` — requires actually starting
Playwright and is slow (~500ms) and noisy. `install --dry-run` is the
documented way to check installation status without mutating anything.

**Rejected alternative.** Checking
`~/Library/Caches/ms-playwright/chromium-*/` directly. Rejected:
platform-dependent path, breaks on Linux/Windows, brittle to Playwright
version bumps.

### ADR-4: Module Routing — Lazy Imports

**Decision.** `novahome/main.py` does NOT do top-level imports of
`novahome.modules.azulito`, `.novahld`, `.aditai`. Imports happen inside the
branch that handles each menu choice:

```
choice = questionary.select(...).ask()
if choice == "azulito":
    from novahome.modules import azulito
    azulito.run()
elif choice == "novahld":
    from novahome.modules import novahld
    novahld.run()
# ...
```

Each module exports exactly one public function: `run() -> None`.

**Rationale.**

- Avoids import-time side effects in modules the user didn't pick. The
  azulito module touches `subprocess`, `dotenv`, and filesystem state on
  import would be a smell.
- Keeps startup snappy — only the banner code runs before the menu paints.
- Makes the contract uniform: every module is a `run()` away. Adding a 4th
  tool means dropping a file and adding one menu line.

**Rejected alternative.** Plugin registry (`MODULES = {"azulito": ...}`).
Overkill for 3 hardcoded entries; revisit if/when we have 6+ modules.

### ADR-5: Rich Layout

**Decision.**

- **Banner** (`ui/banner.py`): a Rich `Panel` containing a styled title
  (the string `NovaHome` rendered with `Text` styling — bold + color — not
  ASCII art), a version line (`v0.1.0`), and a one-line tagline. Rendered
  once per main-loop iteration.
- **Dep check panel** (`ui/checks.py`): a Rich `Table` with 2 columns —
  `Check`, `Status` — wrapped inside a `Panel` titled "Verificación de
  entorno". `Status` column shows `OK` in green, `FAIL` in red followed by
  the remediation hint in dim style on the next line within the same cell.
- **Coming-soon modules**: a single Rich `Panel` with the module name as
  title and a one-line message. After a `questionary.press_any_key()` (or
  short timeout), return to the main menu.
- **Colors**: rely on Rich's default theme — `green` for OK, `red` for
  FAIL, `yellow` for WARNING (reserved; no warning state in this change),
  `dim` for hints.

**Rationale.** ASCII-art banners look broken in 80-column terminals and on
high-DPI fonts. Styled `Text` scales correctly and stays accessible. Table
inside Panel is the idiomatic Rich layout for tabular status — survives
narrow terminals via Rich's auto-wrapping.

**Rejected alternative.** Using Rich `Live` to animate the dep checks in
real time. Rejected: `Live` and `questionary` both grab the terminal and
fight each other (already flagged as a risk in the proposal). The check
loop is fast enough (< 2s) that a static render after-the-fact is fine.

### ADR-6: `requirements.txt` Placement

**Decision.** Create a new repo-root `requirements.txt`:

```
# NovaHome hub
questionary>=2.0,<3.0

# Re-export OneDrive RPA dependencies
-r onedrive_rpa/requirements.txt
```

**Rationale.**

- `-r onedrive_rpa/requirements.txt` keeps the RPA as the single source of
  truth for its own deps. No duplication, no drift.
- Root-level `requirements.txt` means `pip install -r requirements.txt`
  from repo root installs everything for both tools — that's the new
  expected entry point.
- The `onedrive_rpa/requirements.txt` stays untouched, so users who only
  want the RPA can still `cd onedrive_rpa && pip install -r requirements.txt`.

**Rejected alternative.** Inlining all RPA deps into the root file. Rejected:
two files to keep in sync forever.

## 5. Interface Contracts

These signatures define the boundary between modules. Implementation belongs
in `tasks.md` / source files; these are the load-bearing types.

```
# novahome/main.py
def main() -> int: ...
    # Renders banner, runs menu loop. Returns process exit code.
    # KeyboardInterrupt → return 130. Clean exit → return 0.

# novahome/ui/banner.py
def render(console: Console) -> None: ...
    # Prints the banner Panel to the given Console. No return.

# novahome/ui/checks.py
@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    hint: str | None  # None when ok=True

def render(console: Console, results: list[CheckResult]) -> None: ...
    # Renders the 2-column Table-in-Panel for the given results.

# novahome/modules/azulito.py
REPO_ROOT: Path                       # module-level, resolved at import
ENV_PATH: Path                        # REPO_ROOT / "onedrive_rpa" / ".env"
REQUIRED_ENV_KEYS: tuple[str, ...]    # the 3 keys

def run() -> None: ...
    # Entry point called by main.py.

def run_all_checks() -> list[CheckResult]: ...
    # Runs the 5 checks in order, never raises, always returns 5 results.

def env_wizard() -> None: ...
    # Reads ENV_PATH if present, prompts user, rewrites ENV_PATH.
    # Raises on filesystem errors (caller logs and returns to menu).

def launch_rpa() -> int: ...
    # subprocess.run([...], cwd=REPO_ROOT). Returns the RPA's exit code.

# novahome/modules/novahld.py  and  novahome/modules/aditai.py
def run() -> None: ...
    # Render "coming soon" panel, wait for keypress, return.
```

The `run() -> None` shape is the module contract. Any module added later
must conform.

## 6. Error Handling Strategy

| Failure | Where caught | Behavior |
|---------|--------------|----------|
| `KeyboardInterrupt` during menu | `main()` | Print "Cancelado" in dim style, return 130. |
| `KeyboardInterrupt` inside a module's `run()` | the module | Catch, render "Cancelado", return to main menu (do NOT exit the hub). |
| Dep check raises (e.g. subprocess timeout on chromium check) | `run_all_checks()` | Caught per check, converted into `CheckResult(ok=False, hint="check failed: <reason>")`. The 5-result invariant holds. |
| Env wizard write fails (permissions, disk full) | `azulito.run()` | Print red error panel with the OS error message and the target path. Return to menu. |
| RPA subprocess returns non-zero | `azulito.run()` | Print a Rich panel showing the exit code and the RPA's documented meaning (table from `CLAUDE.md`: 1=config, 2=session missing, 3=session expired, 130=user). Return to menu. |
| RPA subprocess raises `FileNotFoundError` (no `python3` on PATH) | `azulito.run()` | Re-run the dep checks panel and instruct the user; this should already have been caught by check #1. |
| Any other unhandled exception in a module | `main()` (outer try/except) | Log to stderr, print red error panel, return to menu (do NOT crash the hub). |

**Principle.** The hub menu is the recovery point for everything except
`KeyboardInterrupt` at the menu itself. The user can always get back to the
menu. The hub never raises out to the shell — `main()` always returns a
clean exit code.

## 7. Cross-Cutting Concerns

- **Logging.** The hub does NOT log to file. Its lifetime is interactive and
  short-lived. The RPA continues to manage its own `logs/` directory via its
  own logger. This avoids two processes contending for the same log path.
- **Internationalization.** Banner, menu, and panel copy are in Spanish to
  match the project's user-facing tone. Code identifiers stay in English.
- **Python version.** The hub targets Python 3.12.8 (project stack). f-string
  syntax, `dataclass(frozen=True, slots=True)`, and PEP 604 union types are
  fair game.
- **Testing surface.** Pure functions (`run_all_checks`, `env_wizard`'s
  read+merge step factored out, exit-code mapping) are unit-testable without
  Rich or questionary. UI renderers are smoke-tested by capturing the Rich
  Console output. The subprocess launch itself is tested by mocking
  `subprocess.run`.

## 8. Open Questions / Assumptions Requiring Validation

1. **`REQUIRED_ENV_KEYS` exact list.** Proposal says "the 3 required vars".
   Confirm against `onedrive_rpa/env.example` during implementation —
   likely `ONEDRIVE_USERNAME`, `ONEDRIVE_PASSWORD`, plus one of
   `LOG_LEVEL` / `HEADLESS` / similar. Tasks phase must read `env.example`
   to lock the names.
2. **Chromium check exit-code stability.** Recorded in ADR-3a as a known
   Playwright-version risk. If `--dry-run` exit codes prove unreliable,
   fall back to the `from playwright.sync_api` probe behind a try/except.
3. **`python3` vs `sys.executable`.** ADR-1 picks `python3`. If the user
   runs in a venv where `python3` resolves to the system Python instead of
   the venv, the RPA would launch outside the venv. Re-evaluate post-MVP.
4. **`questionary` Windows behavior.** Arrow-key menus on cmd.exe are
   known to be flaky. Not a stated requirement, but worth noting.

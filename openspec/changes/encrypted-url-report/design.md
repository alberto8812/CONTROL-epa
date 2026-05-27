# Design: Encrypted URL Column in OneDrive Report

**Change**: encrypted-url-report
**Project**: control-epa
**Status**: design
**Source proposal**: `sdd/encrypted-url-report/proposal`

---

## 1. Architecture Approach

This change is a **vertical slice across two existing layers**, not a new layer. It threads
a single new piece of data (an encrypted URL string) from configuration, through the pure
report-building functions, into the Excel serializer, plus a provisioning step in the launcher.

Two principles govern the design:

1. **Dependency injection over global reads in the hot path.** The crypto primitive (`Fernet`)
   is constructed ONCE at module import in `config.py` and exposed as `config.FERNET: Fernet | None`.
   The pure functions accept it as an injectable parameter (`fernet=None`) that *defaults to*
   `config.FERNET`. This keeps `build_report_rows` deterministic and unit-testable without
   monkeypatching the module global.

2. **Fail-open, never fail-closed.** Encryption is an *enhancement* of the report, not a
   precondition for it. A missing or invalid key MUST degrade to an empty column with a logged
   warning — it MUST NOT raise. The report is the primary artifact; the URL column is additive.

The existing layered separation (CLI → config → reporter → navigation/Playwright) and the
"pure functions are unit-testable, Playwright functions are integration-tested" contract from
the module docstring are preserved exactly. No function changes its layer.

### Layer map

```
config.py            Loads FOLDERS_ENCRYPTION_KEY, constructs FERNET (None on absent/invalid),
                     exposes URL base constants (ONEDRIVE_URL + SHAREPOINT_PERSONAL_PATH).
        │
        ▼  (FERNET injected as default)
rpa/reporter.py
  build_report_rows(folder_names, *, now=None, source_folder="", fernet=None)
        │   computes per-row URL, encrypts when fernet present, else ""
        ▼
  write_excel(rows)  adds "Encrypted URL" header + column; reads row.get("encrypted_url","")
        ▼
  run_report(...)    passes source_folder + config.FERNET through to build_report_rows

novahome/modules/azulito.py
  configure_env()    generates FOLDERS_ENCRYPTION_KEY (Fernet.generate_key) and merges into .env
```

---

## 2. Component & Data Flow

### 2.1 URL assembly (resolves design question 1)

The full URL is built **deterministically from path parts** — we never read it from the live DOM
(per proposal "Out of Scope"). The base is `ONEDRIVE_URL` (`https://archacomco-my.sharepoint.com`)
concatenated with `SHAREPOINT_PERSONAL_PATH` (e.g. `/personal/carlos_velasco_novahold_com`).

**Decision: introduce a single helper `_build_folder_url(source_folder, name)` in reporter.py**
rather than inline f-strings, so the slash-normalization rule lives in one place and is unit-tested.

Construction rule:

```
base     = config.ONEDRIVE_URL.rstrip("/")               # no trailing slash
personal = config.SHAREPOINT_PERSONAL_PATH.strip("/")     # strip both ends
src      = source_folder.strip("/")                        # strip both ends
name     = name.strip("/")
segments = [seg for seg in (personal, "Documents", src, name) if seg]
url      = base + "/" + "/".join(segments)
```

Why `strip("/")` on every segment and filter empties: `SHAREPOINT_PERSONAL_PATH` is documented as
`/personal/...` (leading slash) and an operator may paste it with a trailing slash. `source_folder`
may be `""` (root) or `pruebas/` (trailing slash). Joining stripped, non-empty segments with a single
`/` guarantees **no double slash and no missing segment** regardless of operator input. This directly
answers design question 1: the proposal's raw f-string
`f"{ONEDRIVE_URL}{SHAREPOINT_PERSONAL_PATH}/Documents/{source_folder.rstrip('/')}/{name}"` is
**correct only when the personal path has a leading-but-not-trailing slash and source_folder is
non-empty**; the segment-join helper makes it correct unconditionally and is the chosen approach.

> Note: this is a v1 best-effort canonical URL. It assumes the report's source folder lives directly
> under the personal site's default `Documents` library. URL *correctness against the real tenant*
> is a known risk (see §5) — we mitigate with unit tests on assembly, not live verification.

### 2.2 Encryption (resolves design questions 2 & 3)

`build_report_rows` gains two keyword-only params:

```python
def build_report_rows(
    folder_names: list[str],
    *,
    now: datetime | None = None,
    source_folder: str = "",
    fernet: "Fernet | None" = None,
) -> list[dict[str, Any]]:
```

Per-row logic:

```python
active = fernet if fernet is not None else config.FERNET
...
url = _build_folder_url(source_folder, name)
encrypted_url = active.encrypt(url.encode("utf-8")).decode("ascii") if active else ""
row["encrypted_url"] = encrypted_url
```

- **Injectable default pattern (question 3):** `fernet=None` defaulting to `config.FERNET` at call
  time (not as a default-arg expression — Python binds default args once at def-time, and we want
  tests that patch `config.FERNET` to take effect, plus tests that pass an explicit `Fernet` instance).
  Resolving inside the body is the correct injectable pattern: pass an explicit instance for
  deterministic-decrypt tests, pass `None` + leave `config.FERNET=None` for the empty-column test.
- **Non-determinism (success criterion):** `Fernet.encrypt` generates a random IV per call, so the
  same URL yields different ciphertext each run — this is inherent to Fernet, no extra work needed.
  A unit test asserts `encrypt(url) != encrypt(url)` and that decrypt round-trips both to the same URL.

### 2.3 FERNET construction in config.py (resolves design question 2)

```python
from cryptography.fernet import Fernet

FOLDERS_ENCRYPTION_KEY: str = os.getenv("FOLDERS_ENCRYPTION_KEY", "")

def _build_fernet(key: str) -> "Fernet | None":
    if not key:
        logger.warning("FOLDERS_ENCRYPTION_KEY not set — Encrypted URL column will be empty")
        return None
    try:
        return Fernet(key.encode("ascii"))
    except Exception:  # broad on purpose — see rationale
        logger.warning("FOLDERS_ENCRYPTION_KEY is invalid — Encrypted URL column will be empty")
        return None

FERNET: "Fernet | None" = _build_fernet(FOLDERS_ENCRYPTION_KEY)
```

- **Broad `except Exception` is intentional and correct here.** An invalid Fernet key does NOT raise a
  typed Fernet error during construction — base64 decoding raises `binascii.Error` (a subclass of
  `ValueError`), and a wrong-length key raises `ValueError`. Catching `Exception` and degrading to
  `None` is the only way to honor the fail-open contract for *both* "missing" and "malformed" keys.
  This is a deliberate, narrowly-scoped broad-catch (one constructor call), not a code smell.
- **Logger dependency:** `config.py` currently imports only `os`, `Path`, `dotenv`. We add a
  `from loguru import logger` import. loguru is already a project dependency (used across reporter/
  logger modules) so this introduces no new dependency and matches the existing logging convention.
- The key is validated **at import**, so the warning fires once per process, not once per row.

### 2.4 write_excel backward compatibility (resolves design question 4)

```python
headers = ["Folder Name", "Password", "Encrypted URL", "Creation Date"]
...
ws.append([
    row["folder_name"],
    row["password"],
    row.get("encrypted_url", ""),   # tolerate rows from pre-change callers
    row["creation_date"],
])
```

- **`row.get("encrypted_url", "")` is load-bearing for backward compatibility.** Verified against
  `tests/test_reporter.py::test_write_excel_round_trip`: its fixture rows contain only
  `folder_name`/`password`/`creation_date` (no `encrypted_url`). Using `.get` with a default keeps
  that test green and lets any external/old caller of `write_excel` keep working.
- **Column order is fixed: Folder Name, Password, Encrypted URL, Creation Date** — matches success
  criterion. The existing test asserts header *membership* (`assertIn`) and row *count*
  (`len(data_rows) == 2`), not exact column lists, so inserting the new column mid-table is
  non-breaking. Confirmed by reading the test source.

### 2.5 run_report wiring

`run_report` already computes `subfolders` and the `source_folder` is its own parameter. Single change:

```python
rows = build_report_rows(subfolders, source_folder=source_folder, fernet=config.FERNET)
```

Passing `config.FERNET` explicitly (rather than relying on the body default) makes the data flow
visible at the call site and keeps `run_report` honest about what it injects.

### 2.6 Key provisioning in azulito.configure_env() (resolves design question 5)

The wizard already uses a **read-merge-write** strategy: `dotenv_values(ENV_PATH)` → patch dict →
`ENV_PATH.write_text("".join(f"{k}={v}\n" ...))`. The key-gen step plugs into this without changing
the strategy.

**Placement:** insert AFTER the existing three prompts succeed and BEFORE the final merge/write,
inside `configure_env()`. Logic:

```python
existing_key = existing.get("FOLDERS_ENCRYPTION_KEY") or ""
if existing_key:
    regen = questionary.confirm(
        "Ya existe una clave de cifrado. ¿Generar una NUEVA? "
        "(los reportes anteriores quedarán imposibles de descifrar)",
        default=False,
    ).ask()
    encryption_key = Fernet.generate_key().decode("ascii") if regen else existing_key
else:
    encryption_key = Fernet.generate_key().decode("ascii")
    console.print(Text("Clave de cifrado generada y guardada.", style="green3"))
...
merged["FOLDERS_ENCRYPTION_KEY"] = encryption_key
```

- **No .env corruption (question 5):** `Fernet.generate_key()` returns URL-safe base64 — characters
  `[A-Za-z0-9_-]` plus `=` padding, with **no spaces, no quotes, no `=`-as-separator ambiguity at the
  start**. Written via the existing `f"{k}={v}\n"` line format it parses back cleanly through
  `dotenv_values`. No quoting needed; the existing merge preserves all other keys verbatim.
- **Re-generation guard:** Because a new key makes prior encrypted columns undecryptable (proposal
  out-of-scope: no key rotation), we DEFAULT the "generate new" confirm to `False` when a key exists.
  Idempotent re-runs of the wizard preserve the existing key unless the operator explicitly opts in.
- **`Fernet` import** is done locally inside `configure_env()` (matching the module's existing
  lazy-import style for `questionary`/`dotenv`/`rich`) to keep `azulito` importable without crypto.

### 2.7 REQUIRED_KEYS decision (cross-cutting, in _deps.py)

**`FOLDERS_ENCRYPTION_KEY` is NOT added to `_deps.REQUIRED_KEYS`.** `run_all_checks` marks the `.env`
dependency as failed when any `REQUIRED_KEYS` entry is empty. Adding the encryption key there would
make the `.env` check fail whenever the key is absent — directly contradicting the "graceful no-key
fallback, run succeeds" success criterion. The key is **optional infrastructure**, so it stays out of
the required set. The wizard provisions it proactively, but its absence never blocks a run.

---

## 3. Integration Points

| Integration | Contract | Change |
|-------------|----------|--------|
| `config.FERNET` | `Fernet \| None`, constructed once at import | new symbol |
| `config.ONEDRIVE_URL` + `config.SHAREPOINT_PERSONAL_PATH` | URL base parts | reused (no change) |
| `build_report_rows` ← `run_report` | now passes `source_folder=`, `fernet=` | additive kwargs |
| `write_excel` ← `run_report` | row dict may carry `encrypted_url` | `.get` tolerant |
| `configure_env` → `.env` | merge/patch via `dotenv_values` + line write | one new key |
| `_deps.REQUIRED_KEYS` | env-check gate | deliberately unchanged |
| `requirements.txt` | runtime deps | `cryptography>=42.0.0` added |

---

## 4. ADR-style Decisions

### ADR-EU-1: Fail-open on missing/invalid key (FERNET=None, empty column)
- **Decision:** Treat both absent and malformed `FOLDERS_ENCRYPTION_KEY` as `FERNET=None`; emit an
  empty Encrypted URL column + a single import-time warning; never raise.
- **Rationale:** The report is the primary deliverable. Crypto is additive. Failing the run because an
  optional column can't be filled would regress existing behavior and break the no-key success criterion.
- **Rejected alternative:** Raise/exit on invalid key. Rejected — it conflates an optional enhancement
  with a hard precondition and would make a typo in `.env` brick the whole deletion+report workflow.

### ADR-EU-2: Construct FERNET once at config import, inject as default
- **Decision:** Build `Fernet` once in `config.py`; pure functions take `fernet=None` and resolve to
  `config.FERNET` in the body.
- **Rationale:** One validation point, one warning, no per-row construction cost; explicit injection
  keeps `build_report_rows` deterministic and testable with both a real `Fernet` and `None`.
- **Rejected alternative:** Construct Fernet inside `build_report_rows` from the env key each call.
  Rejected — repeated cost, scattered error handling, harder to test, warning spam per row.

### ADR-EU-3: Broad `except Exception` around Fernet construction
- **Decision:** Wrap the single `Fernet(key)` call in `try/except Exception` → return `None`.
- **Rationale:** Invalid keys surface as `binascii.Error`/`ValueError` (not a typed Fernet exception);
  catching `Exception` is the only way to fail-open for all malformed-key shapes. Scope is one line.
- **Rejected alternative:** Catch specific `(ValueError, binascii.Error)`. Rejected — brittle against
  cryptography-version changes in exception types; the broad catch here is intentional and bounded.

### ADR-EU-4: `write_excel` reads `row.get("encrypted_url", "")`
- **Decision:** Use `.get` with `""` default for the new column; keep `["folder_name"]`/`["password"]`
  as hard keys.
- **Rationale:** Verified `tests/test_reporter.py` fixtures omit `encrypted_url`; `.get` keeps them
  green and tolerates any pre-change caller. Header membership + row-count assertions stay valid.
- **Rejected alternative:** `row["encrypted_url"]`. Rejected — would `KeyError` on existing test
  fixtures and any older caller, breaking the "existing tests pass unchanged" criterion.

### ADR-EU-5: Centralize URL building in `_build_folder_url` with per-segment strip+filter
- **Decision:** Single helper joins `strip("/")`-ed, non-empty segments
  (`personal`, `"Documents"`, `source_folder`, `name`) with `/`.
- **Rationale:** Eliminates double-slash / missing-segment bugs from variable operator input
  (trailing slashes, empty source_folder); one unit-tested place for the rule.
- **Rejected alternative:** Inline f-string per proposal. Rejected — only correct for one exact input
  shape; fragile against trailing slashes and root (empty) source folders.

### ADR-EU-6: Do NOT add FOLDERS_ENCRYPTION_KEY to _deps.REQUIRED_KEYS
- **Decision:** Keep the encryption key out of the env-check required set.
- **Rationale:** The `.env` dependency check fails on any empty required key. Marking the encryption
  key required would block runs without it, contradicting the fail-open design and success criteria.
- **Rejected alternative:** Add it to REQUIRED_KEYS so the wizard "must" set it. Rejected — turns an
  optional feature into a hard gate; the wizard provisions it without making it mandatory.

### ADR-EU-7: Wizard defaults key re-generation to "No" when a key exists
- **Decision:** If `.env` already has a key, the regenerate confirm defaults to `False`.
- **Rationale:** A new key makes prior encrypted columns undecryptable (no rotation in scope). Safe
  default = preserve. Re-running the wizard for other fields must not silently rotate the key.
- **Rejected alternative:** Always regenerate on every `configure_env()` run. Rejected — destroys the
  ability to decrypt previously shared reports without warning.

---

## 5. Risks & Assumptions Requiring Validation

| Risk / Assumption | Severity | Validation / Mitigation |
|-------------------|----------|-------------------------|
| URL canonical form may not match the real tenant (e.g. non-default library, special chars in folder names need URL-encoding) | Med | v1 builds a best-effort path under `/Documents`. Mitigate with assembly unit tests; flag URL-encoding of folder names as a follow-up if operators report broken links. **Open: should names be `urllib.parse.quote`-encoded?** Recommend yes for spaces — decide in tasks. |
| `cryptography` wheel availability on operator machines (esp. older/locked Windows) | Low | Pinned `>=42.0.0`, prebuilt wheels are standard; covered by existing dep-check/install flow if added to `_INSTALL_CMDS` (decide in tasks whether to surface it there). |
| Operator regenerates key and loses ability to decrypt old reports | Med | ADR-EU-7 default-No guard + explicit warning copy in the confirm prompt. |
| `config.py` adding a loguru import at module load | Low | loguru already a transitive project dep; import is safe and matches convention. |
| Decryption tooling is out of scope | Accepted | Proposal explicitly defers the viewer to a separate change; key holder decrypts manually for now. |

**Assumption to confirm with the spec phase:** folder names are used verbatim in the URL path. If
folder names can contain spaces or non-ASCII, the spec should require `urllib.parse.quote` on the
`name` (and `source_folder`) segments before joining.

---

## 6. What this design does NOT do

- No decryption/viewer tooling (out of scope).
- No key rotation, no per-row keys (out of scope).
- No change to Password/Creation Date columns beyond column-order position.
- No live-DOM URL reading — URLs are derived from config + path parts.
- No new application layer — purely additive changes within existing modules.

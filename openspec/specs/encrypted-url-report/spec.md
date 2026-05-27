# Spec: encrypted-url-report

## Capabilities Covered

| Capability | Type |
|---|---|
| report-url-encryption | New |
| env-key-provisioning | New |

---

## Capability: report-url-encryption

### Purpose

`reporter.py` MUST produce an `Encrypted URL` Excel column containing per-row non-deterministic Fernet ciphertext of each subfolder's full OneDrive URL. When no valid key is configured the column MUST be empty and the run MUST NOT fail.

### Requirements

#### Requirement: URL Assembly

The system MUST construct each subfolder URL as:
`{ONEDRIVE_URL}{SHAREPOINT_PERSONAL_PATH}/Documents/{source_folder}/{name}`

where `ONEDRIVE_URL` and `SHAREPOINT_PERSONAL_PATH` are config constants and `source_folder` is passed into `build_report_rows`.

##### Scenario: URL assembled correctly

- GIVEN `ONEDRIVE_URL = "https://archacomco-my.sharepoint.com"`, `SHAREPOINT_PERSONAL_PATH = "/personal/carlos_velasco"`, `source_folder = "clientes"`, and `name = "AlphaClient"`
- WHEN `build_report_rows` is called
- THEN the row's raw URL equals `"https://archacomco-my.sharepoint.com/personal/carlos_velasco/Documents/clientes/AlphaClient"`

##### Scenario: Trailing slash in source_folder is normalised

- GIVEN `source_folder = "clientes/"` (trailing slash present)
- WHEN `build_report_rows` is called
- THEN the assembled URL does NOT contain a double slash (`//`) in the path segment

---

#### Requirement: Non-deterministic Encryption

When a valid Fernet key is available the system MUST encrypt each URL with `Fernet.encrypt()`. The same URL MUST produce different ciphertext on distinct invocations.

##### Scenario: Encrypted URL column populated

- GIVEN a valid `FOLDERS_ENCRYPTION_KEY` is set and a Fernet instance is injected
- WHEN `build_report_rows` is called with `fernet=<Fernet instance>`
- THEN each row dict contains key `"encrypted_url"` with a non-empty bytes or string value

##### Scenario: Non-deterministic output

- GIVEN a valid Fernet instance and a fixed folder name and source_folder
- WHEN `build_report_rows` is called twice with the same inputs
- THEN the two `"encrypted_url"` values are NOT equal to each other

---

#### Requirement: Graceful No-Key Fallback

When `FERNET` is `None` (key absent or invalid) the system MUST set `"encrypted_url"` to an empty string for every row. It MUST NOT raise any exception. It SHOULD log a warning at most once per run.

##### Scenario: No key — column is empty string

- GIVEN `FOLDERS_ENCRYPTION_KEY` is absent from `.env` (so `config.FERNET` is `None`)
- WHEN `build_report_rows` is called with `fernet=None` (default)
- THEN every row's `"encrypted_url"` equals `""`
- AND the function returns normally without raising

##### Scenario: Invalid key — treated identically to absent key

- GIVEN `FOLDERS_ENCRYPTION_KEY` contains a syntactically invalid value
- WHEN `config.py` is imported
- THEN `config.FERNET` is `None`
- AND a warning is logged

---

#### Requirement: Excel Column Order

`write_excel` MUST write columns in the fixed order: **Folder Name | Password | Encrypted URL | Creation Date**.

##### Scenario: Header row correct

- GIVEN any list of rows (with or without encrypted_url populated)
- WHEN `write_excel(rows)` is called
- THEN the workbook's first row reads `["Folder Name", "Password", "Encrypted URL", "Creation Date"]` in that exact order

##### Scenario: Data row populated

- GIVEN rows produced by `build_report_rows` with a valid Fernet instance
- WHEN `write_excel(rows)` is called
- THEN each data row has the encrypted URL value in column 3 (index 2)

---

#### Requirement: Backward-Compatible Signature

`build_report_rows` MUST accept `source_folder: str = ""` and `fernet=None` as keyword-only arguments. Callers that do not pass these arguments MUST continue to work without modification.

##### Scenario: Existing call without new kwargs succeeds

- GIVEN existing tests that call `build_report_rows(folder_names, now=<datetime>)` without `source_folder` or `fernet`
- WHEN those tests execute
- THEN all assertions pass and no `TypeError` is raised

---

#### Requirement: run_report Propagates Context

`run_report` MUST pass `source_folder=source_folder` and `fernet=config.FERNET` to `build_report_rows`.

##### Scenario: Fernet forwarded when key is set

- GIVEN `config.FERNET` is a valid Fernet instance
- WHEN `run_report` executes
- THEN `build_report_rows` receives a non-None `fernet` argument

---

## Capability: env-key-provisioning

### Purpose

The `configure_env()` wizard in `novahome/modules/azulito.py` MUST offer an optional step to generate and persist `FOLDERS_ENCRYPTION_KEY` in `.env`.

### Requirements

#### Requirement: Wizard Key Generation Step

`configure_env()` MUST include an optional step that generates a new Fernet key via `Fernet.generate_key()` and writes it as `FOLDERS_ENCRYPTION_KEY=<key>` to `.env`.

##### Scenario: User opts in — key written

- GIVEN the wizard reaches the key-generation step
- WHEN the user confirms key generation
- THEN `.env` contains a valid `FOLDERS_ENCRYPTION_KEY` entry
- AND the key is decodable as a valid Fernet key without error

##### Scenario: User skips — no key written

- GIVEN the wizard reaches the key-generation step
- WHEN the user declines or skips
- THEN `.env` is NOT modified for `FOLDERS_ENCRYPTION_KEY`
- AND the wizard continues normally

##### Scenario: Key already present — wizard does not overwrite silently

- GIVEN `FOLDERS_ENCRYPTION_KEY` already exists in `.env`
- WHEN the wizard reaches the key-generation step
- THEN the wizard MUST warn the user that a key already exists before overwriting
- AND only overwrite if the user explicitly confirms

---

## Constraints

| Constraint | Value |
|---|---|
| Encryption library | `cryptography>=42.0.0`, `Fernet` only |
| Key source | `.env → FOLDERS_ENCRYPTION_KEY` via `config.py` |
| Column position | Index 2 (zero-based), between Password and Creation Date |
| Crash on missing key | MUST NOT crash — empty string + warning |
| Existing test fixtures | MUST pass unchanged (no key, no source_folder) |
| URL reading | Constructed from config constants — never read from live DOM |

# Proposal: Encrypted URL Column in OneDrive Report

## Intent

The Excel report (`reporter.py`) lists each subfolder with its name, generated password, and creation date. Operators need the full OneDrive URL of each subfolder, but the URL is sensitive and must not appear in plaintext in a shared workbook. Add an **Encrypted URL** column whose ciphertext is non-deterministic (same URL yields different ciphertext per run) so the artifact can be shared while the path stays confidential, decryptable only by the key holder.

## Scope

### In Scope
- New `Encrypted URL` column between `Password` and `Creation Date`.
- Non-deterministic encryption via `cryptography.fernet.Fernet` (AES-128-CBC, random IV per call).
- Key loaded from `.env` as `FOLDERS_ENCRYPTION_KEY`; exposed as `config.FERNET: Fernet | None`.
- URL composed per subfolder from the SharePoint personal path + `source_folder` + name.
- Wizard step in `azulito.py configure_env()` to generate and persist the key.
- Backward compatibility: missing key → empty column + logged warning, no crash.

### Out of Scope
- Decryption tooling / viewer for the encrypted column (separate change).
- Key rotation or per-row distinct keys.
- Changing existing password or date columns.
- Reading the URL from the live DOM (URL is built deterministically from path parts).

## Capabilities

### New Capabilities
- `report-url-encryption`: build per-subfolder OneDrive URLs and emit them as a non-deterministic Fernet-encrypted Excel column, with graceful no-key fallback.
- `env-key-provisioning`: wizard-driven generation and persistence of `FOLDERS_ENCRYPTION_KEY` in `.env`.

### Modified Capabilities
- None (no existing `openspec/specs/` capabilities to amend).

## Approach

Inject an optional `fernet` parameter and a `source_folder` kwarg into `build_report_rows`; when a Fernet is present, compute each URL and store its ciphertext, otherwise store an empty string. `write_excel` gains the new header and column in fixed order. `config.py` loads the key and constructs `FERNET` once (None when unset). `run_report` passes `source_folder` and `config.FERNET` through. The wizard generates a key with `Fernet.generate_key()` and writes it to `.env`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `onedrive_rpa/requirements.txt` | Modified | Add `cryptography>=42.0.0` |
| `onedrive_rpa/config.py` | Modified | Load `FOLDERS_ENCRYPTION_KEY`; expose `FERNET: Fernet \| None` + URL base constants |
| `onedrive_rpa/rpa/reporter.py` | Modified | Extend `build_report_rows`, `write_excel`, `run_report` |
| `novahome/modules/azulito.py` | Modified | Key generation step in `configure_env()` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Missing/invalid key breaks runs | Med | Treat absent/invalid key as `FERNET = None`; empty column + warning, never raise |
| Wrong URL assembly (tenant/user differences) | Med | Derive base from config constants; cover assembly with unit tests |
| Existing tests break on new column | Low | Default `fernet=None`, `source_folder` optional; plaintext fixtures stay valid |
| New dependency footprint | Low | `cryptography` is widely used and pinned with a floor version |

## Rollback Plan

Revert the four files (`requirements.txt`, `config.py`, `reporter.py`, `azulito.py`). The `FOLDERS_ENCRYPTION_KEY` in `.env` is inert once code is reverted. No data migration; previously generated reports are unaffected.

## Dependencies

- `cryptography>=42.0.0` (new pip dependency).
- Existing `.env` management flow in `novahome/modules/azulito.py`.

## Success Criteria

- [ ] Report shows columns in order: Folder Name, Password, Encrypted URL, Creation Date.
- [ ] Same URL encrypts to different ciphertext on repeated runs (non-deterministic).
- [ ] Without `FOLDERS_ENCRYPTION_KEY`, column is empty, a warning is logged, and the run succeeds.
- [ ] Wizard generates and stores a valid `FOLDERS_ENCRYPTION_KEY`.
- [ ] Existing reporter unit tests pass unchanged.

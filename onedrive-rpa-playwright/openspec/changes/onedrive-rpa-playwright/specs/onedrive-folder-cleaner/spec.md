# onedrive-folder-cleaner Specification

## Purpose

Navigate OneDrive for Business folder trees and delete all files recursively within configured target folders. Operates on an authenticated Playwright `Page` instance.

## Requirements

### Requirement: Recursive File Deletion

The system MUST traverse each configured folder depth-first (subcarpetas before files in the current folder) and delete every file found. The system MUST NOT delete the folders themselves — only their contents.

#### Scenario: Single folder with files — happy path

- GIVEN an authenticated page and a folder path "Documentos/Reportes"
- WHEN the cleaner runs against that folder
- THEN every file in "Documentos/Reportes" is deleted
- AND the folder itself remains in OneDrive

#### Scenario: Folder with nested subfolders

- GIVEN a folder "Documentos/Reportes" containing subfolder "Viejos" with files
- WHEN the cleaner runs against "Documentos/Reportes"
- THEN files in "Viejos" are deleted before files in "Documentos/Reportes"
- AND both subfolders remain after the run

### Requirement: Target Folder Not Found

The system MUST detect when a configured folder path does not exist in OneDrive and MUST skip it with a `WARNING` log entry. The run MUST continue with the remaining folders.

#### Scenario: Non-existent folder path

- GIVEN a `folders.json` entry "Documentos/Inexistente"
- WHEN the cleaner attempts to navigate to that path
- THEN the cleaner logs `WARNING: folder not found — Documentos/Inexistente`
- AND processing continues with the next configured folder

### Requirement: Network Error Resilience

The system MUST handle transient network errors (timeouts, connection resets) during navigation or deletion by retrying the failed action up to a configurable number of times. After exhausting retries, the system MUST log the error and continue with the next item.

#### Scenario: Transient timeout on delete action

- GIVEN a file deletion action that times out on first attempt
- WHEN the retry limit has not been reached
- THEN the system retries the deletion
- AND on success, logs the file as deleted

#### Scenario: Retry limit exhausted

- GIVEN a file that fails deletion on every retry attempt
- WHEN the configured retry limit is exceeded
- THEN the system logs `ERROR: could not delete <path> after N retries`
- AND continues with the next file

### Requirement: Dry-Run Mode

When `--dry-run` is active, the system MUST traverse the full folder tree and log each file it would delete, but MUST NOT execute any delete action.

#### Scenario: Dry-run traversal

- GIVEN `--dry-run` is active and a folder contains 3 files
- WHEN the cleaner runs
- THEN 3 `DRY-RUN: would delete <path>` entries appear in the log
- AND no files are removed from OneDrive

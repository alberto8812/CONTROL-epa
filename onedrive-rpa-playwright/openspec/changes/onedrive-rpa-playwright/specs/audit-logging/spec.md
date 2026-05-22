# audit-logging Specification

## Purpose

Provide a structured, tamper-evident log of every action taken by the RPA, supporting post-run audits and incident reconstruction.

## Requirements

### Requirement: Per-File Action Log Entry

The system MUST emit one log line per file action (deleted, skipped, error, dry-run). Each line MUST include: ISO 8601 timestamp, action type, and full OneDrive path of the file.

#### Scenario: File deleted — happy path

- GIVEN a file at "Documentos/Reportes/informe.pdf" is deleted
- WHEN the log entry is written
- THEN the line contains an ISO 8601 timestamp, action `DELETED`, and path `Documentos/Reportes/informe.pdf`

#### Scenario: Dry-run entry

- GIVEN dry-run mode is active and the cleaner would delete a file
- WHEN the log entry is written
- THEN the action field reads `DRY-RUN` instead of `DELETED`

### Requirement: Dual Output (stdout + rotating file)

The system MUST emit logs simultaneously to stdout and to a rotating log file. The log file MUST rotate at a configurable size/interval and MUST retain a configurable number of historical files.

#### Scenario: Log written to both outputs

- GIVEN a deletion action occurs
- WHEN the logger emits the entry
- THEN the same line appears on stdout
- AND is appended to the current log file on disk

### Requirement: Run Summary on Exit

At the end of every run (including dry-run and error-aborted runs), the system MUST print a summary line to stdout and the log file: total files deleted (or would-delete in dry-run), total skipped, total errors, and elapsed time.

#### Scenario: Summary after successful run

- GIVEN a run that deleted 10 files, skipped 0, had 0 errors
- WHEN the run completes
- THEN the summary line reads: `SUMMARY deleted=10 skipped=0 errors=0 elapsed=Xs`

#### Scenario: Summary after aborted run (session expired)

- GIVEN a run aborted due to session expiry after 5 deletions
- WHEN the process exits
- THEN the summary line is still emitted with the partial counts before exit

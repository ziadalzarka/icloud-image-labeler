## ADDED Requirements

### Requirement: Write metadata to Photos.app
The system SHALL write keywords, title, and description back to Photos.app using PhotoScript. OCR text SHALL be stored as an additional keyword with the prefix `ocr:`.

#### Scenario: Write all metadata fields
- **WHEN** labels contain keywords, title, description, and ocr_text
- **THEN** keywords + `ocr:<text>` are written to the photo's keywords, title is written to the photo's title, and description is written to the photo's description

#### Scenario: No OCR text
- **WHEN** labels contain an empty ocr_text
- **THEN** only the keywords list is written (no `ocr:` keyword added)

### Requirement: Ensure Photos.app is running before writing
The system SHALL check if Photos.app is running before attempting to write metadata. If Photos.app is not running, the system SHALL open it automatically.

#### Scenario: Photos.app not running
- **WHEN** a write is attempted and Photos.app is not running
- **THEN** the system opens Photos.app via `open -a Photos` and waits before proceeding

#### Scenario: Photos.app already running
- **WHEN** a write is attempted and Photos.app is already running
- **THEN** the write proceeds immediately

### Requirement: Dry-run mode
The system SHALL support a `--dry-run` / `--no-write` flag that previews the generated metadata without writing to Photos.app. The default behavior is to write (`write=true`).

#### Scenario: Dry-run preview
- **WHEN** the system runs with `write=false`
- **THEN** generated metadata is printed to stdout but not written to Photos.app

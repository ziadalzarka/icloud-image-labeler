## ADDED Requirements

### Requirement: Query unprocessed media from Photos library
The system SHALL query the iCloud Photos library using `osxphotos` and return media items that have no keywords assigned and are not hidden. Results SHALL be sorted by date added (most recent first).

#### Scenario: Find unprocessed photos within date range
- **WHEN** the system queries for unprocessed media with `days=7`
- **THEN** it returns only photos and videos added in the last 7 days that have no keywords and are not hidden, sorted by date added descending

#### Scenario: No unprocessed media found
- **WHEN** the system queries and all media in the date range already has keywords
- **THEN** it returns an empty list

### Requirement: Filter by media type
The system SHALL support filtering results to photos only, videos only, or all media types.

#### Scenario: Filter photos only
- **WHEN** the query is run with `photo=true, video=false`
- **THEN** only photo items (where `isphoto` is true) are returned

#### Scenario: Filter videos only
- **WHEN** the query is run with `photo=false, video=true`
- **THEN** only video items (where `isphoto` is false) are returned

#### Scenario: All media types
- **WHEN** the query is run with `photo=true, video=true`
- **THEN** both photos and videos are returned

### Requirement: Limit result count
The system SHALL return at most `limit` items from the query results.

#### Scenario: Limit applied to results
- **WHEN** there are 50 unprocessed items and `limit=10`
- **THEN** only the 10 most recently added items are returned

### Requirement: Handle iCloud-only media
The system SHALL include media that is not downloaded locally (iCloud-only). When exporting such media, it SHALL use `use_photos_export=True` to trigger download from iCloud via Photos.app.

#### Scenario: Export iCloud-only photo
- **WHEN** a photo has `ismissing=True`
- **THEN** the export uses `use_photos_export=True` with a 120-second timeout

#### Scenario: Export iCloud-only video
- **WHEN** a video has `ismissing=True`
- **THEN** the export uses `use_photos_export=True` with a 300-second timeout

## ADDED Requirements

### Requirement: Parallel processing with thread pool
The system SHALL process media items in parallel using a thread pool with a configurable max thread count (default: 4). Video processing SHALL be limited to 1 concurrent job via a semaphore.

#### Scenario: Parallel photo processing
- **WHEN** 4 photos are queued with `threads=4`
- **THEN** up to 4 photos are processed concurrently

#### Scenario: Video concurrency limit
- **WHEN** 3 videos and 2 photos are queued with `threads=4`
- **THEN** only 1 video processes at a time, while photos fill remaining thread slots

### Requirement: Daemon mode via launchd
The system SHALL support running as a macOS Launch Agent that polls for unprocessed media at a configurable interval (default: 300 seconds). The daemon SHALL auto-start on user login and auto-restart on crash.

#### Scenario: Daemon start
- **WHEN** `daemon start` is executed
- **THEN** a Launch Agent plist is written to `~/Library/LaunchAgents/com.image-labeler.plist` and loaded via `launchctl load`

#### Scenario: Daemon stop
- **WHEN** `daemon stop` is executed
- **THEN** the Launch Agent is unloaded via `launchctl unload` and the plist is removed

#### Scenario: Daemon restart
- **WHEN** `daemon restart` is executed
- **THEN** the Launch Agent is unloaded, the plist is regenerated from current config, and reloaded

#### Scenario: Daemon status
- **WHEN** `daemon status` is executed
- **THEN** the system checks `launchctl list` for `com.image-labeler` and reports whether the daemon is running

#### Scenario: Auto-start on login
- **WHEN** the user logs in and a daemon was previously started
- **THEN** launchd automatically starts the labeler process

### Requirement: Daemon reads all parameters from config
The daemon SHALL read all processing parameters (limit, days, threads, video_frames, photo, video, write, poll_interval) from `~/.image-labeler/config.json`. No CLI flags are passed through the launchd plist.

#### Scenario: Change daemon behavior
- **WHEN** the user runs `config set limit_per_cycle 20` then `daemon restart`
- **THEN** the daemon processes up to 20 items per cycle

### Requirement: Network error retry with delay
The system SHALL retry indefinitely on network errors (LM Studio unreachable, connection timeout, HTTP 5xx) with a 1-2 minute delay between attempts.

#### Scenario: LM Studio temporarily unavailable
- **WHEN** the LLM API returns a connection error
- **THEN** the system waits 1-2 minutes and retries the request

### Requirement: Stop on repeated item failures
The system SHALL track per-item failure counts. After 10 failed attempts for the same item (non-network errors), the system SHALL stop processing entirely and log an error.

#### Scenario: Item fails 10 times
- **WHEN** a specific photo fails JSON parsing 10 times across retries
- **THEN** processing stops and an error is logged with the item details

#### Scenario: Failure count resets on daemon restart
- **WHEN** the daemon is restarted
- **THEN** all per-item failure counts are reset to zero

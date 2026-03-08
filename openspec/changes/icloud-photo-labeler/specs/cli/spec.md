## ADDED Requirements

### Requirement: Run subcommand for one-shot processing
The system SHALL provide a `run` subcommand (default when no subcommand given) that processes a batch of unprocessed media and exits. CLI flags override config values for one-shot runs.

#### Scenario: Run with defaults from config
- **WHEN** `labeler run` is executed with no flags
- **THEN** processing parameters are read from `~/.image-labeler/config.json`

#### Scenario: Run with CLI flag overrides
- **WHEN** `labeler run --limit 5 --days 30` is executed
- **THEN** limit and days are overridden for this run, other parameters come from config

#### Scenario: Run with loop flag
- **WHEN** `labeler run --loop` is executed
- **THEN** the system polls continuously at the configured `poll_interval` instead of exiting after one batch (used by the daemon plist)

### Requirement: CLI flags
The system SHALL support the following CLI flags for the `run` subcommand:

| Flag | Type | Description |
|------|------|-------------|
| `--limit` | int | Number of media items to process |
| `--days` | int | Look back N days for unprocessed media |
| `--photo / --no-photo` | flag | Process photos |
| `--video / --no-video` | flag | Process videos |
| `--write / --no-write` | flag | Write metadata to Photos.app |
| `--dry-run` | flag | Alias for `--no-write` |
| `--base-url` | string | LM Studio API base URL |
| `--model` | string | Model name in LM Studio |
| `--threads` | int | Max parallel processing threads |
| `--video-frames` | int | Number of frames to extract from videos |
| `--loop` | flag | Run continuously at poll interval |

#### Scenario: All flags accepted
- **WHEN** `labeler run --limit 5 --days 14 --no-video --threads 2` is executed
- **THEN** the system processes up to 5 photos from the last 14 days using 2 threads

### Requirement: Config subcommand
The system SHALL provide a `config` subcommand for managing configuration:
- `config show` — display current configuration
- `config set <key> <value>` — update a config value
- `config reset` — reset config to defaults
- `config path` — print the config file path

#### Scenario: Show config
- **WHEN** `labeler config show` is executed
- **THEN** the current config values are printed to stdout

#### Scenario: Set config value
- **WHEN** `labeler config set base_url http://localhost:1234/v1` is executed
- **THEN** the `base_url` field in `~/.image-labeler/config.json` is updated

#### Scenario: Set invalid key
- **WHEN** `labeler config set unknown_key value` is executed
- **THEN** an error is printed listing valid config keys

#### Scenario: Reset config
- **WHEN** `labeler config reset` is executed
- **THEN** `~/.image-labeler/config.json` is overwritten with default values

#### Scenario: Show config path
- **WHEN** `labeler config path` is executed
- **THEN** the absolute path to the config file is printed

### Requirement: Daemon subcommand
The system SHALL provide a `daemon` subcommand with `start`, `stop`, `restart`, and `status` actions.

#### Scenario: Daemon start
- **WHEN** `labeler daemon start` is executed
- **THEN** the Launch Agent plist is created and loaded

#### Scenario: Daemon already running
- **WHEN** `labeler daemon start` is executed while the daemon is already running
- **THEN** an informational message is printed indicating the daemon is already running

#### Scenario: Daemon stop when not running
- **WHEN** `labeler daemon stop` is executed while no daemon is running
- **THEN** an informational message is printed indicating no daemon is running

### Requirement: Config file auto-creation
The system SHALL create `~/.image-labeler/config.json` with default values on first run if it does not exist.

#### Scenario: First run
- **WHEN** any command is executed and `~/.image-labeler/config.json` does not exist
- **THEN** the config file is created with default values and the command proceeds

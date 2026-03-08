## ADDED Requirements

### Requirement: Label photos via local LLM
The system SHALL send photos to a local LM Studio instance (OpenAI-compatible API) and receive structured metadata. Photos SHALL be converted from HEIC to JPEG before sending. The LLM response MUST include: keywords (10-20), title (5-10 words), description (one sentence), and OCR text.

#### Scenario: Successful photo labeling
- **WHEN** a JPEG-encoded photo is sent to the LLM
- **THEN** the system receives and parses a JSON response containing keywords, title, description, and ocr_text fields

#### Scenario: HEIC photo conversion
- **WHEN** a photo is in HEIC format
- **THEN** it is converted to JPEG (quality 85) using Pillow + pillow-heif before sending to the LLM

### Requirement: Resize images to fit LLM context window
The system SHALL resize all images (photos and video frames) so the longest side does not exceed a configurable `max_dimension` (default: 1024px). Aspect ratio MUST be maintained. This prevents LM Studio from running out of context/memory when processing multiple images.

#### Scenario: Large photo resized
- **WHEN** a photo is 4032x3024 pixels and `max_dimension=1024`
- **THEN** it is resized to 1024x768 before encoding and sending to the LLM

#### Scenario: Small photo not resized
- **WHEN** a photo is 800x600 pixels and `max_dimension=1024`
- **THEN** it is sent at its original resolution

#### Scenario: Video frames resized during extraction
- **WHEN** video frames are extracted and the video resolution exceeds `max_dimension`
- **THEN** ffmpeg scales frames down to fit within `max_dimension` while maintaining aspect ratio

### Requirement: Label videos via local LLM with frame extraction
The system SHALL extract frames from videos at equal intervals using ffmpeg and send all frames to the LLM as a multi-image request. The number of frames SHALL be configurable (default: 5).

#### Scenario: Successful video labeling
- **WHEN** a video is processed with `video_frames=10`
- **THEN** 10 frames are extracted at equal intervals, sent together to the LLM, and a JSON response with keywords, title, description, and ocr_text is returned

#### Scenario: Frame extraction failure
- **WHEN** ffmpeg fails to extract a frame at a given timestamp
- **THEN** that frame is skipped and the remaining frames are still sent to the LLM

### Requirement: Strip thinking blocks from LLM responses
The system SHALL remove `<think>...</think>` blocks from LLM responses before parsing JSON, to handle Qwen model thinking mode output.

#### Scenario: Response contains thinking blocks
- **WHEN** the LLM response contains `<think>reasoning here</think>{"keywords": ...}`
- **THEN** the thinking block is stripped and only the JSON portion is parsed

### Requirement: Strip markdown code fences from LLM responses
The system SHALL remove markdown code fences (` ```json ... ``` `) from LLM responses before parsing JSON.

#### Scenario: Response wrapped in code fences
- **WHEN** the LLM response is wrapped in ` ```json\n{...}\n``` `
- **THEN** the code fences are stripped and the JSON is parsed

### Requirement: Retry on JSON parse failure
The system SHALL retry once on JSON parse failure by sending a follow-up message asking for valid JSON only.

#### Scenario: First response is invalid JSON
- **WHEN** the LLM response cannot be parsed as JSON after stripping think blocks and fences
- **THEN** the system sends a follow-up message "Please respond with valid JSON only" and attempts to parse the second response

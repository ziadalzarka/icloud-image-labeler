# Plan: search the library by meaning

**Status:** not started (written 2026-11-20)

## Goal

Add a `search` command that finds photos and videos by what they're about, not by exact words. Searching "kid playing at the beach" should find an item labeled "child" and "seaside", and searching "عيد ميلاد" should find one labeled "birthday". Results go into a Photos album, which syncs to the iPhone through iCloud.

## Why

Photos only matches the words you type. These numbers come from reading the library with osxphotos on 2026-11-20 (read-only):

| | |
|---|---|
| Labeled items | 75,488 |
| Distinct keywords | 148,650 |
| Keywords used only once | 61,491 |

The keywords used only once are mostly correct and specific (`nvidia geforce gtx1650`, `panax ginseng`, people's names), not junk. The gap is word choice:

| Search | Items with a related keyword | Of those, items with the search word nowhere in keywords, title or description |
|---|---|---|
| `dog` | 399 tagged `puppy` | 31 |
| `beach` | 782 tagged `shore`, `seaside`, `coast`, `coastline` or `shoreline` | 128 |
| `kid` | 1,944 tagged `child`, `children`, `toddler`, `boy` or `girl` | 1,590 |

Merging synonym keywords is not the fix. The 128 "beach" misses I looked at really aren't beaches ("Driving along the coast at twilight"), and one `puppy` is a kitten.

The library mixes Arabic and English: about 16k items are tagged `arabic text`, and many transcripts are Arabic. Photos' word search can't match across languages. A multilingual embedding model can.

## How it works

```
Indexing (once for the existing items, then after every daemon cycle):

  osxphotos ──> title + description + keywords + OCR + transcript
                    │
                    ├── text unchanged since last index? ──> skip
                    │
                    └──> /v1/embeddings ──> vector ──> ~/.image-labeler/search.db

Searching:

  "kid playing at the beach" ──> /v1/embeddings ──> vector
                                                      │
                     compare with every stored vector (numpy, milliseconds)
                                                      │
                                            top N item UUIDs
                                                      │
                          PhotoScript ──> album "Search: kid playing at the beach"
```

No vector database is needed. 75k vectors of 1,024 numbers is about 300 MB as float32 or 150 MB as float16, and comparing a query against all of them takes milliseconds.

## Steps

### 1. Pick the embedding model and endpoint

- Check whether the current server (`http://127.0.0.1:8317/v1`) serves `/v1/embeddings`. If not, run an embedding model in LM Studio.
- Candidates, all multilingual with good Arabic: `bge-m3` (1,024 dims, 8k token context), `Qwen3-Embedding-0.6B` (1,024 dims, wants an instruction prefix on queries), `multilingual-e5-large`.
- Build a small test set from the library: about 30 queries (English, Arabic, mixed; objects, events, things said in videos, text in screenshots), each with the items that should come back. Compare models on how many expected items are in the top 20, with Photos' word search as the baseline.

### 2. Config

Add to `DEFAULTS` in `labeler/config.py`:

| Key | Default | Meaning |
|---|---|---|
| `embedding_base_url` | `""` | Embeddings endpoint; empty turns search and indexing off |
| `embedding_model` | `""` | Model id |
| `embedding_api_key` | `""` | Optional |

### 3. Index (`labeler/search.py`)

- Table in `~/.image-labeler/search.db` (separate from `metrics.db` so the stats dashboard isn't affected):
  `item_vectors(uuid TEXT PRIMARY KEY, text_hash TEXT, model TEXT, vector BLOB, updated_at TEXT)`
- Text per item: title, description, descriptive keywords (without `m:` and `v:`), the `ocr:` text and the `trans:` text (not `trans:no-speech` / `trans:no-audio`). Cap the length to the model's context.
- Re-embed an item only when its text hash or the model changed. This also picks up relabels, added transcripts and edits made by hand in Photos.
- Remove rows whose UUID is no longer in the library.
- Send texts in batches. Measure speed on the first 1,000 items before running all 75k.
- Add `numpy` to `dependencies` in `pyproject.toml`. It's installed today only because another package depends on it.

### 4. Commands (`labeler/cli.py`)

- `icloud-image-labeler index`: update the index. The first run embeds all existing items.
- `icloud-image-labeler search "<query>" [--limit 50] [--no-album]`: print the top matches (title, date, score). By default it also replaces the album `Search: <query>` inside a `Labeler Search` folder (`create_folder` / `create_album` in photoscript). Album writes go through `_write_lock` like the other PhotoScript writes.

### 5. Daemon

- After each cycle in `_label_loop`, update the index if `embedding_base_url` is set. Do it even when the cycle found nothing to label (`_process_one_cycle` returns early then), so edits made by hand are picked up.
- An embeddings failure is logged and doesn't fail the cycle.

### 6. Docs and release

- README: a "Search" section with setup and examples. CLAUDE.md: the index constraints.
- Release, then update the daemon through Homebrew. The daemon only runs released versions.

## Open questions

- Does the current server serve embeddings, or does LM Studio need to run next to it?
- Album only, or also a search page in the stats dashboard (Datasette is already a dependency)?
- One vector per item, or separate vectors for the visual labels and the transcript? Start with one and check the test set.

## Later, if the test set shows misses

- **Exact terms:** embeddings are weak on names, product codes and numbers (`gtx1650`). Add SQLite FTS5 word search next to the vectors and combine the two rankings (reciprocal rank fusion).
- **Things the labels never mention:** text search only finds what the model wrote. Image embeddings (CLIP or SigLIP) would search the pixels, but every item would have to be exported again, and videos need frames.

## Not doing

- Merging synonym keywords in Photos (see the "beach" and "puppy" numbers above).
- Skipping near-duplicate photos to save LLM calls. The library is already labeled, so only new photos would benefit.

---
name: douyin-to-obsidian
description: "For Douyin links: extract, summarize, save to Obsidian."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Douyin, Obsidian, Transcription, Media]
    related_skills: [obsidian-note-series, youtube-content]
---

# Douyin → Obsidian Note Extractor

Turns a Douyin (抖音) share link into a structured Obsidian note.

## When to Use

Load this skill when the user:
- Shares a Douyin/TikTok video link (`v.douyin.com`, `www.douyin.com`, `iesdouyin.com`)
- Asks to extract content from a Douyin post
- Wants a Douyin video summarized as a note
- Asks for "抖音转笔记" or similar

## Architecture

```
User: douyin link
  │
  ├─ SSR Resolver (requests + HTML parse) → extract meta + desc + media URLs
  │
  └─ Content Decision Model (agent judges based on SSR data)
       │
       ├─ Video post (has playable audio)
       │   → 音频内容 为主（Whisper 转写）
       │   → desc 文案 为辅助（标题/描述）
       │
       ├─ Live photo (has images + short video clip)
       │   → 音频内容 + desc 文案 结合
       │
       └─ Image / Multi-image post (no audio)
            → 查看图片内容（agent inspects images）
               ├─ 图片带文字（知识截图/海报/语录）
               │   → OCR 提取图片文字 为主
               │   → desc 文案 为辅助
               ├─ 图片无文字（风景/人像/纯视觉）
               │   → desc 文案 为主要内容
               └─ 混合
                   → 两者结合
```

## Content Decision Model

The agent determines which content source to use based on the SSR metadata:

| SSR `content_type` | Has `image_urls` | Has audio | Agent decision |
|-------------------|------------------|-----------|----------------|
| `video` | — | ✅ | Run Whisper for **audio content**; desc is title only |
| `image` | ✅ (has images) | ❌ | **Inspect images**: if they contain text (screenshots, posters, quotes, knowledge cards) → **OCR all images** for full content; if purely visual (scenery, portraits) → desc only |
| `image` | ❌ (no images) | ❌ | Use **desc** only (rare — pure text post) |
| `live_photo` | ✅ | ✅ | Run Whisper for **audio** + desc for **text**; combine both |

**How the agent inspects images**: After SSR extraction, the agent has access to `image_urls[]` from `meta.json`. The agent can:
- Download the first image and use `vision_analyze` (if available) to check for text content
- Or use OCR (easyocr) to extract text from all images

**BGM (background music) handling**: If the video has background music with vocals, Whisper may transcribe the song lyrics instead of or mixed with the voiceover. The agent should:
1. Check if the transcription contains repeated phrases that look like song lyrics (choruses)
2. If suspected, warn the user: "转录可能包含背景音乐歌词，请核对"
3. Audio source separation (demucs) is a planned future enhancement

**OCR fallback (for image text)**: `pip install easyocr` — cross-platform, good Chinese OCR. Run on downloaded images when text content is detected.

## Security Model (for open source)

- **Zero credentials**: No API keys, tokens, cookies, or login required. Douyin share pages inject public SSR data — the script reads what the browser already sends to any visitor.
- **Local Whisper**: `faster-whisper` runs entirely on-device. No audio/text leaves the machine.
- **Temp file cleanup**: Downloaded video and extracted audio are deleted after transcription.
- **No hardcoded paths**: All output paths are configurable or auto-generated.
- **No data exfiltration**: The script is read-only on the network (fetches public data) and write-only locally (saves to user-specified output).
- **URL validation**: Input is validated as a douyin.com link before any processing.

## Dependencies (install once)

```bash
# Core Python packages (cross-platform, all from PyPI)
pip install requests yt-dlp faster-whisper zhconv

# ffmpeg is required for audio extraction from video
# Option A: system install
#   macOS: brew install ffmpeg
#   Ubuntu/Debian: sudo apt install ffmpeg
#   Windows: winget install ffmpeg  or  choco install ffmpeg
# Option B: Python fallback (auto-detected by script)
pip install imageio-ffmpeg

# Playwright (optional) — browser fallback when SSR/yt-dlp are blocked
pip install playwright   # uses system Chrome, no browser download
```

Verify: `python3 -c "import requests, yt_dlp, faster_whisper, zhconv; print('All deps OK')"`

**Network notes**:
- **China users**: Set `HF_ENDPOINT=https://hf-mirror.com` before running (Whisper model downloads are blocked otherwise).
- **Hermes users**: Prefix commands with `env -u PYTHONPATH` if using Python 3.9 (Hermes injects PYTHONPATH which conflicts with older Python versions).

## Workflow

### Step 1: Extract content

Run the extraction script (SKILL_DIR = dir containing this SKILL.md):

```bash
python3 SKILL_DIR/scripts/douyin_extract.py "https://v.douyin.com/xxxxx/" --output /tmp/douyin_extract
```

Output structure:
```
/tmp/douyin_extract/
├── {aweme_id}_{title}/
│   ├── meta.json               # Title, author, aweme_id, content_type
│   ├── transcript.txt          # Transcribed text or desc text
│   └── transcript_segments.json  # Timestamped segments (video only)
```

### Step 2: Content decision — determine what to extract

Read `meta.json` and apply the **Content Decision Model**:

| SSR `content_type` | Has `image_urls` | Has audio | What the agent does |
|-------------------|------------------|-----------|---------------------|
| `video` | — | ✅ | `transcript.txt` has **audio transcription** → use as primary content |
| `image` | ✅ | ❌ | Download first image, inspect for text. If text present → OCR all images. If purely visual → use `transcript.txt` (desc) only |
| `image` | ❌ | ❌ | Use `transcript.txt` (desc) only |
| `live_photo` | ✅ | ✅ | Combine **audio transcription** + **desc text** |

**How to inspect images**: Download the first image URL from `meta.json`'s `image_urls[]` array. Use `vision_analyze` (if your agent has it) or `easyocr` to check if the image contains text (screenshots, posters, quotes, knowledge cards). If yes → OCR all images; if no → scenery/visual → use desc only.

**Long image posts (知识卡片/多图连载)**: Some image posts contain text spread across multiple images (e.g., a 10-slide knowledge deck). The SSR desc only captures the title. For these:
1. Download all images from `image_urls[]`
2. OCR each image to extract text
3. Combine all OCR results into a single transcript, noting which text came from which image
4. The agent then summarizes the combined content into a structured note

### Step 3: Check for duplicates & ambiguous corrections

**Duplicate detection**: Before writing a new note, search the existing `douyinobsidian/` directory for similar content. If a note with similar text already exists, warn the user and ask: skip / merge / create new.

**Ambiguous corrections**: The script may flag ambiguous corrections in `meta.json`'s `ambiguous_corrections` field. When present, show these to the user for manual review before finalizing the note.

### Step 4: Summarize & format

**Short content** (< 100 chars): keep as a quote/insight note.  
**Long content** (100+ chars): summarize with sections, extract key points.

**Note format rules (hard requirements):**

```
# {主题词} · 抖音笔记

> {一句话概括核心观点}

---

## 核心内容

**{核心命题}**

- {提炼要点1}
- {提炼要点2}
- {提炼要点3}

---

## 金句

> "{视频原话金句}"

---

## 下一条线索

[[相关笔记]]
```

**Format rules**:
- No "来源" line (no author, no link, no source metadata)
- No "AI" or "generated" in the note body
- Use `·` (middle dot) in titles
- `---` to separate sections
- Keep it concise — the note is a digest, not a transcript

**Theme grouping**: Extract the primary hashtag from the video's title (e.g., #焦虑, #成长) to determine the subdirectory name. Notes are stored as:

```
douyinobsidian/
├── {主题目录1}/
│   ├── 笔记A.md
│   └── 笔记B.md
├── {主题目录2}/
│   └── 笔记C.md
└── ...
```

The vault folder `douyinobsidian/` serves as the root collection. Each themed subdirectory groups related notes. The note's primary tag (first meaningful hashtag from the video title) determines the subdirectory name. If no relevant hashtag exists, use `未分类/`.

### Step 5: Write to vault

Write the note to the user's Obsidian vault following their existing structure.

## Browser Fallback (when SSR / yt-dlp fail)

When SSR parsing **and** yt-dlp both fail (Douyin anti-scraping, common on short links
that redirect and refuse to inject `_ROUTER_DATA`), fall back to a real browser.

**Root cause**: plain `curl`, SSR, and headless `--dump-dom` all get blocked by Douyin
(either no SSR data, or the page stuck at "视频数据加载中"). Only a browser that
executes JS and passes anti-bot can read the dynamic content.

### Cross-agent solution: Playwright + system Chrome

`scripts/douyin_browser_fallback.py` is a cross-agent, cross-platform script that works
identically for Hermes / Codex / OpenCode / Claude Code. It uses Playwright to drive the
locally-installed Google Chrome (channel="chrome", **no browser download needed**) to:

1. Open the share link (follows redirect)
2. Wait for JS to render the dynamic page
3. Extract `章节要点` (Douyin's AI chapter summary), title, and aweme_id

The `章节要点` is Douyin's AI auto-summary — **not** the full oral transcript — but it
captures the core content reliably even when download is blocked.

### Usage

```bash
pip install playwright   # cross-agent, cross-platform

# Browser fallback extraction
python3 scripts/douyin_browser_fallback.py "https://v.douyin.com/xxxxx/" --output /tmp/out

# As JSON
python3 scripts/douyin_browser_fallback.py "https://v.douyin.com/xxxxx/" --output /tmp/out --json
```

Requires Google Chrome (or Chromium) installed on the machine. Output:
`browser_{aweme_id}/chapter_summary.txt` + `meta.json`.

### Workflow when main script fails

1. Run `scripts/douyin_extract.py <url>` → if "No SSR data found", proceed.
2. Try `yt-dlp --write-auto-sub --skip-download <url>` → if it also fails (cookies needed), proceed.
3. Run `scripts/douyin_browser_fallback.py <url>`.
4. Use the `章节要点` as the content source; **note to the user** that this is a summary,
   not the full transcript (anti-scraping blocked direct download).
5. Summarize into the Obsidian note as usual.

## Error Handling

| Error | Likely Cause | Action |
|-------|-------------|--------|
| SSR data not found | Invalid link or douyin anti-scraping | Try yt-dlp; if that fails, use `scripts/douyin_browser_fallback.py` (Playwright + Chrome) |
| Video download failed | CDN timeout or expired | Retry with a fresh link |
| ffmpeg not found | ffmpeg not installed | Install ffmpeg or `pip install imageio-ffmpeg` |
| Whisper model download failed | Network blocked (China) | Set `HF_ENDPOINT=https://hf-mirror.com` before running |
| Empty transcript | Silent video, no speech | Check if the video has spoken content |
| Low transcription accuracy | Small model or poor audio quality | Retry with `--model large-v3` for best Chinese accuracy |
| OCR fails / no text found | Image has no readable text, or easyocr not installed | Fall back to `transcript.txt` (desc text) only |
| easyocr model download failed | Network blocked (China) | Set `HF_ENDPOINT=https://hf-mirror.com` or use `vision_analyze` instead |
| Transcription contains song lyrics | Video has background music (BGM) with vocals | Whisper may transcribe BGM lyrics instead of/near voiceover. Check `meta.json` for `bgm_detected` flag. Audio source separation (demucs) is a future enhancement. |
| Duplicate content detected | Similar note already exists in vault | Agent will warn and ask user whether to skip, merge, or create a new note. |

## Script Reference

The `scripts/douyin_extract.py` script is a standalone CLI tool that:
- Accepts a douyin URL as argument or stdin
- Uses SSR parsing to resolve the video/audio without login
- Falls back to yt-dlp if SSR download fails
- Transcribes with local faster-whisper
- Cleans up temp files
- Outputs structured JSON + plaintext transcript
- Cross-platform: Windows, macOS, Linux
- Zero API keys, zero credentials

**Recommended usage for best accuracy**: `--model large-v3` (slower first run due to ~3GB model download, but significantly better Chinese transcription).

**Auto-model selection**: Default `--model auto` picks the model based on audio duration:
- `< 30s` → `small` (fast, ~1GB model)
- `30s–2min` → `medium` (balanced, ~3GB)
- `> 2min` → `large-v3` (most accurate, ~3GB)
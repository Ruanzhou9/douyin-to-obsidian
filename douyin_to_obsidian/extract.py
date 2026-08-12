#!/usr/bin/env python3
"""
Douyin (抖音) video/text content extractor.

Extracts content from a Douyin share link:
  - Image/text posts: extracts the description text directly from the share page SSR data (no download).
  - Video posts: downloads the video, extracts audio, transcribes with Whisper.

Usage:
  python douyin_extract.py "https://v.douyin.com/xxxxx/" --output ./output_dir

Security: No API keys, no credentials, local Whisper, temp file cleanup.
Cross-platform: Windows / macOS / Linux.

# ════ 函数导航 ════
# 40  _load_corrections          — 加载错字修正 JSON
# 79  apply_corrections          — 应用错字修正
# 89  get_ambiguous_matches      — 获取含糊修正标记
# 105 class DouyinMeta           — 元数据容器
# 116 class ExtractResult        — 提取结果容器
# 145 _session                   — 创建 requests session
# 155 expand_share_url           — 展开短链
# 166 normalize_to_share_page    — 标准化到分享页
# 177 extract_aweme_id           — 提取作品 ID
# 194 _parse_router_data         — 解析 SSR router data
# 205 _parse_render_data         — 解析 SSR render data
# 215 _find_item_list            — 查找 item 列表
# 234 _build_no_watermark_url    — 构建无水印播放 URL
# 244 _extract_image_urls        — 提取图片 URL 列表
# 259 _has_playable_video        — 判断是否有可播放视频
# 267 _meta_from_item            — 从 item 构建 DouyinMeta
# 313 resolve_ssr               — SSR 解析主入口
# 351 _find_ffmpeg               — 查找 ffmpeg 路径
# 365 extract_audio              — 提取视频音频
# 393 to_simplified_chinese      — 繁体转简体
# 399 transcribe                — Whisper 语音转文字
# 436 download_video_ytdlp       — 下载视频
# 465 process                   — 核心处理流程
# 611 _browser_fallback_patch    — 浏览器兜底
# 647 main                      — CLI 入口
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

# ---------------------------------------------------------------------------
# Text correction: fixes common Whisper misrecognitions
# ---------------------------------------------------------------------------

_CORRECTIONS: dict[str, str] | None = None
_AMBIGUOUS: dict[str, str] | None = None


def _load_corrections(corrections_path: str | Path | None = None) -> dict[str, str]:
    """Load correction rules from JSON file. Returns flat {wrong: correct} dict."""
    global _CORRECTIONS, _AMBIGUOUS
    if _CORRECTIONS is not None:
        return _CORRECTIONS

    paths_to_try = []
    if corrections_path:
        paths_to_try.append(Path(corrections_path))
    # Default: look next to this script
    paths_to_try.append(Path(__file__).resolve().parent / "text_corrections.json")

    for path in paths_to_try:
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                flat: dict[str, str] = {}
                ambiguous: dict[str, str] = {}
                for _section, rules in raw.items():
                    if isinstance(rules, dict):
                        for wrong, correct in rules.items():
                            if wrong.startswith("_"):
                                continue  # skip comments/hints
                            if _section == "_ambiguous":
                                # Store ambiguous corrections separately
                                ambiguous[wrong] = correct
                            else:
                                flat[wrong] = correct
                _CORRECTIONS = flat
                _AMBIGUOUS = ambiguous
                return flat
            except (json.JSONDecodeError, KeyError):
                pass

    _CORRECTIONS = {}
    _AMBIGUOUS = {}
    return _CORRECTIONS


def apply_corrections(text: str, corrections_path: str | Path | None = None) -> str:
    """Apply text correction rules to fix common Whisper misrecognitions."""
    rules = _load_corrections(corrections_path)
    if not rules:
        return text
    for wrong, correct in sorted(rules.items(), key=lambda x: -len(x[0])):
        text = text.replace(wrong, correct)
    return text


def get_ambiguous_matches(text: str, corrections_path: str | Path | None = None) -> list[dict]:
    """Find ambiguous corrections that matched the text, for user review."""
    _load_corrections(corrections_path)
    if not _AMBIGUOUS:
        return []
    matches = []
    for wrong, correct in sorted(_AMBIGUOUS.items(), key=lambda x: -len(x[0])):
        if wrong in text:
            matches.append({"matched": wrong, "suggestions": correct, "position": text.index(wrong)})
    return matches

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class DouyinMeta:
    aweme_id: str
    title: str
    author: str
    source_url: str
    content_type: Literal["video", "image"]  # "video" has speech, "image" is text-only
    download_url: str = ""
    image_urls: list[str] = field(default_factory=list)


@dataclass
class ExtractResult:
    meta: DouyinMeta
    text: str               # Transcribed text (video) or desc text (image)
    segments: list[dict]    # Timestamped segments (empty for image)
    out_dir: Path


# ---------------------------------------------------------------------------
# SSR Resolver (no API key, no login needed)
# ---------------------------------------------------------------------------

SHARE_PAGE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)

ROUTER_DATA_RE = re.compile(
    r"window\._ROUTER_DATA\s*=\s*(\{.+)", re.DOTALL
)
RENDER_DATA_RE = re.compile(
    r'<script id="RENDER_DATA" type="application/json">([^<]+)</script>'
)
IMAGE_AWEME_TYPES = {2, 68}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    import requests
    s = requests.Session()
    s.headers.update({
        "User-Agent": SHARE_PAGE_UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return s


def expand_share_url(text: str) -> str:
    """Extract the first douyin URL from share text."""
    m = re.search(
        r"https?://(?:v\.douyin\.com|www\.douyin\.com|www\.iesdouyin\.com|m\.douyin\.com)[^\s\]]*",
        text,
    )
    if not m:
        raise ValueError("No douyin URL found in input")
    return m.group(0).rstrip("/.,;)")


def normalize_to_share_page(url: str) -> str:
    """Convert www.douyin.com pages to iesdouyin share pages (which contain SSR data)."""
    note = re.search(r"https?://(?:www\.)?douyin\.com/note/(\d+)", url)
    if note:
        return f"https://www.iesdouyin.com/share/note/{note.group(1)}/"
    video = re.search(r"https?://(?:www\.)?douyin\.com/video/(\d+)", url)
    if video:
        return f"https://www.iesdouyin.com/share/video/{video.group(1)}/"
    return url  # Already a share page


def extract_aweme_id(page_url: str, html: str | None = None) -> str:
    patterns = [
        r"/video/(\d+)", r"/note/(\d+)", r"/share/video/(\d+)", r"/share/note/(\d+)",
        r"modal_id=(\d+)", r"item_ids=(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, page_url)
        if m:
            return m.group(1)
    if html:
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                return m.group(1)
    raise ValueError("Cannot extract aweme_id from page")


def _parse_router_data(html: str) -> dict | None:
    m = ROUTER_DATA_RE.search(html)
    if not m:
        return None
    raw = m.group(1).split("</script>")[0].rstrip().rstrip(";")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _parse_render_data(html: str) -> dict | None:
    m = RENDER_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(unquote(m.group(1)))
    except json.JSONDecodeError:
        return None


def _find_item_list(obj: Any) -> list[dict]:
    """Navigate nested JSON to find item_list[0]."""
    if isinstance(obj, dict):
        if "item_list" in obj and isinstance(obj["item_list"], list) and obj["item_list"]:
            first = obj["item_list"][0]
            if isinstance(first, dict) and ("aweme_id" in first or "video" in first or "images" in first):
                return obj["item_list"]
        for v in obj.values():
            found = _find_item_list(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_item_list(item)
            if found:
                return found
    return []


def _build_no_watermark_url(play_addr: dict) -> str:
    uri = play_addr.get("uri") or ""
    url_list = play_addr.get("url_list") or []
    if uri:
        return f"https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio=720p&line=0"
    if url_list:
        return str(url_list[0]).replace("playwm", "play")
    raise ValueError("No playable video URL found")


def _extract_image_urls(item: dict) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for img in item.get("images") or []:
        if isinstance(img, dict):
            for key in ("url_list", "download_url_list"):
                ul = img.get(key) or []
                if ul:
                    u = str(ul[-1])
                    if u not in seen:
                        seen.add(u)
                        urls.append(u)
    return urls


def _has_playable_video(item: dict) -> bool:
    video = item.get("video") or {}
    if not isinstance(video, dict):
        return False
    play_addr = video.get("play_addr") or video.get("playAddr") or {}
    return bool(play_addr.get("uri") or play_addr.get("url_list"))


def _meta_from_item(item: dict, source_url: str) -> DouyinMeta:
    aweme_id = str(item.get("aweme_id") or item.get("awemeId") or "")
    desc = (item.get("desc") or item.get("caption") or "").strip() or f"douyin_{aweme_id}"

    author = ""
    author_info = item.get("author") or {}
    if isinstance(author_info, dict):
        author = author_info.get("nickname") or author_info.get("unique_id") or ""

    # Check if image post (pure image, no video/audio)
    aweme_type = item.get("aweme_type")
    image_urls = _extract_image_urls(item)
    has_video = _has_playable_video(item)

    # Live photo: aweme_type 2/68 but also has a video clip with audio
    # Treat as video if it has playable content (to capture audio for transcription)
    is_live_photo = aweme_type in IMAGE_AWEME_TYPES and has_video and bool(image_urls)
    is_pure_image = (aweme_type in IMAGE_AWEME_TYPES and not has_video) or (bool(image_urls) and not has_video)

    if is_pure_image:
        return DouyinMeta(
            aweme_id=aweme_id,
            title=desc,
            author=author,
            source_url=source_url,
            content_type="image",
            download_url="",
            image_urls=image_urls,
        )

    # Video post
    video = item.get("video") or {}
    play_addr = video.get("play_addr") or video.get("playAddr") or {}
    download_url = _build_no_watermark_url(play_addr)

    return DouyinMeta(
        aweme_id=aweme_id,
        title=desc,
        author=author,
        source_url=source_url,
        content_type="video",
        download_url=download_url,
        image_urls=[],
    )


def resolve_ssr(share_text: str) -> DouyinMeta:
    """
    Resolve Douyin share link via SSR (Server-Side Rendered) data.
    No login, no API key — just reads public data from the share page.
    """
    import requests

    sess = _session()
    share_url = expand_share_url(share_text)
    fetch_url = normalize_to_share_page(share_url)

    # Follow redirect to final share page
    resp = sess.get(fetch_url, allow_redirects=True, timeout=30)
    resp.raise_for_status()
    page_url = str(resp.url)
    html = resp.text

    # Try parsing SSR data
    for parser in (_parse_router_data, _parse_render_data):
        payload = parser(html)
        if payload:
            items = _find_item_list(payload)
            if items:
                meta = _meta_from_item(items[0], share_url)
                if not meta.aweme_id:
                    meta.aweme_id = extract_aweme_id(page_url, html)
                return meta

    raise ValueError(
        "No SSR data found in douyin share page. "
        "The link may be invalid or douyin changed their page structure."
    )


# ---------------------------------------------------------------------------
# Audio extraction (cross-platform via ffmpeg)
# ---------------------------------------------------------------------------

def _find_ffmpeg() -> str | None:
    """Find ffmpeg on the system (cross-platform)."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    # Fallback: imageio-ffmpeg bundles its own binary
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError, FileNotFoundError):
        pass
    return None


def extract_audio(video_path: Path, audio_path: Path) -> Path:
    """Extract 16kHz mono WAV audio from video using ffmpeg."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found. Install it first:\n"
            "  macOS: brew install ffmpeg\n"
            "  Ubuntu: sudo apt install ffmpeg\n"
            "  Windows: winget install ffmpeg"
        )

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        str(audio_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {proc.stderr}")
    return audio_path


# ---------------------------------------------------------------------------
# Transcription (local Whisper, no API)
# ---------------------------------------------------------------------------

def to_simplified_chinese(text: str) -> str:
    """Convert traditional Chinese to simplified (Whisper often outputs traditional)."""
    import zhconv
    return zhconv.convert(text, "zh-cn")


def transcribe(audio_path: Path, model_size: str = "small") -> tuple[str, list[dict]]:
    """
    Transcribe audio using local faster-whisper.
    First run downloads the model (~1-5GB depending on model size).
    """
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="auto", compute_type="default")
    # language=None => auto-detect. Handles Chinese, English, Japanese, Korean, etc.
    # (Hardcoding "zh" would force non-Chinese audio through Chinese recognition -> garbled.)
    segments_iter, _info = model.transcribe(
        str(audio_path),
        language=None,
        vad_filter=True,
        beam_size=5,
    )

    lines: list[str] = []
    records: list[dict] = []
    for seg in segments_iter:
        text = to_simplified_chinese(seg.text.strip())
        if not text:
            continue
        lines.append(text)
        records.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": text,
        })

    full_text = to_simplified_chinese("\n".join(lines))
    full_text = apply_corrections(full_text)
    return full_text, records


# ---------------------------------------------------------------------------
# Video download via yt-dlp (fallback method)
# ---------------------------------------------------------------------------

def download_video_ytdlp(url: str, out_dir: Path) -> Path:
    """
    Download douyin video using yt-dlp.
    Returns path to the downloaded video file.
    """
    import yt_dlp

    ydl_opts = {
        "outtmpl": str(out_dir / "video.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_path = out_dir / f"video.{info.get('ext', 'mp4')}"
        if not video_path.exists():
            # yt-dlp may use a different extension
            for f in out_dir.glob("video.*"):
                video_path = f
                break
        return video_path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process(share_text: str, output_dir: Path, model_size: str = "auto") -> ExtractResult:
    """
    Full pipeline:
    1. Resolve SSR data → get meta + download URL
    2. Image post: extract desc text directly
    3. Video post: download audio → transcribe → cleanup
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Resolve SSR meta
    print("🔍 Resolving douyin share link...", file=sys.stderr)
    meta = resolve_ssr(share_text)

    # Create a dedicated output subdirectory
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", meta.title)[:60]
    safe_name = re.sub(r"\s+", " ", safe_name).strip() or f"douyin_{meta.aweme_id}"
    out_dir = output_dir / f"{meta.aweme_id}_{safe_name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if meta.content_type == "image":
        # Image post: text is in the title/desc
        print(f"📷 Image post detected. Extracting desc text...", file=sys.stderr)
        text = meta.title
        text = apply_corrections(text)  # fix common misrecognitions in desc too
        segments: list[dict] = []
    else:
        # Video post: download + transcribe
        print(f"🎬 Video post detected. Downloading...", file=sys.stderr)

        # Try direct download from SSR URL first
        video_path = None
        if meta.download_url:
            try:
                import requests
                video_path = out_dir / "video.mp4"
                resp = requests.get(
                    meta.download_url,
                    headers={"User-Agent": SHARE_PAGE_UA, "Referer": "https://www.iesdouyin.com/"},
                    stream=True, timeout=120,
                )
                resp.raise_for_status()
                with open(video_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            f.write(chunk)
                print(f"  ✅ Downloaded ({video_path.stat().st_size / 1024 / 1024:.1f} MB)", file=sys.stderr)
            except Exception as e:
                print(f"  ⚠️ Direct download failed: {e}", file=sys.stderr)
                video_path = None

        # Fallback to yt-dlp
        if not video_path or video_path.stat().st_size < 1000:
            print(f"  🔄 Falling back to yt-dlp...", file=sys.stderr)
            try:
                video_path = download_video_ytdlp(share_text, out_dir)
                print(f"  ✅ Downloaded via yt-dlp ({video_path.stat().st_size / 1024 / 1024:.1f} MB)", file=sys.stderr)
            except Exception as e:
                raise RuntimeError(f"Video download failed (both SSR and yt-dlp): {e}")

        # Extract audio
        print(f"  🔊 Extracting audio...", file=sys.stderr)
        audio_path = out_dir / "audio.wav"
        try:
            extract_audio(video_path, audio_path)
        except RuntimeError as e:
            if "ffmpeg not found" in str(e):
                raise
            # Try yt-dlp's built-in audio extraction
            print(f"  ⚠️ ffmpeg extraction failed, trying yt-dlp...", file=sys.stderr)
            import yt_dlp
            ydl_opts = {
                "outtmpl": str(out_dir / "audio.%(ext)s"),
                "format": "bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "wav",
                    "preferredquality": "16",
                }],
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([share_text])
            wavs = list(out_dir.glob("audio.*"))
            if wavs:
                audio_path = wavs[0]
            else:
                raise

        # Transcribe — auto-select model based on audio duration
        if model_size == "auto":
            try:
                import wave
                with wave.open(str(audio_path), 'r') as wf:
                    duration = wf.getnframes() / wf.getframerate()
            except Exception:
                duration = 0
            if duration < 30:
                model_size = "small"
            elif duration < 120:
                model_size = "medium"
            else:
                model_size = "large-v3"
            print(f"  🎯 Auto-selected model: {model_size} (audio: {duration:.0f}s)", file=sys.stderr)

        print(f"  🤖 Transcribing with Whisper ({model_size})...", file=sys.stderr)
        text, segments = transcribe(audio_path, model_size=model_size)

        # Cleanup: delete video and audio files to save space
        if video_path and video_path.exists():
            video_path.unlink()
        if audio_path and audio_path.exists():
            audio_path.unlink()
        print(f"  🧹 Temp files cleaned up", file=sys.stderr)

    # Check for ambiguous corrections
    ambiguous = get_ambiguous_matches(text)
    if ambiguous:
        print(f"  ⚠️ Ambiguous corrections found — review needed:", file=sys.stderr)
        for m in ambiguous:
            print(f"     \"{m['matched']}\" → {m['suggestions']}", file=sys.stderr)

    # Write output files
    meta_path = out_dir / "meta.json"
    meta_dict = asdict(meta)
    if ambiguous:
        meta_dict["ambiguous_corrections"] = ambiguous
    meta_path.write_text(
        json.dumps(meta_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    transcript_path = out_dir / "transcript.txt"
    transcript_path.write_text(text + "\n", encoding="utf-8")

    if segments:
        seg_path = out_dir / "transcript_segments.json"
        seg_path.write_text(
            json.dumps({"segments": segments, "full_text": text}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return ExtractResult(meta=meta, text=text, segments=segments, out_dir=out_dir)


def _browser_fallback_patch(url: str, result: ExtractResult) -> ExtractResult:
    """When Whisper returns an empty transcript, patch in the chapter summary
    obtained via the Playwright browser fallback (if available).

    Returns an ExtractResult whose .text is either the browser chapter summary
    (cleaned of leading '章节要点' label) or the original empty text if the
    browser fallback also fails.
    """
    try:
        from douyin_to_obsidian.browser_fallback import extract_with_playwright
        fb = extract_with_playwright(url)
        if fb.success and fb.chapter_summary:
            # Strip the leading "章节要点" label if present
            summary = fb.chapter_summary
            summary = re.sub(r"^章节要点\s*", "", summary).strip()
            # Merge into result: use chapter summary as the text; keep original meta
            out_dir = result.out_dir
            (out_dir / "chapter_summary.txt").write_text(summary + "\n", encoding="utf-8")
            meta = asdict(result.meta)
            meta["source"] = "browser_fallback"
            meta["is_summary"] = True
            (out_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return ExtractResult(
                meta=result.meta, text=summary, segments=result.segments, out_dir=out_dir
            )
    except Exception as e:
        print(f"  ⚠️ Browser fallback also failed: {e}", file=sys.stderr)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract content from Douyin share links. Cross-platform, no API keys needed.",
    )
    parser.add_argument("url", nargs="?", help="Douyin share link")
    parser.add_argument("-o", "--output", type=Path, default=Path("douyin_output"),
                        help="Output directory (default: ./douyin_output)")
    parser.add_argument("--model", default="auto",
                        choices=["auto", "tiny", "base", "small", "medium", "large-v2", "large-v3"],
                        help="Whisper model size (default: auto — picks based on audio duration: <30s=small, <2min=medium, >2min=large-v3)")
    parser.add_argument("--json", action="store_true",
                        help="Output result as JSON to stdout")
    parser.add_argument("--corrections", type=Path, default=None,
                        help="Path to custom corrections JSON file (default: text_corrections.json next to script)")
    parser.add_argument("--batch", type=Path, default=None,
                        help="Batch mode: file containing douyin URLs, one per line")
    args = parser.parse_args()

    # Batch mode
    if args.batch:
        urls = [line.strip() for line in args.batch.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
        if not urls:
            print("Error: Batch file is empty.", file=sys.stderr)
            return 1
        print(f"📦 Batch mode: {len(urls)} URLs", file=sys.stderr)
        _load_corrections(args.corrections)
        success = 0
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] Processing: {url[:60]}...", file=sys.stderr)
            try:
                result = process(url, args.output, model_size=args.model)
                # If transcription is empty (e.g. SSR parsed but Whisper returned blank,
                # or a silent/broken audio track), auto-fall back to browser chapter summary.
                if not result.text.strip():
                    print(f"  ⚠️ Empty transcript — auto browser-fallback...", file=sys.stderr)
                    result = _browser_fallback_patch(url, result)
                meta = asdict(result.meta)
                tag = "🎬" if meta['content_type'] == "video" else "📷"
                print(f"  {tag} {meta['title'][:50]} ({len(result.text.strip())} chars)", file=sys.stderr)
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {e}", file=sys.stderr)
        print(f"\n📊 Batch complete: {success}/{len(urls)} succeeded", file=sys.stderr)
        return 0 if success == len(urls) else 1

    share = args.url
    if not share:
        print("Paste douyin share link and press Enter (Ctrl+D to finish):", file=sys.stderr)
        share = sys.stdin.read().strip()
    if not share:
        print("Error: No URL provided.", file=sys.stderr)
        return 1

    try:
        # Pre-load corrections (auto-detects text_corrections.json next to script)
        _load_corrections(args.corrections)
        result = process(share, args.output, model_size=args.model)
    except ValueError as e:
        print(f"❌ Parse error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except ImportError as e:
        print(f"❌ Missing dependency: {e}", file=sys.stderr)
        print("   Run: pip install requests yt-dlp faster-whisper zhconv", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({
            "success": True,
            "meta": asdict(result.meta),
            "text": result.text,
            "segment_count": len(result.segments),
            "out_dir": str(result.out_dir),
        }, ensure_ascii=False, indent=2))
    else:
        type_label = "📷 Image" if result.meta.content_type == "image" else "🎬 Video"
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"  {type_label} | {result.meta.title[:50]}", file=sys.stderr)
        print(f"  Author: {result.meta.author or 'unknown'}", file=sys.stderr)
        print(f"  ID: {result.meta.aweme_id}", file=sys.stderr)
        print(f"  Output: {result.out_dir}", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)
        print(f"\n--- Transcript ({len(result.text)} chars) ---")
        print(result.text[:2000] + ("..." if len(result.text) > 2000 else ""))

    return 0


if __name__ == "__main__":
    sys.exit(main())
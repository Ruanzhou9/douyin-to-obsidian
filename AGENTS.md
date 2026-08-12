# AGENTS.md — douyin-to-obsidian 项目导航

## 一句话

把抖音分享链接转为结构化 Obsidian 笔记。纯本地，零 API Key。

## 核心入口（agent 首读，按顺序）

| 文件 | 作用 | 是否必读 |
|------|------|----------|
| `SKILL.md` | Agent 调用指令，含完整工作流 | ✅ 必读（约 13KB） |
| `scripts/douyin_extract.py` | CLI 主入口，最快上手 | ✅ 必读 |

## 核心逻辑

| 文件 | 作用 | 是否必读 |
|------|------|----------|
| `douyin_to_obsidian/extract.py` | 核心提取引擎（SSR 解析 + Whisper 转写 + OCR） | ⚠️ 需要时读 |
| `douyin_to_obsidian/browser_fallback.py` | Playwright 反爬兜底 | ⚠️ SSR 失败时读 |
| `douyin_to_obsidian/text_corrections.json` | 43 条 Whisper 错字修正 | ⚠️ 需要时读 |

## 可直接跳过的文件（节省 token）

| 文件 | 理由 |
|------|------|
| `promo.html` | 宣传页面，与功能无关 |
| `Makefile` | 开发辅助，非核心 |
| `setup.sh` | 一键安装脚本，可跳过 |
| `pyproject.toml` | pip 打包配置，无需读 |
| `LICENSE` | MIT 许可证，无需读 |
| `references/note-format.md` | 笔记格式参考，需要时读 |
| `.gitignore` | 版本控制忽略规则 |

## 依赖清单

- `requests` — SSR 解析
- `yt-dlp` — 视频下载回退
- `faster-whisper` — 本地语音转文字
- `zhconv` — 繁体转简体
- `ffmpeg` — 视频抽音频（`brew install ffmpeg`）
- `playwright` — 浏览器兜底（可选）

## 输出结构

```
output/
└── {aweme_id}_{title}/
    ├── meta.json
    ├── transcript.txt
    └── transcript_segments.json
```

## 快速验证

```bash
python3 scripts/douyin_extract.py "https://v.douyin.com/xxxxx/" --output /tmp/out
```
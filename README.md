# douyin-to-obsidian

> 抖音链接 → 提取内容 → 生成结构化 Obsidian 笔记。零 API Key，纯本地运行。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)

## 功能

- 🔗 **解析抖音分享链接**：支持 `v.douyin.com` 短链、`www.douyin.com` 长链、`iesdouyin.com` 分享页
- 🎬 **视频口播转文字**：本地 Whisper 语音识别，无需 API Key
- 📷 **图文/多图作品**：直接提取描述文字；图片带文字时自动 OCR（可选）
- 🎞️ **实况图识别**：既有图片又有短语音的作品，自动转写音频
- ✏️ **错字自动修正**：内置 43 条确定修正 + 5 条含糊标记，Whisper 常见听错自动纠正
- 🧹 **零残留**：视频/音频/临时文件在转录后自动清理
- 🔒 **隐私优先**：纯本地运行，无数据上传，无需抖音登录
- 📝 **输出结构化笔记**：`meta.json` + `transcript.txt` + 时间戳分段
- 🎵 **BGM 检测**：背景音乐歌词可能干扰转录，输出时警告
- 🔄 **去重提醒**：写笔记前检查是否已有相似内容，询问跳过/合并/新建
- 📋 **长图文 OCR**：知识卡片/多图连载，逐张 OCR 提取完整内容

## 快速开始

### 一键安装

```bash
git clone https://github.com/Ruanzhou9/douyin-to-obsidian.git
cd douyin-to-obsidian
bash setup.sh
```

### CLI 使用

```bash
# 提取视频内容
python3 scripts/douyin_extract.py "https://v.douyin.com/xxxxx/" --output ./output

# 使用 large-v3 模型提高准确度（首次需下载 ~3GB）
python3 scripts/douyin_extract.py "https://v.douyin.com/xxxxx/" --model large-v3

# 输出为 JSON
python3 scripts/douyin_extract.py "https://v.douyin.com/xxxxx/" --json

# 使用自定义错字修正文件
python3 scripts/douyin_extract.py "https://v.douyin.com/xxxxx/" --corrections ./my_corrections.json
```

### Agent 使用（Hermes / Codex / OpenCode / Claude Code）

加载 `douyin-to-obsidian` skill，然后直接给 Agent 发抖音链接：

```
总结这个抖音视频：https://v.douyin.com/xxxxx/
```

Agent 会自动运行提取流程，生成笔记并写入 Obsidian vault。

## 输出结构

```
output/
└── {aweme_id}_{title}/
    ├── meta.json                # 元数据（标题、作者、类型、下载链接、含糊修正标记）
    ├── transcript.txt           # 转录文字（已修正错字）
    └── transcript_segments.json # 时间戳分段（仅视频）
```

## 依赖

| 依赖 | 用途 | 安装方式 |
|------|------|---------|
| Python 3.9+ | 运行环境 | — |
| requests | 抖音分享页 SSR 解析 | `pip install requests` |
| yt-dlp | 视频下载回退 | `pip install yt-dlp` |
| faster-whisper | 本地语音转文字 | `pip install faster-whisper` |
| zhconv | 繁体转简体 | `pip install zhconv` |
| ffmpeg | 视频抽音频 | `brew install ffmpeg` 或 `pip install imageio-ffmpeg` |

## 内容判断模型

Agent 根据 SSR 数据自动判断提取策略：

| SSR 类型 | 有图片 | 有音频 | Agent 处理方式 |
|----------|--------|--------|---------------|
| 视频 | — | ✅ | Whisper 转写音频 |
| 实况图 | ✅ | ✅ | 音频 + 文案结合 |
| 多图/图文 | ✅ | ❌ | 检查图片是否有文字 → 有则逐张 OCR / 无则只用 desc |
| 纯文字 | ❌ | ❌ | 直接用 desc |

### 长图文处理

知识卡片/多图连载类作品，desc 只包含标题，真正内容在图片上：

1. 下载所有图片
2. 逐张 OCR 提取文字
3. 合并为完整转录文本
4. Agent 总结为结构化笔记

### BGM 处理

背景音乐含人声时，Whisper 可能转写歌词而非口播。Agent 会：
1. 检查转录是否包含重复段落（疑似歌词）
2. 输出警告："转录可能包含背景音乐歌词，请核对"
3. 音源分离（demucs）为未来计划

## 错字修正

Whisper 对中文口播的识别常有固定错误模式。`text_corrections.json` 内置修正规则：

| 类型 | 数量 | 示例 |
|------|------|------|
| **确定修正** | 43 条 | 心软上学→形而上学、全盘开→全盘否定、千向一→倾向于 |
| **含糊修正** | 5 条 | 一次→辩证/一次（需人工判断） |

含糊修正会标记在 `meta.json` 的 `ambiguous_corrections` 字段中，由 Agent 展示给用户确认。

## 重复内容检测

写笔记前，Agent 自动搜索 `douyinobsidian/` 目录下已有笔记，发现相似内容时询问：
- **跳过**：不写入
- **合并**：新内容追加到已有笔记
- **新建**：作为独立笔记写入

## 中国用户指南

```bash
# 安装依赖时使用阿里云镜像
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 下载 Whisper 模型时使用 HuggingFace 镜像
export HF_ENDPOINT=https://hf-mirror.com
python3 scripts/douyin_extract.py "https://v.douyin.com/xxxxx/"
```

## 安全说明

- **零凭证**：无需 API Key、Token、Cookie
- **本地处理**：Whisper 在本地运行，音频/文字不离开本机
- **自动清理**：视频/音频文件转录后自动删除
- **无硬编码路径**：输出目录可配置
- **URL 校验**：输入先验证为 douyin.com 链接

## 项目结构

```
douyin-to-obsidian/
├── SKILL.md                          # Hermes Agent skill 定义
├── douyin_to_obsidian/               # Python 包（pip install 用）
│   ├── extract.py                    # 核心提取脚本
│   └── text_corrections.json         # 错字修正规则（43确定+5含糊）
├── scripts/                          # 直接运行入口
│   ├── douyin_extract.py
│   └── text_corrections.json
├── pyproject.toml                    # pip 安装配置
├── setup.sh                          # 一键安装脚本
├── Makefile                          # 快速命令
├── promo.html                        # 宣传页面
└── references/                       # 参考文档
    └── note-format.md
```

## License

MIT
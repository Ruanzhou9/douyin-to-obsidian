#!/usr/bin/env python3
"""
Douyin 剪贴板监听器 — 后台运行，自动检测并处理复制的新抖音链接。

用法:
  python3 douyin_clipboard_watcher.py                        # 默认模式
  python3 douyin_clipboard_watcher.py --output ~/Desktop/out  # 自定义输出目录

依赖:
  pip install pyperclip       # 跨平台剪贴板读取

工作方式:
  - 每 3 秒检查剪贴板
  - 检测到新 douyin.com 链接（v.douyin.com, www.douyin.com, iesdouyin.com）
  - 自动调用 douyin_extract.py 提取并写 Obsidian 笔记
  - 去重：已处理过的链接不再重复处理
  - 去抖：5 秒内相同链接不重复触发
"""

import os
import sys
import time
import json
import subprocess
import hashlib
import argparse

# 将上级目录（SKILL.md 所在目录）加入模块搜索路径
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT_SCRIPT = os.path.join(SKILL_DIR, "scripts", "douyin_extract.py")
HISTORY_FILE = os.path.join(SKILL_DIR, ".clipboard_history.json")

# 默认输出目录（Obsidian vault douyinobsidian/）
DEFAULT_OUTPUT = os.path.expanduser("~/Documents/Obsidian Vault/douyinobsidian")

def load_history():
    """加载已处理链接的历史记录"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_history(history):
    """保存已处理链接的历史记录"""
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def extract_douyin_links(text):
    """从文本中提取所有抖音链接"""
    import re
    patterns = [
        r'https?://v\.douyin\.com/\w+',
        r'https?://www\.douyin\.com/(?:video|note)/\d+',
        r'https?://www\.iesdouyin\.com/share/(?:video|note)/\d+',
        r'https?://www\.douyin\.com/user/\S+',
    ]
    links = []
    for p in patterns:
        links.extend(re.findall(p, text))
    return list(set(links))  # 去重

def get_clipboard_text():
    """读取剪贴板内容，跨平台"""
    try:
        import pyperclip
        return pyperclip.paste()
    except ImportError:
        # macOS 备用方案
        try:
            result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
            return result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            return ""

def process_link(link, output_dir, history):
    """处理单个抖音链接"""
    link_hash = hashlib.md5(link.encode()).hexdigest()
    
    # 去重检查
    now = time.time()
    if link_hash in history:
        elapsed = now - history[link_hash]
        if elapsed < 300:  # 5 分钟内不重复处理
            print(f"  ⏭️ 跳过（已处理）: {link}")
            return False
    
    print(f"  🔗 检测到新链接: {link}")
    print(f"  ⏳ 正在提取...")
    
    # 调用 douyin_extract.py
    cmd = [
        sys.executable, EXTRACT_SCRIPT,
        link,
        "--output", output_dir,
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print(f"  ✅ 提取成功: {link}")
            history[link_hash] = now
            save_history(history)
            return True
        else:
            print(f"  ❌ 提取失败: {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"  ⏰ 超时: {link}")
        return False
    except Exception as e:
        print(f"  ❌ 错误: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Douyin 剪贴板监听器")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="输出目录")
    parser.add_argument("--interval", type=float, default=3.0, help="检测间隔（秒）")
    parser.add_argument("--once", action="store_true", help="只处理一次当前的剪贴板内容")
    args = parser.parse_args()
    
    os.makedirs(args.output, exist_ok=True)
    history = load_history()
    last_text = ""
    
    print(f"🎯 Douyin 剪贴板监听器启动")
    print(f"📁 输出目录: {args.output}")
    print(f"⏱️  检测间隔: {args.interval}s")
    print(f"📋 历史记录: {len(history)} 条已处理")
    print("=" * 50)
    
    if args.once:
        text = get_clipboard_text()
        if not text:
            print("剪贴板为空")
            return
        links = extract_douyin_links(text)
        if not links:
            print("未检测到抖音链接")
            return
        for link in links:
            process_link(link, args.output, history)
        return
    
    # 持续监听模式
    print("持续监听中，复制抖音链接即可自动处理...")
    try:
        while True:
            text = get_clipboard_text()
            if text and text != last_text:
                links = extract_douyin_links(text)
                if links:
                    for link in links:
                        process_link(link, args.output, history)
                last_text = text
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n👋 监听器已停止")
        save_history(history)

if __name__ == "__main__":
    main()
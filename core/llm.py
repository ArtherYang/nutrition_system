# -*- coding: utf-8 -*-
"""共享大模型调用工具（DeepSeek 官方 API）。

未配置 key 或调用失败时返回 None，调用方自行降级到本地规则引擎。
"""
import re

import config

# Markdown → 纯文本清洗规则：AI 常输出 **粗体**、# 标题、- 列表、--- 分隔线等符号，
# 前端以纯文本展示，统一剥离这些符号，让点评更清爽。
_MD_HORIZONTAL = re.compile(r"^\s*(?:---+|\*\*\*+|___+)\s*$", re.MULTILINE)
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MD_BACKTICK = re.compile(r"`([^`]*)`")
_MD_HEADER = re.compile(r"^\s*#{1,6}\s*", re.MULTILINE)
_MD_BLOCKQUOTE = re.compile(r"^\s*>\s?", re.MULTILINE)
_MD_NUM_LIST = re.compile(r"^\s*\d+[.、)]\s*", re.MULTILINE)
_MD_LIST = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)


def strip_markdown(text):
    """把 Markdown 风格文本转成纯文本（去 ** 粗体 / # 标题 / - 列表 / --- 分隔线等）。"""
    if not text:
        return text
    t = _MD_HORIZONTAL.sub("", text)
    t = _MD_BOLD.sub(lambda m: m.group(1) or m.group(2), t)
    t = _MD_BACKTICK.sub(r"\1", t)
    t = _MD_HEADER.sub("", t)
    t = _MD_BLOCKQUOTE.sub("", t)
    t = _MD_NUM_LIST.sub("", t)
    t = _MD_LIST.sub("", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def enabled():
    """是否已配置可用的 DeepSeek key。"""
    return bool(config.DEEPSEEK_API_KEY)


def chat(system, user, history=None, max_tokens=600, temperature=0.7):
    """调用 DeepSeek 对话接口，返回文本；失败 / 未配置时返回 None。

    history：可选的多轮对话历史，形如 [{"role": "user"/"assistant", "content": ...}]，
    会按顺序插入到本轮 user 消息之前，用于「可交互点评师」的连续追问。
    """
    if not enabled():
        return None
    try:
        import requests

        messages = [{"role": "system", "content": system}]
        for m in (history or []):
            messages.append({"role": m.get("role", "user"), "content": m["content"]})
        messages.append({"role": "user", "content": user})
        resp = requests.post(
            f"{config.DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        return strip_markdown(content)
    except Exception:
        return None


def vision(image_bytes, prompt, max_tokens=500, temperature=0.1):
    """调用视觉大模型解析图片，返回文本；未配置 key 或失败返回 None。"""
    if not config.VISION_API_KEY:
        return None
    try:
        import base64
        import requests

        b64 = base64.b64encode(image_bytes).decode()
        resp = requests.post(
            f"{config.VISION_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.VISION_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url",
                             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    }
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None

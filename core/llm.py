# -*- coding: utf-8 -*-
"""共享大模型调用工具（DeepSeek 官方 API）。

未配置 key 或调用失败时返回 None，调用方自行降级到本地规则引擎。
"""
import config


def enabled():
    """是否已配置可用的 DeepSeek key。"""
    return bool(config.DEEPSEEK_API_KEY)


def chat(system, user, max_tokens=600, temperature=0.7):
    """调用 DeepSeek 对话接口，返回文本；失败 / 未配置时返回 None。"""
    if not enabled():
        return None
    try:
        import requests

        resp = requests.post(
            f"{config.DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
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

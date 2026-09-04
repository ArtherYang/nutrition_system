# -*- coding: utf-8 -*-
"""买菜照片评估（Produce）：视觉大模型识别食材 + 品相新鲜度，配参考价区间。

价格来自内置「常见食材参考价区间表」（按常见市场行情整理的静态区间），
仅作参考，非实时价格，最终以当地市场为准。
"""
import json
import re

from core import llm

# 常见食材参考价区间（元/斤），静态整理，仅供买菜参考。
REFERENCE_PRICES = {
    "西红柿": "3.5~5.0",
    "黄瓜": "3.0~4.5",
    "白菜": "1.0~2.0",
    "土豆": "2.0~3.0",
    "胡萝卜": "2.0~3.5",
    "西兰花": "4.0~6.0",
    "菠菜": "3.0~5.0",
    "芹菜": "2.5~4.0",
    "茄子": "2.5~4.5",
    "青椒": "3.0~5.0",
    "豆角": "4.0~6.0",
    "冬瓜": "1.5~2.5",
    "南瓜": "2.0~3.5",
    "玉米": "3.0~5.0",
    "苹果": "4.0~7.0",
    "香蕉": "3.0~5.0",
    "橙子": "4.0~6.5",
    "葡萄": "6.0~10.0",
    "草莓": "12.0~20.0",
    "鸡蛋": "5.0~6.5",
    "猪肉": "15.0~20.0",
    "牛肉": "35.0~45.0",
    "鸡胸肉": "10.0~13.0",
}


def assess(image_bytes):
    """视觉大模型识别图片食材并评估新鲜度，返回 [{name, freshness, note}]；失败返回 None。"""
    prompt = (
        "识别图片中的蔬菜、水果、肉类、蛋类等食材，并评估每种食材的品相与新鲜度。"
        "只输出一个 JSON 数组，每个元素形如 "
        '{"name":"西红柿","freshness":"新鲜|一般|不新鲜","note":"简短说明"}。'
        "如果图中没有食材，输出 []。不要输出任何其他文字、解释或代码块。"
    )
    text = llm.vision(image_bytes, prompt, max_tokens=2000)
    print(f"[produce] 收到 {len(image_bytes)} 字节；视觉返回: {text!r}", flush=True)
    if not text:
        return None
    return _parse_items(text)


def _parse_items(text):
    """从模型回复中解析 [{name, freshness, note}] 列表。"""
    if not text:
        return []
    arr = _extract_json(text)
    if isinstance(arr, list):
        items = []
        for x in arr:
            if isinstance(x, dict) and x.get("name"):
                items.append({
                    "name": str(x["name"]).strip(),
                    "freshness": str(x.get("freshness", "一般")).strip(),
                    "note": str(x.get("note", "")).strip(),
                })
        return items
    return []


def _extract_json(text):
    try:
        obj = json.loads(text)
        return obj
    except Exception:
        pass
    m = re.search(r"\[[^\]]*\]", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return []


def price_hint(name):
    """按名称查参考价区间（元/斤），未收录返回 None。"""
    return REFERENCE_PRICES.get(name)


def freshness_emoji(freshness):
    """新鲜度 → 表情符号（用于前端展示）。"""
    return {"新鲜": "🟢", "一般": "🟡", "不新鲜": "🔴"}.get(freshness, "⚪")

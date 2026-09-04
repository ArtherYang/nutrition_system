# -*- coding: utf-8 -*-
"""餐食照片估算（MealPhoto）：视觉大模型识别一餐食物并估算热量。

与 produce.assess / health_report.parse_report 同源：调用 llm.vision，输出 JSON。
照片估热天然不精确，仅作参考，用户可手动调整，最终以用户确认为准。
"""
import json
import re

from core import llm


def estimate(image_bytes):
    """视觉大模型识别一餐照片，返回 [{name, calories, note}]；失败返回 None。

    calories 为模型估算的单份热量（kcal），note 为简要说明显。
    """
    prompt = (
        "这是用户的一餐（可能含多个菜品/食物）的照片。请识别图中主要食物或菜品，"
        "并估算每种食物的热量（kcal）。只输出一个 JSON 数组，每个元素形如 "
        '{"name":"米饭","calories":200,"note":"约一碗"}。'
        "热量请给整数。如果无法识别，输出 []。不要输出任何其他文字、解释或代码块。"
    )
    # max_tokens 需给足：该视觉模型为推理型，太小会因 finish_reason=length 而 content 为空。
    text = llm.vision(image_bytes, prompt, max_tokens=2000)
    print(f"[meal_photo] 收到 {len(image_bytes)} 字节；视觉返回: {text!r}", flush=True)
    if not text:
        return None
    return _parse_items(text)


def _parse_items(text):
    """从模型回复解析 [{name, calories, note}] 列表。"""
    if not text:
        return []
    arr = _extract_json(text)
    if not isinstance(arr, list):
        return []
    items = []
    for x in arr:
        if isinstance(x, dict) and x.get("name"):
            items.append({
                "name": str(x["name"]).strip(),
                "calories": _to_int(x.get("calories")),
                "note": str(x.get("note", "")).strip(),
            })
    return items


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


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

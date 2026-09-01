# -*- coding: utf-8 -*-
"""把西餐/饮料的英文菜名+步骤批量翻译成中文（DeepSeek）。

输入：data/recipes_western.json（整合脚本产出的英文版）
输出：data/recipes_western_zh.json（菜名+步骤中文化；食材已是中文不动）
失败/解析不了的条目保留英文原文，不中断。
"""
import json
import os
import re
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

from core import llm

IN = "data/recipes_western.json"
OUT = "data/recipes_western_zh.json"
BATCH = 10

SYSTEM = (
    "你是专业食谱翻译。把英文菜名和制作步骤翻译成简洁自然的中文。"
    "食材用中文（chicken→鸡肉、olive oil→橄榄油、salmon→三文鱼）；"
    "度量单位转常用中文（g→克、ml→毫升、tbsp→汤匙、tsp→茶匙、°C→℃、cup→杯）。"
    "只输出一个 JSON 数组，元素形如 {\"i\": 序号, \"name\": \"中文菜名\", \"steps\": [\"步骤1\", \"步骤2\"]}，"
    "不要输出任何其他文字或代码块标记。"
)


def _parse(text):
    """解析模型返回的 JSON 数组，失败返回 None。"""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(json)?\s*|\s*```$", "", t, flags=re.I).strip()
    try:
        arr = json.loads(t)
        return arr if isinstance(arr, list) else None
    except Exception:
        return None


def translate_batch(items):
    """翻译一批 [{i,name,steps}] -> {i: {name,steps}}，失败递归二分重试。"""
    if not items:
        return {}
    user = json.dumps([{"i": it["i"], "name": it["name"], "steps": it["steps"]}
                       for it in items], ensure_ascii=False)
    try:
        text = llm.chat(SYSTEM, user, max_tokens=4000, temperature=0.2)
        arr = _parse(text)
        if arr:
            out = {}
            for r in arr:
                i = r.get("i")
                if isinstance(i, int) and r.get("name") and isinstance(r.get("steps"), list):
                    out[i] = {"name": r["name"].strip(), "steps": [s.strip() for s in r["steps"] if str(s).strip()]}
            return out
    except Exception:
        pass
    # 失败：二分重试
    if len(items) == 1:
        return {items[0]["i"]: {"name": items[0]["name"], "steps": items[0]["steps"]}}  # 保留英文
    mid = len(items) // 2
    out = translate_batch(items[:mid])
    out.update(translate_batch(items[mid:]))
    return out


def main():
    recipes = json.load(open(IN, encoding="utf-8"))
    items = [{"i": idx, "name": r["name"], "steps": r["steps"]} for idx, r in enumerate(recipes)]
    result = {}
    total = len(items)
    for start in range(0, total, BATCH):
        batch = items[start:start + BATCH]
        result.update(translate_batch(batch))
        print(f"  已翻译 {min(start + BATCH, total)}/{total}", flush=True)
        time.sleep(0.3)

    # 回填：翻译成功的替换 name/steps，失败的保留英文
    changed = 0
    for idx, r in enumerate(recipes):
        tr = result.get(idx)
        if tr and tr["name"] and tr["name"] != r["name"]:
            r["name"] = tr["name"]
            changed += 1
        if tr and tr["steps"]:
            r["steps"] = tr["steps"]

    json.dump(recipes, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"完成：共 {total} 道，菜名翻译 {changed} 道 -> {OUT}")


if __name__ == "__main__":
    main()

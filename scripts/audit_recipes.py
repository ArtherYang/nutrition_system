# -*- coding: utf-8 -*-
"""菜谱库数据质量审计 + 修复脚本。

用法：
    python scripts/audit_recipes.py             # 只报告，不修改数据
    python scripts/audit_recipes.py --fix       # 应用 FIXES 中的人工核实修正

检测项：
    1. 烘焙/西点名（面包/饼/披萨/派…）但做法不符（应为烤/煎/炸/蒸）
    2. 烘焙名却缺少面粉等主料（疑似食材列表错误，会导致错误匹配）
    3. 食材列表完全重复的菜谱组（疑似张冠李戴）
    4. 食材数过少（≤2）的菜谱
    5. 食材未收录进营养库的菜谱（会导致无法匹配/被忽略）
"""
import json
import os
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECIPES_JSON = os.path.join(BASE_DIR, "data", "recipes.json")
INGREDIENTS_JSON = os.path.join(BASE_DIR, "data", "ingredients.json")

# 名字含这些词，通常意味着烘焙/西点类（做法应为烤/煎/炸/蒸）
BAKE_WORDS = ("面包", "饼", "披萨", "派", "蛋糕", "饼干", "曲奇", "马芬", "司康", "吐司", "蛋挞")
BAKE_METHODS = ("烤", "煎", "炸", "蒸")
# 面点类应有的主料（缺这些大概率是食材列表写错）
STAPLES = ("面粉", "面包", "土豆", "淀粉", "米粉", "糯米", "大米", "玉米面", "燕麦", "全麦面粉")

# 人工核实后的修正（键=菜谱名，值=需覆盖的字段）
# 哈拉面包 / 恩赛马达：原食材漏了「面粉」，且做法标错，导致只凭「鸡蛋」就误判 100% 匹配
FIXES = {
    "哈拉面包": {"ingredients": ["面粉", "白砂糖", "鸡蛋", "食用油"], "method": "烤"},
    "恩赛马达": {"ingredients": ["面粉", "白砂糖", "鸡蛋", "食用油"], "method": "烤"},
    "Pizza Express玛格丽特披萨": {"method": "烤"},
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def audit(recipes, ingredient_names):
    report = {}

    # 1) 烘焙名做法不符
    bake_method_bad = [
        r["name"] for r in recipes
        if any(w in r["name"] for w in BAKE_WORDS) and r.get("method") not in BAKE_METHODS
    ]
    report["烘焙名做法不符"] = bake_method_bad

    # 2) 烘焙名却缺主料
    bake_no_staple = [
        r["name"] for r in recipes
        if any(w in r["name"] for w in BAKE_WORDS)
        and not any(s in r.get("ingredients", []) for s in STAPLES)
    ]
    report["烘焙名缺主料(疑似食材错)"] = bake_no_staple

    # 3) 食材列表完全重复
    sig = defaultdict(list)
    for r in recipes:
        sig[tuple(sorted(r.get("ingredients", [])))].append(r["name"])
    dup = {tuple(k): v for k, v in sig.items() if len(v) > 1 and len(k) > 0}
    report["食材列表完全重复组"] = dup

    # 4) 食材数过少
    report["食材数≤2"] = [r["name"] for r in recipes if len(r.get("ingredients", [])) <= 2]

    # 5) 食材未收录进营养库
    unknown = defaultdict(list)
    for r in recipes:
        for ing in r.get("ingredients", []):
            if ing not in ingredient_names:
                unknown[ing].append(r["name"])
    report["未收录食材"] = dict(unknown)

    return report


def print_report(recipes, report):
    print(f"菜谱总数：{len(recipes)}\n")

    print(f"[1] 烘焙名做法不符：{len(report['烘焙名做法不符'])} 条")
    for n in report["烘焙名做法不符"][:12]:
        print("    -", n)
    if len(report["烘焙名做法不符"]) > 12:
        print(f"    … 共 {len(report['烘焙名做法不符'])} 条")

    print(f"\n[2] 烘焙名缺主料(疑似食材错)：{len(report['烘焙名缺主料(疑似食材错)'])} 条")
    for n in report["烘焙名缺主料(疑似食材错)"]:
        print("    -", n)

    print(f"\n[3] 食材列表完全重复组：{len(report['食材列表完全重复组'])} 组")
    for k, v in report["食材列表完全重复组"].items():
        print(f"    {list(v)} ← {list(k)}")

    print(f"\n[4] 食材数≤2：{len(report['食材数≤2'])} 条（多为简单家常菜，属正常）")

    print(f"\n[5] 未收录进营养库的食材：{len(report['未收录食材'])} 种")
    for ing, names in sorted(report["未收录食材"].items(), key=lambda x: -len(x[1]))[:15]:
        print(f"    {ing}（出现在 {len(names)} 道菜）")


def apply_fixes(recipes):
    changed = 0
    for r in recipes:
        fix = FIXES.get(r["name"])
        if fix:
            r.update(fix)
            changed += 1
            print(f"  ✓ 修正：{r['name']} -> {fix}")
    return changed


def main():
    recipes = load(RECIPES_JSON)
    ingredient_names = {i["name"] for i in load(INGREDIENTS_JSON)}

    do_fix = "--fix" in sys.argv
    if do_fix:
        print("应用人工修正：")
        changed = apply_fixes(recipes)
        if changed:
            with open(RECIPES_JSON, "w", encoding="utf-8") as f:
                json.dump(recipes, f, ensure_ascii=False, indent=2)
            print(f"已写回 {RECIPES_JSON}（共修正 {changed} 条）\n")
        else:
            print("  没有需要修正的条目\n")

    report = audit(recipes, ingredient_names)
    print_report(recipes, report)


if __name__ == "__main__":
    main()

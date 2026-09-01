# -*- coding: utf-8 -*-
"""把《中国食物成分表(第6版)》数据合并进 ingredients.json。

来源：data_sources/cfcd/（Sanotsu/china-food-composition-data 的 fixed 版）
产出：data/ingredients.json（在现有 215 种基础上扩充水果/乳制品/坚果等）

规则：
- 名称：取第一个括号/方括号前的基础名；水果按「品种名 → 基础果名」归一
- 同基础名优先取「代表值/均值」条目（权威代表值）
- 类别由文件名映射；禁忌标签按类别 + GI/脂肪阈值推断
- 与现有食材按 name/aliases 去重：已有的只补 GI，不覆盖营养；新增的整条加入
"""
import json
import os
import re
import glob

RAW_DIR = "data_sources/cfcd"
OUT = "data/ingredients.json"

# 文件名关键词 -> 类别（None 表示跳过）
CAT_MAP = [
    ("水果", "水果"),
    ("乳类", "乳制品"),
    ("坚果", "坚果"),
    ("干豆", "豆类"),
    ("畜肉", "肉类"),
    ("禽肉", "肉类"),
    ("蛋类", "禽蛋"),
    ("鱼虾蟹贝", "水产"),
    ("蔬菜", "蔬菜"),
    ("菌藻", "蔬菜"),
    ("谷类", "主食"),
    ("薯类", "主食"),
    ("淀粉", "主食"),
    ("植物油", "油脂"),
    ("动物油脂", "油脂"),
    ("其他类", None),   # 药材/补品/虫类，跳过
]

# 水果品种归一：名称以这些基础果名结尾时，收敛到基础果名
FRUIT_BASES = ["苹果", "梨", "桃", "葡萄", "石榴", "橙", "柑橘", "橘", "柚",
               "柿", "枣", "李", "梅", "杏", "樱桃", "荔枝", "龙眼", "芒果",
               "菠萝", "柠檬", "香蕉", "草莓", "蓝莓", "猕猴桃", "山楂",
               "无花果", "杨梅", "枇杷", "椰子", "火龙果", "百香果", "木瓜"]

# 独立水果白名单：虽以某个基础果名结尾，但本身是另一种水果，禁止被归一化
FRUIT_KEEP = {"鳄梨", "杨桃", "番石榴", "葡萄柚", "蒲桃", "刺梨", "西梅"}

# 常见别名覆盖：规范名 -> 补充别名（用户常打的俗称/别称，补进 aliases）
ALIAS_OVERRIDES = {
    "鳄梨": ["牛油果", "酪梨"],
    "番石榴": ["芭乐"],
    "葡萄柚": ["西柚"],
}

# 给「已有」食材补别名（这些 CFCD 条目被去重并进了已有食材，规范名不再新增）
EXISTING_ALIAS_OVERRIDES = {
    "卷心菜": ["紫甘蓝", "结球甘蓝"],
}


def category_of(filename):
    for key, cat in CAT_MAP:
        if key in filename:
            return cat
    return None


def clean_name(raw, category):
    base = re.split(r"[（(\[［]", raw)[0].strip()
    if category == "水果" and base not in FRUIT_KEEP:
        for b in FRUIT_BASES:
            if base.endswith(b) and base != b:
                return b
    return base


def extract_aliases(raw):
    """从方括号里提取别名（如 薏米［薏仁米，苡米］）。"""
    aliases = []
    for m in re.findall(r"[\[［]([^\]］]+)[\]］]", raw):
        for a in re.split(r"[,，、;；]", m):
            a = a.strip()
            if a:
                aliases.append(a)
    return aliases


def num(v):
    """把 CFCD 的字符串/数值转 float；Tr/微量/— 等特殊值按 None/0 处理。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s in ("", "—", "-", "Tr", "tr", "微量", "未检出", "未测定"):
        return None
    s = s.rstrip("*†‡#")  # 去掉脚注标记（如 899*）
    try:
        return float(s)
    except ValueError:
        return None


def representative_priority(entry):
    """同基础名择优：代表值 > 均值/平均 > 其他。"""
    raw = entry["foodName"]
    if "代表值" in raw:
        return 2
    if "均值" in raw or "平均" in raw:
        return 1
    return 0


def taboo_of(name, category, gi, fat):
    tags = []
    if category == "乳制品":
        tags.append("乳制品")
    if category == "坚果":
        tags.extend(["坚果", "高脂"])
        if "花生" in name:
            tags.append("花生")
    if category == "水产":
        tags.append("海鲜")
    if category == "油脂":
        tags.append("高脂")
    if any(s in name for s in ("大豆", "黄豆", "黑豆", "青豆", "毛豆")):
        tags.append("大豆")
    if category == "禽蛋" and "蛋" in name:
        tags.append("鸡蛋")
    if category == "主食" and any(
        s in name for s in ("小麦", "面粉", "面条", "面包", "馒头", "饺子", "饼干", "意面", "挂面")
    ):
        tags.append("麸质")
    if gi is not None and gi >= 70:
        tags.append("高GI")
    if fat is not None and fat >= 25:
        tags.append("高脂")
    return sorted(set(tags))


def load_gi():
    gi_map = {}
    for f in glob.glob(os.path.join(RAW_DIR, "glycemic_index_of_foods.json")):
        data = json.load(open(f, encoding="utf-8"))
        for group in data:
            for it in group.get("list", []):
                name = it.get("foodName", "").strip()
                g = num(it.get("GI"))
                if name and g is not None:
                    gi_map[name] = g
    return gi_map


def main():
    gi_map = load_gi()
    existing = json.load(open(OUT, encoding="utf-8"))
    # 名称/别名 -> 规范名 索引
    index = {}
    for it in existing:
        index[it["name"]] = it
        for a in it.get("aliases", []):
            index.setdefault(a, it)

    # 收集 CFCD 新食材（按基础名去重、代表值优先）
    new_map = {}   # base_name -> (entry, category)
    for f in glob.glob(os.path.join(RAW_DIR, "*.json")):
        fn = os.path.basename(f)
        cat = category_of(fn)
        if cat is None or fn == "glycemic_index_of_foods.json":
            continue
        for it in json.load(open(f, encoding="utf-8")):
            raw = it.get("foodName", "").strip()
            if not raw:
                continue
            base = clean_name(raw, cat)
            if not base:
                continue
            cur = new_map.get(base)
            if cur is None or representative_priority(it) > representative_priority(cur[0]):
                new_map[base] = (it, cat)

    # 合并：已有补 GI，新增加入
    updated_gi = 0
    added = []
    for base, (it, cat) in new_map.items():
        gi = gi_map.get(base) or gi_map.get(it.get("foodName", "").strip())
        aliases = extract_aliases(it.get("foodName", ""))
        for a in ALIAS_OVERRIDES.get(base, []):
            if a not in aliases:
                aliases.append(a)
        # 名称或别名撞上已有食材，视为同一食材，只补 GI（不覆盖营养/别名/禁忌）
        hit = index.get(base) or next((index[a] for a in aliases if a in index), None)
        if hit is not None:
            if hit.get("gi") is None and gi is not None:
                hit["gi"] = gi
                updated_gi += 1
            continue
        cal = num(it.get("energyKCal"))
        protein = num(it.get("protein")) or 0.0
        fat = num(it.get("fat")) or 0.0
        carb = num(it.get("CHO")) or 0.0
        fiber = num(it.get("dietaryFiber")) or 0.0
        # 缺能量值则用宏量营养素反推（4/4/9），仍无能量来源（蛋白/脂肪/碳水全 0）则跳过
        if cal is None:
            cal = round(4 * protein + 4 * carb + 9 * fat) or None
        if cal is None and protein == 0 and fat == 0 and carb == 0:
            continue
        added.append({
            "name": base,
            "aliases": aliases,
            "category": cat,
            "calories": round(cal, 0) if cal is not None else None,
            "protein": round(protein, 1),
            "fat": round(fat, 1),
            "carb": round(carb, 1),
            "fiber": round(fiber, 1),
            "gi": gi,
            "taboo_tags": taboo_of(base, cat, gi, fat),
        })

    # 修正啤酒/可乐分类（油脂 -> 饮料）并补 GI
    drink_gi = {"啤酒": 66, "可乐": 40, "可乐饮料": 40}
    fixed = 0
    for it in existing:
        if it["name"] in ("啤酒", "可乐") and it.get("category") == "油脂":
            it["category"] = "饮料"
            it["gi"] = drink_gi.get(it["name"])
            fixed += 1
        # 给已有食材补常见别名（如 卷心菜 -> 紫甘蓝/结球甘蓝）
        for a in EXISTING_ALIAS_OVERRIDES.get(it["name"], []):
            if a not in it.setdefault("aliases", []):
                it["aliases"].append(a)

    # 按类别排序新食材，追加到末尾
    added.sort(key=lambda x: (x["category"], x["name"]))
    merged = existing + added
    json.dump(merged, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"原有食材: {len(existing)}")
    print(f"新增食材: {len(added)}")
    print(f"补齐 GI 的已有食材: {updated_gi}")
    print(f"修正分类(啤酒/可乐): {fixed}")
    print(f"合并后总数: {len(merged)}")
    # 分类统计
    from collections import Counter
    c = Counter(i["category"] for i in merged)
    print("分类分布:", dict(c))


if __name__ == "__main__":
    main()

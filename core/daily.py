# -*- coding: utf-8 -*-
"""一日饮食规划（Daily）：热量缺口计算 + 三餐安排 + 当日报告汇总。"""
import random

from core import llm
from core.health_goal import GOAL_PROFILES
from core.recommender import STAPLE

# 活动系数（前端下拉顺序）→ 乘数
ACTIVITY_FACTORS = [
    ("久坐（几乎不运动）", 1.2),
    ("轻度活动（每周 1~3 次）", 1.375),
    ("中度活动（每周 3~5 次）", 1.55),
    ("高强度活动（每周 6~7 次）", 1.725),
    ("极高强度（体力劳动/运动员）", 1.9),
]
DEFAULT_ACTIVITY = 1.375

# 健康目标 → 每日热量调整量（相对 TDEE，正=盈余，负=缺口）
GOAL_CALORIE_ADJUST = {
    "减脂": -500,
    "增肌": +300,
    "控糖": 0,
    "均衡": 0,
}

# 目标 → 缺口说明文案
GOAL_GAP_DESC = {
    "减脂": "建议每日制造约 500 kcal 热量缺口（约每周减 0.5 kg）",
    "增肌": "建议每日增加约 300 kcal 热量盈余（配合力量训练促进增肌）",
    "控糖": "维持能量平衡，重点放在低 GI 饮食与平稳血糖",
    "均衡": "维持能量平衡，保证营养全面、种类多样",
}

# 三餐名称与分配比例
MEALS = [
    ("早餐", 0.30),
    ("午餐", 0.40),
    ("晚餐", 0.30),
]


def tdee(bmr, activity):
    """由 BMR（kcal/天）与活动系数估算每日总消耗 TDEE（kcal）。"""
    if bmr is None:
        return None
    return round(bmr * activity)


def target_intake(tdee_value, goal):
    """由 TDEE + 目标调整量得到建议每日摄入（kcal）。"""
    if tdee_value is None:
        return None
    adjust = GOAL_CALORIE_ADJUST.get(goal, 0)
    return round(tdee_value + adjust)


def deficit(tdee_value, target):
    """热量缺口 = TDEE − 目标摄入（kcal）；减脂为正缺口、增肌为负（即盈余）。"""
    if tdee_value is None or target is None:
        return None
    return round(tdee_value - target)


def meal_targets(target):
    """按三餐比例拆分目标摄入，返回 [{"meal":名称, "target":kcal}]。"""
    if target is None:
        return [{"meal": name, "target": None} for name, _ in MEALS]
    return [{"meal": name, "target": round(target * ratio)} for name, ratio in MEALS]


# ---------- 三餐安排 ----------

def _goal_fit(recipe, goal, ingredient_index):
    """菜谱与健康目标的契合度（0~1）：目标命中标签 + 主料营养加权。"""
    weights = GOAL_PROFILES[goal]["score"]
    main = [i for i in recipe.get("ingredients", []) if i not in STAPLE]
    if not main:
        return 0.0

    vals = []
    for name in main:
        d = ingredient_index.get(name)
        if not d:
            continue
        p = (d["protein"] or 0.0) / 30.0
        c = (d["calories"] or 0.0) / 500.0
        f = (d["fat"] or 0.0) / 30.0
        fb = (d["fiber"] or 0.0) / 10.0
        gi_val = d["gi"] if d["gi"] is not None else 50.0
        gi = (gi_val - 50.0) / 40.0
        vals.append(weights["protein"] * p + weights["calories"] * c
                    + weights["fat"] * f + weights["fiber"] * fb + weights["gi"] * gi)
    if not vals:
        return 0.0
    nutrition = max(0.0, min(1.0, (sum(vals) / len(vals) + 0.5) / 1.0))

    tags = recipe.get("tags", [])
    if goal in tags:
        tag_match = 1.0
    elif "均衡" in tags:
        tag_match = 0.6
    else:
        tag_match = 0.3
    return 0.7 * tag_match + 0.3 * nutrition


def plan_meals(recipes, goal, ingredient_index, n_per_meal=5, shuffle=False,
               priority_names=None):
    """把（已过禁忌的）菜谱安排到三餐，每餐 n_per_meal 道。

    返回 {"早餐":[{"recipe","calories","fit"}], "午餐":[...], "晚餐":[...]}。
    - priority_names：优先置顶的菜谱名（来自「食谱推荐」页导入），总是入选。
    - shuffle：为 True 时从契合度靠前的候选中随机采样（用于「刷新」换一批）。
    分配策略：入选菜谱按 estimated_calories 升序切成三段，
    低热量 → 早餐、高热量 → 晚餐、中间 → 午餐。
    """
    priority = set(priority_names or [])
    scored = []
    for r in recipes:
        fit = _goal_fit(r, goal, ingredient_index)
        cal = float(r.get("estimated_calories") or 0)
        scored.append({
            "recipe": r, "calories": cal, "fit": round(fit, 3),
            "pinned": r.get("name") in priority,
        })

    pinned = [s for s in scored if s["pinned"]]
    rest = [s for s in scored if not s["pinned"]]
    rest.sort(key=lambda x: -x["fit"])

    total = n_per_meal * 3
    need = max(0, total - len(pinned))
    if shuffle and need > 0:
        # 从契合度前 2 倍候选里随机采样，保证每次「刷新」结果不同
        pool = rest[:need * 2]
        fill = random.Random().sample(pool, min(need, len(pool)))
    else:
        fill = rest[:need]

    chosen = pinned + fill
    chosen_sorted = sorted(chosen, key=lambda x: x["calories"])
    k = len(chosen_sorted)
    third = max(1, k // 3)
    breakfast = chosen_sorted[:third]
    dinner = chosen_sorted[k - third:] if k > third else []
    lunch = chosen_sorted[third:k - third] if k > 2 * third else []
    return {"早餐": breakfast, "午餐": lunch, "晚餐": dinner}


def plan_week(recipes, goal, ingredient_index, days=7, shuffle=False):
    """生成一周（days 天）三餐计划，每天早/午/晚各一道，尽量不重复。

    返回 [{"day":1, "meals":{"早餐":[...],"午餐":[...],"晚餐":[...]}}...]，
    每道为 {"recipe","calories","fit"}。shuffle=True 时从契合度靠前候选中随机采样换一批。
    """
    scored = []
    for r in recipes:
        fit = _goal_fit(r, goal, ingredient_index)
        cal = float(r.get("estimated_calories") or 0)
        scored.append({"recipe": r, "calories": cal, "fit": round(fit, 3)})
    scored.sort(key=lambda x: -x["fit"])

    need = days * 3
    if not scored:
        picks = []
    elif shuffle and len(scored) > need:
        rng = random.Random()
        picks = rng.sample(scored[: need * 2], need)
    else:
        reps = (need // len(scored)) + 1
        picks = (scored * reps)[:need]

    week = []
    for d in range(days):
        day_picks = sorted(picks[d * 3:(d + 1) * 3], key=lambda x: x["calories"])
        week.append({
            "day": d + 1,
            "meals": {
                "早餐": day_picks[0:1],
                "午餐": day_picks[1:2],
                "晚餐": day_picks[2:3],
            },
        })
    return week


# ---------- 实际摄入解析与汇总 ----------

def parse_manual_items(text):
    """把「菜名 热量」多行文本解析为 [{name, calories, source}]。

    每行末尾若是整数则当热量（kcal），其余部分为菜名；无数字时热量记为 0。
    """
    items = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if parts and parts[-1].isdigit():
            cal = int(parts[-1])
            name = " ".join(parts[:-1])
        else:
            cal = 0
            name = " ".join(parts)
        if name:
            items.append({"name": name, "calories": cal, "source": "手动"})
    return items


def summarize_day(target, actual):
    """汇总当日实际摄入。

    actual: {"早餐":[{"name","calories","source","note"}], ...}
    返回 {total, per_meal:{meal: total}, diff}；diff 为正=盈余、负=缺口（kcal）。
    """
    per_meal, total = {}, 0
    for meal, items in actual.items():
        s = sum(int(it.get("calories") or 0) for it in items)
        per_meal[meal] = s
        total += s
    diff = (total - target) if target is not None else None
    return {"total": total, "per_meal": per_meal, "diff": diff}


def daily_comment(goal, taboos, target, gap, actual):
    """调用大模型输出当日饮食改进建议；失败/未配置返回 None（前端降级）。"""
    if not llm.enabled():
        return None
    lines = [
        f"健康目标：{goal}（{GOAL_GAP_DESC.get(goal, '')}）",
        f"建议每日摄入：{target} kcal" if target is not None else "建议每日摄入：未知",
        f"热量缺口（TDEE−目标）：{gap} kcal" if gap is not None else "热量缺口：未知",
    ]
    if taboos:
        lines.append("需规避的禁忌：" + "、".join(taboos))
    lines.append("当日实际摄入：")
    for meal, items in actual.items():
        names = "、".join(f"{it['name']}{it.get('calories')}kcal" for it in items) or "（无）"
        lines.append(f"  {meal}：{names}")
    return llm.chat(
        system="你是一位注册营养师，请依据用户当日的目标摄入与实际摄入，"
               "给出简洁、可执行、安全（不含医疗诊断）的改进建议。"
               "请用纯文本回答，不要使用 Markdown 语法（不要 **、#、- 等符号）。",
        user="\n".join(lines),
        max_tokens=500,
    )


def calc_streak(logs):
    """计算连续打卡天数：从今天（今天未打卡则从昨天）往前推连续有记录的天数。"""
    import datetime as _dt
    if not logs:
        return 0
    days = {lg["date"] for lg in logs}
    cursor = _dt.date.today()
    if cursor.isoformat() not in days:
        cursor -= _dt.timedelta(days=1)
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor -= _dt.timedelta(days=1)
    return streak


def score_day(target, actual, gap=None):
    """给当日饮食打分（0~100）+ 星级（1~5）+ 一句评语，让热量数据更直观。

    基于实际总热量与目标摄入的偏差率：越接近目标分越高。
    target 或 actual 为空（如只看规划未记录）时返回 None。
    """
    if not target or not actual:
        return None
    total = sum(int(it.get("calories") or 0) for items in actual.values() for it in items)
    if total <= 0:
        return None
    ratio = (total - target) / float(target)  # 正=超，负=不足
    abs_ratio = abs(ratio)
    if abs_ratio <= 0.05:
        score, level = 100, "perfect"
    elif abs_ratio <= 0.15:
        score, level = 85, "good"
    elif abs_ratio <= 0.30:
        score, level = 70, "ok"
    elif abs_ratio <= 0.50:
        score, level = 55, "off"
    else:
        score, level = 40, "poor"
    stars = max(1, min(5, round(score / 20.0)))
    if level == "perfect":
        comment = "热量控制得刚刚好，继续保持！"
    elif level == "good":
        comment = "很接近目标，稍微微调就更完美了。"
    elif level == "ok":
        comment = ("今天吃得略多，下一餐可以清淡一点。"
                   if ratio > 0 else "今天吃得略少，注意别饿着哦。")
    elif level == "off":
        comment = ("今日热量偏高，建议增加蔬菜、减少主食和油脂。"
                   if ratio > 0 else "今日摄入不足，长期可能影响代谢，记得吃够。")
    else:
        comment = ("今日热量明显超标，明天注意控制份量。"
                   if ratio > 0 else "今日摄入严重不足，请务必补足能量。")
    return {
        "score": score, "stars": stars, "comment": comment,
        "total": total, "ratio": round(ratio * 100),
    }

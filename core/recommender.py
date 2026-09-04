# -*- coding: utf-8 -*-
"""食谱推荐（RecipeRecommender）：本地规则引擎 + 可选大模型增强。"""
from core import llm
from core.health_goal import GOAL_PROFILES

# 厨房常备调味/辅料，视为用户默认拥有，不计入「缺料清单」
STAPLE = {
    "食用油", "橄榄油", "花生油", "盐", "酱油", "醋", "白砂糖", "蜂蜜",
    "蚝油", "料酒", "鸡精", "大葱", "大蒜", "生姜", "香菜",
    "八角", "花椒", "香叶", "桂皮", "冰糖", "豆瓣酱", "干辣椒",
    "淀粉", "白胡椒粉", "黑胡椒", "番茄酱", "香油", "啤酒", "可乐",
}


class RecipeRecommender:
    """基于「食材覆盖度 + 目标匹配 + 营养适配」的规则推荐。"""

    def __init__(self, ingredient_index, recipes):
        self.ingredient_index = ingredient_index
        self.recipes = recipes

    # ---------- 营养适配分 ----------
    def _nutrition_fitness(self, ing_names, weights):
        """对一组食材按目标权重计算归一化的营养适配分（0~1）。"""
        vals = []
        for name in ing_names:
            d = self.ingredient_index.get(name)
            if not d:
                continue
            p = (d["protein"] or 0.0) / 30.0      # 蛋白 30g 记高分
            c = (d["calories"] or 0.0) / 500.0    # 热量 500kcal 记高
            f = (d["fat"] or 0.0) / 30.0          # 脂肪 30g 记高脂
            fb = (d["fiber"] or 0.0) / 10.0       # 纤维 10g 记高纤
            gi_val = d["gi"] if d["gi"] is not None else 50.0
            gi = (gi_val - 50.0) / 40.0           # GI 归一化到约 [-1, 1]
            score = (weights["protein"] * p + weights["calories"] * c
                     + weights["fat"] * f + weights["fiber"] * fb + weights["gi"] * gi)
            vals.append(score)
        if not vals:
            return 0.5
        avg = sum(vals) / len(vals)
        return max(0.0, min(1.0, (avg + 0.5) / 1.0))

    # ---------- 单道菜打分 ----------
    def _score_recipe(self, recipe, available_names, goal):
        weights = GOAL_PROFILES[goal]["score"]
        main = [i for i in recipe["ingredients"] if i not in STAPLE]
        # 主料为空（纯调味料）不参与推荐，避免「无主料却满覆盖度」的假高分
        if not main:
            return None
        avail = [i for i in main if i in available_names]
        missing = [i for i in main if i not in available_names]
        coverage = len(avail) / len(main)

        tags = recipe.get("tags", [])
        if goal in tags:
            tag_match = 1.0
        elif "均衡" in tags:
            tag_match = 0.6
        else:
            tag_match = 0.3

        # 主料加权：鼓励优先推荐「主料更丰富、且能用上用户更多现有食材」的菜，
        # 避免只有 1 个主料就 100% 覆盖的过简菜抢占排名。
        richness = min(len(main), 4) / 4.0           # 主料丰富度（0.25~1.0，≥4 封顶）
        utilization = len(avail) / max(len(available_names), 1)  # 食材利用率

        # 仅对主食材（不含油盐等常备调味料）计算营养适配分
        nutrition = self._nutrition_fitness(main, weights)
        # 覆盖度主导 + 主料加权 + 目标匹配 + 营养适配
        score = (45 * coverage + 10 * richness + 15 * utilization
                 + 20 * tag_match + 10 * nutrition)
        return score, avail, missing, coverage

    # ---------- 推荐入口 ----------
    def recommend(self, available_ingredients, goal, top_n=3):
        """返回按得分降序的推荐结果（含可用/缺料/食材匹配度信息）。"""
        available_names = {d["name"] for d in available_ingredients}
        results = []
        for recipe in self.recipes:
            scored = self._score_recipe(recipe, available_names, goal)
            if scored is None:
                continue
            score, avail, missing, coverage = scored
            results.append({
                "recipe": recipe,
                "score": round(score, 2),
                "available": avail,
                "missing": missing,
                "coverage": round(coverage, 2),
            })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_n]

    # ---------- 可选大模型增强 ----------
    def llm_enabled(self):
        return llm.enabled()

    def llm_enhance(self, profile, ingredient_names, top_recipes):
        """调用 DeepSeek 生成增强文案；未配置 key 或失败时返回 None（降级）。"""
        return llm.chat(
            system="你是一位注册营养师，请基于给定食材与健康目标，"
                   "给出简洁、可执行、安全（不含医疗建议）的个性化食谱与搭配建议。"
                   "请用纯文本回答，不要使用 Markdown 语法（不要 **、#、- 等符号）。",
            user=self._build_prompt(profile, ingredient_names, top_recipes),
        )

    @staticmethod
    def _build_prompt(profile, ingredient_names, top_recipes):
        lines = [
            f"健康目标：{profile['goal']}（{profile['goal_desc']}）",
            "现有食材：" + "、".join(ingredient_names) if ingredient_names else "现有食材：（无）",
        ]
        if profile.get("taboos"):
            lines.append("需规避的禁忌：" + "、".join(profile["taboos"]))
        lines.append("规则引擎初筛候选：")
        for r in top_recipes:
            lines.append(f"- {r['recipe']['name']}（可用：{'、'.join(r['available']) or '无'}；"
                         f"缺：{'、'.join(r['missing']) or '无'}）")
        lines.append("请从中推荐 1~2 道最合适的菜，并简要说明理由与搭配建议。")
        return "\n".join(lines)

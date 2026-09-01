# -*- coding: utf-8 -*-
"""搭配建议与禁忌过滤（DietAdvisor）。"""

# 各健康目标的搭配建议文案
GOAL_ADVICE = {
    "减脂": [
        "优先蒸、煮、炖、拌，少油少盐，控制每餐总热量",
        "多选高蛋白低脂食材（鸡胸、鱼虾、蛋、豆制品），搭配足量蔬菜",
        "主食可换成糙米、燕麦等粗粮，增加饱腹感、稳定血糖",
    ],
    "增肌": [
        "保证每餐优质蛋白（鸡胸、鱼虾、蛋奶、豆制品）",
        "训练后 30 分钟内补充蛋白质 + 碳水，促进恢复",
        "适量增加主食摄入，保证训练能量充足",
    ],
    "控糖": [
        "优先选择低 GI 食材，避免精制糖与高升糖主食",
        "主食粗细搭配，先吃蔬菜再吃主食，延缓血糖上升",
        "水果选低糖品种（柚子、草莓、樱桃等），控制份量",
    ],
    "均衡": [
        "荤素搭配，主食粗细结合，种类多样",
        "每天保证足量蔬菜、优质蛋白与适量水果",
        "减少油炸、高糖、高盐，培养长期健康饮食习惯",
    ],
}


class DietAdvisor:
    """对食材/菜谱做过敏原与慢病禁忌过滤，并给出搭配建议。"""

    def __init__(self, ingredient_index, taboo_tags=None):
        self.ingredient_index = ingredient_index
        self.taboo_tags = set(taboo_tags or [])

    def filter_ingredients(self, items):
        """返回 (通过项, 被滤项)；被滤项携带命中的禁忌标签。"""
        safe, filtered = [], []
        for d in items:
            hit = set(d.get("taboo_tags", [])) & self.taboo_tags
            if hit:
                filtered.append({"item": d, "tags": sorted(hit)})
            else:
                safe.append(d)
        return safe, filtered

    def filter_recipes(self, recipes):
        """剔除含禁忌食材的菜谱，返回 (通过项, 被滤项)。"""
        safe, filtered = [], []
        for r in recipes:
            hit_tags = set()
            for ing_name in r["ingredients"]:
                d = self.ingredient_index.get(ing_name)
                if d:
                    hit_tags |= set(d.get("taboo_tags", [])) & self.taboo_tags
            if hit_tags:
                filtered.append({"recipe": r, "tags": sorted(hit_tags)})
            else:
                safe.append(r)
        return safe, filtered

    def suggest_pairing(self, goal):
        """按健康目标返回搭配建议列表。"""
        return GOAL_ADVICE.get(goal, GOAL_ADVICE["均衡"])

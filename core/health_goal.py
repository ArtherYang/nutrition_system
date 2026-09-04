# -*- coding: utf-8 -*-
"""健康目标管理（HealthGoalManager）：目标画像 + 禁忌/过敏原。"""
import config

# 各健康目标的评分权重与说明（权重作用于归一化后的营养维度，用于菜谱打分）
GOAL_PROFILES = {
    "减脂": {
        "desc": "控制总热量，高蛋白低脂肪，优先高纤蔬菜",
        "score": {"protein": 0.5, "calories": -0.3, "fat": -0.4, "fiber": 0.2, "gi": 0.0},
    },
    "增肌": {
        "desc": "高蛋白、充足碳水，保证训练恢复",
        "score": {"protein": 0.6, "calories": 0.0, "fat": -0.2, "fiber": 0.1, "gi": 0.0},
    },
    "控糖": {
        "desc": "低升糖指数（GI），平稳血糖",
        "score": {"protein": 0.1, "calories": -0.1, "fat": -0.2, "fiber": 0.2, "gi": -0.6},
    },
    "均衡": {
        "desc": "营养均衡，荤素搭配，种类多样",
        "score": {"protein": 0.2, "calories": -0.05, "fat": -0.1, "fiber": 0.2, "gi": -0.1},
    },
}

# 慢病禁忌 → 食材 taboo_tags 中的过滤标签（可多标签）。
# 痛风/高尿酸血症除「高嘌呤」外还规避「海鲜」——海鲜嘌呤含量普遍较高，
# 而营养库中海鲜主要被打上过敏原「海鲜」标签，仅 4 种被标「高嘌呤」。
CONDITION_TAG_MAP = {
    "糖尿病（控糖）": ["高GI"],
    "痛风（高嘌呤）": ["高嘌呤", "海鲜"],
    "高血压（高钠）": ["高钠"],
    "高血脂（高脂）": ["高脂"],
    "脂肪肝": ["高脂"],
    "冠心病": ["高脂"],
    "胆结石/胆囊炎": ["高脂"],
    "甲亢（忌碘）": ["高碘"],
    "高尿酸血症": ["高嘌呤", "海鲜"],
}


class HealthGoalManager:
    """管理用户健康目标与个人禁忌，输出用户画像。"""

    def __init__(self, goal="均衡"):
        self.goal = goal
        self.taboos = []  # 用户勾选的禁忌项（过敏原 + 慢病）

    def set_goal(self, goal):
        if goal not in config.GOALS:
            raise ValueError(f"未知健康目标: {goal}")
        self.goal = goal

    def add_taboo(self, item):
        if item and item not in self.taboos:
            self.taboos.append(item)

    def add_taboos(self, items):
        for it in items or []:
            self.add_taboo(it)

    def taboo_tags(self):
        """把用户勾选的禁忌项转换为食材 taboo_tags 标签集合。"""
        tags = set()
        for t in self.taboos:
            if t in config.TABOO_OPTIONS and config.TABOO_OPTIONS[t] == "过敏原":
                tags.add(t)
            elif t in CONDITION_TAG_MAP:
                tags.update(CONDITION_TAG_MAP[t])
        return tags

    def get_profile(self):
        """返回用户画像（目标 + 目标说明 + 评分权重 + 禁忌）。"""
        return {
            "goal": self.goal,
            "goal_desc": GOAL_PROFILES[self.goal]["desc"],
            "score_weights": GOAL_PROFILES[self.goal]["score"],
            "taboos": list(self.taboos),
            "taboo_tags": sorted(self.taboo_tags()),
        }

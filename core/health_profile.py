# -*- coding: utf-8 -*-
"""健康画像（HealthProfile）：基于年龄/性别/身高/体重计算 BMI、基础代谢等。"""
from core import llm

GENDERS = ["男", "女"]


def _to_float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_int(v):
    f = _to_float(v)
    return int(f) if f is not None else None


class HealthProfile:
    """按可选的年龄/性别/身高(cm)/体重(kg)计算健康指标。"""

    def __init__(self, age=None, gender=None, height=None, weight=None):
        self.age = _to_int(age)
        self.gender = gender if gender in GENDERS else None
        self.height = _to_float(height)  # cm
        self.weight = _to_float(weight)  # kg

    # ---------- 是否具备计算条件 ----------
    def has_bmi(self):
        return self.height and self.weight

    def has_bmr(self):
        return all([self.age, self.gender, self.height, self.weight])

    # ---------- 指标计算 ----------
    def bmi(self):
        """体重指数 = 体重(kg) / 身高(m)^2。"""
        if not self.has_bmi():
            return None
        h_m = self.height / 100.0
        return round(self.weight / (h_m * h_m), 1)

    def bmi_category(self):
        b = self.bmi()
        if b is None:
            return None
        if b < 18.5:
            return "偏瘦"
        if b < 24:
            return "正常"
        if b < 28:
            return "超重"
        return "肥胖"

    def bmr(self):
        """基础代谢率（Mifflin-St Jeor），单位 kcal/天。"""
        if not self.has_bmr():
            return None
        base = 10 * self.weight + 6.25 * self.height - 5 * self.age
        base += 5 if self.gender == "男" else -161
        return round(base, 0)

    def ideal_weight_range(self):
        """按 BMI 18.5~24 反推理想体重区间（kg）。"""
        if not self.has_bmi():
            return None
        h_m = self.height / 100.0
        low = round(18.5 * h_m * h_m, 1)
        high = round(24 * h_m * h_m, 1)
        return f"{low} ~ {high} kg"

    # ---------- 汇总 + 软建议 ----------
    def goal_hint(self, goal):
        """当 BMI 与所选目标明显冲突时给出软性建议，否则返回 None。"""
        cat = self.bmi_category()
        if cat is None or goal is None:
            return None
        if cat in ("超重", "肥胖") and goal == "增肌":
            return f"你的 BMI 处于「{cat}」区间，当前选择「增肌」可能进一步增加体重负担，建议优先考虑「减脂」或「均衡」。"
        if cat == "偏瘦" and goal == "减脂":
            return f"你的 BMI 偏低（{cat}），不建议继续减脂，建议选择「增肌」或「均衡」目标。"
        return None

    def summarize(self, goal=None):
        """返回本地健康评估结果，供模板与 AI 点评使用。"""
        return {
            "has_profile": self.has_bmi() or self.has_bmr(),
            "age": self.age,
            "gender": self.gender,
            "height": self.height,
            "weight": self.weight,
            "bmi": self.bmi(),
            "bmi_category": self.bmi_category(),
            "bmr": self.bmr(),
            "ideal_range": self.ideal_weight_range(),
            "goal_hint": self.goal_hint(goal),
        }

    def llm_comment(self, goal):
        """可选：调用大模型生成健康状况点评；失败返回 None。"""
        s = self.summarize(goal)
        if not s["has_profile"]:
            return None
        lines = [
            f"年龄：{self.age or '未知'}岁，性别：{self.gender or '未知'}",
            f"身高：{self.height or '未知'}cm，体重：{self.weight or '未知'}kg",
            f"BMI：{s['bmi'] if s['bmi'] is not None else '未知'}"
            f"（{s['bmi_category'] or '未知'}），基础代谢约 {s['bmr'] or '未知'} kcal/天",
            f"健康目标：{goal or '未选择'}",
        ]
        return llm.chat(
            system="你是一位注册营养师，请依据用户的基础健康数据，"
                   "给出简洁、安全（不含医疗诊断）的健康状况解读与膳食目标建议。",
            user="\n".join(lines),
            max_tokens=400,
        )

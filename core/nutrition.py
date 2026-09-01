# -*- coding: utf-8 -*-
"""营养分析（NutritionAnalyzer）：食材营养查询与多食材汇总。"""


class NutritionAnalyzer:
    """基于内存索引（{名称/别名 -> 食材 dict}）的营养查询与汇总。"""

    def __init__(self, ingredient_index):
        self.index = ingredient_index

    def analyze(self, name):
        """按名称或别名查单个食材营养；未命中返回 None。"""
        return self.index.get(name.strip()) if name else None

    def resolve(self, names):
        """把用户输入的食材列表解析为 (命中项列表, 未命中名列表)。

        按规范名去重：别名与规范名指向同一食材时只保留一次。
        """
        matched, missing = [], []
        seen_ing, seen_miss = set(), set()
        for raw in names:
            name = raw.strip()
            if not name:
                continue
            d = self.index.get(name)
            if d:
                if d["name"] not in seen_ing:
                    seen_ing.add(d["name"])
                    matched.append(d)
            elif name not in seen_miss:
                seen_miss.add(name)
                missing.append(name)
        return matched, missing

    @staticmethod
    def calc_total(items, grams=100.0):
        """按每 100g 数值汇总多个食材（默认各 100g 估算）。"""
        total = {"calories": 0.0, "protein": 0.0, "fat": 0.0, "carb": 0.0, "fiber": 0.0}
        for d in items:
            for key in total:
                total[key] += (d[key] or 0.0) * grams / 100.0
        return total

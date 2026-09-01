# -*- coding: utf-8 -*-
"""智能营养膳食制作与推荐系统 V1.1 —— Flask Web 应用入口。

启动：在项目根目录执行  python app.py  ，然后浏览器访问 http://127.0.0.1:5000

V1.1 新增：健康画像（BMI/BMR）、基础疾病禁忌、冰箱图片识别、地区×季节买菜推荐。
"""
import datetime
import os
import re

from flask import Flask, render_template, request

import config
from database import db
from core.health_goal import HealthGoalManager
from core.nutrition import NutritionAnalyzer
from core.recommender import RecipeRecommender
from core.diet_advisor import DietAdvisor
from core.health_profile import HealthProfile
from core.recognizer import IngredientRecognizer
from core import market as market_mod

app = Flask(__name__)

_INGREDIENT_INDEX = None
_RECIPES = None
_RECOGNIZER = None


def get_data():
    """懒加载：确保数据库已初始化，并加载营养库 / 菜谱库到内存。"""
    global _INGREDIENT_INDEX, _RECIPES
    if _INGREDIENT_INDEX is None:
        if not os.path.exists(config.DB_PATH):
            conn = db.get_connection()
            db.create_tables(conn)
            db.seed_from_json(conn)
            conn.close()
        conn = db.get_connection()
        _INGREDIENT_INDEX = db.load_ingredients(conn)
        _RECIPES = db.load_recipes(conn)
        conn.close()
    return _INGREDIENT_INDEX, _RECIPES


def get_recognizer():
    """懒加载识别器（YOLO 模型只加载一次）。"""
    global _RECOGNIZER
    if _RECOGNIZER is None:
        _RECOGNIZER = IngredientRecognizer()
    return _RECOGNIZER


def parse_ingredients(text):
    """按逗号 / 顿号 / 空格 / 换行切分食材名。"""
    parts = re.split(r"[,，、\s]+", text or "")
    return [p for p in parts if p]


def _safe_month(value):
    try:
        m = int(value)
        return m if 1 <= m <= 12 else 1
    except (TypeError, ValueError):
        return 1


@app.route("/")
def index():
    return render_template(
        "index.html",
        goals=config.GOALS,
        taboo_options=config.TABOO_OPTIONS,
        ingredients_input=request.args.get("ingredients", ""),
        age=None, gender=None, height=None, weight=None,
        recognize_done=False, recognized=[], recognized_mode="",
    )


@app.route("/recognize", methods=["POST"])
def recognize():
    """独立图片识别：识别后把结果回填到食材文本框，再由用户走文字推荐。"""
    image_file = request.files.get("image")
    recognized, recognized_mode = [], ""
    if image_file and image_file.filename:
        rec = get_recognizer()
        image_bytes = image_file.read()
        recognized = rec.recognize_with_vision(image_bytes)
        if recognized:
            recognized_mode = "视觉大模型"
        else:
            recognized = rec.recognize(image_bytes)
            recognized_mode = "YOLO"
    # 与文本框中已有食材合并（已有在前，识别结果追加，去重）
    existing = request.form.get("existing", "")
    names = [n for n in re.split(r"[,，、\s]+", existing) if n]
    for r in recognized:
        if r["name"] not in names:
            names.append(r["name"])
    return render_template(
        "index.html",
        goals=config.GOALS,
        taboo_options=config.TABOO_OPTIONS,
        recognize_done=True,
        recognized=recognized,
        recognized_mode=recognized_mode,
        ingredients_input=" ".join(names),
        age=None, gender=None, height=None, weight=None,
    )


@app.route("/recommend", methods=["POST"])
def recommend():
    ingredient_index, recipes = get_data()

    goal = request.form.get("goal", "均衡")
    if goal not in config.GOALS:
        goal = "均衡"
    taboos = request.form.getlist("taboos")
    raw_names = parse_ingredients(request.form.get("ingredients", ""))

    # 1. 健康目标 + 禁忌画像
    goal_mgr = HealthGoalManager(goal)
    goal_mgr.add_taboos(taboos)
    profile = goal_mgr.get_profile()

    # 1.5 健康档案评估（BMI / BMR / 理想体重 + 可选 AI 点评）
    health = HealthProfile(
        age=request.form.get("age"),
        gender=request.form.get("gender"),
        height=request.form.get("height"),
        weight=request.form.get("weight"),
    )
    health_summary = health.summarize(goal)
    health_comment = health.llm_comment(goal)

    # 2. 食材解析 + 营养分析
    analyzer = NutritionAnalyzer(ingredient_index)
    matched, missing = analyzer.resolve(raw_names)

    # 3. 禁忌过滤（食材 + 菜谱）
    advisor = DietAdvisor(ingredient_index, profile["taboo_tags"])
    safe_ingredients, filtered_ingredients = advisor.filter_ingredients(matched)
    safe_recipe_pool, filtered_recipes = advisor.filter_recipes(recipes)

    # 4. 规则推荐
    recommender = RecipeRecommender(ingredient_index, safe_recipe_pool)
    top = recommender.recommend(safe_ingredients, goal, top_n=3)

    # 5. 营养汇总（每种食材按 100g 估算）
    totals = (
        NutritionAnalyzer.calc_total(safe_ingredients) if safe_ingredients else None
    )

    # 6. 可选大模型增强
    llm_text = recommender.llm_enhance(
        profile, [d["name"] for d in safe_ingredients], top
    )

    return render_template(
        "index.html",
        goals=config.GOALS,
        taboo_options=config.TABOO_OPTIONS,
        submitted=True,
        goal=goal,
        taboos=taboos,
        ingredients_input=request.form.get("ingredients", ""),
        age=request.form.get("age"),
        gender=request.form.get("gender"),
        height=request.form.get("height"),
        weight=request.form.get("weight"),
        recognize_done=False,
        health=health_summary,
        health_comment=health_comment,
        profile=profile,
        matched=safe_ingredients,
        missing=missing,
        filtered_ingredients=filtered_ingredients,
        filtered_recipe_names=[f["recipe"]["name"] for f in filtered_recipes],
        recommendations=top,
        totals=totals,
        advice=advisor.suggest_pairing(goal),
        llm_text=llm_text,
    )


@app.route("/market", methods=["GET", "POST"])
def market():
    if request.method == "POST":
        region = request.form.get("region", "华北")
        month = _safe_month(request.form.get("month"))
    else:
        region = "华北"
        month = datetime.date.today().month
    selected = market_mod.recommend(region, month)
    ingredient_param = " ".join(market_mod.combined_names(selected))
    return render_template(
        "market.html",
        regions=market_mod.REGIONS,
        months=market_mod.MONTHS,
        selected=selected,
        ingredient_param=ingredient_param,
    )


if __name__ == "__main__":
    app.run(debug=True)

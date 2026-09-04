# -*- coding: utf-8 -*-
"""知食分子 V1.1 —— Flask Web 应用入口。

启动：在项目根目录执行  python app.py  ，然后浏览器访问 http://127.0.0.1:5000

V1.1 新增：健康画像（BMI/BMR）、基础疾病禁忌、冰箱图片识别、地区×季节买菜推荐。
"""
import datetime
import os
import random
import re
import time
from urllib.parse import urlencode

from flask import Flask, jsonify, render_template, request, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

import config
from database import db
from core.health_goal import HealthGoalManager
from core.nutrition import NutritionAnalyzer
from core.recommender import RecipeRecommender, STAPLE
from core.diet_advisor import DietAdvisor
from core.health_profile import HealthProfile
from core.recognizer import IngredientRecognizer
from core import health_report as report_mod
from core import llm
from core import market as market_mod
from core import produce as produce_mod
from core import daily as daily_mod
from core import meal_photo as meal_photo_mod
from core import achievements as ach_mod

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 上传体积上限 10MB

# 简单内存限流：{key: [最近请求时间戳]}，用于大模型端点防刷
_RATE_LIMIT = {}


def _rate_limited(key, limit=20, window=60):
    """滑动窗口限流：key 在 window 秒内最多 limit 次。超限返回 True。"""
    now = time.time()
    ts = [t for t in _RATE_LIMIT.get(key, []) if now - t < window]
    if len(ts) >= limit:
        _RATE_LIMIT[key] = ts
        return True
    ts.append(now)
    _RATE_LIMIT[key] = ts
    return False


@app.errorhandler(404)
def _not_found(e):
    return render_template("error.html", code=404, msg="页面不存在"), 404


@app.errorhandler(413)
def _too_large(e):
    return render_template("error.html", code=413, msg="上传文件过大（超过 10MB）"), 413


@app.errorhandler(500)
def _server_error(e):
    return render_template("error.html", code=500, msg="服务器内部错误，请稍后重试"), 500

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


def parse_taboos(value):
    """把逗号分隔的禁忌字符串解析为列表（用于 URL query 参数传递）。"""
    if not value:
        return []
    return [t.strip() for t in value.split(",") if t.strip()]


def _request_goal(default="均衡"):
    """从 query 或 form 读取健康目标，非法值回退默认。"""
    goal = request.values.get("goal", default)
    return goal if goal in config.GOALS else default


def _request_taboos():
    """从 query 或 form 读取禁忌项列表（兼容复选框 / 逗号串 / 多值三种来源）。"""
    values = request.form.getlist("taboos")
    if not values:
        values = request.args.getlist("taboos")
    out = []
    for v in values:
        out.extend(parse_taboos(v))
    return out


def _suggest_goal(summary):
    """按 BMI 类别给出健康目标建议；无 BMI 数据时返回 None。"""
    cat = (summary or {}).get("bmi_category")
    if cat in ("超重", "肥胖"):
        return "减脂"
    if cat == "偏瘦":
        return "增肌"
    if (summary or {}).get("bmi") is not None:
        return "均衡"
    return None


def _build_chat_context(goal, taboos, ingredient_names, recipes):
    """构建可交互点评师的对话上下文（随每次追问回传，保证多轮记忆）。"""
    return {
        "goal": goal,
        "taboos": list(taboos),
        "ingredients": ingredient_names,
        "recipes": [{"name": r["recipe"]["name"]} for r in recipes],
    }


def _build_chat_system(ctx):
    """由上下文拼出营养师 system 提示。"""
    lines = [
        "你是一位注册营养师，正在与用户进行关于本次膳食推荐的对话。",
        "请基于以下背景，简洁、友好、安全地作答（不提供医疗诊断建议），"
        "并用纯文本回答，不要使用 Markdown 语法（不要 **、#、- 等符号）。",
        f"健康目标：{ctx.get('goal', '均衡')}",
    ]
    if ctx.get("taboos"):
        lines.append("需规避的禁忌：" + "、".join(ctx["taboos"]))
    if ctx.get("ingredients"):
        lines.append("用户现有食材：" + "、".join(ctx["ingredients"]))
    if ctx.get("recipes"):
        lines.append("已推荐菜谱：" + "、".join(r["name"] for r in ctx["recipes"]))
    # 一日饮食规划上下文（可选）
    if ctx.get("target") is not None:
        lines.append(f"建议每日摄入：{ctx['target']} kcal")
    if ctx.get("gap") is not None:
        lines.append(f"热量缺口（TDEE−目标）：{ctx['gap']} kcal")
    if ctx.get("actual"):
        lines.append("当日实际摄入：" + "、".join(
            f"{m} {v}kcal" for m, v in ctx["actual"].items()))
    return "\n".join(lines)


def _safe_month(value):
    try:
        m = int(value)
        return m if 1 <= m <= 12 else 1
    except (TypeError, ValueError):
        return 1


def current_user_id():
    """返回当前登录用户 id；未登录返回 None。"""
    return session.get("user_id")


def _current_username():
    """返回当前登录用户名（未登录返回 None）。"""
    uid = current_user_id()
    if not uid:
        return None
    conn = db.get_connection()
    db.ensure_users_table(conn)
    u = db.get_user_by_id(conn, uid)
    conn.close()
    return u["username"] if u else None


def _load_saved_profile(user_id=None):
    """读取已持久化的健康档案；未登录（无 user_id）返回空 dict。"""
    if user_id is None:
        user_id = current_user_id()
    if not user_id:
        return {}
    conn = db.get_connection()
    db.ensure_profile_table(conn)
    saved = db.load_profile(conn, user_id)
    conn.close()
    return saved or {}


@app.context_processor
def inject_user():
    """向所有模板注入当前登录用户名 + 烹饪方式 emoji 映射。"""
    return {"current_user": _current_username(), "method_emoji": config.METHOD_EMOJI}


@app.route("/register", methods=["GET", "POST"])
def register():
    """注册：成功后自动登录并跳转到健康档案。"""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        error = None
        if not username or not password:
            error = "请填写用户名和密码"
        elif len(username) > 32:
            error = "用户名不能超过 32 个字符"
        elif len(password) < 4:
            error = "密码至少 4 位"
        elif password != confirm:
            error = "两次输入的密码不一致"
        if not error:
            conn = db.get_connection()
            db.ensure_users_table(conn)
            uid = db.create_user(conn, username, generate_password_hash(password))
            conn.close()
            if uid is None:
                error = "用户名已存在，请直接登录"
            else:
                session["user_id"] = uid
                return redirect(url_for("profile"))
        return render_template("register.html", error=error, username=username)
    return render_template("register.html", error=None, username="")


@app.route("/login", methods=["GET", "POST"])
def login():
    """登录。"""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = db.get_connection()
        db.ensure_users_table(conn)
        u = db.get_user_by_username(conn, username)
        conn.close()
        if u and check_password_hash(u["password_hash"], password):
            session["user_id"] = u["id"]
            return redirect(url_for("profile"))
        return render_template("login.html", error="用户名或密码错误", username=username)
    return render_template("login.html", error=None, username="")


@app.route("/logout")
def logout():
    """退出登录。"""
    session.pop("user_id", None)
    return redirect(url_for("home"))


@app.route("/")
def home():
    """封面入口页：欢迎页，链接到四大功能模块。"""
    saved = _load_saved_profile()
    return render_template("home.html", profile_loaded=bool(saved))


@app.route("/recipes")
def index():
    # 健康上下文：闭环 URL 参数优先，其次已存档案（健康档案为唯一权威来源）
    saved = _load_saved_profile()
    goal = request.args.get("goal") or saved.get("goal") or "均衡"
    if goal not in config.GOALS:
        goal = "均衡"
    taboos = parse_taboos(request.args.get("taboos", ""))
    if not taboos:
        taboos = saved.get("taboos", [])
    preset_health = (
        HealthProfile(
            age=saved.get("age"), gender=saved.get("gender"),
            height=saved.get("height"), weight=saved.get("weight"),
        ).summarize(goal)
        if saved else None
    )
    return render_template(
        "index.html",
        goals=config.GOALS,
        taboo_options=config.TABOO_OPTIONS,
        ingredients_input=request.args.get("ingredients", ""),
        preset_goal=goal,
        preset_taboos=taboos,
        age=None, gender=None, height=None, weight=None,
        profile_loaded=bool(saved),
        preset_health=preset_health,
        recognize_done=False, recognized=[], recognized_mode="",
    )


@app.route("/library")
def library():
    """知识库：集中展示并可检索全部食材营养库与菜谱库。"""
    ingredient_index, recipes = get_data()
    # 营养索引含别名条目（同一食材多条），按 id 去重取规范条目
    ingredients = list({d["id"]: d for d in ingredient_index.values()}.values())
    ingredients.sort(key=lambda d: (d.get("category") or "其他", d.get("name") or ""))
    recipes = sorted(recipes, key=lambda r: (r.get("region") or "", r.get("name") or ""))
    categories = sorted({d.get("category") or "其他" for d in ingredients})
    methods = sorted({r.get("method") or "其他" for r in recipes})
    return render_template(
        "library.html",
        ingredients=ingredients,
        recipes=recipes,
        categories=categories,
        methods=methods,
    )


@app.route("/recognize", methods=["POST"])
def recognize():
    """独立图片识别：识别后把结果回填到食材文本框，再由用户走文字推荐。"""
    if _rate_limited(f"rec:{request.remote_addr}", limit=10, window=60):
        return render_template("error.html", code=429, msg="请求过于频繁，请稍后再试"), 429
    saved = _load_saved_profile()
    recognized, recognized_mode = [], ""
    image_files = [f for f in request.files.getlist("image") if f and f.filename and (f.content_type or "").startswith("image/")]
    if image_files:
        rec = get_recognizer()
        best, vision_hit, yolo_hit = {}, False, False
        for image_file in image_files:
            image_bytes = image_file.read()
            items = rec.recognize_with_vision(image_bytes)
            if items:
                vision_hit = True
            else:
                items = rec.recognize(image_bytes)
                if items:
                    yolo_hit = True
            for r in (items or []):
                if r["confidence"] > best.get(r["name"], -1.0):
                    best[r["name"]] = r["confidence"]
        recognized = sorted(
            [{"name": n, "confidence": c} for n, c in best.items()],
            key=lambda x: x["confidence"], reverse=True,
        )
        if vision_hit:
            recognized_mode = "视觉大模型"
        elif yolo_hit:
            recognized_mode = "YOLO"
    # 与文本框中已有食材合并（已有在前，识别结果追加，去重）
    existing = request.form.get("existing", "")
    names = [n for n in re.split(r"[,，、\s]+", existing) if n]
    for r in recognized:
        if r["name"] not in names:
            names.append(r["name"])
    goal = _request_goal(saved.get("goal") or "均衡")
    taboos = _request_taboos()
    if not taboos:
        taboos = saved.get("taboos", [])
    preset_health = (
        HealthProfile(
            age=saved.get("age"), gender=saved.get("gender"),
            height=saved.get("height"), weight=saved.get("weight"),
        ).summarize(goal)
        if saved else None
    )
    return render_template(
        "index.html",
        goals=config.GOALS,
        taboo_options=config.TABOO_OPTIONS,
        recognize_done=True,
        recognized=recognized,
        recognized_mode=recognized_mode,
        ingredients_input=" ".join(names),
        preset_goal=goal,
        preset_taboos=taboos,
        age=None, gender=None, height=None, weight=None,
        profile_loaded=bool(saved),
        preset_health=preset_health,
    )


@app.route("/recommend", methods=["POST"])
def recommend():
    ingredient_index, recipes = get_data()

    # 健康上下文：表单参数优先，其次已存档案（身高体重仅来自档案）
    saved = _load_saved_profile()
    goal = request.form.get("goal") or saved.get("goal") or "均衡"
    if goal not in config.GOALS:
        goal = "均衡"
    taboos = request.form.getlist("taboos")
    if not taboos:
        taboos = saved.get("taboos", [])
    raw_names = parse_ingredients(request.form.get("ingredients", ""))

    # 1. 健康目标 + 禁忌画像
    goal_mgr = HealthGoalManager(goal)
    goal_mgr.add_taboos(taboos)
    profile = goal_mgr.get_profile()

    # 1.5 健康档案评估（BMI / BMR / 理想体重 + 可选 AI 点评）
    health = HealthProfile(
        age=request.form.get("age") or saved.get("age"),
        gender=request.form.get("gender") or saved.get("gender"),
        height=request.form.get("height") or saved.get("height"),
        weight=request.form.get("weight") or saved.get("weight"),
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

    # 6.5 AI 分析食材营养成分（针对健康目标解读宏观营养 + 搭配）
    nutrition_llm = None
    if llm.enabled() and safe_ingredients:
        ing_lines = []
        for d in safe_ingredients:
            gi_text = f"{d['gi']:.0f}" if d.get("gi") is not None else "未知"
            ing_lines.append(
                f"{d['name']}（每100g：热量 {d['calories']:.0f} kcal，"
                f"蛋白质 {d['protein']:.1f} g，脂肪 {d['fat']:.1f} g，"
                f"碳水 {d['carb']:.1f} g，纤维 {d['fiber']:.1f} g，GI {gi_text}）"
            )
        nutrition_llm = llm.chat(
            system="你是一位注册营养师。请依据用户提供的食材与健康目标，"
                   "分析这批食材的营养成分特点（宏观营养素、热量、GI），"
                   "指出它们是否符合该目标、哪些食材值得保留、哪些需要控制摄入，"
                   "并给出更合理的搭配建议。请用纯文本回答，不要使用 Markdown 语法。",
            user=f"健康目标：{goal}\n" + "\n".join(ing_lines),
            max_tokens=500,
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
        preset_goal=goal,
        preset_taboos=taboos,
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
        nutrition_llm=nutrition_llm,
        llm_enabled=llm.enabled(),
        chat_context=_build_chat_context(
            goal, taboos, [d["name"] for d in safe_ingredients], top
        ),
    )


@app.route("/market", methods=["GET", "POST"])
def market():
    # 健康上下文：闭环参数优先，其次已存档案（未建档用户仍可直接用）
    saved = _load_saved_profile()
    goal = _request_goal(saved.get("goal") or "均衡")
    taboos = _request_taboos()
    if not taboos:
        taboos = saved.get("taboos", [])

    if request.method == "POST":
        region = request.form.get("region", "华北")
        month = _safe_month(request.form.get("month"))
    else:
        region = "华北"
        month = datetime.date.today().month

    selected = market_mod.recommend(region, month)

    # 健康过滤：按目标 + 禁忌剔除不适宜食材（有健康上下文时才加载营养库过滤）
    filtered_info = []
    if taboos or goal != "均衡":
        ingredient_index, _ = get_data()
        goal_mgr = HealthGoalManager(goal)
        goal_mgr.add_taboos(taboos)
        selected, filtered_info = market_mod.apply_health_filter(
            selected, ingredient_index, goal_mgr.taboo_tags(), goal
        )

    # 买菜照片评估（可选）：识别食材 + 新鲜度，配参考价区间（支持多张，按食材名去重合并）
    produce_items, produce_status = [], ""
    produce_photos = [f for f in request.files.getlist("produce_photo") if f and f.filename and (f.content_type or "").startswith("image/")]
    if produce_photos:
        if not config.VISION_API_KEY:
            produce_status = "未配置视觉大模型，无法评估"
        else:
            merged, any_failed = {}, False
            for photo in produce_photos:
                items = produce_mod.assess(photo.read())
                if items is None:
                    any_failed = True
                    continue
                for it in items:
                    merged.setdefault(it["name"], it)
            if merged:
                produce_items = list(merged.values())
                for it in produce_items:
                    it["price"] = produce_mod.price_hint(it["name"])
                    it["emoji"] = produce_mod.freshness_emoji(it["freshness"])
                if any_failed:
                    produce_status = "部分照片识别失败，已展示成功识别的结果"
            elif any_failed:
                produce_status = "评估失败，请重试"
            else:
                produce_status = "未识别到图片中的食材"

    ingredient_param = " ".join(market_mod.combined_names(selected))
    recipe_link = url_for("index") + "?" + urlencode({
        "ingredients": ingredient_param,
        "goal": goal,
        "taboos": ",".join(taboos),
    })
    return render_template(
        "market.html",
        regions=market_mod.REGIONS,
        months=market_mod.MONTHS,
        selected=selected,
        filtered_info=filtered_info,
        goal=goal,
        taboos=taboos,
        produce_items=produce_items,
        produce_status=produce_status,
        ingredient_param=ingredient_param,
        recipe_link=recipe_link,
    )


@app.route("/profile", methods=["GET", "POST"])
def profile():
    """健康档案独立页：先录入基础信息生成评估（输出 BMI + 建议目标），
    再依据评估结果确认最终目标与禁忌（先评后选），最后带去推荐买菜。"""
    if request.method == "POST":
        stage = request.form.get("stage", "assess")
        uid = current_user_id()
        if not uid:
            return redirect(url_for("login"))

        # 阶段 2：依据评估结果确认最终健康目标 + 禁忌
        if stage == "confirm":
            goal = _request_goal("均衡")
            taboos = request.form.getlist("taboos")

            conn = db.get_connection()
            db.ensure_profile_table(conn)
            saved = db.load_profile(conn, uid) or {}
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.save_profile(conn, uid, {
                "age": saved.get("age"), "gender": saved.get("gender"),
                "height": saved.get("height"), "weight": saved.get("weight"),
                "goal": goal, "taboos": taboos,
                "health_report": saved.get("health_report", ""),
                "health_report_markers": saved.get("health_report_markers", {}),
                "updated_at": now,
            })
            conn.close()

            health = HealthProfile(
                age=saved.get("age"), gender=saved.get("gender"),
                height=saved.get("height"), weight=saved.get("weight"),
            )
            summary = health.summarize(goal)
            market_link = "/market?" + urlencode({
                "goal": goal,
                "taboos": ",".join(taboos),
            })
            return render_template(
                "profile.html",
                goals=config.GOALS,
                taboo_options=config.TABOO_OPTIONS,
                stage="confirmed",
                age=saved.get("age"), gender=saved.get("gender"),
                height=saved.get("height"), weight=saved.get("weight"),
                goal=goal, taboos=taboos,
                health=summary,
                suggested_goal=_suggest_goal(summary),
                report_summary=saved.get("health_report", ""),
                report_status="",
                market_link=market_link,
                saved_at=now,
            )

        # 阶段 1：保存基础信息 + 体检单 → 生成评估（目标/禁忌按建议预填，待确认）
        age = request.form.get("age")
        gender = request.form.get("gender")
        height = request.form.get("height")
        weight = request.form.get("weight")

        # 体检单解析（可选）：识别异常指标 → 建议目标 / 预填禁忌（支持图片/PDF 多张，后页覆盖前页合并）
        report_summary, report_markers, report_status = "", {}, ""
        report_files = [f for f in request.files.getlist("report") if f and f.filename and (
            (f.content_type or "").startswith("image/") or (f.content_type or "") == "application/pdf")]
        if report_files:
            if not config.VISION_API_KEY:
                report_status = "未配置大模型，无法解析体检单"
            else:
                merged, any_failed = {}, False
                for report_file in report_files:
                    markers = report_mod.parse_report_file(report_file.content_type, report_file.read())
                    if markers is None:
                        any_failed = True
                        continue
                    merged.update(markers)  # 后页覆盖前页
                if merged:
                    report_markers = merged
                    report_summary = report_mod.markers_summary(merged)
                    report_status = "已解析体检单，识别到异常指标"
                elif any_failed:
                    report_status = "体检单解析失败，请重试"
                else:
                    report_status = "已解析体检单，未发现异常指标"

        health = HealthProfile(age=age, gender=gender, height=height, weight=weight)
        summary = health.summarize("均衡")
        suggested_goal = _suggest_goal(summary)
        # 血糖偏高时优先建议「控糖」
        if report_markers.get("血糖") in ("偏高", "高", "↑", "异常", "超标"):
            suggested_goal = "控糖"
        auto_taboos = report_mod.markers_to_taboos(report_markers)

        # 持久化基础信息 + 体检单（目标/禁忌先存建议值，confirm 阶段再覆盖）
        conn = db.get_connection()
        db.ensure_profile_table(conn)
        db.save_profile(conn, uid, {
            "age": health.age, "gender": health.gender,
            "height": health.height, "weight": health.weight,
            "goal": suggested_goal or "均衡",
            "taboos": auto_taboos,
            "health_report": report_summary,
            "health_report_markers": report_markers,
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        conn.close()

        return render_template(
            "profile.html",
            goals=config.GOALS,
            taboo_options=config.TABOO_OPTIONS,
            stage="assessed",
            age=age, gender=gender, height=height, weight=weight,
            goal=suggested_goal or "均衡",
            taboos=auto_taboos,
            health=summary,
            suggested_goal=suggested_goal,
            report_summary=report_summary,
            report_status=report_status,
            market_link=None,
            saved_at=None,
        )

    # GET：加载已保存的档案预填
    conn = db.get_connection()
    db.ensure_profile_table(conn)
    uid = current_user_id()
    saved = db.load_profile(conn, uid) if uid else None
    conn.close()
    return render_template(
        "profile.html",
        goals=config.GOALS,
        taboo_options=config.TABOO_OPTIONS,
        stage="init",
        age=saved["age"] if saved else None,
        gender=saved["gender"] if saved else None,
        height=saved["height"] if saved else None,
        weight=saved["weight"] if saved else None,
        goal=saved["goal"] if saved else "均衡",
        taboos=saved["taboos"] if saved else [],
        health=None, suggested_goal=None,
        report_summary=saved["health_report"] if saved else "",
        report_status="",
        market_link=None,
        saved_at=saved["updated_at"] if saved else None,
    )


@app.route("/daily", methods=["GET", "POST"])
def daily():
    """一日饮食规划：按健康档案算热量缺口 → 推荐三餐 → 记录实际摄入 → 输出当天报告。"""
    ingredient_index, recipes = get_data()
    saved = _load_saved_profile()

    goal = _request_goal(saved.get("goal") or "均衡")
    taboos = _request_taboos()
    if not taboos:
        taboos = saved.get("taboos", []) if saved else []

    health = HealthProfile(
        age=saved.get("age") if saved else None,
        gender=saved.get("gender") if saved else None,
        height=saved.get("height") if saved else None,
        weight=saved.get("weight") if saved else None,
    )
    health_summary = health.summarize(goal)

    # 目标计算参数（活动系数可调，缺口自动按 BMR×活动系数−目标摄入计算）
    if request.method == "POST":
        try:
            activity = float(request.form.get("activity", daily_mod.DEFAULT_ACTIVITY))
        except (TypeError, ValueError):
            activity = daily_mod.DEFAULT_ACTIVITY
    else:
        activity = daily_mod.DEFAULT_ACTIVITY

    bmr = health.bmr()
    tdee_value = daily_mod.tdee(bmr, activity)
    target = daily_mod.target_intake(tdee_value, goal)
    gap = daily_mod.deficit(tdee_value, target) if tdee_value is not None else None
    meals = daily_mod.meal_targets(target)

    # 三餐安排（已过禁忌）
    goal_mgr = HealthGoalManager(goal)
    goal_mgr.add_taboos(taboos)
    advisor = DietAdvisor(ingredient_index, goal_mgr.taboo_tags())
    safe_pool, _ = advisor.filter_recipes(recipes)
    # 来自「食谱推荐」页导入的优先菜谱名（逗号分隔，随表单回传保持）
    recipes_param = request.values.get("recipes", "")
    priority_names = [n.strip() for n in recipes_param.split(",") if n.strip()]
    # action=refresh 时随机换一批菜谱
    action = request.form.get("action", "plan") if request.method == "POST" else ""
    shuffle = action == "refresh"
    plan = daily_mod.plan_meals(safe_pool, goal, ingredient_index, n_per_meal=5,
                                shuffle=shuffle, priority_names=priority_names)

    # 实际摄入 + 当天报告（仅 action=report 时）
    report, report_actual, llm_text, chat_context, day_score = None, None, None, None, None
    manual_texts = {name: "" for name, _ in daily_mod.MEALS}
    if request.method == "POST":
        for name, _ in daily_mod.MEALS:
            manual_texts[name] = request.form.get(f"manual_{name}", "")
        if action == "report":
            actual = {}
            for name, _ in daily_mod.MEALS:
                items = daily_mod.parse_manual_items(manual_texts[name])
                for photo in request.files.getlist(f"{name}_photo"):
                    if not photo or not photo.filename or not (photo.content_type or "").startswith("image/"):
                        continue
                    est = meal_photo_mod.estimate(photo.read())
                    if est:
                        for it in est:
                            it["source"] = "照片估算"
                            items.append(it)
                actual[name] = items
            report_actual = actual
            report = daily_mod.summarize_day(target, actual)
            day_score = daily_mod.score_day(target, actual)
            llm_text = daily_mod.daily_comment(goal, taboos, target, gap, actual)
            chat_context = {
                "goal": goal,
                "taboos": list(taboos),
                "target": target,
                "gap": gap,
                "actual": report["per_meal"],
            }
            # 持久化当日记录（供趋势图表 / 打卡；未登录则跳过）
            uid = current_user_id()
            if uid:
                try:
                    conn = db.get_connection()
                    db.ensure_daily_log_table(conn)
                    db.save_daily_log(conn, uid, {
                        "date": datetime.date.today().isoformat(),
                        "goal": goal,
                        "tdee": tdee_value,
                        "target": target,
                        "gap": gap,
                        "total": report["total"],
                        "diff": report["diff"],
                        "weight": saved.get("weight") if saved else None,
                        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    })
                    conn.close()
                except Exception:
                    pass

    # 历史趋势 + 打卡统计（供可视化图表）
    logs = []
    uid = current_user_id()
    if uid:
        try:
            conn = db.get_connection()
            db.ensure_daily_log_table(conn)
            logs = db.load_daily_logs(conn, uid, limit=30)
            conn.close()
        except Exception:
            logs = []
    streak = daily_mod.calc_streak(logs)
    achievements = ach_mod.compute_achievements(
        streak=streak, log_count=len(logs),
        profile_loaded=bool(saved), goal=goal,
    )
    history = [
        {
            "date": lg["date"],
            "target": lg["target"],
            "total": lg["total"],
            "diff": lg["diff"],
            "weight": lg["weight"],
        }
        for lg in logs
        if lg.get("target") is not None and lg.get("total") is not None
    ]
    trend_max = max((max(h["target"], h["total"]) for h in history), default=0) or 1
    avg_total = round(sum(h["total"] for h in history) / len(history)) if history else 0
    # 体重记录（仅保留有体重值的日期）
    weights = [{"date": h["date"], "weight": h["weight"]} for h in history if h.get("weight")]

    return render_template(
        "daily.html",
        goals=config.GOALS,
        activity_options=daily_mod.ACTIVITY_FACTORS,
        activity=activity,
        goal=goal,
        taboos=taboos,
        profile_loaded=bool(saved),
        health=health_summary,
        bmr=int(bmr) if bmr else None,
        tdee=tdee_value,
        target=target,
        gap=gap,
        gap_desc=daily_mod.GOAL_GAP_DESC.get(goal, ""),
        meals=meals,
        plan=plan,
        report=report,
        report_actual=report_actual,
        day_score=day_score,
        llm_text=llm_text,
        llm_enabled=llm.enabled(),
        manual_texts=manual_texts,
        chat_context=chat_context,
        recipes_param=recipes_param,
        priority_names=priority_names,
        shuffle=shuffle,
        history=history,
        streak=streak,
        log_count=len(logs),
        achievements=achievements,
        trend_max=trend_max,
        weights=weights,
        avg_total=avg_total,
    )


@app.route("/week", methods=["GET", "POST"])
def week():
    """AI 一周食谱计划：按健康档案生成 7 天早中晚三餐，可刷新换一批。"""
    ingredient_index, recipes = get_data()
    saved = _load_saved_profile()
    goal = _request_goal(saved.get("goal") or "均衡")
    taboos = _request_taboos()
    if not taboos:
        taboos = saved.get("taboos", []) if saved else []

    goal_mgr = HealthGoalManager(goal)
    goal_mgr.add_taboos(taboos)
    advisor = DietAdvisor(ingredient_index, goal_mgr.taboo_tags())
    safe_pool, _ = advisor.filter_recipes(recipes)

    shuffle = request.method == "POST" and request.form.get("action") == "refresh"
    week_plan = daily_mod.plan_week(safe_pool, goal, ingredient_index, days=7, shuffle=shuffle)

    # 一周营养概览 + 采购清单 + 每天「开始这一天」联动（跳转到一日饮食规划预填该天三餐）
    week_totals = []
    shopping = {}
    for d in week_plan:
        names = []
        day_cal = 0
        for picks in d["meals"].values():
            for p in picks:
                names.append(p["recipe"]["name"])
                day_cal += int(p["calories"] or 0)
                for ing in p["recipe"].get("ingredients", []):
                    if ing not in STAPLE:
                        shopping[ing] = shopping.get(ing, 0) + 1
        d["recipe_names"] = ",".join(names)
        d["day_total"] = day_cal
        week_totals.append(day_cal)
    avg_week = round(sum(week_totals) / len(week_totals)) if week_totals else 0
    week_max = max(week_totals) if week_totals else 1
    shopping_list = sorted(shopping.items(), key=lambda kv: -kv[1])[:20]

    return render_template(
        "week.html",
        goal=goal,
        taboos=taboos,
        week=week_plan,
        goal_desc=daily_mod.GOAL_GAP_DESC.get(goal, ""),
        profile_loaded=bool(saved),
        llm_enabled=llm.enabled(),
        week_totals=week_totals,
        avg_week=avg_week,
        week_max=week_max,
        shopping_list=shopping_list,
    )


@app.route("/week_advice", methods=["POST"])
def week_advice():
    """异步生成一周饮食原则建议（JSON），供一周计划页按需加载，避免阻塞计划秒出。"""
    if _rate_limited(f"week:{request.remote_addr}", limit=10, window=60):
        return jsonify({"error": "请求过于频繁，请稍后再试"}), 429
    data = request.get_json(silent=True) or {}
    goal = data.get("goal") or "均衡"
    taboos = data.get("taboos") or []
    if not isinstance(taboos, list):
        taboos = []
    if not llm.enabled():
        return jsonify({"advice": "", "error": "未配置大模型"})
    text = llm.chat(
        system="你是一位注册营养师。请针对用户的一周饮食计划，给出总体原则与执行建议，"
               "约 3~4 句，简洁可执行、安全（不含医疗诊断），用纯文本，不要用 Markdown 语法。",
        user=f"健康目标：{goal}" + (f"；需规避的禁忌：{'、'.join(taboos)}" if taboos else ""),
        max_tokens=300,
    )
    if not text:
        return jsonify({"advice": "", "error": "生成失败，请重试"})
    return jsonify({"advice": text})


@app.route("/random_recipe")
def random_recipe():
    """「今天吃什么」随机摇一摇：按健康目标从契合度靠前候选中随机推荐一道菜（JSON）。"""
    ingredient_index, recipes = get_data()
    saved = _load_saved_profile()
    goal = _request_goal(saved.get("goal") or "均衡")
    taboos = _request_taboos()
    if not taboos:
        taboos = saved.get("taboos", []) if saved else []

    goal_mgr = HealthGoalManager(goal)
    goal_mgr.add_taboos(taboos)
    advisor = DietAdvisor(ingredient_index, goal_mgr.taboo_tags())
    safe_pool, _ = advisor.filter_recipes(recipes)
    if not safe_pool:
        return jsonify({"error": "暂无可用食谱"})
    scored = sorted(
        safe_pool, key=lambda r: daily_mod._goal_fit(r, goal, ingredient_index), reverse=True
    )
    pool = scored[: min(10, len(scored))]
    r = random.choice(pool)
    return jsonify({
        "name": r.get("name"),
        "method": r.get("method"),
        "calories": r.get("estimated_calories"),
        "steps": r.get("steps", []),
        "tags": r.get("tags", []),
        "region": r.get("region"),
        "flavor": r.get("flavor"),
        "goal": goal,
    })


@app.route("/chat", methods=["POST"])
def chat():
    """可交互 AI 营养点评师：接收追问消息 + 历史 + 上下文，返回点评师回复。"""
    if _rate_limited(f"chat:{request.remote_addr}", limit=30, window=60):
        return jsonify({"reply": "", "error": "请求过于频繁，请稍后再试"}), 429
    if not llm.enabled():
        return jsonify({"reply": "", "error": "未配置大模型"})
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"reply": "", "error": "消息为空"})
    history = data.get("history") or []
    context = data.get("context") or {}
    reply = llm.chat(_build_chat_system(context), message, history=history, max_tokens=500)
    if reply is None:
        return jsonify({"reply": "", "error": "调用失败，请稍后重试"})
    return jsonify({"reply": reply})


if __name__ == "__main__":
    app.run(debug=True)

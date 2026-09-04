# -*- coding: utf-8 -*-
"""SQLite 数据访问层：建表、灌入种子数据、查询营养库与菜谱库。"""
import json
import os
import sqlite3

import config


def get_connection(db_path=None):
    """返回 SQLite 连接（行以 dict 形式返回）。"""
    path = db_path or config.DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables(conn):
    """重建食材表与菜谱表。"""
    conn.executescript(
        """
        DROP TABLE IF EXISTS ingredients;
        CREATE TABLE ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            category TEXT,
            calories REAL,
            protein REAL,
            fat REAL,
            carb REAL,
            fiber REAL,
            gi REAL,
            taboo_tags TEXT,
            aliases TEXT
        );
        DROP TABLE IF EXISTS recipes;
        CREATE TABLE recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            ingredients TEXT,
            steps TEXT,
            tags TEXT,
            flavor TEXT,
            region TEXT,
            estimated_calories REAL,
            method TEXT
        );
        """
    )
    conn.commit()


def seed_from_json(conn, ingredients_path=None, recipes_path=None):
    """从 JSON 种子文件灌入营养库与菜谱库，返回 (食材数, 菜谱数)。"""
    ing_path = ingredients_path or config.INGREDIENTS_JSON
    rec_path = recipes_path or config.RECIPES_JSON

    with open(ing_path, encoding="utf-8") as f:
        ingredients = json.load(f)
    with open(rec_path, encoding="utf-8") as f:
        recipes = json.load(f)

    for it in ingredients:
        conn.execute(
            "INSERT INTO ingredients"
            "(name, category, calories, protein, fat, carb, fiber, gi, taboo_tags, aliases)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                it["name"], it["category"], it["calories"], it["protein"],
                it["fat"], it["carb"], it["fiber"], it["gi"],
                json.dumps(it.get("taboo_tags", []), ensure_ascii=False),
                json.dumps(it.get("aliases", []), ensure_ascii=False),
            ),
        )
    for r in recipes:
        conn.execute(
            "INSERT INTO recipes(name, ingredients, steps, tags, flavor, region, estimated_calories, method)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                r["name"],
                json.dumps(r["ingredients"], ensure_ascii=False),
                json.dumps(r["steps"], ensure_ascii=False),
                json.dumps(r["tags"], ensure_ascii=False),
                r.get("flavor", ""),
                r.get("region", ""),
                r["estimated_calories"], r["method"],
            ),
        )
    conn.commit()
    return len(ingredients), len(recipes)


def load_ingredients(conn):
    """加载营养库到内存索引：{规范名或别名 -> 食材 dict}。"""
    index = {}
    for row in conn.execute("SELECT * FROM ingredients").fetchall():
        d = dict(row)
        d["taboo_tags"] = json.loads(d["taboo_tags"])
        d["aliases"] = json.loads(d["aliases"])
        index[d["name"]] = d
        for alias in d["aliases"]:
            index[alias] = d
    return index


def load_recipes(conn):
    """加载菜谱库为 dict 列表（ingredients/steps/tags 还原为 list）。"""
    recipes = []
    for row in conn.execute("SELECT * FROM recipes").fetchall():
        d = dict(row)
        d["ingredients"] = json.loads(d["ingredients"])
        d["steps"] = json.loads(d["steps"])
        d["tags"] = json.loads(d["tags"])
        recipes.append(d)
    return recipes


# ---------- 用户（注册 / 登录） ----------

def ensure_users_table(conn):
    """创建用户表（幂等）。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT
        )
        """
    )
    conn.commit()


def create_user(conn, username, password_hash):
    """新建用户，成功返回 user_id；用户名已存在返回 None。"""
    try:
        cur = conn.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, ""),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_user_by_username(conn, username):
    """按用户名查用户；不存在返回 None。"""
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(conn, user_id):
    """按 id 查用户；不存在返回 None。"""
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


# ---------- 健康档案（多用户，主键 user_id） ----------

def ensure_profile_table(conn):
    """创建健康档案表（幂等）；旧单用户表（id 主键）自动迁移为多用户。"""
    cols = conn.execute("PRAGMA table_info(user_profile)").fetchall()
    if cols and cols[0]["name"] != "user_id":
        conn.execute("DROP TABLE IF EXISTS user_profile")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id INTEGER PRIMARY KEY,
            age INTEGER,
            gender TEXT,
            height REAL,
            weight REAL,
            goal TEXT,
            taboos TEXT,
            health_report TEXT,
            health_report_markers TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()


def load_profile(conn, user_id):
    """读取指定用户的健康档案（不存在返回 None）。"""
    row = conn.execute("SELECT * FROM user_profile WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["taboos"] = json.loads(d["taboos"] or "[]")
    d["health_report_markers"] = json.loads(d["health_report_markers"] or "{}")
    return d


def save_profile(conn, user_id, data):
    """保存指定用户的健康档案（upsert）。data 需含 age/gender/height/weight/goal/
    taboos/health_report/health_report_markers/updated_at 字段。"""
    conn.execute(
        """
        INSERT INTO user_profile
            (user_id, age, gender, height, weight, goal, taboos,
             health_report, health_report_markers, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            age = excluded.age,
            gender = excluded.gender,
            height = excluded.height,
            weight = excluded.weight,
            goal = excluded.goal,
            taboos = excluded.taboos,
            health_report = excluded.health_report,
            health_report_markers = excluded.health_report_markers,
            updated_at = excluded.updated_at
        """,
        (
            user_id, data.get("age"), data.get("gender"), data.get("height"),
            data.get("weight"), data.get("goal"),
            json.dumps(data.get("taboos", []), ensure_ascii=False),
            data.get("health_report", ""),
            json.dumps(data.get("health_report_markers", {}), ensure_ascii=False),
            data.get("updated_at", ""),
        ),
    )
    conn.commit()


# ---------- 每日饮食记录（趋势 / 打卡，多用户） ----------

def ensure_daily_log_table(conn):
    """创建每日饮食记录表（幂等）；旧单用户表自动迁移。"""
    cols = conn.execute("PRAGMA table_info(daily_log)").fetchall()
    if cols and not any(c["name"] == "user_id" for c in cols):
        conn.execute("DROP TABLE IF EXISTS daily_log")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            goal TEXT,
            tdee INTEGER,
            target INTEGER,
            gap INTEGER,
            total INTEGER,
            diff INTEGER,
            weight REAL,
            created_at TEXT,
            UNIQUE(user_id, date)
        )
        """
    )
    conn.commit()


def save_daily_log(conn, user_id, data):
    """按 (user, 日期) upsert 一条每日饮食记录（同一天重复提交以最新覆盖）。"""
    conn.execute(
        """
        INSERT INTO daily_log
            (user_id, date, goal, tdee, target, gap, total, diff, weight, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET
            goal = excluded.goal,
            tdee = excluded.tdee,
            target = excluded.target,
            gap = excluded.gap,
            total = excluded.total,
            diff = excluded.diff,
            weight = excluded.weight,
            created_at = excluded.created_at
        """,
        (
            user_id, data.get("date"), data.get("goal"), data.get("tdee"),
            data.get("target"), data.get("gap"), data.get("total"), data.get("diff"),
            data.get("weight"), data.get("created_at", ""),
        ),
    )
    conn.commit()


def load_daily_logs(conn, user_id, limit=30):
    """按日期升序读取指定用户最近 limit 条每日记录（供趋势图表 / 打卡）。"""
    rows = conn.execute(
        "SELECT * FROM daily_log WHERE user_id = ? ORDER BY date ASC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]

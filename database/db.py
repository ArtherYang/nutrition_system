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

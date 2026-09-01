# -*- coding: utf-8 -*-
"""下载西餐菜谱（TheMealDB）与无酒精饮料（TheCocktailDB）到 data_sources/。

- 西餐：search.php?f=a..z 遍历全表，保存带完整配料/步骤的 meal 对象
- 饮料：filter.php?a=Non_Alcoholic 取无酒精清单，再逐条 lookup 取完整配方
"""
import json
import os
import time
import urllib.parse
import urllib.request

MEALDB = "https://www.themealdb.com/api/json/v1/1"
COCKTAILDB = "https://www.thecocktaildb.com/api/json/v1/1"
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 关闭代理
_opener.addheaders = [("User-Agent", "Mozilla/5.0")]


def _get(url, tries=3):
    for i in range(tries):
        try:
            with _opener.open(url, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(1.5)


def download_meals(out_dir):
    meals = []
    seen = set()
    for c in "abcdefghijklmnopqrstuvwxyz":
        d = _get(f"{MEALDB}/search.php?f={c}")
        for m in d.get("meals") or []:
            if m["idMeal"] not in seen:
                seen.add(m["idMeal"])
                meals.append(m)
        time.sleep(0.25)
    path = os.path.join(out_dir, "meals.json")
    json.dump(meals, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return len(meals)


def download_drinks(out_dir):
    non_alc = _get(f"{COCKTAILDB}/filter.php?a=Non_Alcoholic").get("drinks") or []
    drinks = []
    for d in non_alc:
        detail = _get(f"{COCKTAILDB}/lookup.php?i={d['idDrink']}")
        drinks.extend(detail.get("drinks") or [])
        time.sleep(0.25)
    path = os.path.join(out_dir, "drinks.json")
    json.dump(drinks, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return len(drinks)


def main():
    out_dir = os.path.join("data_sources", "themealdb")
    os.makedirs(out_dir, exist_ok=True)
    n = download_meals(out_dir)
    print(f"西餐 meals: {n} 道 -> {out_dir}/meals.json")
    n2 = download_drinks(out_dir)
    print(f"无酒精 drinks: {n2} 款 -> {out_dir}/drinks.json")


if __name__ == "__main__":
    main()

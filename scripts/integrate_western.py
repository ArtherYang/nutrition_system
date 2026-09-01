# -*- coding: utf-8 -*-
"""把 TheMealDB 西餐菜谱 + TheCocktailDB 无酒精饮料 整合进 recipes.json。

来源：data_sources/themealdb/{meals.json, drinks.json}
产出：data/recipes_western.json（先落盘供审查，不直接改 recipes.json）

规则：
- 菜系：strArea -> 中文菜系；亚洲/中东/未知 跳过
- 食材：英文名经 EN_ZH 映射到营养库中文名；映射不到的（香草/酒/高汤等）丢弃
- 保留条件：映射后 >=2 个食材，且至少有 1 个「主料」（非纯调味）
- 口味/做法/标签 由 strCategory 推断；热量按食材类别估算
"""
import json
import os
import re

MEALDB = os.path.join("data_sources", "themealdb")
OUT = os.path.join("data", "recipes_western.json")
INGREDIENTS = os.path.join("data", "ingredients.json")

# ---------- 菜系映射（值=中文菜系；不在表内的 strArea 跳过） ----------
AREA_MAP = {
    "British": "英式", "United States": "美式", "American": "美式", "Canadian": "美式",
    "France": "法式", "French": "法式", "Italian": "意式",
    "Spanish": "西班牙式", "Greek": "希腊式", "Mexican": "墨西哥式",
    "Turkish": "土耳其式", "Polish": "波兰式", "Norway": "北欧式", "Norwegian": "北欧式",
    "Australian": "澳式", "Netherlands": "荷兰式", "Dutch": "荷兰式",
    "Irish": "爱尔兰式", "Croatian": "东欧式", "Portuguese": "葡式",
    "Russian": "俄式", "Ukrainian": "俄式",
    "Argentine": "拉美式", "Uruguayan": "拉美式", "Venezuelan": "拉美式",
    "Jamaican": "加勒比式", "Slovakia": "东欧式", "Moroccan": "摩洛哥式",
}

# ---------- 英文食材 -> 中文（对齐营养库规范名；小写 key） ----------
EN_ZH = {
    # 肉类
    "chicken": "鸡胸肉", "chicken breast": "鸡胸肉", "chicken breasts": "鸡胸肉",
    "chicken thighs": "鸡腿", "chicken legs": "鸡腿", "chicken wings": "鸡翅",
    "whole chicken": "鸡胸肉", "beef": "牛肉", "ground beef": "牛肉",
    "minced beef": "牛肉", "beef steak": "牛肉", "steak": "牛肉",
    "pork": "猪肉", "pork chop": "猪肉", "pork chops": "猪肉", "bacon": "培根",
    "ham": "火腿", "sausage": "香肠", "sausages": "香肠", "chorizo": "香肠",
    "lamb": "羊肉", "lamb chops": "羊肉", "turkey": "鸡胸肉", "duck": "鸭肉",
    "bacon lardons": "培根",
    # 水产
    "salmon": "三文鱼", "tuna": "金枪鱼", "cod": "鳕鱼", "haddock": "鳕鱼",
    "fish": "鳕鱼", "white fish": "鳕鱼", "prawns": "虾", "prawn": "虾",
    "shrimp": "虾", "king prawns": "虾", "crab": "螃蟹",
    "squid": "鱿鱼", "clams": "蛤蜊", "scallops": "扇贝",
    # 蛋奶
    "egg": "鸡蛋", "eggs": "鸡蛋", "egg yolks": "鸡蛋", "egg yolk": "鸡蛋",
    "egg white": "鸡蛋", "egg whites": "鸡蛋", "milk": "牛奶", "whole milk": "牛奶",
    "skim milk": "脱脂牛奶", "condensed milk": "炼乳", "buttermilk": "牛奶",
    "cream": "奶油", "double cream": "奶油", "heavy cream": "奶油",
    "single cream": "奶油", "light cream": "奶油", "sour cream": "奶油",
    "whipping cream": "奶油", "creme fraiche": "奶油", "clotted cream": "奶油",
    "butter": "黄油", "unsalted butter": "黄油", "salted butter": "黄油",
    "melted butter": "黄油", "cheese": "芝士", "cheddar cheese": "芝士",
    "cheddar": "芝士", "mozzarella": "芝士", "mozzarella cheese": "芝士",
    "parmesan": "芝士", "parmesan cheese": "芝士", "parmigiano reggiano": "芝士",
    "feta": "芝士", "feta cheese": "芝士", "goat cheese": "芝士",
    "goats cheese": "芝士", "cream cheese": "奶酪", "ricotta": "芝士",
    "gruyère": "芝士", "gruyere": "芝士", "blue cheese": "芝士",
    "yogurt": "酸奶", "greek yogurt": "酸奶", "yoghurt": "酸奶",
    # 蔬菜
    "onion": "洋葱", "onions": "洋葱", "red onion": "洋葱", "red onions": "洋葱",
    "shallots": "洋葱", "shallot": "洋葱", "spring onions": "大葱",
    "spring onion": "大葱", "scallions": "大葱", "scallion": "大葱",
    "green onion": "大葱", "leek": "大葱", "leeks": "大葱",
    "garlic": "大蒜", "garlic clove": "大蒜", "garlic cloves": "大蒜",
    "ginger": "生姜", "fresh ginger": "生姜", "ground ginger": "生姜",
    "root ginger": "生姜", "tomato": "西红柿", "tomatoes": "西红柿",
    "tinned tomatos": "西红柿", "tinned tomatoes": "西红柿", "canned tomatoes": "西红柿",
    "plum tomatoes": "西红柿", "cherry tomatoes": "西红柿", "sun-dried tomatoes": "西红柿",
    "tomato puree": "番茄酱", "tomato purée": "番茄酱", "tomato puree": "番茄酱",
    "tomato paste": "番茄酱", "passata": "番茄酱", "tomato ketchup": "番茄酱",
    "ketchup": "番茄酱",
    "potato": "土豆", "potatoes": "土豆", "new potatoes": "土豆",
    "baby potatoes": "土豆", "sweet potato": "红薯", "sweet potatoes": "红薯",
    "carrot": "胡萝卜", "carrots": "胡萝卜", "broccoli": "西兰花",
    "cauliflower": "菜花", "spinach": "菠菜", "baby spinach": "菠菜",
    "lettuce": "生菜", "iceberg lettuce": "生菜", "romaine lettuce": "生菜",
    "cabbage": "卷心菜", "red cabbage": "紫甘蓝", "savoy cabbage": "卷心菜",
    "white cabbage": "卷心菜", "cucumber": "黄瓜", "bell pepper": "彩椒",
    "red pepper": "红椒", "red bell pepper": "红椒", "green pepper": "青椒",
    "green bell pepper": "青椒", "yellow pepper": "彩椒", "orange pepper": "彩椒",
    "capsicum": "彩椒", "chilli": "辣椒", "chili": "辣椒", "red chilli": "辣椒",
    "green chilli": "辣椒", "scotch bonnet": "辣椒", "chilli powder": "辣椒",
    "cayenne pepper": "辣椒", "mushroom": "蘑菇", "mushrooms": "蘑菇",
    "chestnut mushrooms": "蘑菇", "portobello mushrooms": "蘑菇",
    "shiitake mushrooms": "香菇", "aubergine": "茄子", "eggplant": "茄子",
    "courgette": "西葫芦", "courgettes": "西葫芦", "zucchini": "西葫芦",
    "asparagus": "芦笋", "celery": "芹菜", "celery sticks": "芹菜",
    "celery stalk": "芹菜", "peas": "豌豆", "garden peas": "豌豆",
    "green beans": "四季豆", "runner beans": "四季豆", "broad beans": "蚕豆",
    "fava beans": "蚕豆", "kidney beans": "黑豆", "black beans": "黑豆",
    "chickpeas": "鹰嘴豆", "chickpea": "鹰嘴豆", "lentils": "扁豆",
    "sweetcorn": "玉米", "sweetcorn kernels": "玉米", "corn": "玉米",
    "corn kernels": "玉米", "brussels sprouts": "卷心菜", "avocado": "鳄梨",
    "olives": "橄榄", "beetroot": "甜菜", "pumpkin": "南瓜",
    "butternut squash": "南瓜", "turnip": "白萝卜", "radish": "白萝卜",
    "fennel": "茴香", "bamboo shoots": "竹笋", "bean sprouts": "豆芽",
    "pak choi": "小白菜", "bok choy": "小白菜", "chinese cabbage": "白菜",
    "swede": "白萝卜",
    # 水果
    "apple": "苹果", "apples": "苹果", "cooking apple": "苹果", "banana": "香蕉",
    "bananas": "香蕉", "lemon": "柠檬", "lemon juice": "柠檬", "lemon zest": "柠檬",
    "lemon juice": "柠檬", "lime": "柠檬", "lime juice": "柠檬", "limes": "柠檬",
    "orange": "橙子", "oranges": "橙子", "orange juice": "橙子",
    "strawberries": "草莓", "strawberry": "草莓", "blueberries": "蓝莓",
    "raspberries": "蓝莓", "mango": "芒果", "pineapple": "菠萝",
    "peach": "桃", "peaches": "桃", "pear": "梨", "pears": "梨", "plum": "李子",
    "cherry": "樱桃", "cherries": "樱桃", "grapes": "葡萄", "raisins": "葡萄干",
    "sultanas": "葡萄干", "currants": "葡萄干", "dates": "枣", "figs": "无花果",
    "coconut": "椰子", "coconut milk": "椰子", "coconut cream": "椰子",
    "apricot": "杏", "apricots": "杏", "passion fruit": "百香果", "kiwi": "猕猴桃",
    "watermelon": "西瓜", "melon": "甜瓜", "cantaloupe": "甜瓜", "papaya": "木瓜",
    "pomegranate": "石榴", "grapefruit": "葡萄柚", "dried fruit": "葡萄干",
    "berries": "蓝莓", "mixed berries": "蓝莓", "apple juice": "苹果",
    "mango juice": "芒果", "pineapple juice": "菠萝", "grapefruit juice": "葡萄柚",
    "grape juice": "葡萄", "guava juice": "番石榴", "passion fruit juice": "百香果",
    "tomato juice": "西红柿", "peach nectar": "桃",
    # 主食/谷物
    "rice": "大米", "basmati rice": "大米", "brown rice": "糙米",
    "jasmine rice": "大米", "risotto rice": "大米", "arborio rice": "大米",
    "sticky rice": "糯米", "pasta": "意面", "spaghetti": "意面", "penne": "意面",
    "fusilli": "意面", "macaroni": "意面", "tagliatelle": "意面",
    "linguine": "意面", "fettuccine": "意面", "lasagne sheets": "意面",
    "lasagne": "意面", "orzo": "意面", "noodles": "面条", "rice noodles": "面条",
    "egg noodles": "面条", "bread": "面包", "breadcrumbs": "面包",
    "pitta bread": "面包", "pita bread": "面包", "baguette": "面包",
    "buns": "面包", "sourdough": "面包", "white bread": "面包",
    "flour": "面粉", "plain flour": "面粉", "self-raising flour": "面粉",
    "all purpose flour": "面粉", "corn flour": "淀粉", "cornstarch": "淀粉",
    "oats": "燕麦", "rolled oats": "燕麦", "porridge oats": "燕麦",
    "cornmeal": "玉米", "polenta": "玉米", "quinoa": "藜麦", "couscous": "意面",
    # 油脂
    "olive oil": "橄榄油", "extra virgin olive oil": "橄榄油",
    "vegetable oil": "食用油", "sunflower oil": "食用油", "rapeseed oil": "食用油",
    "oil": "食用油", "sesame seed oil": "香油", "sesame oil": "香油",
    "peanut oil": "花生油", "groundnut oil": "花生油",
    # 调味（能映射到库内的）
    "salt": "盐", "sea salt": "盐", "kosher salt": "盐", "celery salt": "盐",
    "black pepper": "黑胡椒",
    "pepper": "黑胡椒", "white pepper": "黑胡椒", "sugar": "白砂糖",
    "caster sugar": "白砂糖", "granulated sugar": "白砂糖", "brown sugar": "白砂糖",
    "muscovado sugar": "白砂糖", "demerara sugar": "白砂糖", "icing sugar": "白砂糖",
    "honey": "蜂蜜", "soy sauce": "酱油", "light soy": "酱油", "dark soy": "酱油",
    "vinegar": "醋", "balsamic vinegar": "醋", "white wine vinegar": "醋",
    "red wine vinegar": "醋", "rice vinegar": "醋", "cider vinegar": "醋",
    "oyster sauce": "蚝油", "cinnamon": "肉桂", "ground cinnamon": "肉桂",
    "cinnamon stick": "肉桂", "bay leaf": "香叶", "bay leaves": "香叶",
    "star anise": "八角", "coriander": "香菜", "cilantro": "香菜",
    "coriander leaves": "香菜", "basil": "罗勒", "basil leaves": "罗勒",
    "fresh basil": "罗勒", "nutmeg": "肉桂",
    # 坚果/种子/豆制品
    "almonds": "杏仁", "almond": "杏仁", "flaked almonds": "杏仁",
    "ground almonds": "杏仁", "peanuts": "花生", "cashews": "腰果",
    "cashew nuts": "腰果", "walnuts": "核桃", "walnut": "核桃",
    "pistachios": "开心果", "pecans": "核桃", "hazelnuts": "榛子",
    "pine nuts": "松子", "sesame seed": "芝麻", "sesame seeds": "芝麻",
    "tofu": "豆腐", "miso": "豆腐",
}

# ---------- 类别 -> 口味/做法/标签 ----------
CATEGORY_CONF = {
    "Dessert":       {"flavor": "香甜", "method": "烤", "tags": ["均衡"]},
    "Vegetarian":    {"flavor": "清淡", "method": "拌", "tags": ["减脂"]},
    "Vegan":         {"flavor": "清淡", "method": "拌", "tags": ["减脂"]},
    "Side":          {"flavor": "清淡", "method": "拌", "tags": ["减脂"]},
    "Starter":       {"flavor": "清爽", "method": "煎", "tags": ["减脂"]},
    "Seafood":       {"flavor": "鲜香", "method": "烧", "tags": ["增肌"]},
    "Chicken":       {"flavor": "咸鲜", "method": "煎", "tags": ["增肌"]},
    "Beef":          {"flavor": "浓郁鲜香", "method": "烧", "tags": ["增肌"]},
    "Pork":          {"flavor": "咸鲜", "method": "烧", "tags": ["增肌"]},
    "Lamb":          {"flavor": "浓郁鲜香", "method": "炖", "tags": ["增肌"]},
    "Goat":          {"flavor": "浓郁鲜香", "method": "炖", "tags": ["增肌"]},
    "Pasta":         {"flavor": "咸鲜", "method": "煮", "tags": ["增肌"]},
    "Breakfast":     {"flavor": "香甜", "method": "煎", "tags": ["均衡"]},
    "Miscellaneous": {"flavor": "其他", "method": "煮", "tags": ["均衡"]},
}

# 饮料类别 -> 口味
DRINK_FLAVOR = {"Shake": "香甜", "Other / Unknown": "清爽", "Ordinary Drink": "清爽"}

# 调味/油脂类：估算热量时按低克数
SEASONING = {"盐", "白砂糖", "酱油", "醋", "蜂蜜", "黑胡椒", "番茄酱", "蚝油",
             "淀粉", "香油", "橄榄油", "食用油", "黄油"}
GRAM_BY_CATEGORY = {
    "油脂": 15, "坚果": 25, "乳制品": 60, "饮料": 200, "主食": 100, "豆类": 80,
    "蔬菜": 100, "水果": 90, "肉类": 120, "禽蛋": 90, "水产": 110,
}


def load_index():
    """加载营养库：{中文名 -> 食材 dict}。"""
    index = {}
    for it in json.load(open(INGREDIENTS, encoding="utf-8")):
        index[it["name"]] = it
        for a in it.get("aliases", []):
            index[a] = it
    return index


def map_ingredient(en, index):
    """单个英文食材 -> 营养库中文名；映射不到返回 None。"""
    key = en.strip().lower()
    zh = EN_ZH.get(key)
    if zh and zh in index:
        return index[zh]["name"]  # 归一到规范名
    return None


def recipe_ingredients(entry, n_max):
    """提取 strIngredient1..n_max 中非空食材名。"""
    out = []
    for i in range(1, n_max + 1):
        s = (entry.get(f"strIngredient{i}") or "").strip()
        if s:
            out.append(s)
    return out


def split_steps(instructions):
    """把英文步骤文本切成步骤列表（去掉 STEP 1 / step 2 等编号标记）。"""
    text = (instructions or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [ln.strip() for ln in text.split("\n")]
    steps = [ln for ln in lines if ln and not re.match(r"^step\s*\d*\s*[:.]?$", ln, re.I)]
    if len(steps) <= 1:
        steps = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    return [s for s in steps if s][:12]


def estimate_calories(mapped, index):
    """按食材类别估算一道菜的热量（kcal）。"""
    total = 0.0
    for name in mapped:
        d = index.get(name)
        if not d:
            continue
        cal = d.get("calories") or 0
        grams = 12 if name in SEASONING else GRAM_BY_CATEGORY.get(d.get("category"), 80)
        total += cal * grams / 100.0
    return max(20, int(round(total)))


def build_recipe(entry, n_max, region, index):
    """把 meal/drink 条目转为菜谱 dict；映射不足返回 None。"""
    mapped = []
    for en in recipe_ingredients(entry, n_max):
        zh = map_ingredient(en, index)
        if zh and zh not in mapped:
            mapped.append(zh)
    # 至少 2 个食材，且至少一个非纯调味主料
    mains = [m for m in mapped if m not in SEASONING]
    if len(mapped) < 2 or not mains:
        return None
    is_drink = n_max <= 15
    cat = entry.get("strCategory") or ("Other / Unknown" if is_drink else "Miscellaneous")
    if is_drink:
        # 饮料只保留含水果的（果汁/奶昔/冰沙），过滤咖啡/可可/汽水等无水果的
        if not any(index.get(m, {}).get("category") == "水果" for m in mapped):
            return None
    conf = CATEGORY_CONF.get(cat, CATEGORY_CONF["Miscellaneous"])
    if is_drink:
        conf = dict(conf, flavor=DRINK_FLAVOR.get(cat, "清爽"))
    return {
        "name": entry.get("strMeal") or entry.get("strDrink"),
        "ingredients": mapped,
        "steps": split_steps(entry.get("strInstructions")),
        "tags": conf["tags"],
        "flavor": conf["flavor"],
        "region": region,
        "estimated_calories": estimate_calories(mapped, index),
        "method": "饮" if is_drink else conf["method"],
    }


def main():
    index = load_index()
    meals = json.load(open(os.path.join(MEALDB, "meals.json"), encoding="utf-8"))
    drinks_path = os.path.join(MEALDB, "drinks.json")
    drinks = json.load(open(drinks_path, encoding="utf-8")) if os.path.exists(drinks_path) else []

    recipes, skipped = [], {"area": 0, "mapped": 0}
    for m in meals:
        area = AREA_MAP.get(m.get("strArea") or "")
        if not area:
            skipped["area"] += 1
            continue
        r = build_recipe(m, 20, area, index)
        if r:
            recipes.append(r)
        else:
            skipped["mapped"] += 1
    n_meal = len(recipes)

    for d in drinks:
        r = build_recipe(d, 15, "西式", index)
        if r:
            recipes.append(r)
        else:
            skipped["mapped"] += 1
    n_drink = len(recipes) - n_meal

    json.dump(recipes, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"西餐菜谱: {n_meal}  饮料: {n_drink}  合计: {len(recipes)}")
    print(f"跳过(非西餐地区): {skipped['area']}  跳过(食材映射不足): {skipped['mapped']}")
    from collections import Counter
    print("菜系分布:", dict(Counter(r["region"] for r in recipes)))
    print("\n--- 样例 6 条 ---")
    for r in recipes[:3] + recipes[-3:]:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""全局配置。

DeepSeek / SiliconFlow 为可选项：把 API Key 留空即走「本地规则引擎」，
填上 key 后会自动切到大模型增强生成（调用失败仍降级回规则引擎）。
"""
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 大模型 API 配置（DeepSeek 官方平台）
# key 从本地机密文件 _local_secrets.py 读取（已 gitignore，防止泄露到仓库）；
# 没有该文件则退回到环境变量 DEEPSEEK_API_KEY，再没有就留空（走本地规则引擎）。
try:
    from _local_secrets import DEEPSEEK_API_KEY  # type: ignore
except ImportError:
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"  # 官方别名，自动指向最新对话模型

# 视觉大模型配置：DeepSeek 官方视觉模型（2026-08 上线），图片识别优先走它，
# 失败自动降级回本地 YOLO。复用上方 DEEPSEEK_API_KEY，无需额外充值/换平台。
VISION_API_KEY = DEEPSEEK_API_KEY
VISION_BASE_URL = DEEPSEEK_BASE_URL
VISION_MODEL = "deepseek-v4-flash-vision-exp"

# 会话签名密钥（生产环境请改用环境变量 SECRET_KEY）
SECRET_KEY = os.environ.get("SECRET_KEY", "nutrition-demo-secret-key")

# 数据库与数据文件路径（相对项目根目录，运行时解析为绝对路径）
DB_PATH = os.path.join(_BASE_DIR, "database", "nutrition.db")
INGREDIENTS_JSON = os.path.join(_BASE_DIR, "data", "ingredients.json")
RECIPES_JSON = os.path.join(_BASE_DIR, "data", "recipes.json")

# 健康目标（前端展示用）
GOALS = ["减脂", "增肌", "控糖", "均衡"]

# 烹饪方式 → 封面 emoji（菜谱成品图占位；无真实图片时的视觉兜底）
METHOD_EMOJI = {
    "炒": "🍳", "煎": "🍳", "炸": "🍤",
    "蒸": "🥟", "煮": "🍲", "炖": "🍲", "焖": "🍲", "烧": "🍖",
    "烤": "🍢", "拌": "🥗", "饮": "🥤",
}

# 可选禁忌项（过敏原 + 慢病），映射到食材 taboo_tags
TABOO_OPTIONS = {
    "花生": "过敏原",
    "海鲜": "过敏原",
    "鸡蛋": "过敏原",
    "乳制品": "过敏原",
    "麸质": "过敏原",
    "大豆": "过敏原",
    "坚果": "过敏原",
    "糖尿病（控糖）": "慢病",
    "痛风（高嘌呤）": "慢病",
    "高血压（高钠）": "慢病",
    "高血脂（高脂）": "慢病",
    "脂肪肝": "慢病",
    "冠心病": "慢病",
    "胆结石/胆囊炎": "慢病",
    "甲亢（忌碘）": "慢病",
    "高尿酸血症": "慢病",
}

# 图片识别模型（参考 ANFridge：自训练冰箱物品模型可替换此处路径）
YOLO_MODEL = "yolov8n.pt"  # 默认 COCO 预训练兜底；可换成 fridge.pt / fridge.onnx 提升精度

# 模型类别名 -> 营养库中文名映射（COCO 兜底覆盖常见果蔬；定制模型时同步替换此表）
CLASS_TO_INGREDIENT = {
    "banana": "香蕉",
    "apple": "苹果",
    "orange": "橙子",
    "broccoli": "西兰花",
    "carrot": "胡萝卜",
    "sandwich": "面包",
    "hot dog": "香肠",
}

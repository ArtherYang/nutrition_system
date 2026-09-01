# 智能营养膳食制作与推荐系统（V1.1）

面向健康管理场景的 Flask Web 应用：**输入健康目标 + 现有食材 → 输出个性化食谱与搭配建议**。

V1.1 在 M1「数据层 + 核心推荐链路」基础上新增：健康画像、基础疾病禁忌、冰箱图片识别、地区×季节买菜推荐。

## 功能

1. **健康目标管理**（减脂 / 增肌 / 控糖 / 均衡）
2. **健康画像评估**（年龄 / 性别 / 身高 / 体重 → BMI、基础代谢 BMR、理想体重区间 + AI 点评）
3. **营养分析**（995 种食材含调味料：热量 + 三大营养素 + 纤维 + GI）
4. **个性化食谱推荐**（本地规则引擎，1038 道真实菜谱，每道菜标注口味 + 地域/菜系，按目标打分排序）
5. **禁忌 / 过敏原 / 基础疾病过滤**（花生/海鲜/鸡蛋等过敏原 + 糖尿病/痛风/高血压/高血脂/脂肪肝/冠心病/甲亢等慢病）
6. **冰箱图片识别**（拍照识别食材：DeepSeek 视觉大模型优先，本地 YOLO 兜底）
7. **按地区 × 季节买菜推荐**（7 大地区 × 四季时令食材）

## 目录结构

```
nutrition_system/
├── app.py            # Flask 入口（/ 食谱推荐、/market 买菜推荐）
├── config.py         # 配置（DeepSeek / 视觉大模型 / YOLO 可选）
├── requirements.txt
├── yolov8n.pt        # YOLO 本地兜底模型（首次运行自动下载）
├── core/             # 业务模块
│   ├── health_goal.py    # 健康目标 + 禁忌映射
│   ├── health_profile.py # 健康画像（BMI / BMR / 理想体重）
│   ├── nutrition.py      # 营养分析
│   ├── recommender.py    # 食谱推荐（规则引擎 + 可选 LLM 增强）
│   ├── diet_advisor.py   # 搭配建议 + 禁忌过滤
│   ├── recognizer.py     # 图片识别（DeepSeek 视觉大模型 + YOLO 兜底）
│   ├── market.py         # 地区 × 季节买菜推荐
│   └── llm.py            # 共享大模型调用工具
├── data/             # 运行时数据：营养库 ingredients.json + 菜谱库 recipes.json + 基础菜谱 recipes_base.json
├── data_sources/     # 原始下载数据：cfcd/（食物成分表）+ themealdb/（西餐）+ cookbook_kg_entities.json（知识图谱）
├── scripts/          # 一次性脚本：数据下载 / 合并 / 翻译 / 菜谱生成（运行时不依赖）
├── database/         # SQLite 访问层 + 初始化脚本
├── templates/        # 前端页面（index.html / market.html）
└── static/           # 样式
```

## 运行方式

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化数据库（首次运行自动创建，也可手动执行）
python database/init_db.py

# 3. 启动
python app.py
# 浏览器访问 http://127.0.0.1:5000
```

## 大模型增强（可选）

默认走本地规则引擎，无需任何 API Key。如需 DeepSeek 增强生成，在 `config.py` 中填入：

```python
DEEPSEEK_API_KEY = "sk-xxxx"          # DeepSeek 官方平台 key
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
```

调用失败会自动降级回规则引擎，不影响功能。

## 图片识别

- **视觉大模型（优先）**：调用 DeepSeek 官方视觉模型 `deepseek-v4-flash-vision-exp`（复用 `DEEPSEEK_API_KEY`，无需额外充值），可识别任意果蔬/食材，约 2~3 秒返回；失败自动降级到 YOLO。
- **本地兜底**：YOLO（默认 COCO 预训练 `yolov8n.pt`，仅覆盖香蕉/苹果/橙子/西兰花/胡萝卜/面包/香肠 7 类）。首次运行会自动下载模型（约 6MB，需联网）。
- **可替换模型**：参考 [ANFridge](https://github.com/stmxmv/ANFridge)（自训练冰箱物品 YOLOv8 模型）——把 `config.YOLO_MODEL` 指向定制模型 `fridge.pt/.onnx`，并同步更新 `config.CLASS_TO_INGREDIENT` 即可提升本地识别精度。

## 营养数据来源

- 内置 **995 种食材**（原 215 种常用食材 + 扩充）：核心营养数据整合自 [《中国食物成分表（标准版第 6 版）》](https://github.com/Sanotsu/china-food-composition-data)（1677 种食品、61 个分类），经 `scripts/download_cfcd.py` 下载、`scripts/merge_cfcd.py` 解析映射合并进 `data/ingredients.json`。水果 32→79、乳制品 10→45、坚果/肉类/水产/蔬菜等大幅扩充，并补齐常见别名（牛油果/芭乐/西柚/紫甘蓝 等）。
- **GI（升糖指数）**：整合自同仓库 `glycemic_index_of_foods.json`（259 条，含饮料/速食等 11 组）。
- 说明：食物成分表覆盖「食材」营养，不含饮品配方与西餐菜谱；饮料与西餐菜谱如需扩充可参考 [TheMealDB](https://www.themealdb.com)（西餐 + 饮品，免费 API）与 [RecipeNLG](https://recipenlg.cs.utah.edu)（220 万道带步骤菜谱）。

## 菜谱数据来源

- 内置 **1038 道真实菜谱，无模板菜**，全部来自真实来源：
  - **611 道中文菜谱**：**64 道**基础家常菜（`data/recipes_base.json`）+ **359 道**精选名菜（八大菜系 / 家常 / 西式）+ **188 道** [CookBook-KG](https://github.com/ngl567/CookBook-KG) 知识图谱导入（图谱原始数据见 `data_sources/cookbook_kg_entities.json`）。
  - **427 道西餐 / 饮料**：**395 道**西餐来自 [TheMealDB](https://www.themealdb.com)（英式/法式/意式/西班牙式/美式等 20 个菜系）+ **32 款**无酒精水果饮料（奶昔/冰沙/果汁）来自 [TheCocktailDB](https://www.thecocktaildb.com)，经 `scripts/download_western.py` 下载、`scripts/integrate_western.py` 英文食材→中文映射整合。
- 食材全部对齐营养库（995 种，含调味料）。可运行 `python scripts/gen_recipes.py` 重新生成中文菜谱。
- **CookBook-KG**（中式菜谱知识图谱）提供了真实的结构化菜谱：每道菜含 `主料/辅料/特色(口味/工艺/耗时/难度)/制作步骤`，导入时经食材映射对齐到营养库、保留真实口味（`flavor`）、推断地域/菜系（`region`）、保留真实制作步骤。
- 每道菜标注 `flavor`（口味）+ `region`（地域/菜系）两个标签：口味同时参考 [what-to-eat](https://github.com/liu-ziting/what-to-eat)（一饭封神，中华八大菜系 + 国际料理的「口味 specialty」字段）。
- 说明：为遵循「只用真实菜、不要模板菜」，水果、坚果等生食类食材按真实菜谱自然覆盖（未用「X 酸奶杯 / X 奶昔 / 每日坚果碗」等批量模板补位）；蔬菜、肉类、水产、豆类、主食等主要食材均覆盖 ≥3 道菜。
- 如需更大规模中文菜谱，可参考 [Cookbook-Dataset](https://github.com/Cathy-wang132/Cookbook-Dataset)（13943 道中文菜谱，需付费获取）。

> ⚠️ 本系统建议仅供膳食参考，不构成医疗诊断或治疗建议。

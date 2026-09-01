# -*- coding: utf-8 -*-
"""食材识别（IngredientRecognizer）：YOLO 本地兜底 + 预留视觉大模型接口。

参考 ANFridge 的「检测 → 映射到物品清单」模式：
- 本地兜底：YOLO（默认 COCO 预训练 yolov8n.pt，可替换为定制冰箱模型 fridge.pt/.onnx）
- 预留接口：视觉大模型（配置 VISION_API_KEY 后优先走，失败自动降级回 YOLO）
"""
import base64
import io

import config

_CONF_THRESHOLD = 0.35


class IngredientRecognizer:
    """识别图片中的食材，返回 [{name, confidence}]。"""

    def __init__(self):
        self._model = None

    # ---------- YOLO 本地兜底 ----------
    def _load_model(self):
        if self._model is None:
            import os

            # 模型文件缺失时快速失败（返回空），避免在请求里卡住去慢速下载
            if not os.path.exists(config.YOLO_MODEL):
                raise RuntimeError(
                    f"模型文件不存在：{config.YOLO_MODEL}，请先运行 download_model.py 下载"
                )
            from ultralytics import YOLO

            self._model = YOLO(config.YOLO_MODEL)
        return self._model

    def recognize(self, image_bytes):
        """YOLO 检测，仅保留映射表中的食物类，按置信度降序去重返回。"""
        try:
            model = self._load_model()
            img = _open_image(image_bytes)
            results = model.predict(img, verbose=False)
            best = {}
            for r in results:
                for box in r.boxes:
                    cls_name = model.names.get(int(box.cls[0]))
                    conf = float(box.conf[0])
                    if cls_name in config.CLASS_TO_INGREDIENT and conf >= _CONF_THRESHOLD:
                        name = config.CLASS_TO_INGREDIENT[cls_name]
                        if conf > best.get(name, -1.0):
                            best[name] = conf
            return sorted(
                [{"name": n, "confidence": round(c, 3)} for n, c in best.items()],
                key=lambda x: x["confidence"],
                reverse=True,
            )
        except Exception:
            return []

    # ---------- 预留视觉大模型接口 ----------
    def recognize_with_vision(self, image_bytes):
        """视觉大模型解析；未配置 key 或失败返回 None（调用方降级到 YOLO）。"""
        if not config.VISION_API_KEY:
            return None
        try:
            import requests

            b64 = base64.b64encode(image_bytes).decode()
            prompt = (
                "识别图片中出现的食材（蔬菜、水果、肉类、蛋奶、主食等）。"
                "只输出一个 JSON 数组，元素是食材的中文名称，例如 [\"土豆\",\"白菜\"]；"
                "如果图中没有食材，输出 []。不要输出任何其他文字、解释或代码块。"
            )
            resp = requests.post(
                f"{config.VISION_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.VISION_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.VISION_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url",
                                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            ],
                        }
                    ],
                    "temperature": 0.1,
                    "max_tokens": 200,
                },
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            print(f"[vision] 原始返回: {text!r}", flush=True)  # 调试日志，便于排查
            return [{"name": n, "confidence": 1.0}
                    for n in _parse_vision_names(text)]
        except Exception as e:
            print(f"[vision] 调用失败: {type(e).__name__}: {e}", flush=True)
            return None


def _parse_vision_names(text):
    """把视觉模型的回复解析成食材名列表：优先 JSON，兜底按分隔符切分。"""
    import json
    import re

    if not text:
        return []
    stop = {"无", "没有", "无食材", "没有食材", "未识别", "未识别到",
            "识别不到", "无法识别", "图中没有食材", "[]", "无。", "没有。"}
    # 1) 整段就是 JSON 数组
    try:
        arr = json.loads(text)
        if isinstance(arr, list):
            return [str(x).strip() for x in arr if str(x).strip()]
    except Exception:
        pass
    # 2) 模型常在外层包一层说明/代码块，提取方括号里的 JSON
    m = re.search(r"\[[^\]]*\]", text)
    if m:
        try:
            arr = json.loads(m.group(0))
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    # 3) 兜底：按顿号/逗号/空格切分，过滤明显否定词
    names = [n.rstrip("。.!！：:") for n in re.split(r"[,，、;；\s]+", text) if n]
    return [n for n in names if n and n not in stop]


def _open_image(image_bytes):
    """把字节流转成 PIL Image（YOLO 可直接推理）。"""
    from PIL import Image

    return Image.open(io.BytesIO(image_bytes)).convert("RGB")

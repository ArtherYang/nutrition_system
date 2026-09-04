# -*- coding: utf-8 -*-
"""体检单解析（HealthReport）：视觉大模型读取体检报告 → 关键异常指标 → 禁忌建议。

解析结果仅用于「自动勾选禁忌 / 提示健康目标」，不构成医疗诊断。
"""
import json
import re

from core import llm

# 判定为「异常」的状态词
_ABNORMAL = {"偏高", "高", "↑", "异常", "超标"}


def parse_report(image_bytes):
    """调用视觉大模型解析体检单，返回 {指标: 状态} dict；失败/未配置返回 None。"""
    prompt = (
        "这是用户的体检报告图片。请识别其中与膳食相关的关键指标（血糖、尿酸、血脂、血压等），"
        "判断其是否异常。只输出一个 JSON 对象，键为指标名，值为「正常 / 偏高 / 偏低」，"
        '例如 {"血糖":"偏高","尿酸":"偏高"}。'
        "如果图中没有这些指标或无法识别，输出 {}。不要输出任何其他文字、解释或代码块。"
    )
    # max_tokens 需给足：该视觉模型为推理型，会在 reasoning 阶段消耗大量 token，
    # 太小会因 finish_reason=length 而 content 为空，导致解析失败。
    text = llm.vision(image_bytes, prompt, max_tokens=2000)
    if not text:
        return None
    return _parse_json(text)


def extract_pdf_text(pdf_bytes):
    """用 PyMuPDF 提取 PDF 全文，返回纯文本；失败返回空串。"""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            return "\n".join(page.get_text() for page in doc).strip()
        finally:
            doc.close()
    except Exception:
        return ""


def pdf_pages_to_images(pdf_bytes, max_pages=2, dpi=150):
    """把 PDF 前几页渲染为 PNG 图片字节列表（用于无文本的扫描件走视觉识别）。"""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        imgs = []
        try:
            for page in doc[:max_pages]:
                pix = page.get_pixmap(matrix=mat)
                imgs.append(pix.tobytes("png"))
        finally:
            doc.close()
        return imgs
    except Exception:
        return []


def parse_report_text(text):
    """用文本大模型解析体检报告文本，返回 {指标: 状态} dict；失败返回 None。"""
    if not text:
        return None
    prompt = (
        "你是体检报告解析助手。下面给出体检报告的文字内容，请识别其中与膳食相关的关键指标"
        "（血糖/葡萄糖、尿酸、胆固醇/甘油三酯/血脂、血压等），判断是否异常。"
        "只输出一个 JSON 对象，键为指标名，值为「正常 / 偏高 / 偏低」。"
        '例如 {"血糖":"偏高","尿酸":"偏高"}。'
        "如果没有这些指标或无法判断，输出 {}。不要输出任何其他文字、解释或代码块。"
    )
    result = llm.chat(prompt, f"体检报告文本：\n{text}", max_tokens=500, temperature=0.1)
    if not result:
        return None
    return _parse_json(result)


def parse_report_file(content_type, data):
    """按文件类型解析体检单，返回 {指标: 状态} dict；失败返回 None。

    图片：直接走视觉大模型。PDF：优先提取文本用文本大模型解析；
    文本为空（扫描件）或解析失败时，渲染前几页为图片回退到视觉大模型。
    """
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return parse_report(data)
    if ct == "application/pdf":
        text = extract_pdf_text(data)
        if len(text) >= 20:
            markers = parse_report_text(text)
            if markers is not None:
                return markers
        for img in pdf_pages_to_images(data):
            markers = parse_report(img)
            if markers:
                return markers
        return None
    return None


def _parse_json(text):
    """从模型回复中提取 JSON 对象，失败返回空 dict。"""
    if not text:
        return {}
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    m = re.search(r"\{[^{}]*\}", text)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            pass
    return {}


def markers_to_taboos(markers):
    """把异常指标映射为禁忌项 label 列表（仅保留异常项，去重）。

    化验单常出现「空腹血糖/葡萄糖/总胆固醇/甘油三酯/低密度脂蛋白」等具体指标名，
    因此按关键词匹配；「高密度脂蛋白胆固醇」（好胆固醇）偏高不算高血脂，予以排除。
    """
    if not markers:
        return []
    taboos = []

    def abnormal(pred):
        return any(markers[k] in _ABNORMAL for k in markers if pred(k))

    if abnormal(lambda k: "血糖" in k or "葡萄糖" in k):
        taboos.append("糖尿病（控糖）")
    if abnormal(lambda k: "尿酸" in k):
        taboos.append("高尿酸血症")
    if abnormal(lambda k: ("胆固醇" in k or "甘油三酯" in k or "血脂" in k)
                and "高密度脂蛋白" not in k):
        taboos.append("高血脂（高脂）")
    if abnormal(lambda k: "血压" in k or "收缩压" in k or "舒张压" in k):
        taboos.append("高血压（高钠）")
    return taboos


def markers_summary(markers):
    """把 markers 转成可读摘要文本（用于展示 / 存储）。"""
    if not markers:
        return ""
    return "；".join(f"{k}：{v}" for k, v in markers.items())

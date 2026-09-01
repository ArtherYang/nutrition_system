# -*- coding: utf-8 -*-
"""下载《中国食物成分表(第6版)》JSON 数据（Sanotsu/china-food-composition-data）。

把 fixed 版 61 个分类文件 + GI 文件下载到 data_sources/cfcd/。
"""
import base64
import json
import os
import urllib.parse
import urllib.request

API = "https://api.github.com/repos/Sanotsu/china-food-composition-data"
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 关闭代理
_opener.addheaders = [("User-Agent", "Mozilla/5.0")]


def _get(url):
    with _opener.open(url, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    tree = _get(f"{API}/git/trees/main?recursive=1")["tree"]
    files = [
        t for t in tree
        if t["type"] == "blob" and t["path"].endswith(".json")
        and ("_fixed/" in t["path"] and "log" not in t["path"]
             or t["path"].endswith("glycemic_index_of_foods.json"))
    ]
    out_dir = os.path.join("data_sources", "cfcd")
    os.makedirs(out_dir, exist_ok=True)

    total = 0
    for t in files:
        d = _get(f"{API}/contents/{urllib.parse.quote(t['path'], safe='/')}")
        raw = base64.b64decode(d["content"])
        name = t["path"].split("/")[-1]
        if name.startswith("merged_"):
            name = name[len("merged_"):]
        local = os.path.join(out_dir, name)
        with open(local, "wb") as f:
            f.write(raw)
        n = len(json.loads(raw))
        total += n
        print(f"  {name:38} {n:5} 条")
    print(f"\n共 {len(files)} 个文件，{total} 条食品 -> {out_dir}")


if __name__ == "__main__":
    main()

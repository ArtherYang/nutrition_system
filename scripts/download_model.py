# -*- coding: utf-8 -*-
"""下载 YOLO 预训练权重 yolov8n.pt。

问题：github.com 的 CDN（release-assets.githubusercontent.com）在本网络被墙，
    但底层 Azure Blob（releaseassetproduction.blob.core.windows.net）可达。
做法：走 api.github.com 拿到 302 重定向的签名 URL，把主机换成 Azure Blob 直连下载。
"""
import sys

import requests

# yolov8n.pt 的 release 资产 ID（v8.4.0，仓库 ultralytics/assets）
ASSET_URL = "https://api.github.com/repos/ultralytics/assets/releases/assets/340060940"
CDN_HOST = "release-assets.githubusercontent.com"
BLOB_HOST = "releaseassetproduction.blob.core.windows.net"
OUT = "yolov8n.pt"


def main():
    # 1. 拿 302 Location（不跟随重定向，得到 CDN 签名 URL）
    resp = requests.get(
        ASSET_URL,
        headers={"Accept": "application/octet-stream"},
        allow_redirects=False,
        timeout=30,
    )
    if resp.status_code not in (301, 302, 307, 308):
        print(f"[!] 获取重定向失败，HTTP {resp.status_code}", file=sys.stderr)
        sys.exit(1)
    loc = resp.headers["Location"]

    # 2. 把被墙的 CDN 主机替换成可达的 Azure Blob 主机（路径 + SAS 签名不变）
    if CDN_HOST in loc:
        loc = loc.replace(CDN_HOST, BLOB_HOST)
    print("下载源已切换为 Azure Blob 直连…")

    # 3. 流式下载
    with requests.get(loc, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with open(OUT, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    print(f"\r  下载中 {done}/{total} 字节（{pct}%）", end="", flush=True)
        print()
    print(f"完成：{OUT}（{done} 字节）")


if __name__ == "__main__":
    main()

"""
最小脚本：提取小红书作品真实直链（视频/图文）

依赖：httpx, lxml, pyyaml

用法示例：
  python xhs_extract_links.py "https://www.xiaohongshu.com/explore/XXXXXXXX"
  python xhs_extract_links.py "https://xhslink.com/xxxx" --image-format PNG

参数：
  --cookie 可选，若访问受限可提供网页版 Cookie
  --proxy  可选，HTTP 代理，如：http://127.0.0.1:7890
  --image-format 图文直链格式：PNG/WEBP/JPEG/HEIC/AVIF/AUTO（默认：PNG）

返回：JSON，包含作品类型、作品ID、下载直链数组。
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import httpx
from lxml.etree import HTML
from yaml import safe_load


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def clean_share_url(text: str) -> str:
    """从分享文案中提取首个合法链接，保留全部查询参数与锚点。

    - 支持 xhslink 短链
    - 支持 xiaohongshu explore/discovery/item 链接
    - 不修改 URL 的查询参数（如 xsec_token）与锚点
    """
    import re

    if not text:
        return text

    pattern = re.compile(
        r"https?://(?:www\.)?(?:xiaohongshu\.com/(?:explore|discovery/item)/[0-9a-zA-Z]+(?:\?[^\s#]*)?(?:#[^\s]*)?|xhslink\.com/[^\s\"<>\\^`{|}，。；！？、【】《》]+)",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return text

    url = m.group(0)
    return url


def format_url(url: str) -> str:
    try:
        return bytes(url, "utf-8").decode("unicode_escape")
    except Exception:
        return url


def deep_get(data: Dict[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    cur: Any = data
    try:
        for key in keys:
            if isinstance(cur, dict):
                cur = cur[key]
            elif isinstance(cur, (list, tuple)):
                if not key.startswith("[") or not key.endswith("]"):
                    # 将普通 key 映射为索引 0 的取值（兼容 noteDetailMap 为 dict 的情况）
                    cur = list(cur)[0]  # type: ignore[index]
                else:
                    idx = int(key[1:-1])
                    cur = cur[idx]
            else:
                return default
        return cur
    except Exception:
        return default


def safe_get(data: Any, index: int) -> Any:
    if isinstance(data, dict):
        return list(data.values())[index]
    if isinstance(data, (list, tuple)):
        return data[index]
    raise TypeError


def get_initial_state_script(html_text: str) -> str:
    if not html_text:
        return ""
    tree = HTML(html_text)
    scripts = tree.xpath("//script/text()")
    scripts.reverse()
    for script in scripts:
        if isinstance(script, str) and script.startswith("window.__INITIAL_STATE__"):
            return script
    return ""


def parse_note_payload(html_text: str) -> Dict[str, Any]:
    script = get_initial_state_script(html_text)
    if not script:
        return {}
    try:
        data = safe_load(script.lstrip("window.__INITIAL_STATE__="))
    except Exception:
        return {}

    # 路径：note -> noteDetailMap -> [-1] -> note
    # 兼容 noteDetailMap 为 dict/list 的情况
    def _deep_get(d: Dict[str, Any], keys: Sequence[str]) -> Any:
        cur: Any = d
        try:
            for key in keys:
                if key.startswith("[") and key.endswith("]"):
                    idx = int(key[1:-1])
                    if isinstance(cur, dict):
                        cur = list(cur.values())[idx]
                    else:
                        cur = cur[idx]
                else:
                    cur = cur[key]
            return cur
        except Exception:
            return None

    payload = _deep_get(data, ("note", "noteDetailMap", "[-1]", "note"))
    if not payload:
        # 回退尝试常见结构
        try:
            ndm = data.get("note", {}).get("noteDetailMap", {})
            if isinstance(ndm, dict) and ndm:
                payload = list(ndm.values())[-1]["note"]
        except Exception:
            payload = None
    return payload or {}


def classify_note_type(payload: Dict[str, Any]) -> str:
    note_type = payload.get("type")
    image_list = payload.get("imageList") or []
    if note_type not in {"video", "normal"} or len(image_list) == 0:
        return "未知"
    if note_type == "video":
        return "视频" if len(image_list) == 1 else "图集"
    return "图文"


def extract_image_token(url_default: str) -> str:
    # 与项目逻辑一致：取第 6 段及后续拼接，再去掉 ! 之后的参数
    parts = url_default.split("/")
    token = "/".join(parts[5:]) if len(parts) >= 6 else url_default
    return token.split("!")[0]


def build_image_links(payload: Dict[str, Any], image_format: str) -> List[str]:
    image_list = payload.get("imageList") or []
    tokens: List[str] = []
    for item in image_list:
        url_default = ((item or {}).get("urlDefault")) or ""
        if url_default:
            tokens.append(extract_image_token(url_default))

    fmt = image_format.strip().lower()
    links: List[str] = []
    if fmt in {"png", "webp", "jpeg", "heic", "avif"}:
        for t in tokens:
            links.append(format_url(f"https://ci.xiaohongshu.com/{t}?imageView2/format/{fmt}"))
    elif fmt == "auto":
        for t in tokens:
            links.append(format_url(f"https://sns-img-bd.xhscdn.com/{t}"))
    else:
        raise ValueError("Unsupported image format. Use PNG/WEBP/JPEG/HEIC/AVIF/AUTO")
    return links


def build_video_links(payload: Dict[str, Any]) -> List[str]:
    key = (
        payload.get("video", {})
        .get("consumer", {})
        .get("originVideoKey")
    )
    if not key:
        return []
    return [format_url(f"https://sns-video-bd.xhscdn.com/{key}")]


def fetch_html(url: str, *, cookie: Optional[str], proxy: Optional[str]) -> Tuple[str, str]:
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if cookie:
        headers["Cookie"] = cookie

    if not url.startswith("http"):
        url = f"https://{url}"

    request_kwargs: Dict[str, Any] = {
        "headers": headers,
        "follow_redirects": True,
        "timeout": 15.0,
    }
    if proxy:
        request_kwargs["proxies"] = {"http": proxy, "https": proxy}
        request_kwargs["verify"] = False

    resp = httpx.get(url, **request_kwargs)
    resp.raise_for_status()
    return str(resp.url), resp.text


def extract_xhs_links(
    url: str,
    *,
    image_format: str = "PNG",
    cookie: Optional[str] = None,
    proxy: Optional[str] = None,
) -> Dict[str, Any]:
    url = clean_share_url(url)
    final_url, html = fetch_html(url, cookie=cookie, proxy=proxy)
    payload = parse_note_payload(html)
    if not payload:
        return {
            "ok": False,
            "message": "解析失败：未找到 note 数据",
            "url": final_url,
        }

    note_type = classify_note_type(payload)
    note_id = payload.get("noteId") or urlparse(final_url).path.split("/")[-1]
    # 尝试提取标题与作者
    title = payload.get("title") or payload.get("desc") or ""
    author = ""
    try:
        u = payload.get("user") or {}
        author = (u.get("nickname") or u.get("name") or "") if isinstance(u, dict) else ""
    except Exception:
        author = ""

    if note_type in {"图文", "图集"}:
        urls = build_image_links(payload, image_format)
    elif note_type == "视频":
        urls = build_video_links(payload)
    else:
        urls = []

    return {
        "ok": True if urls else False,
        "type": note_type,
        "note_id": note_id,
        "url": final_url,
        "download_urls": urls,
        "title": title,
        "author": author,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = ArgumentParser(description="提取小红书作品真实直链（视频/图文）")
    parser.add_argument("url", help="作品链接，支持 xhslink 短链、explore/discovery/item 页面链接")
    parser.add_argument("--cookie", default=None, help="可选，网页版 Cookie")
    parser.add_argument("--proxy", default=None, help="可选，HTTP 代理，如：http://127.0.0.1:7890")
    parser.add_argument(
        "--image-format",
        default="PNG",
        choices=["PNG", "WEBP", "JPEG", "HEIC", "AVIF", "AUTO", "png", "webp", "jpeg", "heic", "avif", "auto"],
        help="图文直链格式（默认：PNG）",
    )
    args = parser.parse_args(argv)

    try:
        result = extract_xhs_links(
            args.url,
            image_format=args.image_format,
            cookie=args.cookie,
            proxy=args.proxy,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    except Exception as e:
        print(json.dumps({"ok": False, "message": f"异常：{e}"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())



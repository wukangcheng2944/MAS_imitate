#!/usr/bin/env python3
"""
YouTube audio link extractor (仅支持 YouTube)

This script uses yt-dlp to retrieve direct downloadable links and metadata for YouTube only.

Usage:
  python direct_link_extractor.py <video_url>

Output: JSON to stdout with fields:
  - status: success|error
  - site: extractor name
  - id, title, duration, thumbnail, webpage_url
  - best: a selected best direct link entry
  - formats: list of available formats (filtered, direct links)

Dependencies:
  pip install -r requirements.txt  (yt-dlp)
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional
import argparse
import os
import random
from urllib.parse import urlparse

# Avoid curl_cffi (may pull gevent/greenlet causing binary incompatibility)
os.environ.setdefault("YTDLP_NO_CURL_CFFI", "1")

import yt_dlp


def _random_user_agent() -> str:
    """Generate a realistic desktop/mobile User-Agent string."""
    chrome_major = random.randint(114, 127)
    chrome_build = random.randint(0, 6000)
    candidates = [
        # Windows Chrome
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.{chrome_build}.0 Safari/537.36",
        # Windows 11 Chrome
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.{chrome_build}.0 Safari/537.36",
        # macOS Chrome
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_{random.randint(14, 15)}_{random.randint(0, 7)}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.{chrome_build}.0 Safari/537.36",
        # Android Chrome
        f"Mozilla/5.0 (Linux; Android {random.randint(10, 14)}; Pixel {random.randint(4, 8)}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.{chrome_build}.0 Mobile Safari/537.36",
    ]
    return random.choice(candidates)


def _build_referer_for(url: str) -> str:
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or "www.youtube.com"
        return f"{scheme}://{netloc}/"
    except Exception:
        return "https://www.youtube.com/"


def _build_rotating_headers(page_url: str, *, randomize: bool = True) -> Dict[str, str]:
    ua = _random_user_agent() if randomize else (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    lang_pool = [
        "zh-CN,zh;q=0.9",
        "en-US,en;q=0.9",
        "zh-CN,zh;q=0.8,en;q=0.6",
    ]
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": random.choice(lang_pool),
        "Referer": _build_referer_for(page_url),
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
    }
    return headers


def _should_retry_with_new_headers(err: Exception) -> bool:
    text = str(err).lower()
    return any(code in text for code in ["403", "429", "forbidden", "too many requests"]) 

def _select_preferred_format(formats: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick a good direct link format (progressive MP4 with audio preferred)."""
    if not formats:
        return None

    def is_progressive_mp4(fmt: Dict[str, Any]) -> bool:
        ext = (fmt.get("ext") or "").lower()
        has_video = (fmt.get("vcodec") or "none") != "none"
        has_audio = (fmt.get("acodec") or "none") != "none"
        protocol = (fmt.get("protocol") or "").lower()
        return ext == "mp4" and has_video and has_audio and protocol in {"https", "http"}

    # 1) Prefer progressive MP4 with highest resolution/bitrate
    progressive = [f for f in formats if is_progressive_mp4(f)]
    if progressive:
        # Sort by resolution, then by tbr (total bitrate)
        progressive.sort(key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)
        return progressive[0]

    # 2) Otherwise pick the highest tbr https format that includes video
    https_with_video = [
        f for f in formats
        if (f.get("protocol") or "").lower() in {"https", "http"}
        and (f.get("vcodec") or "none") != "none"
    ]
    if https_with_video:
        https_with_video.sort(key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)
        return https_with_video[0]

    # 3) Fallback to max tbr format regardless of protocol
    by_quality = sorted(formats, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)
    return by_quality[0] if by_quality else None


def _filter_direct_formats(all_formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only formats with direct URL usable for download (exclude manifests when possible)."""
    if not all_formats:
        return []

    filtered: List[Dict[str, Any]] = []
    for fmt in all_formats:
        url: Optional[str] = fmt.get("url")
        if not url:
            continue

        protocol = (fmt.get("protocol") or "").lower()
        # Exclude manifests unless nothing else is available
        if protocol in {"m3u8", "m3u8_native", "http_dash_segments", "dash"}:
            continue

        filtered.append({
            "format_id": fmt.get("format_id"),
            "ext": fmt.get("ext"),
            "vcodec": fmt.get("vcodec"),
            "acodec": fmt.get("acodec"),
            "tbr": fmt.get("tbr"),
            "fps": fmt.get("fps"),
            "width": fmt.get("width"),
            "height": fmt.get("height"),
            "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
            "protocol": protocol,
            "url": url,
        })

    # If nothing left, allow manifests as fallback
    if not filtered:
        for fmt in all_formats:
            url = fmt.get("url")
            if not url:
                continue
            filtered.append({
                "format_id": fmt.get("format_id"),
                "ext": fmt.get("ext"),
                "vcodec": fmt.get("vcodec"),
                "acodec": fmt.get("acodec"),
                "tbr": fmt.get("tbr"),
                "fps": fmt.get("fps"),
                "width": fmt.get("width"),
                "height": fmt.get("height"),
                "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
                "protocol": (fmt.get("protocol") or "").lower(),
                "url": url,
            })

    return filtered


def _filter_audio_formats(all_formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter audio-only formats with direct URLs when possible."""
    if not all_formats:
        return []

    audio_list: List[Dict[str, Any]] = []
    for fmt in all_formats:
        url: Optional[str] = fmt.get("url")
        if not url:
            continue

        vcodec = (fmt.get("vcodec") or "none").lower()
        acodec = (fmt.get("acodec") or "none").lower()
        protocol = (fmt.get("protocol") or "").lower()

        # Audio-only: vcodec is none, acodec present
        if vcodec == "none" and acodec != "none":
            # Prefer direct links over manifests
            if protocol in {"m3u8", "m3u8_native", "http_dash_segments", "dash"}:
                # skip manifest when we can; we'll fallback later if needed
                continue

            audio_list.append({
                "format_id": fmt.get("format_id"),
                "ext": (fmt.get("ext") or "").lower(),
                "acodec": acodec,
                "abr": fmt.get("abr"),  # audio bitrate
                "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
                "protocol": protocol,
                "url": url,
            })

    # If none, allow manifests as fallback
    if not audio_list:
        for fmt in all_formats:
            url = fmt.get("url")
            if not url:
                continue
            vcodec = (fmt.get("vcodec") or "none").lower()
            acodec = (fmt.get("acodec") or "none").lower()
            if vcodec == "none" and acodec != "none":
                audio_list.append({
                    "format_id": fmt.get("format_id"),
                    "ext": (fmt.get("ext") or "").lower(),
                    "acodec": acodec,
                    "abr": fmt.get("abr"),
                    "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
                    "protocol": (fmt.get("protocol") or "").lower(),
                    "url": url,
                })

    return audio_list


def _select_preferred_audio_format(audio_formats: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Choose best audio-only format. Prefer m4a > webm/opus > others by abr and filesize."""
    if not audio_formats:
        return None

    def preference_score(fmt: Dict[str, Any]) -> tuple:
        ext = fmt.get("ext") or ""
        # Higher is better
        ext_pref = {
            "m4a": 3,
            "mp4a": 3,
            "mp4": 2,
            "webm": 1,
        }.get(ext, 0)
        abr = fmt.get("abr") or 0
        size = fmt.get("filesize") or 0
        return (ext_pref, abr, size)

    return sorted(audio_formats, key=preference_score, reverse=True)[0]


def extract_direct_links(
    url: str,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    browser_profile: Optional[str] = None,
    proxy: Optional[str] = None,
    rotate_headers: bool = True,
) -> Dict[str, Any]:
    """Extract direct links and metadata for a given URL using yt-dlp."""
    # yt_dlp = _import_yt_dlp()

    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "forcejson": True,
    }

    # 自动更换请求头，降低被识别概率
    if rotate_headers:
        hdrs = _build_rotating_headers(url, randomize=True)
        ydl_opts["http_headers"] = hdrs
        ydl_opts["user_agent"] = hdrs.get("User-Agent")
        ydl_opts["referer"] = hdrs.get("Referer")

    # 可选：代理
    if proxy:
        ydl_opts["proxy"] = proxy

    # 可选：Cookies 文件（Netscape 格式）
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file

    # 可选：从浏览器读取 Cookies（如 chrome）
    # 注意：在 WSL 中直接读取 Windows Chrome Cookies 可能失败，推荐使用 cookies 文件
    if cookies_from_browser:
        # 格式: (browser, profile, keyring, container)
        # 仅指定 browser 与可选的 profile
        ydl_opts["cookiesfrombrowser"] = (
            cookies_from_browser,
            browser_profile if browser_profile else None,
            None,
            None,
        )

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        # 如果启用了浏览器 Cookie 且失败，回退为不使用浏览器 Cookie 再试一次
        if ydl_opts.get("cookiesfrombrowser") is not None:
            ydl_opts.pop("cookiesfrombrowser", None)
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as exc2:
                # 再尝试更换一组请求头
                if rotate_headers and _should_retry_with_new_headers(exc2):
                    hdrs = _build_rotating_headers(url, randomize=True)
                    ydl_opts["http_headers"] = hdrs
                    ydl_opts["user_agent"] = hdrs.get("User-Agent")
                    ydl_opts["referer"] = hdrs.get("Referer")
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(url, download=False)
                    except Exception as exc3:
                        return {"status": "error", "error": str(exc3)}
                else:
                    return {"status": "error", "error": str(exc2)}
        else:
            # 未启用浏览器 Cookie，若是风控类错误则更换请求头重试一次
            if rotate_headers and _should_retry_with_new_headers(exc):
                hdrs = _build_rotating_headers(url, randomize=True)
                ydl_opts["http_headers"] = hdrs
                ydl_opts["user_agent"] = hdrs.get("User-Agent")
                ydl_opts["referer"] = hdrs.get("Referer")
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                except Exception as exc4:
                    return {"status": "error", "error": str(exc4)}
            else:
                return {"status": "error", "error": str(exc)}

    # If it's a playlist/channel, try to pick the first entry
    if info.get("entries"):
        entries = info["entries"]
        info = entries[0] if entries else info

    extractor: str = info.get("extractor", info.get("extractor_key", "unknown"))
    title: Optional[str] = info.get("title")
    uploader: Optional[str] = info.get("uploader") or info.get("channel")
    video_id: Optional[str] = info.get("id")
    duration: Optional[float] = info.get("duration")
    thumbnail: Optional[str] = info.get("thumbnail")
    webpage_url: Optional[str] = info.get("webpage_url", url)

    direct_formats = _filter_direct_formats(info.get("formats") or [])
    best = _select_preferred_format(direct_formats)

    audio_formats = _filter_audio_formats(info.get("formats") or [])
    audio_best = _select_preferred_audio_format(audio_formats)

    return {
        "status": "success",
        "site": extractor,
        "id": video_id,
        "title": title,
        "uploader": uploader,
        "duration": duration,
        "thumbnail": thumbnail,
        "webpage_url": webpage_url,
        "best": best,
        "formats": direct_formats,
        "audio_best": audio_best,
        "audio_formats": audio_formats,
    }


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Direct video link extractor (yt-dlp)")
    parser.add_argument("url", help="视频页面 URL")
    parser.add_argument("--cookies-file", dest="cookies_file", help="Netscape 格式 cookies.txt 文件路径")
    parser.add_argument("--cookies-from-browser", dest="cookies_from_browser", default="chrome", help="从浏览器读取 Cookies（默认: chrome）")
    parser.add_argument("--browser-profile", dest="browser_profile", default="Default", help="浏览器配置文件名（默认: Default）")
    parser.add_argument("--proxy", dest="proxy", help="代理，例如: http://127.0.0.1:7890 或 socks5://127.0.0.1:1080")
    parser.add_argument("--audio-only", dest="audio_only", action="store_true", help="仅输出音频直链（若找到）")
    parser.add_argument("--disable-rotate-headers", dest="disable_rotate_headers", action="store_true", help="禁用自动更换请求头（默认启用）")

    args = parser.parse_args(argv[1:])

    result = extract_direct_links(
        url=args.url,
        cookies_file=args.cookies_file,
        cookies_from_browser=args.cookies_from_browser,
        browser_profile=args.browser_profile,
        proxy=args.proxy,
        rotate_headers=not args.disable_rotate_headers,
    )
    if args.audio_only:
        if result.get("status") == "success" and result.get("audio_best"):
            # 仅输出音频 URL，便于脚本管道使用
            print(result["audio_best"]["url"])  # type: ignore[index]
            return 0
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1

    # YouTube 默认仅输出带音频的视频中画质最好的直链（优先 progressive MP4）
    if (
        result.get("status") == "success"
        and isinstance(result.get("site"), str)
        and "youtube" in str(result.get("site")).lower()
        and result.get("best")
    ):
        print(result["best"]["url"])  # type: ignore[index]
        return 0

    # 仅支持 YouTube，其它站点返回错误
    if result.get("status") == "success":
        site = str(result.get("site") or "").lower()
        if "youtube" not in site:
            print(json.dumps({
                "status": "error",
                "error": "仅支持 YouTube 链接。",
                "site": result.get("site"),
            }, ensure_ascii=False, indent=2))
            return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))



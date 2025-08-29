#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
未实现，暂时不使用
Azure AI Speech - Batch Transcription (single public URL) -> plain text to stdout
Async version using asyncio + httpx.

Install:
  pip install httpx python-dotenv

Env (fallback if CLI args not provided):
  AZURE_SPEECH_KEY
  AZURE_SPEECH_REGION

CLI:
  python azure_plain_transcribe_async_single.py "https://example.com/video.mp4" --locale zh-CN --name "demo"
"""

import os
import sys
import json
import time
import argparse
import asyncio
from typing import Dict, Any, Optional, List

API_VERSION = "2024-11-15"  # Azure Speech Batch Transcription REST API

# --- optional dotenv (no hard dependency if not installed) ---
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    def load_dotenv(*args, **kwargs):
        return None

import httpx


def _headers(key: str, is_json: bool = True) -> Dict[str, str]:
    h = {"Ocp-Apim-Subscription-Key": key}
    if is_json:
        h["Content-Type"] = "application/json"
    return h


async def _submit(
    client: httpx.AsyncClient,
    endpoint: str,
    key: str,
    url_single: str,
    locale: str,
    display_name: str,
    ttl_hours: int = 48,
) -> Dict[str, Any]:
    api = f"{endpoint}/speechtotext/transcriptions:submit?api-version={API_VERSION}"
    payload = {
        "contentUrls": [url_single],  # 只提交一条公网直链
        "locale": locale,
        "displayName": display_name,
        "properties": {
            "wordLevelTimestampsEnabled": False,
            "punctuationMode": "DictatedAndAutomatic",
            "profanityFilterMode": "Masked",
            "timeToLiveHours": int(ttl_hours),
        },
    }
    r = await client.post(api, headers=_headers(key, True), content=json.dumps(payload))
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"Submit failed: {r.status_code} {r.text}")
    return r.json()


def _transcription_id(self_uri: str) -> str:
    return self_uri.rstrip("/").split("/")[-1]


async def _poll(
    client: httpx.AsyncClient,
    endpoint: str,
    key: str,
    transcription_id: str,
    poll_interval: float = 5.0,
    max_minutes: int = 360,
    log: bool = True,
) -> Dict[str, Any]:
    api = f"{endpoint}/speechtotext/transcriptions/{transcription_id}?api-version={API_VERSION}"
    deadline = time.time() + max_minutes * 60
    last_status: Optional[str] = None

    while True:
        r = await client.get(api, headers=_headers(key, False))
        if r.status_code != 200:
            raise RuntimeError(f"Poll failed: {r.status_code} {r.text}")
        data = r.json()
        status = data.get("status")
        if log and status != last_status:
            print(f"[status] {status}", file=sys.stderr)
            last_status = status
        if status in ("Succeeded", "Failed"):
            return data
        if time.time() > deadline:
            raise TimeoutError("Polling timed out")
        await asyncio.sleep(poll_interval)


async def _list_files(
    client: httpx.AsyncClient, endpoint: str, key: str, transcription_id: str
) -> Dict[str, Any]:
    api = f"{endpoint}/speechtotext/transcriptions/{transcription_id}/files?api-version={API_VERSION}"
    r = await client.get(api, headers=_headers(key, False))
    if r.status_code != 200:
        raise RuntimeError(f"List files failed: {r.status_code} {r.text}")
    return r.json()


async def _download_bytes(client: httpx.AsyncClient, url: str, timeout: float = 60.0) -> bytes:
    r = await client.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def _extract_text(result_json: Dict[str, Any]) -> str:
    """
    优先 combinedRecognizedPhrases.display；若没有则拼接
    recognizedPhrases[*].nBest[0].display。
    """
    parts: List[str] = []

    comb = result_json.get("combinedRecognizedPhrases")
    if isinstance(comb, list) and comb:
        for item in comb:
            disp = (item or {}).get("display")
            if disp:
                parts.append(disp)

    if not parts:
        for ph in result_json.get("recognizedPhrases") or []:
            nbest = (ph or {}).get("nBest") or []
            if nbest and (nbest[0].get("display") or "").strip():
                parts.append(nbest[0]["display"])

    return "\n".join(parts).strip()


async def transcribe_url(
    key: str,
    region: str,
    url: str,
    *,
    locale: str = "zh-CN",
    name: str = "single-url-job",
    ttl_hours: int = 48,
    poll_interval: float = 5.0,
    max_minutes: int = 360,
    http2: bool = True,
    log_status: bool = True,
) -> str:
    """
    单 URL 异步转写：返回纯文本字符串。
    """
    endpoint = f"https://{region}.api.cognitive.microsoft.com"
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    timeout = httpx.Timeout(60.0, read=60.0, write=60.0, connect=60.0)

    async with httpx.AsyncClient(http2=http2, timeout=timeout, limits=limits) as client:
        submit_resp = await _submit(client, endpoint, key, url, locale, name, ttl_hours=ttl_hours)
        self_uri = submit_resp.get("self")
        if not self_uri:
            raise RuntimeError(f"Unexpected submit response: {submit_resp}")
        tid = _transcription_id(self_uri)
        if log_status:
            print(f"[submitted] {tid}", file=sys.stderr)

        status = await _poll(
            client, endpoint, key, tid, poll_interval=poll_interval, max_minutes=max_minutes, log=log_status
        )
        if status.get("status") != "Succeeded":
            raise RuntimeError(f"Transcription failed: {json.dumps(status, ensure_ascii=False)}")

        files = (await _list_files(client, endpoint, key, tid)).get("values", [])
        # 只挑 kind == Transcription 的结果（通常就是该 URL 对应的一份 JSON）
        texts: List[str] = []
        for f in files:
            if f.get("kind") != "Transcription":
                continue
            content_url = (f.get("links") or {}).get("contentUrl")
            if not content_url:
                continue
            blob = await _download_bytes(client, content_url)
            result_json = json.loads(blob.decode("utf-8", errors="ignore"))
            txt = _extract_text(result_json)
            if txt:
                texts.append(txt)

        # 合并（通常只有一份；如有多份，顺序拼接）
        return ("\n\n").join(texts).strip()


# ---------------- CLI ----------------

async def _cli_main():
    load_dotenv()

    ap = argparse.ArgumentParser(description="Azure Batch Transcription (single URL, async) -> plain text")
    ap.add_argument("url", help="Public media direct URL (single)")
    ap.add_argument("--key", help="Azure Speech key; fallback to env AZURE_SPEECH_KEY")
    ap.add_argument("--region", help="Azure Speech region (e.g. eastus); fallback to env AZURE_SPEECH_REGION")
    ap.add_argument("--locale", default="zh-CN", help="Locale, e.g. zh-CN, en-US")
    ap.add_argument("--name", default="single-url-job", help="Display name")
    ap.add_argument("--ttl", type=int, default=48, help="Azure result TTL hours (6~744)")
    ap.add_argument("--interval", type=float, default=5.0, help="Polling interval seconds")
    ap.add_argument("--max-minutes", type=int, default=360, help="Polling timeout in minutes")
    ap.add_argument("--no-http2", action="store_true", help="Disable HTTP/2")
    ap.add_argument("--quiet", action="store_true", help="Silence status logs to stderr")
    args = ap.parse_args()

    key = args.key or os.getenv("AZURE_SPEECH_KEY")
    region = args.region or os.getenv("AZURE_SPEECH_REGION")
    if not key or not region:
        print("Missing key/region. Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION, or pass --key/--region.", file=sys.stderr)
        sys.exit(2)

    text = await transcribe_url(
        key=key,
        region=region,
        url=args.url,
        locale=args.locale,
        name=args.name,
        ttl_hours=args.ttl,
        poll_interval=args.interval,
        max_minutes=args.max_minutes,
        http2=not args.no_http2,
        log_status=not args.quiet,
    )
    # 仅输出纯文本
    print(text if text else "", end="")

if __name__ == "__main__":
    asyncio.run(_cli_main())

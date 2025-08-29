#!/usr/bin/env python3
"""
能拿到视频BV号，公网链接
使用方法:
python quick_convert.py "https://www.bilibili.com/video/BV1234567890"
"""

import asyncio
import sys
from . import function

async def quick_convert(url: str):
    """快速转换B站链接"""
    try:
        result = await function.get_video_public_url(url)
        if result and 'public_url' in result:
            return result['public_url']
        return None
    except:
        return None

async def main():
    if len(sys.argv) != 2:
        print("使用方法: python quick_convert.py \"B站链接\"")
        print("示例: python quick_convert.py \"https://www.bilibili.com/video/BV1234567890\"")
        return
    
    url = sys.argv[1]
    print(f"转换中: {url}")
    
    public_url = await quick_convert(url)
    
    if public_url:
        print(f"✅ 转换成功!")
        print(f"🔗 公网链接: {public_url}")
    else:
        print("❌ 转换失败，请检查链接是否正确")

if __name__ == "__main__":
    url = "【传统资金如何在加密市场获利? 详解RWA发行实操和投资策略】 https://www.bilibili.com/video/BV1ssTqzjECD/?share_source=copy_web&vd_source=f6971e45ffdcfa0c22b3659f35a22f0d"
    bilibili_url = asyncio.run(quick_convert(url))
    # bilibili_url = await quick_convert(url)
    print(bilibili_url)
    # asyncio.run(main())
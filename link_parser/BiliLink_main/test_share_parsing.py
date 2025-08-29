#!/usr/bin/env python3
"""
测试B站分享链接解析功能
"""
import asyncio
import function

async def test_share_link_parsing():
    """测试分享链接解析功能"""
    print("=== B站分享链接解析功能测试 ===\n")
    
    # 测试用例
    test_cases = [
        "https://www.bilibili.com/video/BV1234567890",
        "https://www.bilibili.com/video/BV1234567890?p=2",
        "https://www.bilibili.com/video/BV1234567890?p=1&t=30",
        "https://m.bilibili.com/video/BV1234567890",
        # "https://b23.tv/example",  # 短链接需要真实地址测试
    ]
    
    for i, test_url in enumerate(test_cases, 1):
        print(f"测试用例 {i}: {test_url}")
        result = await function.parse_bilibili_share_link(test_url)
        if result:
            print(f"  ✅ 解析成功:")
            print(f"     BVID: {result['bvid']}")
            print(f"     页面: {result['page']}")
            print(f"     时间: {result['time']}秒")
        else:
            print(f"  ❌ 解析失败")
        print()

async def test_public_url_generation():
    """测试公网链接生成功能"""
    print("=== 公网链接生成功能测试 ===\n")
    
    # 注意：这需要真实的BVID才能测试
    test_url = "https://www.bilibili.com/video/BV1ssTqzjECD/?buvid=ZC4E66C0CC191FD94237A16032EB96A1466D&from_spmid=united.player-video-detail.0.0&is_story_h5=false&mid=HwCg5rk5Roou6t75mUWbrQ%3D%3D&plat_id=114&share_from=ugc&share_medium=iphone&share_plat=ios&share_session_id=B936B3F8-2113-4F5B-8D02-0AAD1F72BA38&share_source=WEIXIN&share_tag=s_i&timestamp=1754923763&unique_k=cFCGxr9&up_id=26829472&vd_source=6a2f9b19eadda082b3cddcffb1c9e785"
    print(f"测试链接: {test_url}")
    
    result = await function.get_video_public_url(test_url)
    if result:
        print("✅ 公网链接生成成功:")
        print(f"   BVID: {result['bvid']}")
        print(f"   页面: {result['page']}")
        print(f"   公网链接: {result['public_url'][:100]}...")
        print(f"   时间参数: {result['time']}")
    else:
        print("❌ 公网链接生成失败（可能需要真实的BVID）")

if __name__ == "__main__":
    asyncio.run(test_share_link_parsing())
    print("\n" + "="*50 + "\n")
    asyncio.run(test_public_url_generation())
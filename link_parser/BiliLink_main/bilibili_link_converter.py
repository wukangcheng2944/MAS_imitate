#!/usr/bin/env python3
"""
B站链接转换器
直接输入B站分享链接，自动返回公网可访问的视频链接

使用方法:
1. 命令行参数: python bilibili_link_converter.py "https://www.bilibili.com/video/BV1234567890"
2. 交互模式: python bilibili_link_converter.py
3. 作为模块导入: from bilibili_link_converter import get_public_link
"""

import asyncio
import sys
from . import function
import logging

# 设置日志级别
logging.basicConfig(level=logging.WARNING)  # 只显示警告和错误

async def get_public_link(bilibili_url: str) -> dict:
    """
    获取B站视频的公网链接
    
    Args:
        bilibili_url (str): B站分享链接
        
    Returns:
        dict: 包含视频信息和公网链接的字典
    """
    try:
        print(f"🔍 正在解析链接: {bilibili_url}")
        
        # 解析分享链接
        result = await function.get_video_public_url(bilibili_url)
        
        if result:
            return {
                'success': True,
                'data': result,
                'message': '链接转换成功'
            }
        else:
            return {
                'success': False,
                'error': '无法解析此链接，请检查链接是否正确或网络连接'
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': f'处理过程中出错: {str(e)}'
        }

def print_result(result: dict):
    """格式化打印结果"""
    print("\n" + "="*60)
    
    if result['success']:
        data = result['data']
        print("✅ 转换成功!")
        print(f"📺 视频ID: {data['bvid']}")
        print(f"📄 分P页面: 第{data['page']}页")
        if data['time'] > 0:
            print(f"⏰ 起始时间: {data['time']}秒")
        print(f"🌐 公网链接:")
        print(f"   {data['public_url']}")
        print("\n💡 提示: 可以直接复制上面的链接在浏览器中播放")
    else:
        print("❌ 转换失败!")
        print(f"错误信息: {result['error']}")
    
    print("="*60)

async def interactive_mode():
    """交互模式"""
    print("🎬 B站链接转换器 - 交互模式")
    print("输入 'quit' 或 'exit' 退出程序\n")
    
    while True:
        try:
            url = input("请输入B站分享链接: ").strip()
            
            if url.lower() in ['quit', 'exit', 'q']:
                print("👋 再见!")
                break
                
            if not url:
                print("❗ 请输入有效的链接")
                continue
                
            # 简单验证是否包含bilibili相关域名
            if not any(domain in url.lower() for domain in ['bilibili.com', 'b23.tv', 'bili2233.cn']):
                print("❗ 请输入有效的B站链接")
                continue
            
            result = await get_public_link(url)
            print_result(result)
            print()
            
        except KeyboardInterrupt:
            print("\n👋 程序已退出")
            break
        except Exception as e:
            print(f"❌ 发生错误: {e}")

async def command_line_mode(url: str):
    """命令行模式"""
    print("🎬 B站链接转换器 - 命令行模式")
    result = await get_public_link(url)
    print_result(result)
    
    # 如果成功，返回链接供shell脚本使用
    if result['success']:
        return result['data']['public_url']
    return None

def show_usage():
    """显示使用说明"""
    print("""
🎬 B站链接转换器使用说明

1. 命令行模式:
   python bilibili_link_converter.py "https://www.bilibili.com/video/BV1234567890"
   
2. 交互模式:
   python bilibili_link_converter.py
   
3. 支持的链接格式:
   - https://www.bilibili.com/video/BVxxxxxxxxxx
   - https://m.bilibili.com/video/BVxxxxxxxxxx
   - https://b23.tv/xxxxxxx
   - 带参数: ?p=2&t=30 (分P页面和时间戳)

4. 作为Python模块使用:
   from bilibili_link_converter import get_public_link
   result = await get_public_link("https://www.bilibili.com/video/BV1234567890")
""")

async def main():
    """主函数"""
    if len(sys.argv) == 1:
        # 无参数，进入交互模式
        await interactive_mode()
    elif len(sys.argv) == 2:
        url = sys.argv[1]
        if url in ['-h', '--help', 'help']:
            show_usage()
        else:
            # 命令行模式
            public_url = await command_line_mode(url)
            # 为了方便shell脚本获取结果，在最后输出纯链接
            if public_url:
                print(f"\n🔗 纯链接输出: {public_url}")
    else:
        print("❗ 参数错误")
        show_usage()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 程序已退出")
    except Exception as e:
        print(f"❌ 程序运行出错: {e}")
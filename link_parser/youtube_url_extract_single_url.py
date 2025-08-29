#!/usr/bin/env python3
"""
使用 yt-dlp 和 cookies 绕过 YouTube 机器人检测
"""

import yt_dlp
import os

def extract_video_urls(info):
    """从 yt-dlp 的 info 中提取各种类型的视频链接"""
    
    formats = info.get('formats', [])
    
    # 分类存储不同类型的链接
    direct_video_urls = []  # 包含视频+音频的直接链接
    video_only_urls = []    # 仅视频链接
    audio_only_urls = []    # 仅音频链接
    best_video_url = None   # 最佳质量视频链接
    
    for fmt in formats:
        url = fmt.get('url')
        if not url or url.startswith('https://i.ytimg.com/'):  # 跳过缩略图
            continue
            
        # 获取格式信息
        format_note = fmt.get('format_note', 'unknown')
        quality = fmt.get('quality', fmt.get('height', 'unknown'))
        ext = fmt.get('ext', 'unknown')
        filesize = fmt.get('filesize')
        
        # 格式化文件大小
        if filesize:
            size_mb = filesize / (1024 * 1024)
            size_str = f"{size_mb:.2f} MB"
        else:
            size_str = "未知大小"
        
        # 构建链接信息
        url_info = {
            'url': url,
            'quality': f"{format_note}_{quality}" if quality != 'unknown' else format_note,
            'ext': ext,
            'size': size_str,
            'filesize': filesize or 0,
            'itag': fmt.get('itag'),
            'format_id': fmt.get('format_id'),
            'vcodec': fmt.get('vcodec', 'unknown'),
            'acodec': fmt.get('acodec', 'unknown')
        }
        
        # 分类链接
        vcodec = fmt.get('vcodec', 'none')
        acodec = fmt.get('acodec', 'none')
        
        if vcodec != 'none' and acodec != 'none':
            # 包含视频和音频
            direct_video_urls.append(url_info)
        elif vcodec != 'none' and acodec == 'none':
            # 仅视频
            video_only_urls.append(url_info)
        elif vcodec == 'none' and acodec != 'none':
            # 仅音频
            audio_only_urls.append(url_info)
    
    # 选择最佳视频链接 (优先选择包含音频的)
    if direct_video_urls:
        # 按文件大小排序，选择最大的
        best_video_url = max(direct_video_urls, key=lambda x: x['filesize'])
    elif video_only_urls:
        best_video_url = max(video_only_urls, key=lambda x: x['filesize'])
    
    # 按文件大小排序
    direct_video_urls.sort(key=lambda x: x['filesize'], reverse=True)
    video_only_urls.sort(key=lambda x: x['filesize'], reverse=True)
    audio_only_urls.sort(key=lambda x: x['filesize'], reverse=True)
    
    return {
        'direct_video_urls': direct_video_urls,
        'video_only_urls': video_only_urls,
        'audio_only_urls': audio_only_urls,
        'best_video_url': best_video_url,
        'total_formats': len(formats)
    }

def get_specific_quality_url(info, target_quality='720p'):
    """获取特定质量的视频链接"""
    formats = info.get('formats', [])
    
    for fmt in formats:
        format_note = fmt.get('format_note', '')
        if target_quality in format_note:
            return {
                'url': fmt.get('url'),
                'quality': format_note,
                'ext': fmt.get('ext'),
                'filesize': fmt.get('filesize')
            }
    return None

def get_youtube_urls_with_fallbacks(url):
    """使用多种方法尝试获取 YouTube 视频信息"""
    v2t_url = None
    # 方法1: 使用浏览器 cookies
    methods = [
        {
            'name': '使用 Chrome cookies',
            'opts': {
                'quiet': False,
                'cookiesfrombrowser': ('chrome',),
                'extract_flat': False,
            }
        },
        {
            'name': '使用 Firefox cookies', 
            'opts': {
                'quiet': False,
                'cookiesfrombrowser': ('firefox',),
                'extract_flat': False,
            }
        },
        {
            'name': '使用 Edge cookies',
            'opts': {
                'quiet': False, 
                'cookiesfrombrowser': ('edge',),
                'extract_flat': False,
            }
        },
        {
            'name': '不使用 cookies (基本方法)',
            'opts': {
                'quiet': False,
                'extract_flat': False,
                # 添加更多用户代理伪装
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
                }
            }
        }
    ]
    
    for i, method in enumerate(methods, 1):
        print(f"\n方法 {i}: {method['name']}")
        print("-" * 50)
        
        try:
            with yt_dlp.YoutubeDL(method['opts']) as ydl:
                info = ydl.extract_info(url, download=False)
                
                print("✅ 成功获取视频信息!")
                print(f"标题: {info.get('title', 'Unknown')}")
                print(f"作者: {info.get('uploader', 'Unknown')}")
                print(f"时长: {info.get('duration', 'Unknown')} 秒")
                
                # 提取并显示视频链接
                formats = info.get('formats', [])
                video_urls = extract_video_urls(info)
                
                print(f"\n📹 视频链接提取结果:")
                print("=" * 40)
                
                if video_urls['direct_video_urls']:
                    print("🎬 直接视频链接 (包含音频):")
                    for i, url_info in enumerate(video_urls['direct_video_urls'], 1):
                        print(f"  {i}. {url_info['quality']} ({url_info['ext']}) - {url_info['size']}")
                        print(f"     完整URL: {url_info['url']}")
                        print()
                
                if video_urls['video_only_urls']:
                    print("🎥 纯视频链接 (无音频):")
                    for i, url_info in enumerate(video_urls['video_only_urls'][:3], 1):
                        print(f"  {i}. {url_info['quality']} ({url_info['ext']}) - {url_info['size']}")
                        print(f"     完整URL: {url_info['url']}")
                        print()

                if video_urls['audio_only_urls']:
                    print("🎵 纯音频链接:")
                    for i, url_info in enumerate(video_urls['audio_only_urls'][:], 1):
                        if i==1:
                            v2t_url = url_info['url']
                            print(f"v2t_url: {v2t_url}")
                        print(f"  {i}. {url_info['quality']} ({url_info['ext']}) - {url_info['size']}")
                        print(f"     完整URL: {url_info['url']}")
                        print()
                        
                    
                # 推荐最佳链接
                if video_urls['best_video_url']:
                    print("⭐ 推荐最佳视频链接:")
                    best = video_urls['best_video_url']
                    print(f"   {best['quality']} ({best['ext']}) - {best['size']}")
                    print(f"   完整URL: {best['url']}")
                    if not v2t_url:
                        v2t_url = best['url']
                        print(f"v2t_url: {v2t_url}")
                return info,v2t_url
                
        except Exception as e:
            print(f"❌ 失败: {str(e)}")
            continue
    
    print("\n所有方法都失败了。")
    return None

def manual_cookie_method(url, cookie_file_path):
    """使用手动导出的 cookie 文件"""
    if not os.path.exists(cookie_file_path):
        print(f"Cookie 文件不存在: {cookie_file_path}")
        return None
    
    ydl_opts = {
        'quiet': False,
        'cookies': cookie_file_path,
        'extract_flat': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            print("✅ 使用手动 cookie 成功!")
            return info
    except Exception as e:
        print(f"❌ 手动 cookie 方法失败: {e}")
        return None

def print_instructions():
    """打印使用说明"""
    print("""
🔧 如果所有自动方法都失败，你可以尝试以下手动方法:

1. 导出浏览器 Cookies:
   - 安装浏览器扩展 "Get cookies.txt LOCALLY"
   - 访问 YouTube 并登录
   - 点击扩展图标，导出 cookies.txt
   - 保存到本地文件

2. 使用命令行:
   yt-dlp --cookies cookies.txt "你的YouTube链接"

3. 从浏览器导出 cookies:
   yt-dlp --cookies-from-browser chrome "你的YouTube链接"

4. 使用代理 (如果是地区限制):
   yt-dlp --proxy socks5://127.0.0.1:1080 "你的YouTube链接"

更多信息请查看:
- https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp
- https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies
""")



def youtube_extract_main(url):
    # 测试 URL
    test_url = url
    
    print("YouTube 视频信息提取 (多种方法)")
    print("=" * 60)
    print(f"目标视频: {test_url}")
    
    # 尝试多种方法
    result,v2t_url = get_youtube_urls_with_fallbacks(test_url)
    print(f"v2t_url: {v2t_url}")
    if not result:
        print_instructions()
        
        # 尝试手动 cookie 方法 (如果有 cookie 文件)
        cookie_file = "cookies.txt"
        if os.path.exists(cookie_file):
            print(f"\n发现 cookie 文件 {cookie_file}，尝试使用...")
            manual_cookie_method(test_url, cookie_file)
    return v2t_url

def main():
    url = "https://youtu.be/YdQ0pLim0jA?si=LsxDGnrCViW54g8K"
    v2t_url = youtube_extract_main(url)
    print(f"v2t_url: {v2t_url}")

if __name__ == "__main__":
    # 检查依赖
    try:
        import yt_dlp
        main()
    except ImportError:
        print("请先安装 yt-dlp: pip install yt-dlp")
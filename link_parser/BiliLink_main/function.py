import random
import re
from urllib.parse import urlparse, urlunparse, parse_qs
import asyncio
import aiohttp
from . import wbi
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_bilibili_cookies(SESSDATA=None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get('https://www.bilibili.com', headers=headers) as response:
                response.raise_for_status()
                cookies = response.cookies
                if SESSDATA is not None:
                    cookies['SESSDATA'] = SESSDATA
                return cookies
        except aiohttp.ClientError as err:
            logger.error(f"HTTP error occurred: {err}")
        except Exception as err:
            logger.error(f"An error occurred: {err}")

async def MyRequest(APIurl, params, cookies):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36',
        'Accept': 'application/json',
    }
    async with aiohttp.ClientSession(cookies=cookies) as session:
        try:
            async with session.get(APIurl, headers=headers, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                return data
        except aiohttp.ClientError as err:
            logger.error(f"HTTP error occurred: {err}")
            return None
        except Exception as err:
            logger.error(f"An error occurred: {err}")
            return None

async def checkLoginStatus(cookies):
    APIurl = 'https://api.bilibili.com/x/web-interface/nav'
    params = {}
    return await MyRequest(APIurl, params, cookies)

def getSessionData():
    try:
        with open('data.json', 'r') as f:
            data = json.load(f)
            return data.get('SESSDATA')
    except:
        return None

async def Search(keyword, page=1):
    cookies = await get_bilibili_cookies(getSessionData())
    APIurl = 'https://api.bilibili.com/x/web-interface/wbi/search/all/v2'
    params = {
        'keyword': keyword,
        'page': page,
    }
    return await MyRequest(APIurl, params, cookies)

async def getCid(BV, cookies):
    APIurl = 'https://api.bilibili.com/x/player/pagelist'
    params = {
        'bvid': BV,
    }
    return await MyRequest(APIurl, params, cookies)

def CalOR(a, b):  # OR运算 二进制属性位
    return a | b

async def getVideoInfo(BV, CID, cookies):
    APIurl = 'https://api.bilibili.com/x/player/playurl'
    params = {
        'bvid': BV,
        'cid': CID,
        'qn': 120,
        'otype': 'json',
        'platform': 'html5',
        'high_quality': 1,
        'fnval': CalOR(1, 128),
        'fourk': 1
    }
    return await MyRequest(APIurl, params, cookies)

async def BiliAnalysis(BV, p=1):
    cookies = await get_bilibili_cookies(getSessionData())
    CID = await getCid(BV, cookies)
    p -= 1
    if p < 0 or p >= len(CID['data']):
        p = 0
    VideoInfo = await getVideoInfo(BV, CID['data'][p]['cid'], cookies)
    Video = {
        'BV': BV,
        'page': p + 1,
        'url': VideoInfo['data']['durl'][0]['url'],
    }
    return Video

def ChangeBiliCDN(url):
    BiliCDN = [
        "upos-sz-mirrorcos.bilivideo.com",
        "upos-sz-mirrorali.bilivideo.com",
        "upos-sz-mirror08c.bilivideo.com",
    ]
    parsed_url = urlparse(url)
    new_netloc = random.choice(BiliCDN)
    new_url = urlunparse(parsed_url._replace(netloc=new_netloc))
    return new_url

async def room_play_info(room_id: int, sessdata: str = None):
    APIurl = 'https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo'
    params = {
        'room_id': str(room_id),
        'protocol': '0,1',
        'format': '1',
        'codec': '0,1',
        'platform': 'h5'
    }
    cookies = await get_bilibili_cookies(sessdata)
    return await MyRequest(APIurl, params, cookies)

async def room_play_url(room_id: int, sessdata: str = None):
    body = await room_play_info(room_id, sessdata)
    c = body.get('data', {}).get('playurl_info', {}).get('playurl', {}).get('stream', [{}])[0].get('format', [{}])[0].get('codec', [{}])[0]
    if not c:
        return ''
    return f"{c['url_info'][0]['host']}{c['base_url']}{c['url_info'][0]['extra']}"

async def parse_bilibili_share_link(share_url: str):
    """
    解析B站分享链接，提取BVID和其他参数
    支持多种B站分享链接格式:
    - https://www.bilibili.com/video/BVxxxxxxxxxx
    - https://b23.tv/xxxxxxx
    - https://m.bilibili.com/video/BVxxxxxxxxxx
    """
    try:
        # 预处理：从输入文本中提取真实 URL，避免将“标题+空格+URL”整体当作请求地址
        url_match = re.search(r'(https?://[^\s]+)', share_url)
        if url_match:
            share_url = url_match.group(1).strip()
        else:
            # 兼容无协议短链，如 b23.tv/xxxx 或 bili2233.cn/xxxx
            bare_match = re.search(r'(?:https?://)?(b23\.tv|bili2233\.cn)/[^\s]+', share_url)
            if bare_match:
                candidate = bare_match.group(0)
                if not candidate.startswith('http'):
                    share_url = 'https://' + candidate
                else:
                    share_url = candidate
            else:
                return None

        # 处理短链接 b23.tv
        if 'b23.tv' in share_url or 'bili2233.cn' in share_url:
            # 需要请求短链接获取真实URL
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36',
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(share_url, headers=headers, allow_redirects=True) as response:
                    share_url = str(response.url)
                    print(share_url)
        
        # 从URL中提取BVID
        bv_match = re.search(r'BV[a-zA-Z0-9]{10}', share_url)
        if not bv_match:
            return None
        
        bvid = bv_match.group(0)
        
        # 解析URL参数
        parsed_url = urlparse(share_url)
        query_params = parse_qs(parsed_url.query)
        
        # 提取页面参数
        p = 1
        if 'p' in query_params:
            try:
                p = int(query_params['p'][0])
            except (ValueError, IndexError):
                p = 1
        
        # 提取时间参数
        t = 0
        if 't' in query_params:
            try:
                t = int(query_params['t'][0])
            except (ValueError, IndexError):
                t = 0
        
        return {
            'bvid': bvid,
            'page': p,
            'time': t
        }
        
    except Exception as e:
        logger.error(f"Error parsing share link {share_url}: {e}")
        return None

async def get_video_public_url(share_url: str):
    """
    从B站分享链接获取可访问的公网视频链接
    """
    # 解析分享链接
    parsed_info = await parse_bilibili_share_link(share_url)
    if not parsed_info:
        return None
    
    try:
        # 获取视频信息
        video_info = await BiliAnalysis(parsed_info['bvid'], parsed_info['page'])
        if not video_info or 'url' not in video_info:
            return None
        
        # 优化CDN链接
        public_url = ChangeBiliCDN(video_info['url'])
        
        # 如果有时间参数，添加到结果中
        result = {
            'bvid': parsed_info['bvid'],
            'page': parsed_info['page'],
            'public_url': public_url,
            'time': parsed_info['time']
        }
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting public URL for {share_url}: {e}")
        return None
"""
parse_share_url 返回抖音视频解析结果：{"direct_url": video_url}
parse_share_url_with_meta 返回携带元数据的抖音视频解析结果：{"direct_url": video_url, "title": desc, "author": author}
"""
import re
import requests
import json


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1'
}
def parse_share_url(share_text: str) -> dict:
        """从分享文本中提取无水印视频链接或图文图片链接列表
        返回：
        - 图文：图片直链列表 List[str]
        - 视频：视频直链 str
        """
        # 提取分享链接
        urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', share_text)
        if not urls:
            raise ValueError("未找到有效的分享链接")
        
        share_url = urls[0]
        share_response = requests.get(share_url, headers=HEADERS)
        video_id = share_response.url.split("?")[0].strip("/").split("/")[-1]
        share_url = f'https://www.iesdouyin.com/share/video/{video_id}'
        
        # 获取视频页面内容
        response = requests.get(share_url, headers=HEADERS)
        response.raise_for_status()
        
        pattern = re.compile(
            pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
            flags=re.DOTALL,
        )
        find_res = pattern.search(response.text)

        if not find_res or not find_res.group(1):
            raise ValueError("从HTML中解析视频信息失败")

        # 解析JSON数据
        json_data = json.loads(find_res.group(1).strip())
        # print(json_data)
        VIDEO_ID_PAGE_KEY = "video_(id)/page"
        NOTE_ID_PAGE_KEY = "note_(id)/page"
        
        if VIDEO_ID_PAGE_KEY in json_data["loaderData"]:
            original_video_info = json_data["loaderData"][VIDEO_ID_PAGE_KEY]["videoInfoRes"]
        elif NOTE_ID_PAGE_KEY in json_data["loaderData"]:
            original_video_info = json_data["loaderData"][NOTE_ID_PAGE_KEY]["videoInfoRes"]
        else:
            raise Exception("无法从JSON中解析视频或图集信息")

        data = original_video_info["item_list"][0]

        # 如果是图文（包含图片数组），返回图片链接列表
        images = []
        if isinstance(data.get("images"), list) and data["images"]:
            for img in data["images"]:
                # 常见字段：url_list 为列表，取首个或最后一个皆可
                if isinstance(img, dict):
                    url_list = img.get("url_list") or []
                    if isinstance(url_list, list) and url_list:
                        images.append(url_list[-1])
                    elif isinstance(img.get("url"), str):
                        images.append(img["url"])
            if images:
                return images
        # 有些老结构使用 image_list
        if not images and isinstance(data.get("image_list"), list) and data["image_list"]:
            for img in data["image_list"]:
                if isinstance(img, dict):
                    url_list = img.get("url_list") or []
                    if isinstance(url_list, list) and url_list:
                        images.append(url_list[-1])
                    elif isinstance(img.get("url"), str):
                        images.append(img["url"])
            if images:
                return images

        # 否则按视频处理
        video_url = data["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
        desc = data.get("desc", "").strip() or f"douyin_{video_id}"
        # 作者昵称（尽力获取）
        try:
            author = (data.get("author") or {}).get("nickname") or ""
        except Exception:
            author = ""
        
        # 替换文件名中的非法字符
        desc = re.sub(r'[\\/:*?"<>|]', '_', desc)
        
        return video_url
        
def parse_share_url_with_meta(share_text: str) -> dict:
        """返回携带元数据的抖音视频解析结果：direct_url/title/author
        若为图文，返回 {"images": List[str], "title": str, "author": str}
        若为视频，返回 {"direct_url": str, "title": str, "author": str}
        """
        urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', share_text)
        if not urls:
            raise ValueError("未找到有效的分享链接")
        share_url = urls[0]
        share_response = requests.get(share_url, headers=HEADERS)
        video_id = share_response.url.split("?")[0].strip("/").split("/")[-1]
        share_url = f'https://www.iesdouyin.com/share/video/{video_id}'

        response = requests.get(share_url, headers=HEADERS)
        response.raise_for_status()
        pattern = re.compile(
            pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
            flags=re.DOTALL,
        )
        find_res = pattern.search(response.text)
        if not find_res or not find_res.group(1):
            raise ValueError("从HTML中解析视频信息失败")
        json_data = json.loads(find_res.group(1).strip())
        VIDEO_ID_PAGE_KEY = "video_(id)/page"
        NOTE_ID_PAGE_KEY = "note_(id)/page"
        if VIDEO_ID_PAGE_KEY in json_data["loaderData"]:
            original_video_info = json_data["loaderData"][VIDEO_ID_PAGE_KEY]["videoInfoRes"]
        elif NOTE_ID_PAGE_KEY in json_data["loaderData"]:
            original_video_info = json_data["loaderData"][NOTE_ID_PAGE_KEY]["videoInfoRes"]
        else:
            raise Exception("无法从JSON中解析视频或图集信息")
        data = original_video_info["item_list"][0]
        # 图文
        images = []
        if isinstance(data.get("images"), list) and data["images"]:
            for img in data["images"]:
                if isinstance(img, dict):
                    url_list = img.get("url_list") or []
                    if isinstance(url_list, list) and url_list:
                        images.append(url_list[-1])
                    elif isinstance(img.get("url"), str):
                        images.append(img["url"])
        if not images and isinstance(data.get("image_list"), list) and data["image_list"]:
            for img in data["image_list"]:
                if isinstance(img, dict):
                    url_list = img.get("url_list") or []
                    if isinstance(url_list, list) and url_list:
                        images.append(url_list[-1])
                    elif isinstance(img.get("url"), str):
                        images.append(img["url"])
        desc = data.get("desc", "").strip() or f"douyin_{video_id}"
        desc = re.sub(r'[\\/:*?"<>|]', '_', desc)
        try:
            author = (data.get("author") or {}).get("nickname") or ""
        except Exception:
            author = ""
        if images:
            return {"images": images, "title": desc, "author": author}
        # 视频
        video_url = data["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
        #抖音解析结果
        return {"direct_url": video_url, "title": desc, "author": author}
        
def main():
    share_text = input("请输入分享链接:")
    result = parse_share_url(share_text)
    if isinstance(result, list):
        for index,img_url in enumerate(result):
            print(f"img_url_{index}:",img_url)
    else:
        print("video_url:",result)

if __name__ == "__main__":
    main()
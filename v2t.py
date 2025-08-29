"""
不带总结的转文字版本
"""
#必须使用公网链接，否则无法转录
import json
from http import HTTPStatus
import requests
from typing import List
import dashscope
import asyncio
from dashscope.audio.asr import Transcription
import os
from os import getenv
from dotenv import load_dotenv
load_dotenv()
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGSMITH_PROJECT"] = "imitate_v2t"
from  typing import Dict
from langsmith import traceable
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from link_parser.douyin_parse import parse_share_url
from link_parser.xhs_extract_links import extract_xhs_links
from link_parser.youtube_url_extract_single_url import youtube_extract_main
import pandas as pd
from datetime import datetime
from link_parser.BiliLink_main.quick_convert import quick_convert
load_dotenv()
dashscope.api_key = getenv("DASH_SCOPE_API_KEY")
sem = asyncio.Semaphore(5)

@traceable(name="v2t(1)bilibili解析链接")
async def transform_bilibili_url(url:str)->str:
    bilibili_url = await quick_convert(url)
    return bilibili_url
#使用dashscope的paraformer-v2模型进行转录，返回包含所有子任务的结果列表，包含源文件url和转录文字结果url
@traceable(name="v2t(2)转录文字")
async def get_one_text_url(url:str)->list:
    task_id = f"task_{id(url)}"  # 为每个任务生成唯一ID
    print(f"[{task_id}] 开始处理视频: {url[:50]}...", flush=True)
    
    # ✅ 修复：每个任务独立使用信号量，实现真正的并发控制
    async with sem:  # 控制单个任务的并发数
        print(f"[{task_id}] 获得信号量，开始API调用", flush=True)
        transcribe_response = Transcription.async_call(
            model='paraformer-v2',
            file_urls=[url],
            language_hints=['zh', 'en']  # "language_hints"只支持paraformer-v2模型
        )

        while True:
            if transcribe_response.output.task_status == 'SUCCEEDED' or transcribe_response.output.task_status == 'FAILED':
                break
            transcribe_response = Transcription.fetch(task=transcribe_response.output.task_id)
            print(f"[{task_id}] 转录任务状态: {transcribe_response.output.task_status}", flush=True)
            await asyncio.sleep(0.5)  # 添加短暂等待，避免过度轮询

        if transcribe_response.status_code == HTTPStatus.OK:
            results = transcribe_response.output["results"]
            print(f'[{task_id}] transcription done!')
            return results        #返回包含所有子任务的结果列表，包含源文件url和转录文字结果url
        else:
            print(f"[{task_id}] 转录任务失败: {transcribe_response.output}", flush=True)
            return None

#提取转录文字结果JSON url中的文字 - 修复为真正的异步并行

async def get_text_url(url_list:list)->list:
    print(f"🚀 开始异步并行处理{len(url_list)}个视频")
    
    # ✅ 修复：移除外层信号量，让每个任务自己管理并发
    tasks = [get_one_text_url(url) for url in url_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_text_url = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"❌ 第{i+1}个视频处理失败: {result}")
        elif result is not None:
            all_text_url += result
            print(f"✅ 第{i+1}个视频处理成功")
        else:
            print(f"⚠️ 第{i+1}个视频返回空结果")
    
    print(f"🎉 批量处理完成，共获得{len(all_text_url)}个转录结果")
    return all_text_url

#提取转录文字结果url中的文字
@traceable(name="v2t(3)提取转录JSON格式结果url中的文字")
async def extract_text(transcrip_url)->Dict:
    timeout = 60
    try:
        response = requests.get(transcrip_url, timeout=timeout)
        response.raise_for_status()  # 如果不是 200，会抛异常
        data =response.json()
        file_url=data["file_url"]
        text = data["transcripts"][0]["text"]
        result={"file_url":file_url,"text":text}
        print(f"提取转录文字结果url中的文字：\n{text}")
        return result         #返回包含源文件url和转录文字结果的字典
    except requests.exceptions.RequestException as e:
        print(f"请求出错: {e}")
        return None 

@traceable(name="v2t(4)文本纠错")
async def correct_text(llm, text_dict:Dict):
    text = text_dict["text"]
    task_id = f"llm_{id(text)}"  # 为每个LLM任务生成唯一ID
    print(f"[{task_id}] 开始文本纠错，文本长度: {len(text)}", flush=True)
    try:
        async with sem:  # 控制LLM调用的并发数
            print(f"[{task_id}] 获得LLM信号量，开始纠错", flush=True)
            correct_prompt = ChatPromptTemplate.from_messages([
                ("system", """The following is a speech to text transcription of a video. 
                The text is primarily in Chinese, although it may also contain English. 
                Correct the transcription of any errors. Make sure to output the FULL transcript. 
                Output just the corrected transcript in your response and nothing else."""),
                ("user", """the following is the transcription of a video:\n
                -------------------------------------------------------------------
                {input}
                -------------------------------------------------------------------"""),
            ])
            correct_chain = correct_prompt | llm | StrOutputParser()
            corrected_text = await correct_chain.ainvoke({"input": text})
            print(f"[{task_id}] 文本纠错完成\n原文本长度：{len(text)}\n纠错后文本长度：{len(corrected_text)}", flush=True)
            print(corrected_text)
            text_dict.update({"text":corrected_text})
            return text_dict
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[{task_id}] 文本纠错失败返回原文本: {e}", flush=True)
        return text_dict      



async def v2t(llm,url_list:list)->List:
    print("开始转录")
    results_list = await get_text_url(url_list)
    print(f"results_list：{results_list}")
    print("提取转录文字结果url中的文字")
    
    # 过滤出成功的结果，并确保有transcription_url字段
    valid_results = []
    fail_list = []
    for result in results_list:
        if result["subtask_status"] == "SUCCEEDED" and result["transcription_url"] !="":
            valid_results.append(result)
        elif result["subtask_status"] == "FAILED":
            fail_list.append(result)
            print(f"跳过失败或无效的结果: {result}")
    
    if not valid_results:
        print("没有有效的转录结果")
        return []
    
    # 提取文本
    tasks = [extract_text(result["transcription_url"]) for result in valid_results]
    second_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 过滤出成功的文本提取结果
    second_result_list = []
    for _, result in enumerate(second_results):
        if isinstance(result, Exception):
            print(f"文本提取失败: {result}")
        elif result is not None:
            second_result_list.append(result)
    
    if not second_result_list:
        print("没有成功提取的文本")
        return []
    
    # 文本纠错
    tasks = [correct_text(llm, result) for result in second_result_list]
    final_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    final_result_list = []
    for result in final_results:
        if isinstance(result, Exception):
            print(f"文本纠错失败: {result}")
        elif result is not None:
            final_result_list.append(result)
    if len(fail_list) > 0:
        print(f"失败链接：{fail_list}")
    return final_result_list

async def _resolve_one_url(url: str) -> List[str]:
    """将原始链接解析成可直接转录的公网直链（并发友好，不阻塞事件循环）。"""
    try:
        # 已经是公网直链，直接返回
        if url.startswith("https://finder.video.qq.com/") or url.startswith("http://wxapp.tc.qq.com/") or url.startswith("https://ppwtoss01.oss") or url.startswith("https://v5-small.douyinvod.com/"):
            return [url]

        # B站：异步转换
        if ("https://www.bilibili.com/video/" in url) or ("https://b23.tv/" in url) or ("https://bili2233.cn/" in url):
            bilibili_url = await transform_bilibili_url(url)
            return [bilibili_url] if bilibili_url else []

        # 抖音：同步解析，放入线程池避免阻塞
        if "douyin.com" in url:
            douyin_url = await asyncio.to_thread(parse_share_url, url)
            return [douyin_url] if douyin_url else []

        # 小红书：同步解析，放入线程池避免阻塞
        if "xiaohongshu.com" in url or "xhslink.com" in url:
            xhs = await asyncio.to_thread(extract_xhs_links, url)
            if xhs and xhs.get("ok"):
                return list(xhs.get("download_urls") or [])
            print(f"小红书链接解析失败: {xhs}")
            return []

        # YouTube：同步解析，放入线程池避免阻塞
        if "youtube.com" in url or "youtu.be" in url:
            yt = await asyncio.to_thread(youtube_extract_main, url)
            if yt :
                return [yt]
            print(f"Youtube链接解析失败: {yt}")
            return []

        # 其他：直接返回原URL
        return [url]
    except Exception as e:
        print(f"解析链接出错: {url} -> {e}")
        return []


async def _resolve_all_urls(url_list: List[str]) -> List[str]:
    print(f"🧭 并行解析 {len(url_list)} 个链接为可转录直链...")
    tasks = [_resolve_one_url(u) for u in url_list]
    groups = await asyncio.gather(*tasks, return_exceptions=True)
    direct_urls: List[str] = []
    for i, g in enumerate(groups):
        if isinstance(g, Exception):
            print(f"❌ 第{i+1}个链接解析异常: {g}")
            continue
        direct_urls.extend([x for x in g if isinstance(x, str) and x])
    print(f"✅ 解析完成，获得 {len(direct_urls)} 条直链")
    return direct_urls


async def main_v2t_no_summary(llm,url_list:list):
    # 1) 并发解析每个链接（判断是否公网/需要解析），确保不阻塞
    direct_url_list = await _resolve_all_urls(url_list)

    # 2) 并发进行转录、提取文本与纠错（各子任务内部已使用并发控制）
    if direct_url_list:
        direct_final_result_list = await v2t(llm, direct_url_list)
        print(f"公网链接转录结果：{len(direct_final_result_list)}个成功")
    else:
        direct_final_result_list = []

    # 3) 返回最终结果
    final_result_list = direct_final_result_list
    return final_result_list

def save_to_local(final_result_list:list):
    current_path = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(current_path,"result","v2t_result")   # 视频链接转文字结果保存文件夹路径
    if not os.path.exists(output_path):
        os.makedirs(output_path)
    file_list = []
    text_list = []
    for result in final_result_list:
        file_list.append(result["file_url"])
        text_list.append(result["text"])
    df = pd.DataFrame({"file_url":file_list,"text":text_list})
    time_now = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    df.to_excel(os.path.join(output_path,f"v2t_result_{time_now}.xlsx"), index=False)

if __name__ == "__main__":
    correct_llm = ChatOpenAI(
    model="google/gemini-2.5-flash",
    max_tokens=64000,
    timeout=600,
    max_retries=2,
    api_key=getenv("OPENROUTER_API_KEY"),
    base_url=getenv("OPENROUTER_BASE_URL")
    )
    url_list = []
    while True:
        url = input("请输入视频链接(输入完毕后再次回车开始执行转文字):")
        if url == "":
            break
        url_list.append(url)
    # url_list = ["https://www.xiaohongshu.com/discovery/item/6895a4e3000000002501a26e?source=webshare&xhsshare=pc_web&xsec_token=ABgYkBkMvPzSYLMTYRRV2fwV5g3icoj6RmC3txDOTi70s=&xsec_source=pc_share",
    # "https://www.xiaohongshu.com/explore/684980030000000021007bb5?app_platform=ios&app_version=8.94.2&share_from_user_hidden=true&xsec_source=app_share&type=video&xsec_token=CBEjRSsYktwgn-4FmYmAXWlQcs_XHeDkZO0anJl1vGyEI=&author_share=1&xhsshare=WeixinSession&shareRedId=NztHODZISk08PkdFPz0zN0w5OTlKPjhK&apptime=1754356150&share_id=1dba6c6c1ec44a82a0b0217e5c8ff21c"]
    final_result_list = asyncio.run(main_v2t_no_summary(correct_llm,url_list))
    save_to_local(final_result_list)





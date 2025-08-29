import os
import json
import sys
from os import getenv
from dotenv import load_dotenv
load_dotenv()
import asyncio
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from datetime import datetime
from typing import Optional
llm_sem = asyncio.Semaphore(8)

# Configure stdout/stderr to safely handle any non-UTF-8 encodable characters during printing
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

def _remove_surrogates_from_str(text: str) -> str:
    """Remove lone surrogate code points to avoid UTF-8 encode errors."""
    if not isinstance(text, str):
        return text
    return "".join(ch for ch in text if not (0xD800 <= ord(ch) <= 0xDFFF))

def _sanitize_surrogates(obj):
    """Recursively remove surrogate code points from strings in nested structures."""
    if isinstance(obj, str):
        return _remove_surrogates_from_str(obj)
    if isinstance(obj, list):
        return [_sanitize_surrogates(x) for x in obj]
    if isinstance(obj, dict):
        return { _sanitize_surrogates(k): _sanitize_surrogates(v) for k, v in obj.items() }
    return obj

def read_multiline(prompt="可输入多篇文章进行总结\n每一篇均需完成以下步骤\n1.输入文章2.输入完成后回车输入/end\n全部文章输入完成后再次回车输入/end："):
    print(prompt)
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break  # 用户直接 Ctrl-D/Ctrl-Z 也能结束
        if line.strip() in ["/end"]:
            break
        elif line.strip().lower() in ["/exit","/quit","exit","quit","q"]:
            sys.exit(0)
        # 逐行移除孤立代理并去掉行首空白（不影响链接本体，仅去前导空白）
        cleaned_line = _remove_surrogates_from_str(line)
        lines.append(cleaned_line.lstrip())
    combined = "\n".join(lines)
    return _remove_surrogates_from_str(combined)

async def summarize_one_text(llm,dict_item:dict)->dict:
    try:
        async with llm_sem:
            text = dict_item["text"]
            print(f"开始总结文本")
            summarize_prompt = ChatPromptTemplate.from_messages([
                ("system", """你是一名资深信息架构师与领域分析员。请从输入文本中，产出一份结构化大纲，要求深度理解、客观克制、证据配对、可追踪。
                                只输出主题、摘要、大纲，不展示推理过程。
                                输出格式（严格遵循）
                                一句话摘要：（≤30字，呈现出本文的属性、核心观点及结论）
                                大纲核心结论（3–6条）：（面向决策/复用，避免空话）
                                大纲核心结论需要在文中有充足的证据支撑,不允许编造数据，须与原文一致
                                大纲中只允许包含大纲标题与内容本身,禁止直接输出“标题”“内容”等指明结构的部分，大纲标题和大纲标题对应的内容呈现格式以在json中示例为标准
                                只输出大纲，不输出提示词、过程或与大纲无关内容。
                                最终输出格式为JSON格式：
                                {{
                                    "theme": "",
                                    "summary": "",
                                    "outline": "[{{大纲标题1:大纲内容1}},{{大纲标题2:大纲内容2}},{{大纲标题3:大纲内容3}}]",
                                }}
                                """),
                ("user", "需要总结的文本如下:\n{input}"),
            ])
            summarize_chain = summarize_prompt | llm | JsonOutputParser()
            input_text = _remove_surrogates_from_str(str(text))
            summarize_result = await summarize_chain.ainvoke({"input": input_text})
            summarize_result = _sanitize_surrogates(summarize_result)
            
            """
            summarize_result结构如下：
            {
                "theme": "",
                "summary": "",
                "outline": "[{大纲标题1:大纲内容1},{大纲标题2:大纲内容2},{大纲标题3:大纲内容3}]",
            }
            或
            {
                "theme": "",
                "summary": "",
                "outline": "[{一级大纲标题1:{大纲内容1}},{大纲标题2:{大纲内容2}},{大纲标题3:{大纲内容3}}]",
            }
            """
            #设置json本地化保存的路径和文件名
            #以下为打印和保存结果的代码
            print(f"主题:{summarize_result['theme']}\n\n摘要:{summarize_result['summary']}\n\n")
            print("大纲:")
            for outlinepart in summarize_result['outline']:
                for key,value in outlinepart.items():
                    if type(value) == str:
                        print(f"{key}\n{value}\n")
                        continue
                    elif type(value) == dict:
                        for k,v in value.items():
                            print(f"\t{k}\n\t{v}\n")
                        continue
                    else:
                        print(f"{key}\n{value}\n")
            dict_item.update({"summary":summarize_result})
            return dict_item
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"文本总结失败: {e}")
        dict_item.update({"summary":None})
        return dict_item

async def summarize_all_text(llm,final_result_list:list)->list:
    """
    输入：
    {other_info:"",text:"the text need to be summarized"}
    输出：
    {other_info:"",text:"the text need to be summarized",summary:"the summary of the text"}
    """
    #result是一个字典
    tasks = [summarize_one_text(llm,result) for result in final_result_list]
    results = await asyncio.gather(*tasks)
    #返回一个结果列表，列表中每个元素是一个字典，字典中包含原始文本和总结结果
    return results

def save_to_local(time_now:str,dict_item_list:list):
    summary_dict_list=[]
    for dict_item in dict_item_list:
        if dict_item["summary"] is not None:
            if dict_item["other_info"] !="":
                summary_dict_list.append({"other_info":dict_item["other_info"],"origin_article":dict_item["text"][:20],"summarize_result":dict_item["summary"]})
            else:
                summary_dict_list.append({"origin_article":dict_item["text"][:20],"summarize_result":dict_item["summary"]})
    path = os.path.dirname(os.path.abspath(__file__))
    path=os.path.join(path,"result","summary_result")
    os.makedirs(path,exist_ok=True)
    if time_now:
        pass
    else:
        time_now=datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    with open(os.path.join(path, f"{time_now}_summarize_result.json"), "a", encoding="utf-8") as f:
        for dict_item in summary_dict_list:
            # Ensure no surrogate escapes leak into file
            json.dump(_sanitize_surrogates(dict_item), f, ensure_ascii=False)
    print("文章摘要大纲本地化保存完成")
    return 

async def main_summarize(llm,text:Optional[str]=None):
    text_list=[]
    if text is None:
        while True:
            text=read_multiline()
            if text.strip()=="":
                break
            text_list.append(text)
    else:
        text_list=[text]
    dict_list=[{"other_info":"","text":text} for text in text_list]
    time_now=datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    result=await summarize_all_text(llm,dict_list)
    save_to_local(time_now,result)

if __name__ == "__main__":
    summarize_llm = ChatOpenAI(
    model_name="google/gemini-2.5-flash",
    temperature=0.5,
    api_key=getenv("OPENROUTER_API_KEY"),
    base_url=getenv("OPENROUTER_BASE_URL"),
    streaming=False,
    timeout=60,
    max_retries=10,
    # stream_usage=True
    )
    asyncio.run(main_summarize(summarize_llm))
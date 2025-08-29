import os
import time
from os import getenv
from dotenv import load_dotenv
load_dotenv()
#如果有需要将下面注释的启用！！
# os.environ["LANGCHAIN_TRACING_V2"] = "true"
# os.environ["LANGCHAIN_PROJECT"] = "MAS"
# os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
# os.environ["LANGCHAIN_API_KEY"] = getenv("LANGSMITH_API_KEY")
app_id = getenv("FEISHU_APP_ID")
app_secret = getenv("FEISHU_APP_SECRET")
folder_token = getenv("FEISHU_FOLDER_TOKEN")
from langsmith import traceable
import re
import sys
import asyncio
import uuid
import json
from collections import defaultdict
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate,MessagesPlaceholder
from langgraph.graph import StateGraph,START,END
from langgraph.prebuilt import create_react_agent
from langgraph.graph.message import add_messages
from langgraph.graph.message import MessagesState
from langchain_core.messages import AIMessageChunk, BaseMessage,HumanMessage,SystemMessage,ToolMessage,AIMessage
from typing_extensions import TypedDict,Annotated,Any,Literal
from datetime import datetime
from langgraph.types import Command,Send
from langchain_core.runnables import RunnableConfig
from operator import or_, add
from v2t import main_v2t_no_summary
from template_list import role_list
from langchain_core.callbacks import UsageMetadataCallbackHandler
from text_summary import main_summarize
from feishu4MAS_copy_user import upload_imitate_to_feishu_simple1, get_user_access_token, get_auth_code_url
from feishu4MAS_copy_tenant import get_refresh_app_access_token,upload_imitate_to_feishu_simple2
callback = UsageMetadataCallbackHandler()
sem = asyncio.Semaphore(8)
config = RunnableConfig(
    recursion_limit=200,                        # ✅ 放在顶层
    configurable={"thread_id": str(uuid.uuid4())},
    callbacks=[callback]
)
time_now = datetime.now().strftime("%Y-%m-%d %H:%M")

dashscope_model = ChatOpenAI(
    model_name="qwen-plus-latest",
    temperature=1,
    api_key=getenv("DASH_SCOPE_API_KEY"),
    base_url=getenv("DASH_SCOPE_BASE_URL"),
    streaming=True,
    timeout=60,
    max_retries=10,
    stream_usage=True
)
correct_model = ChatOpenAI(
    model_name="google/gemini-2.5-flash-lite",
    temperature=0.5,
    api_key=getenv("OPENROUTER_API_KEY"),
    base_url=getenv("OPENROUTER_BASE_URL"),
    streaming=False,
    timeout=60,
    max_retries=10,
    stream_usage=True
)
openrouter1 = ChatOpenAI(
    model_name="google/gemini-2.5-flash-lite",
    temperature=1,
    api_key=getenv("OPENROUTER_API_KEY"),
    base_url=getenv("OPENROUTER_BASE_URL"),
    streaming=True,
    timeout=60,
    max_retries=10,
    stream_usage=True
)
summarize_model = ChatOpenAI(
    model_name="google/gemini-2.5-flash-lite",
    temperature=1,
    api_key=getenv("OPENROUTER_API_KEY"),
    base_url=getenv("OPENROUTER_BASE_URL"),
    streaming=True,
    timeout=60,
    max_retries=10,
    stream_usage=True
)
v2t_model = correct_model
imitate_model = openrouter1
def _remove_surrogates_from_str(text: str) -> str:
    """Remove lone surrogate code points to avoid UTF-8 encode errors."""
    if not isinstance(text, str):
        return text
    return "".join(ch for ch in text if not (0xD800 <= ord(ch) <= 0xDFFF))
def read_multiline(prompt="请输入多行文章，结束请输入单独一行 /end 或直接按两次回车："):
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

async def open_tcp_sink(port: int):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    return writer 

#用于更新状态和流式打印LLM输出的函数，只用于仿写
async def collect_state_and_stream_print_imitate(agent, state, stream_mode=("messages",), writer: asyncio.StreamWriter | None = None):
    full_messages = state["messages"]
    new_messages = []
    buf, printed_header = [], False

    async def _emit(text: str):
        if writer is None:
            pass
            # print(text, end="", flush=True)
        else:
            try:
                writer.write(text.encode("utf-8"))
                await writer.drain()
            except ConnectionResetError:
                # 对端（nc）关掉了也别让任务崩
                pass

    async for kind, payload in agent.astream(state, stream_mode=list(stream_mode)):
        if kind == "messages":
            piece = payload[0].content
            if piece:
                if not printed_header:
                    await _emit("\n========== Ai Message ==========\n")
                    printed_header = True
                await _emit(piece)
                buf.append(piece)

    await _emit("\n")
    text_format = "".join(buf)
    if buf:
        new_messages.append(AIMessage(content=text_format))
    return full_messages + new_messages, text_format
#用于工具调用的流式打印
async def collect_state_and_stream_print(agent, state, stream_mode=("messages","updates")):
    """同时打印工具调用信息 + 流式 tokens；并按到达顺序写回 AI/Tool 消息。"""
    full_messages = state["messages"]
    new_messages = []

    buf = []            # 累积 token 文本
    printed_header = False

    # 去重：优先使用消息 id，其次使用(类型, 内容, 名称)作为近似键
    seen_message_ids = set()
    seen_fallback_keys = set()

    def append_if_new(msg):
        mid = getattr(msg, "id", None)
        if mid:
            if mid in seen_message_ids:
                return
            seen_message_ids.add(mid)
            new_messages.append(msg)
            return
        key = (msg.__class__.__name__, getattr(msg, "content", None), getattr(msg, "name", None))
        if key in seen_fallback_keys:
            return
        seen_fallback_keys.add(key)
        new_messages.append(msg)

    def extract_tool_calls_from_update(update_dict):
        """返回 [(tool_name, args_dict), ...]"""
        out = []
        agent = update_dict.get("agent", {})
        for m in agent.get("messages", []):
            # 情况1：规范化后的 tool_calls
            tc = getattr(m, "tool_calls", None)
            if tc:
                for c in tc:
                    name = c.get("name") or (c.get("function") or {}).get("name") or "unknown_tool"
                    args = c.get("args")
                    if args is None:
                        raw = (c.get("function") or {}).get("arguments")
                        try:
                            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
                        except Exception:
                            args = {"raw": raw}
                    out.append((name, args))

            # 情况2：OpenAI 兼容格式在 additional_kwargs.tool_calls
            ak = getattr(m, "additional_kwargs", {}) or {}
            for c in ak.get("tool_calls") or []:
                name = (c.get("function") or {}).get("name") or c.get("name") or "unknown_tool"
                raw = (c.get("function") or {}).get("arguments")
                try:
                    args = json.loads(raw) if isinstance(raw, str) else (raw or {})
                except Exception:
                    args = {"raw": raw}
                out.append((name, args))
        return out

    def extract_tool_message_from_update(update_dict):
        """返回 [(tool_content, tool_name), ...]（仅用于日志打印的降级方案）"""
        out = []
        agent = update_dict.get("tools", {})
        for m in agent.get("messages", []):
            tc = getattr(m, "tool_calls", None)
            if tc:
                for c in tc:
                    name = c.get("name") or "unknown_tool"
                    content = c.get("content")
                    out.append((content, name))
            ak = getattr(m, "additional_kwargs", {}) or {}
            for c in ak.get("tool_calls") or []:
                name = (c.get("function") or {}).get("name") or c.get("name") or "unknown_tool"
                content = (c.get("function") or {}).get("content")
                out.append((name, content))
        return out

    async for kind, payload in agent.astream(state, stream_mode=list(stream_mode)):
        if kind == "updates":
            # 1) 模型规划工具调用：把带有 tool_calls 的 AIMessage 记录到消息序列
            if "agent" in payload and "messages" in payload["agent"]:
                for m in payload["agent"]["messages"]:
                    has_tc = bool(getattr(m, "tool_calls", None)) or bool((getattr(m, "additional_kwargs", {}) or {}).get("tool_calls"))
                    if has_tc:
                        append_if_new(m)
                for name, args in extract_tool_calls_from_update(payload):
                    print(f"[ToolCall] {name} args={args}")

            # 2) 工具返回：直接追加 ToolMessage（若是标准类型）
            if "tools" in payload and "messages" in payload["tools"]:
                for m in payload["tools"]["messages"]:
                    try:
                        if isinstance(m, ToolMessage):
                            append_if_new(m)
                    except Exception:
                        pass
                # 打印（降级解析，仅用于日志）
                for name, content in extract_tool_message_from_update(payload):
                    print(f"[ToolResult] {name} content={content}")

        if kind == "messages":
            # 3) 流式 tokens（只打印一次，不重复）
            piece = payload[0].content
            if piece:
                if not printed_header:
                    print("\n=================================== Ai Message =================================\n")
                    printed_header = True
                print(piece, end="", flush=True)
                buf.append(piece)

    print()  # 换行

    # 4) 加入最终 AI 回复（聚合后的单条，位于工具消息之后）
    if buf:
        append_if_new(AIMessage(content="".join(buf)))

    return full_messages + new_messages

def strip_markdown_fences(text: str) -> str:
    open_pat = re.compile(r'^([ \t]{0,3})(`{3,})[ \t]*markdown[ \t]*$',
                          re.IGNORECASE | re.MULTILINE)
    lines = text.splitlines(keepends=True)
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = open_pat.match(line.rstrip('\n\r'))
        if not m:
            out.append(line)
            i += 1
            continue
        # 进入 “去栏模式”
        fence = m.group(2)  # 记录开栏的反引号数量
        i += 1  # 跳过开栏行
        close_pat = re.compile(rf'^[ \t]{{0,3}}{re.escape(fence)}[ \t]*$')
        while i < len(lines):
            # 如果到闭栏行就跳过该行并退出；否则照常输出
            if close_pat.match(lines[i].rstrip('\n\r')):
                i += 1
                break
            out.append(lines[i])
            i += 1
    return ''.join(out)

#仿写
class imitate_state(MessagesState):
    user_input:str
    video_url:str
    article:str
    summary:dict
    app_id:str
    app_secret:str
    folder_token:str
    template_choose_list:list[dict]
    role_graph_list:Annotated[list[StateGraph],add]
    messages:Annotated[list[BaseMessage],add_messages]
    each_role_text:Annotated[dict[str,str],or_] #{"角色1":"正文","角色2":"正文"}

class each_role_state(MessagesState):
            role_name:str
            messages:Annotated[list[BaseMessage],add_messages]
            final_text:dict[str,str]

class each_node_state(MessagesState):
                role_name:str
                messages:Annotated[list[BaseMessage],add_messages]
                final_text:dict[str,str]
                writer:asyncio.StreamWriter

async def create_role_imitate_graph(state:imitate_state):
    """create the imitate graph dynamically for the role"""

    role_graph_list = []
    article=state["article"]
    #为每一个角色依据name和template创建一个imitate_graph
    #遍历role_choose_list中的每一个角色取出name和template，创建一个imitate_graph
    #role_dict是role_choose_list中的每一个角色，每个角色包含name和template(list)
    for role_dict in state["template_choose_list"]:
        #为template中的每一个template创建一个imitate_node,然后将其组合为完整的graph并编译它
        node_list=[]
        for i, template_item in enumerate(role_dict["template"]):
            
            if i==0:
                #对于第一步需要将原始文案交进去，然后进行仿写
                async def each_node_imitate_node(state:each_node_state, template_value=template_item):
                    """imitate the text to specific style"""
                    prompt = ChatPromptTemplate.from_messages([
                        ("system", template_value),
                        ("user", f"<原始文案>\n{article}\n</原始文案>")
                    ])
                    imitate_agent = create_react_agent(
                        model = imitate_model,
                        tools=[],
                        prompt = prompt
                    )
                    AI_messages,text_format = await collect_state_and_stream_print_imitate(imitate_agent,state,stream_mode=["messages"],writer=None)
                    return {"messages":AI_messages,"final_text":text_format}
                node_list.append(each_node_imitate_node)
            else:
                async def each_node_imitate_node(state:each_node_state, template_value=template_item):
                    """imitate the text to specific style"""
                    prompt = ChatPromptTemplate.from_messages([
                        MessagesPlaceholder("messages"),
                        ("user", template_value)])
                    agent=create_react_agent(
                        model = imitate_model,
                        tools=[],
                        prompt = prompt
                    )
                    AI_messages,text_format = await collect_state_and_stream_print_imitate(agent,state,stream_mode=["messages"],writer=None)
                    return {"messages":AI_messages,"final_text":text_format}
                node_list.append(each_node_imitate_node)
        if role_dict["name"]=="小A":
            async def each_node_imitate_node(state:each_node_state):
                """imitate the text to specific style"""
                prompt = ChatPromptTemplate.from_messages([
                        MessagesPlaceholder("messages"),
                        ("user", f"""\n\n<待优化文案>\n{state['final_text']}\n</待优化文案>\n
                        以上就是需要优化开头部分的文案，请直接以markdown格式输出优化完成后的全部文案，不要改变文案其他部分的结构和内容
                        """)
                        ])
                agent=create_react_agent(
                        model = imitate_model,
                        tools=[],
                        prompt = prompt
                    )
                AI_messages,text_format = await collect_state_and_stream_print_imitate(agent,state,stream_mode=["messages"],writer=None)
                return {"messages":AI_messages,"final_text":text_format}
            node_list.append(each_node_imitate_node)
        #实例化graph_builder
        role_graph_builder = StateGraph(each_role_state)
        #将node_list中的每一个node添加到graph_builder中，并设置START_edge和END_edge,以及每个节点之间的edge
        for i, node in enumerate(node_list):
            role_graph_builder.add_node(f"imitate_{role_dict['name']}_node{i+1}",node)
        role_graph_builder.add_edge(START,f"imitate_{role_dict['name']}_node1")
        for i in range(len(node_list)-1):
            role_graph_builder.add_edge(f"imitate_{role_dict['name']}_node{i+1}",f"imitate_{role_dict['name']}_node{i+2}")
        role_graph_builder.add_edge(f"imitate_{role_dict['name']}_node{len(node_list)}",END)
        #编译graph
        role_graph = role_graph_builder.compile()
        #将graph添加到role_graph_list中
        role_graph_list.append(role_graph)
    #返回role_graph_list
    return {"role_graph_list":role_graph_list}

#仿写
@traceable(name = "imitate_node")
async def imitate_node(state:imitate_state):
    time_start = time.time()
    
    async with sem:
        """imitate the text to specific style"""
        task_list = []
        for role_graph in state["role_graph_list"]:
            task_list.append(role_graph.ainvoke(state,config))
        result_list = await asyncio.gather(*task_list)
        result = {"each_role_text":defaultdict(str)}
        #gather顺序和template_choose_list顺序一致
        for i, role in enumerate(state["template_choose_list"]):
            role_key = role["name"] if isinstance(role, dict) and "name" in role else str(role)
            result["each_role_text"][role_key] = result_list[i]["final_text"]
        time_end = time.time()
        print(f"程序运行时间：{time_end - time_start}秒")
        return result

@traceable(name = "imitate_v2t_node")
async def imitate_v2t_node(state:imitate_state):
    """transfer vieo link to text including correct"""
    #将输入的视频链接转文字
    v2t_text_list = await main_v2t_no_summary(v2t_model,[state["video_url"]])
    # 回退策略：若无有效结果，走 text_fanout_node，以原始输入继续流程
    if not v2t_text_list:
        raise RuntimeError("没有有效的转录结果")
    #将转文字的结果交接给create_role_imitate_graph
    return Command(goto="create_role_imitate_graph",update={"article":v2t_text_list[0].get("text","")})

async def summarize_node(state:imitate_state):
    """summarize the text to specific style"""
    text = state["article"]
    summarize_result=await main_summarize(summarize_model,text)
    return {"summary":summarize_result}
async def text_fanout_node(state:imitate_state):
    """fan out to summarize and create graph for plain text path"""
    return {}
    
@traceable(name = "select_node")
async def select_node(state:imitate_state):
    """select the node to run"""
    #如果是链接形式就尝试转文字
    if "https" in state["user_input"] or "http" in state["user_input"]:
        return Command(goto="imitate_v2t_node",update={"video_url":state["user_input"]})
    #否则当作文章处理
    else:
        return Command(goto="text_fanout_node",update={"article":state["user_input"]})


def save_to_local(state:imitate_state):
    """save the text to local as txt and md"""
    time_now = datetime.now().strftime("%Y-%m-%d %H:%M")
    title=state["article"][:10]
    floder_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(floder_dir,"result","imitate_result")
    os.makedirs(output_dir,exist_ok=True)
    with open(os.path.join(output_dir,f"{title}_{time_now}.txt"),"a") as f:
        f.write(f"原文章:\n{state['article']}\n")
        for role,text in state["each_role_text"].items():
            f.write(f"\n{role}仿写文案:\n{text}\n")
    with open(os.path.join(output_dir,f"{title}_{time_now}.md"),"a") as f:
        f.write(f"# 原文章:\n{state['article']}\n\n")
        for role,text in state["each_role_text"].items():
            text = strip_markdown_fences(text)
            f.write(f"\n# {role}仿写文案:\n{text}\n")
        if callback.usage_metadata:
            f.write(f"\n# token使用量:\n")
            for key,value in callback.usage_metadata.items():
                f.write(f"{key}:  \n{value}\n")
            f.write("\n")
    print(f"保存到本地:\t{title}_{time_now}")

    return {}

@traceable(name = "upload2feishu_node")
async def upload2feishu_node(state:imitate_state):
    """upload the text to feishu"""
    roles=[]
    articles=[]
    origin_article = state["article"]
    theme = state["article"][:10]
    app_id = state["app_id"]
    app_secret = state["app_secret"]
    folder_token = state["folder_token"]
    if app_id !="" and app_secret !="" and folder_token !="":
        #将state中的each_role_text中的每个角色的title和final_text上传到飞书
        print("开始将仿写结果上传至飞书")
        for role,text in state["each_role_text"].items():
            roles.append(role)
            articles.append(text)
            #将title和article上传到飞书
        async def upload_to_feishu_user(app_id, app_secret, folder_token, theme, origin_article, roles, articles) -> str:
            # 优先从环境变量读取 user_access_token；否则用 FEISHU_CODE 换取；仍缺失则打印授权 URL 并中止
            REDIRECT_URI = "https://open.feishu.cn/api-explorer/loading"
            user_access_token = os.environ.get("FEISHU_USER_ACCESS_TOKEN", "").strip()
            if not user_access_token:
                code = os.environ.get("FEISHU_CODE", "").strip()
                if code:
                    token_data = get_user_access_token(app_id, app_secret, code)
                    user_access_token = token_data.get("access_token", "")
            if not user_access_token:
                auth_url = get_auth_code_url(app_id, REDIRECT_URI, state="state123")
                print(f"[AUTH] 请在浏览器打开以下链接完成授权，并在回调后获取 code：\n{auth_url}")
                print("[AUTH] 完成后以环境变量 FEISHU_CODE=... 再次运行，或直接提供 FEISHU_USER_ACCESS_TOKEN。")
                raise RuntimeError("缺少 user_access_token/FEISHU_CODE，已输出授权链接")

            upload_imitate_to_feishu_simple1(
                folder_token=folder_token,
                theme=theme,
                origin_article=origin_article,
                roles=roles,
                imitate_contents=articles,
                app_id=app_id,
                app_secret=app_secret,
                user_access_token=user_access_token
            )
            print("已成功上传至飞书")
        async def upload_to_feishu_tenant(app_id, app_secret, folder_token, theme, origin_article, roles, articles) -> str:
            tenant_access_token = get_refresh_app_access_token(app_id, app_secret)
            upload_imitate_to_feishu_simple2(
                folder_token=folder_token,
                theme=theme,
                origin_article=origin_article,
                roles=roles,
                imitate_contents=articles,
                app_id=app_id,
                app_secret=app_secret,
                tenant_access_token=tenant_access_token
            )
            print("已成功上传至飞书")
        try:
            await upload_to_feishu_tenant(app_id, app_secret, folder_token, theme, origin_article, roles, articles)
        except Exception as e:
            print(f"上传失败: {e}")
            print("尝试使用user_access_token上传")
            try:
                await upload_to_feishu_user(state["app_id"], state["app_secret"], folder_token, theme, origin_article, roles, articles)
            except Exception as e:
                print(f"上传失败: {e}")
                print("上传失败")
        #将state中的each_role_text中的每个角色的final_text上传到飞书
    return {}

def usage_node(state:imitate_state):
    if callback.usage_metadata:
        for key,value in callback.usage_metadata.items():
            print(f"{key}:\n{value}\n")
        callback.usage_metadata.clear()
    return {}

imitate_graph_builder = StateGraph(imitate_state)
imitate_graph_builder.add_node("select_node",select_node)
imitate_graph_builder.add_node("create_role_imitate_graph",create_role_imitate_graph)
imitate_graph_builder.add_node("imitate_v2t_node",imitate_v2t_node)
imitate_graph_builder.add_node("imitate_node",imitate_node)
imitate_graph_builder.add_node("summarize_node",summarize_node)
imitate_graph_builder.add_node("text_fanout_node",text_fanout_node)
imitate_graph_builder.add_node("save_to_local",save_to_local)
imitate_graph_builder.add_node("upload2feishu_node",upload2feishu_node)
imitate_graph_builder.add_node("usage_node",usage_node)
imitate_graph_builder.add_edge(START,"select_node")
imitate_graph_builder.add_edge("imitate_v2t_node","create_role_imitate_graph")
imitate_graph_builder.add_edge("imitate_v2t_node","summarize_node")
imitate_graph_builder.add_edge("text_fanout_node","create_role_imitate_graph")
imitate_graph_builder.add_edge("text_fanout_node","summarize_node")
imitate_graph_builder.add_edge("summarize_node","usage_node")
imitate_graph_builder.add_edge("create_role_imitate_graph","imitate_node")
imitate_graph_builder.add_edge("imitate_node","save_to_local")
imitate_graph_builder.add_edge("save_to_local","upload2feishu_node")
imitate_graph_builder.add_edge("upload2feishu_node","usage_node")
imitate_graph_builder.add_edge("usage_node",END)
imitate_graph = imitate_graph_builder.compile()


async def main():
    role=" ".join([f"({i+1}:{role_list[i]['name']})" for i in range(len(role_list))])
    while True:
        template_choose=input(f"请选择模板{role}\t**默认模板全选(如需全选直接回车)**:\n输入示例：123,12,23,13,1,2,3\n")
        if template_choose=="":
            template_choose_list = role_list
            break        
        elif template_choose.lower() in ["/exit","/quit","exit","quit","q"]:
            print("退出程序")
            sys.exit(0)
        else:
            template_choose_list = [role_list[int(i)-1] for i in list(template_choose)]
            break
    for role in template_choose_list:
        print(f"""已选择*{role["name"]}*模板""")
    user_input = read_multiline("请输入链接或者文章内容（可含空行），结束请输入 /end ：\n 退出请输入quit")
    imitate_state = {"user_input":user_input,"messages":[],"template_choose_list":template_choose_list,"app_id":app_id,"app_secret":app_secret,"folder_token":folder_token}
    result = await imitate_graph.ainvoke(imitate_state,config)
    imitate_state=result
    sys.exit(0)
if __name__ == "__main__":
    asyncio.run(main())


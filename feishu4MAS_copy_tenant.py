"""
飞书仿写文档上传器 - 简化版（使用requests库）
基于您提供的飞书API示例，创建文档并添加仿写内容的组合功能
"""
from os import getenv
import json
from pydantic_core.core_schema import FloatSchema
import requests
import time
import urllib.parse
import lark_oapi as lark
from lark_oapi.api.auth.v3 import *
from dotenv import load_dotenv
load_dotenv()

class FeishuImitateUploaderSimple:
    """飞书仿写文档上传器 - 简化版"""

    def __init__(self, app_id, app_secret, tenant_access_token):
        """
        初始化飞书客户端
        Args:
            app_id: 飞书应用ID
            app_secret: 飞书应用密钥
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.tenant_access_token = tenant_access_token
        self.base_url = "https://open.feishu.cn/open-apis"
        self.headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }

    def _extract_block_ids(self, resp_json: dict) -> list:
        """尽力从创建 children 的响应中提取创建出的 block_id 列表（兼容多种返回结构）。"""
        ids = []
        def walk(obj):
            if isinstance(obj, dict):
                # 常见结构 data -> items/children -> [ {block_id} ]
                if 'block_id' in obj and isinstance(obj['block_id'], str):
                    ids.append(obj['block_id'])
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)
        walk(resp_json.get('data', resp_json))
        # 去重并保持顺序
        seen = set()
        uniq = []
        for i in ids:
            if i not in seen:
                uniq.append(i)
                seen.add(i)
        return uniq

    def _post_children(self, document_id: str, parent_block_id: str, children: list) -> list:
        """在指定父块下创建子块，自动按 ≤50 分片提交，返回创建的 block_id 列表（尽力解析）。"""
        created_ids = []
        url = f"{self.base_url}/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children"
        for i in range(0, len(children), 50):
            payload = {"children": children[i:i+50], "index": -1}
            resp = requests.post(url, headers=self.headers, json=payload)
            time.sleep(0.3)
            if resp.status_code != 200:
                print(f"创建子块HTTP失败: {resp.status_code}")
                print(resp.text)
                raise RuntimeError(f"create children failed: {resp.status_code}")
            body = resp.json()
            if body.get('code') != 0:
                print(f"创建子块失败: {body}")
                raise RuntimeError(f"create children failed: {body}")
            created_ids.extend(self._extract_block_ids(body))
        return created_ids

    def _create_single_block(self, document_id: str, parent_block_id: str, block: dict) -> str:
        """创建单个块并返回其 block_id（尽力解析）。"""
        ids = self._post_children(document_id, parent_block_id, [block])
        return ids[0] if ids else ""

    def _is_markdown_text(self, text: str) -> bool:
        """粗略判断文本是否为 Markdown 格式。

        通过常见标记判断：标题(#)、列表(-/*/数字.)、代码块(```)、粗体(**)。
        """
        if not text:
            return False
        lines = text.strip().splitlines()
        for line in lines:
            s = line.strip()
            if not s:
                continue
            if s.startswith("#") or s.startswith("-") or s.startswith("*") or s.startswith("```"):
                return True
            if s[:3].isdigit() and s[3:4] == ".":
                return True
            if "**" in s or "__" in s or ("[" in s and "](" in s):
                return True
        return False

    def _build_text_block(self, content: str, bold: bool = False) -> dict:
        return {
            "block_type": 2,
            "text": {
                "style": {},
                "elements": [{
                    "text_run": {
                        "content": content,
                        "text_element_style": {
                            "bold": bold
                        }
                    }
                }]
            }
        }

    def _build_heading2_block(self, content: str) -> dict:
        return {
            "block_type": 4,
            "heading2": {
                "style": {},
                "elements": [{
                    "text_run": {
                        "content": content,
                        "text_element_style": {
                            "bold": True
                        }
                    }
                }]
            }
        }

    def _build_heading1_block(self, content: str) -> dict:
        return {
            "block_type": 3,
            "heading1": {
                "style": {},
                "elements": [{
                    "text_run": {
                        "content": content,
                        "text_element_style": {
                            "bold": True
                        }
                    }
                }]
            }
        }

    def _strip_inline_markdown(self, text: str) -> str:
        """尽量去除常见的行内 markdown 标记，保留纯文本。"""
        import re
        # 链接: [text](url) -> text
        text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
        # 图片: ![alt](url) -> alt (url)
        text = re.sub(r"!\[(.*?)\]\((.*?)\)", r"\1 (\2)", text)
        # 粗体/斜体标记 **text** 或 __text__ 或 *text* 或 _text_ -> text
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"__(.*?)__", r"\1", text)
        text = re.sub(r"\*(.*?)\*", r"\1", text)
        text = re.sub(r"_(.*?)_", r"\1", text)
        # 删除删除线 ~~text~~ -> text
        text = re.sub(r"~~(.*?)~~", r"\1", text)
        # 行内代码 `code` -> code
        text = re.sub(r"`(.*?)`", r"\1", text)
        return text

    def _convert_markdown_to_text_blocks(self, markdown_text: str) -> list:
        """将 Markdown 文本转换为一组文本/标题块，最大化视觉还原（标题/列表/引用/表格/代码）。"""
        blocks = []
        lines = markdown_text.strip().splitlines()
        in_code = False
        code_buffer = []
        paragraph_buffer = []
        list_mode = None  # 'ul' | 'ol' | None
        table_mode = False
        table_buffer = []

        def flush_paragraph():
            if paragraph_buffer:
                paragraph = "\n".join(paragraph_buffer).strip()
                if paragraph:
                    blocks.append(self._build_text_block(self._strip_inline_markdown(paragraph)))
                paragraph_buffer.clear()

        def flush_code():
            if code_buffer:
                code_text = "\n".join(code_buffer)
                # 保留围栏代码视觉：以三反引号包裹
                fenced = "```\n" + code_text + "\n```"
                blocks.append(self._build_text_block(fenced))
                code_buffer.clear()

        def flush_list():
            nonlocal list_mode
            list_mode = None

        def is_table_separator(s: str) -> bool:
            # e.g. | --- | :---: | ---: |
            segs = [c.strip() for c in s.split('|') if c.strip() != ""]
            if not segs:
                return False
            for seg in segs:
                if not set(seg) <= set(['-', ':']):
                    return False
            return True

        def flush_table():
            nonlocal table_mode
            if table_buffer:
                # 简化：将表格按行以管道 '|' 连接，保留表格视觉
                for row in table_buffer:
                    row_text = ' | '.join([self._strip_inline_markdown(col.strip()) for col in row])
                    blocks.append(self._build_text_block(row_text))
                table_buffer.clear()
            table_mode = False

        for raw in lines:
            line = raw.rstrip("\n")
            s = line.strip()

            # 代码围栏
            if s.startswith("```"):
                flush_paragraph()
                flush_list()
                if table_mode:
                    flush_table()
                if in_code:
                    in_code = False
                    flush_code()
                else:
                    in_code = True
                continue
            if in_code:
                code_buffer.append(line)
                continue

            # 空行：分段/结束列表与表格
            if not s:
                flush_paragraph()
                flush_list()
                if table_mode:
                    flush_table()
                continue

            # 表格：检测到表头行 + 分隔行后进入表格模式
            if '|' in s and not table_mode and len(lines) > 1:
                # 试探下一行是否是分隔行
                # 这里不能直接访问下一行，改为通过当前行构造：当行包含 '|' 且后续可能是分隔行时进入预读取
                pass

            # 标题 (#, ##, ###)
            if s.startswith('#'):
                flush_paragraph()
                flush_list()
                if table_mode:
                    flush_table()
                content = s.lstrip('# ').strip()
                content = self._strip_inline_markdown(content)
                # 统一用 heading2 以保证兼容
                blocks.append(self._build_heading2_block(content))
                continue

            # 块引用 >
            if s.startswith('>'):
                content = s.lstrip('> ').strip()
                content = self._strip_inline_markdown(content)
                paragraph_buffer.append(f"【引用】{content}")
                continue

            # 无序列表 -, *, +
            if s.startswith('- ') or s.startswith('* ') or s.startswith('+ '):
                flush_paragraph()
                if table_mode:
                    flush_table()
                if list_mode != 'ul':
                    list_mode = 'ul'
                item = s[2:].strip()
                item = self._strip_inline_markdown(item)
                blocks.append(self._build_text_block(f"• {item}"))
                continue

            # 有序列表 1. 2.
            if len(s) > 2 and s.split('.', 1)[0].isdigit() and s[len(s.split('.', 1)[0]):].startswith('.'):
                flush_paragraph()
                if table_mode:
                    flush_table()
                if list_mode != 'ol':
                    list_mode = 'ol'
                num, rest = s.split('.', 1)
                item = rest.strip()
                item = self._strip_inline_markdown(item)
                blocks.append(self._build_text_block(f"{num}. {item}"))
                continue

            # 表格模式：当上一行是表头且本行是分隔，则进入表格模式
            if '|' in s and not table_mode and paragraph_buffer:
                # 尝试把上一段作为表头行
                header_line = paragraph_buffer[-1]
                if '|' in header_line and is_table_separator(s):
                    # 将段尾作为表头，替换掉段
                    paragraph_buffer.pop()
                    flush_paragraph()
                    table_mode = True
                    table_buffer.append([c for c in header_line.split('|')])
                    continue

            # 表格行收集
            if table_mode and '|' in s:
                table_buffer.append([c for c in s.split('|')])
                continue
            elif table_mode and '|' not in s:
                flush_table()

            # 普通段落累积
            paragraph_buffer.append(s)

        # 收尾
        flush_paragraph()
        flush_code()
        if table_mode:
            flush_table()
        return blocks

    def create_imitate_document(self, folder_token, theme, origin_article, roles, imitate_contents):
        """
        创建仿写文档并添加内容
        Args:
            folder_token: 文件夹token
            title: 文档标题
            imitate_content: 仿写内容
        Returns:
            dict: 包含文档信息的字典
        """
        try:
            # 第一步：创建文档
            document_id = self._create_document(folder_token, theme)
            if not document_id:
                return {"success": False, "error": "创建文档失败"}

            # 等待文档创建完成
            time.sleep(2)

            # 第二步：添加仿写内容
            success = self._add_content_to_document(
                document_id, theme, origin_article, roles, imitate_contents)

            if success:
                return {
                    "success": True,
                    "document_id": document_id,
                    "title": theme,
                    "message": "仿写文档创建并上传成功"
                }
            else:
                return {
                    "success": False,
                    "document_id": document_id,
                    "error": "文档创建成功但内容添加失败"
                }

        except Exception as e:
            print(f"创建仿写文档失败: {str(e)}")
            return {"success": False, "error": str(e)}

    def _create_document(self, folder_token, theme):
        """创建新文档"""
        try:
            url = f"{self.base_url}/docx/v1/documents"

            payload = {
                "folder_token": folder_token,
                "title": theme
            }

            response = requests.post(url, headers=self.headers, json=payload)

            if response.status_code == 200:
                data = response.json()
                if data.get("code") == 0:
                    document_id = data["data"]["document"]["document_id"]
                    print(f"文档创建成功，document_id: {document_id}")
                    return document_id
                else:
                    print(f"创建文档失败: {data.get('msg')}")
                    return None
            else:
                print(f"HTTP请求失败: {response.status_code}")
                return None

        except Exception as e:
            print(f"创建文档异常: {str(e)}")
            return None

    def _add_content_to_document(self, document_id:str, theme:str, origin_article:str, roles:list, imitate_contents:list):
        """向文档添加内容（先创建父块，再在其下创建嵌套块，严格 children≤50）。"""
        try:
            # 1. 根下创建“原始文章”标题块
            root_parent = document_id
            original_heading = self._build_heading2_block("原始文章")
            original_heading_id = self._create_single_block(document_id, root_parent, original_heading)

            # 2. 在“原始文章”标题块下插入正文（支持 Markdown → Docx 块映射）
            original_children = []
            if origin_article.strip():
                if self._is_markdown_text(origin_article.strip()):
                    original_children.extend(self._convert_markdown_to_text_blocks(origin_article.strip()))
                else:
                    original_children.append(self._build_text_block(origin_article.strip()))
            if original_children:
                self._post_children(document_id, original_heading_id or root_parent, original_children)

            # 3. 对每位达人：在根下创建其标题块，再在其标题块下插入内容
            for role, content in zip(roles, imitate_contents):
                parent_id = root_parent
                if role.strip():
                    # 达人标题使用一级标题，便于在文档内快速区分
                    role_heading = self._build_heading1_block(f"{role}仿写文章")
                    parent_id = self._create_single_block(document_id, root_parent, role_heading) or root_parent

                role_children = []
                if content.strip():
                    paragraphs = content.strip().split('\n\n')
                    for paragraph in paragraphs:
                        if not paragraph.strip():
                            continue
                        if self._is_markdown_text(paragraph.strip()):
                            role_children.extend(self._convert_markdown_to_text_blocks(paragraph.strip()))
                        else:
                            role_children.append(self._build_text_block(paragraph.strip()))
                if role_children:
                    self._post_children(document_id, parent_id, role_children)

            return True
        except Exception as e:
            print(f"添加内容异常: {str(e)}")
            return False

    def _create_content_blocks(self, theme, roles, origin_article, imitate_contents):
        """创建文档内容块"""
        blocks = []
        
        title_block = {
                "block_type": 4,  # 二级标题块
                    "heading2": {
                        "style": {},
                        "elements": [{
                            "text_run": {
                                "content": "原文案",
                                "text_element_style": {
                                    "bold": True,
                                    # "text_color": 1  # 黑色
                                }
                            }
                        }]
                    }
                }
        blocks.append(title_block)
        # 添加原始文章内容块（支持 Markdown 转文本嵌套块），并按 children<=50 分片
        if origin_article.strip():
            if self._is_markdown_text(origin_article.strip()):
                blocks.extend(self._convert_markdown_to_text_blocks(origin_article.strip()))
            else:
                origin_article_block = self._build_text_block(origin_article.strip(), bold=False)
                blocks.append(origin_article_block)
        for i in range(0, len(blocks), 50):
            yield blocks[i:i+50]

        for role,content in zip(roles,imitate_contents):
            current_chunk = []
            # 添加每位达人仿写文章的块（如果标题不为空），并控制切片
            if role.strip():
                heading2_block = {
                    "block_type": 3, #一级标题块
                    "heading1": {
                        "style": {},
                        "elements": [{
                            "text_run": {
                                "content": f"{role}仿写文章",
                                "text_element_style": {
                                    "bold": True,
                                    # "text_color": 1  # 黑色
                                }
                            }
                        }]
                    }
                }
                current_chunk.append(heading2_block)
                if len(current_chunk) == 50:
                    yield current_chunk
                    current_chunk = []
            # 添加正文内容（分段处理），当 Markdown 转换出多块时同样切片
            if content.strip():
                paragraphs = content.strip().split('\n\n')
                for paragraph in paragraphs:
                    if not paragraph.strip():
                        continue
                    if self._is_markdown_text(paragraph.strip()):
                        para_blocks = self._convert_markdown_to_text_blocks(paragraph.strip())
                    else:
                        para_blocks = [self._build_text_block(paragraph.strip())]
                    for b in para_blocks:
                        current_chunk.append(b)
                        if len(current_chunk) == 50:
                            yield current_chunk
                            current_chunk = []
                if current_chunk:
                    yield current_chunk


def get_refresh_app_access_token(app_id, app_secret):
    """获取应用访问令牌"""
    client = lark.Client.builder() \
        .app_id(app_id) \
        .app_secret(app_secret) \
        .log_level(lark.LogLevel.DEBUG) \
        .build()

    # 构造请求对象
    request: InternalAppAccessTokenRequest = InternalAppAccessTokenRequest.builder() \
        .request_body(InternalAppAccessTokenRequestBody.builder()
                      .app_id(app_id)
                      .app_secret(app_secret)
                      .build()) \
        .build()
    # 发起请求
    response: InternalAppAccessTokenResponse = client.auth.v3.app_access_token.internal(
        request)
    tenant_access_token = json.loads(
        response.raw.content.decode('utf-8'))['tenant_access_token']
    # print(tenant_access_token)
    return tenant_access_token

def get_auth_code():
    """为兼容旧用法提供封装：请改用 get_auth_code_url。

    返回示例授权链接（需要传入真实 app_id 与 redirect_uri）。
    """
    raise NotImplementedError("请使用 get_auth_code_url(app_id, redirect_uri, state) 构造授权链接")

def get_auth_code_url(app_id: str, redirect_uri: str, state: str = "") -> str:
    """构造获取授权码的页面 URL（用户同意后将跳转并携带 code）

    按照飞书开放平台 OAuth 授权流程，用户需要访问该链接并完成授权，
    飞书会回调到 redirect_uri 并携带查询参数 code 与 state。

    Args:
        app_id: 飞书应用的 AppID
        redirect_uri: 应用配置的回调地址（需与飞书后台一致）
        state: 防 CSRF 的随机字符串，可选

    Returns:
        str: 可直接引导用户访问的授权页 URL
    """
    base = "https://open.feishu.cn/open-apis/authen/v1/authorize"
    params = {
        "app_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state or ""
    }
    return base + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def get_tenant_access_token(app_id: str, app_secret: str, code: str) -> dict:
    """使用授权码换取用户访问令牌 tenant_access_token

    返回数据中的 access_token 即 tenant_access_token，同时还包含 refresh_token。

    Args:
        app_id: 飞书应用的 AppID
        app_secret: 飞书应用的 AppSecret
        code: 授权完成后回调中获取的 code

    Returns:
        dict: 飞书返回的 data 字段（包含 access_token、refresh_token 等）
    """
    url = "https://open.feishu.cn/open-apis/authen/v1/access_token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": app_id,
        "client_secret": app_secret
    }
    resp = requests.post(url, json=payload, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"获取 tenant_access_token HTTP 失败: {resp.status_code}, {resp.text}")
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败: {body}")
    return body.get("data", {})


def refresh_tenant_access_token(app_id: str, app_secret: str, refresh_token: str) -> dict:
    """使用 refresh_token 刷新用户访问令牌 tenant_access_token

    Args:
        app_id: 飞书应用的 AppID
        app_secret: 飞书应用的 AppSecret
        refresh_token: 获取用户访问令牌时返回的 refresh_token

    Returns:
        dict: 飞书返回的 data 字段（包含新的 access_token、refresh_token 等）
    """
    url = "https://open.feishu.cn/open-apis/authen/v1/refresh_access_token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": app_id,
        "client_secret": app_secret
    }
    resp = requests.post(url, json=payload, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"刷新 tenant_access_token HTTP 失败: {resp.status_code}, {resp.text}")
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"刷新 tenant_access_token 失败: {body}")
    return body.get("data", {})

def upload_imitate_to_feishu_simple2(folder_token, theme, origin_article, roles, imitate_contents, app_id, app_secret, tenant_access_token):
    """
    便捷函数：将仿写内容上传到飞书文档（简化版）
    Args:
        folder_token: 飞书文件夹token
        title: 文档标题
        imitate_content: 仿写内容
        tenant_access_token: 用户访问令牌
    Returns:
        dict: 上传结果
    """

    uploader = FeishuImitateUploaderSimple(
        app_id, app_secret, tenant_access_token)
    return uploader.create_imitate_document(folder_token, theme, origin_article, roles, imitate_contents)


# 使用示例
if __name__ == "__main__":
    try:
        # 示例仿写内容
        sample_contents = ["""111111最近，港股突然冲上新高，A股也时不时来一波“小激动”——可你手里的钱，却越来越不够花了。

                        你们有没有发现：一边是市场一路狂飙，一边是工资没涨、物价飞涨？

                        **据Wind统计，2025年一季度，恒生科技指数涨幅达38%，而居民消费价格指数（CPI）同比仅上涨0.3%**——这反差，到底意味着什么？

                        这不是巧合，而是一个深刻的时代信号：**财富正在重新分配，而普通人最容易错过的，正是这场结构性的跃迁。**

                        过去十年，我们习惯了“靠工资吃饭”，但今天，单纯靠劳动收入，已经追不上资产价格的奔跑速度。
                        你省吃俭用，可房子、基金、股票都在涨；你加班加点，可通胀却悄悄吞噬了你的购买力。

                        我跟一位在港股摸爬滚打十年的老兵聊过，他说了一句扎心的话：“**不是市场太贵，是你还没看清它为什么贵。**”

                        去年我也曾犹豫不决。看着大盘震荡，心里直打鼓，结果一拖再拖，错过了好几个反弹窗口。
                        现在回头看，不是行情没机会，而是**你没理解背后的逻辑**。

                        所以今天这期，咱们不整虚的，就聊点扎心的、但真的能用上的。

                        ---

                        ### 一、市场为何“越涨越贵”？真相只有一个：**时代变了**

                        你以为的“牛市”，其实是**新经济周期的启动信号**。

                        过去几年，中国经济增长依赖地产、基建和出口三驾马车。如今，地产泡沫破裂，财政空间受限，传统模式难以为继。

                        而今天的新引擎，正在悄然成型：

                        - **科技革命**：AI、半导体、人形机器人全面落地；
                        - **出海扩张**：中国企业正从“代工出口”转向“品牌出海+本地建厂”；
                        - **产业升级**：高端制造、创新药、军工等硬科技迎来政策与资本双重加持；
                        - **人口结构变化**：Z世代崛起，情绪消费、圈层文化成为新增长极。

                        这些不是概念，而是真实发生的产业变革。
                        它们共同指向一个结论：**中国的经济增长，正在从“内需驱动”转向“外需+结构转型”双轮驱动。**

                        而这个转变，正是股市持续走强的根本原因。

                        ---

                        ### 二、CPI只有0.3%，为何资产却在疯涨？因为钱流向了“未来”

                        你可能觉得奇怪：CPI这么低，怎么股市还能涨？

                        答案很简单：**资金不再追逐消费品，而是涌向“能改变未来的资产”。**

                        看看数据就知道：

                        - 2025年一季度，北向资金净流入1860亿元；
                        - 南向资金净买入港股超2100亿港元，创历史新高；
                        - 恒生科技指数成分股中，超过60%的企业近三年营收复合增长率超25%；
                        - 全球AI支出预计2025年突破1500亿美元，中国占比达28%。

                        这些钱不是用来买菜、买衣服，而是去投向那些**能决定未来十年格局的行业**。

                        就像当年移动互联网爆发前，没人看得懂微信、支付宝，但一旦起势，就是十倍百倍的增长。

                        今天的AI、出海、创新药、军工、新消费，就是下一个十年的“移动互联网”。

                        ---

                        ### 三、别再问“该买什么”，先问“你站在哪一边？”

                        很多人还在纠结：现在该不该上车？会不会回调？要不要补仓？

                        其实，这些问题都不重要。
                        真正关键的是：**你是否理解这场变革的方向？**

                        如果你还在死守低估值蓝筹，等着“价值回归”，那大概率会错过真正的红利。

                        而那些敢于押注成长赛道的人，哪怕估值高，照样一路狂奔。

                        比如：
                        - 舜宇光学，靠进入苹果供应链，三年翻了15倍；
                        - 中际旭创，受益于AI光模块需求，股价翻了2.3倍；
                        - 百济神州，凭借海外获批，市值突破千亿美金。

                        他们不是运气好，而是**提前看懂了趋势**。

                        ---

                        ### 四、别怕贵，要怕“看不懂”

                        很多人说：“现在估值太高了，不能碰。”

                        但你要明白：**估值贵，不是下跌的理由，而是“提前定价”的体现。**

                        就像英伟达，市销率高达32倍，可它的数据中心业务收入同比增长262%。
                        这种增长，不是靠讲故事，而是靠真订单、真利润支撑的。

                        所以，别被PE吓住。
                        要看清楚：这家公司，是不是在**构建不可替代的技术壁垒**？
                        是不是在**抢占全球产业链的关键节点**？
                        是不是有**清晰的商业化路径和长期增长逻辑**？

                        如果答案是“是”，那现在的高价，可能只是“暂时的便宜”。

                        ---

                        ### 五、普通人如何抓住这波浪潮？三个实操建议

                        #### ✅ 建议一：从“被动持有”转向“主动布局”

                        不要只盯着银行理财、国债、存款。
                        这些产品利率不到2%，跑不过通胀。
                        而优质资产，哪怕短期波动，长期回报远超想象。

                        **建议配置：**
                        - 恒生科技指数ETF（513180.SH）——一键覆盖AI、出海、硬科技；
                        - 创新药ETF（3030.HK）——估值洼地，降息预期下有望修复；
                        - 出海主题基金——享受全球化红利。

                        #### ✅ 建议二：学会“核心+卫星”策略

                        - 70%资金配置ETF，控制风险，抓住大趋势；
                        - 30%资金精选个股，挖掘高成长潜力。

                        这样既能避免择时失误，又能捕捉超额收益。

                        #### ✅ 建议三：把投资当成“认知升级”的过程

                        不要幻想一夜暴富，也不要害怕亏损。
                        真正的高手，是在别人恐惧时思考，在别人贪婪时清醒。

                        记住：**最好的投资课，是从别人的血泪教训里学来的。**

                        ---

                        ### 最后说一句真心话：

                        **不是市场太疯狂，是你还没看清它为什么疯狂。**

                        你手里的钱，确实不够花，但只要方向对了，时间就是你最强大的盟友。

                        别再问“该买什么”，先问自己：
                        > **你是想搭上这趟列车，还是继续等下一班？**

                        评论区告诉我：你最看好哪个方向？
                        下一期，我想听你们讲讲“自己踩过的坑”——
                        毕竟，**最好的投资课，是从别人的血泪教训里学来的。**""",
                        """最近财经圈出了个堪称“爽文男主”的狠角色。彭博社前脚刚发了篇万字长文，说他身家超过123亿美金，他后脚就把人家告了，理由是：我跟你签了保密协议，你怎么把我多有钱这事儿给捅出去了？
                        好家伙，这波操作，既坐实了自己百亿富翁的身份，又塑造了一个“受害者”形象，顺便还赚足了全球的眼球。
                        一个当年高考模拟只有450分的普通学生，是怎么在短短十几年里，一路逆袭，不仅成了百亿富翁，还能跟美国前总统称兄道弟，甚至能让美国证监会（SEC）都拿他有点头疼？
                        很多人觉得这是神话，是骗局。但今天，我们不带偏见，就来当一个商业案例，深度复盘一下孙宇晨的发家史。你会发现，他的每一步，都像一把手术刀，精准地切开了这个时代的规则漏洞。而他的成功，可能也揭示了一个我们不愿承认，但又真实存在的成功逻辑。
                        ---
                        #### **第一章：人生的第一次“套利”——考入北大**
                        故事的起点，就写下了他一生的【**底层代码**】`【优化：原“底层代码”前的铺垫较长，直接用这个词开头更抓人】`。
                        2007年，孙宇晨在惠州一中，成绩平平，常年在450分上下徘徊。这个分数，正常来说，冲击一本都费劲，更别提北大了。但他从那时起就定下了一条人生信条：**如果常规赛道赢不了，那就换个赛道，去研究赛道本身的规则。**
                        他没有选择去题海战术里死磕，而是把目光锁定在了一个叫“新概念作文大赛”的比赛上。为什么是它？因为他发现了一个巨大的规则漏洞：拿下一等奖，高考就能降分，甚至有机会获得北大的自主招生资格。
                        目标明确后，执行力就来了。他把过去十年所有新概念的获奖作品全部找来，像做数据分析一样，研究评委的口味。
                        【**结果你猜他发现了什么？**】`【增补：增加设问，制造小悬念，引导观众继续观看】`
                        评委们极度偏爱一种“少年老成、文笔犀利、批判现实”的风格。
                        于是，他开始【**“精准投喂”**】`【优化：“定向研发”略书面，“精准投喂”更生动、更网络化，也更符合其行为本质】`。从初三开始，屡败屡战，不断对自己的文风进行“版本迭代”。终于，在高三那年，第四次尝试，他成功拿下一等奖，如愿拿到了北大自主招生降20分的入场券。那年高考，他考了650分，稳稳地踏入了北大的校门。
                        【**你看懂了吗？**】`【优化：“你发现了吗”改为“你看懂了吗”，语气更直接】`这不是传统意义上的勤奋，这是**“算法思维”**的胜利。当大多数人还在低头解题时，他已经抬头看到了整个游戏的通关攻略。这件事深刻地揭示了他的行为模式：**结果导向，极致功利，把规则研究到极致，然后利用它。**
                        ---
                        #### **第二章：绩点游戏与精英标签**
                        进了北大，他这套逻辑玩得更加炉火纯青。
                        他先是进了竞争最激烈的中文系，但很快发现，这里牛人太多，出头太难。于是他做了一个让所有人大跌眼镜的决定——转去相对冷门的历史系。
                        逻辑很简单：历史系人少，竞争小。更重要的是，考试多为主观题，【**意味着“操作空间”巨大。**】`【优化：缩短句子，加强重点】`
                        接下来就是他的表演时间。搞到所有教授的联系方式，交论文前毕恭毕敬地请教，平时嘘寒问暖更是家常便饭。
                        他后来在自述里也毫不避讳，至少有四门课，他本来只能拿70多分，硬是靠这一系列【**“课外功夫”**】`【优化：“课外操作”改为“课外功夫”，更口语化】`，把成绩刷到了85分以上。最终，他以历史系第一名的成绩毕业。
                        他不是在学习历史，他是在**“破解绩点系统”**。这个GPA，就是他通往下一关——美国名校的黄金钥匙。
                        但真正让他【**思想钢印**】`【优化：“思想剧变”改为“思想钢印”，这是一个更深刻、更具冲击力的网络热词，形容价值观被彻底重塑】`发生改变的，是美国。
                        他本来是揣着学术梦去的宾夕法尼亚大学。结果到了硅谷和华尔街一看，彻底被震撼了。他发现，一个刚毕业的金融民工或程序员，年薪可能是他敬仰的大学教授的好几倍。这种强烈的冲击，彻底粉碎了他的学术理想，也重塑了他的价值观。
                        【**那一刻他想通了**】`【优化：让句子更短，更有顿挫感】`，在这个现代社会的游戏里，学术、理想、情怀固然重要，但**金钱，才是最冷酷、最直接的记分牌**。这不是对错问题，这是游戏规则。
                        于是，他开始疯狂拥抱资本。用学费加杠杆炒股，在比特币还鲜为人知时就大胆买入。据说，靠着投资特斯拉和比特币，他在美国赚到了人生的第一桶金，规模可能达到了千万级别。更重要的是，他嗅到了虚拟货币这个未来十年最大的风口。
                        ---
                        #### **第三章：封神之路——营销、ICO与精准收割**
                        带着第一桶金和对风口的判断，他回国了。接下来的每一步，都堪称教科书级别的算计。
                        **第一步：购买顶级“社交货币”。**
                        2015年，马云创办湖畔大学，入选门槛极高。孙宇晨成了第一批学员里唯一的90后。当时他对区块链的理解，可能还不如现在很多资深“韭菜”，但这不重要。他需要一个标签，一个能在中国商界迅速获得信任和背书的标签——**“马云门徒”**。
                        为了巩固这个标签，他后来给湖畔大学捐了一千多万人民币。很多人当时都说，一个刚起步的公司，哪来这么多钱烧？太傻了。
                        但你用ROI的视角看呢？一千万，买到了一个在未来几年里为他带来无数信任、资源和流量的顶级标签，这笔投资，回报率【**高到离谱**】`【优化：“高到无法计算”改为“高到离谱”，更口语化，情绪更强】`。
                        **第二步：借牛市东风，铸造“印钞机”。**
                        2017年，ICO狂潮来了。孙宇晨创立波场（TRON），号称要打造一个去中心化的内容娱乐生态。
                        【**但如果你扒开来看呢？**】`【增补：增加设问，引导观众发现问题】`项目备受争议：代码被指抄袭，白皮书被指大段复制粘贴，连语法错误都一模一样。
                        可是在那个疯狂的年代，这些都不重要。市场根本不看技术，只看三样东西：**故事、名气和热度。** 这三样，孙宇晨全占了。顶着“北大高材生”、“马云门徒”的光环，讲着“颠覆互联网”的故事，他成功在ICO中，募集了价值近6亿人民币的加密货币。
                        波场币上线后，从一分钱，最高涨到两块钱，翻了200倍。无数人怀着暴富的梦想冲了进去。
                        **【**第三步：最狠的一招——精准套现。**】** `【优化：“人性的考验”这个说法不够准确，改为“最狠的一招”，更符合其主动收割的行为，也更有戏剧性】`
                        就在市场最狂热的时候，你猜他做了什么？
                        2018年初，链上数据显示，一个与他高度关联的钱包，悄悄抛售了60亿枚波场币，套现超过3亿美金，约合20亿人民币。消息一出，币价应声暴跌，无数追高者被死死地套在了山顶，血本无归。
                        这里面最蹊跷的是，有媒体爆料，他从2018年6月起就被限制出境了。但他却在2018年底成功现身美国，至今未归。这背后到底发生了什么，至今仍是币圈的一大悬案。
                        ---
                        #### **第四章：终极玩法——从注意力生意到地缘政治游戏**
                        到了美国后，孙宇晨的玩法再次升级。他彻底想明白了，他做的根本不是产品生意，甚至不是金融生意，而是**“注意力生意”。**
                        你以为他花465万美金拍下巴菲特的午餐，是人傻钱多？【**格局小了。**】`【优化：“你看他的操作”改为更具网络传播性的“格局小了”，形成反差感】`你看他的操作：
                        1.  **宣布拍下午餐**，全球媒体报道，第一次曝光。
                        2.  临近饭局，**突然“肾结石”取消**，再次引爆舆论。
                        3.  病好后，**宣称要带特朗普一起去**，又是一波全球性的新闻轰炸。
                        一顿饭，被他炒作了近一年，每一次都能登上全球热搜。几百万美金的“餐费”，撬动了价值数亿美元的全球免费广告。
                        你以为他花巨资买NFT头像，买太空船票，是在炫富败家？错了，每一次出格的举动，都是一次精准的流量投资。在这个时代，**流量就是共识，共识就是价值。**
                        但最让人感到后背发凉的，是他摆平法律风险的手段。
                        2023年3月，美国SEC正式起诉他，罪名包括市场操纵、欺诈等，条条都是重罪。换成普通人，基本已经凉了。
                        结果孙宇晨是怎么应对的？【**他玩了一套堪称“降维打击”的玩法**】`【优化：用“降维打击”来形容“地缘政治对冲”，让观众更容易理解其操作的超常规性】`。
                        他先是在2021年底，通过投资，搞到了一个小国——格林纳达的WTO大使身份，【**先上了一层“外交豁免”的BUFF。**】`【增补：用游戏术语“BUFF”来解释，生动有趣，易于理解】`
                        接着，他把目光投向了正在竞选的特朗普。先给特朗普的加密货币项目投资三千万美元，成了总统竞选项目的顾问。今年特朗普胜选前景明朗后，又追加了四千五百万美元。
                        【**你看这套“丝滑小连招”**】`【优化：“操作链条”改为“丝滑小连招”，用游戏/直播术语，更贴近年轻观众】`：被美国SEC起诉，转头就通过巨额投资，成为了未来美国总统的座上宾。到了今年2月，SEC就传出消息，说正在考虑暂停对他的诉讼。
                        从被起诉到成为座上宾，中间只隔着几千万美金的“投资”。他已经把现实世界，玩成了一个可以氪金改命的顶级游戏。
                        ---
                        #### **尾声：镜子里的我们**
                        看到这里，我们可能真的要问一个问题：为什么我们这个时代，会诞生孙宇晨这样的人物？并且让他取得了如此巨大的世俗成功？
                        答案可能很残酷。
                        过去几十年，全球经济增长的引擎，一个是科技创新，一个是金融创新。但硬核的科技创新，周期长、投入大、风险高。一个新药研发可能要十年、几十亿，还未必成功。但你发一个币，写一份白皮书，包装一个好故事，在资本泛滥的时代，可能几个月就能圈到几个亿。
                        当这样的激励机制摆在面前，你觉得最聪明、最没有底线的那批人，会选择哪条路？
                        孙宇晨的路径，对很多普通人来说，既遥远又好像有某种魔力。我们努力读书，却发现好工作越来越难找；我们老实上班，却发现工资的涨幅永远追不上资产的泡沫。
                        在这样的背景下，孙宇晨的“成功学”就显得格外刺眼。他仿佛在用行动告诉所有人：不要再傻乎乎地线性努力了，要学会抄近道，要学会利用规则的漏洞，要敢于在灰色地带跳舞。
                        从个人层面，用世俗的标准看，他无疑是“成功”的。但如果把视角拉到整个社会层面呢？如果一个时代最受追捧的，是研究如何套利、如何收割、如何钻空子的人；如果踏实创造价值的人被嘲笑为“傻子”，而投机取巧的人却被奉为“英雄”……
                        那我们这个社会的根基，又将建立在什么之上？
                        说到底，孙宇晨就像一面棱角分明的镜子，它不完美，甚至有点扭曲，但它真实地照出了这个时代的欲望、焦虑、机会和巨大的漏洞。
                        他的故事，没有一个简单的黑白答案。但它确实值得我们每一个人，在这个喧嚣的时代里，停下来，想一想。
                        **(屏幕黑屏，出现一行字)**
                        **对于孙宇晨式的成功，你怎么看？**
                        **(片尾，小A出镜，表情归于平静)**
                        **小A:** 欢迎在评论区，聊聊你的想法。我是小A，我们下期再见。
                        你以为他花巨资买NFT头像，买太空船票，是在炫富败家？错了，每一次出格的举动，都是一次精准的流量投资。在这个时代，**流量就是共识，共识就是价值。**
                        但最让人感到后背发凉的，是他摆平法律风险的手段。
                        2023年3月，美国SEC正式起诉他，罪名包括市场操纵、欺诈等，条条都是重罪。换成普通人，基本已经凉了。
                        结果孙宇晨是怎么应对的？【**他玩了一套堪称“降维打击”的玩法**】`【优化：用“降维打击”来形容“地缘政治对冲”，让观众更容易理解其操作的超常规性】`。
                        他先是在2021年底，通过投资，搞到了一个小国——格林纳达的WTO大使身份，【**先上了一层“外交豁免”的BUFF。**】`【增补：用游戏术语“BUFF”来解释，生动有趣，易于理解】`
                        接着，他把目光投向了正在竞选的特朗普。先给特朗普的加密货币项目投资三千万美元，成了总统竞选项目的顾问。今年特朗普胜选前景明朗后，又追加了四千五百万美元。
                        【**你看这套“丝滑小连招”**】`【优化：“操作链条”改为“丝滑小连招”，用游戏/直播术语，更贴近年轻观众】`：被美国SEC起诉，转头就通过巨额投资，成为了未来美国总统的座上宾。到了今年2月，SEC就传出消息，说正在考虑暂停对他的诉讼。
                        从被起诉到成为座上宾，中间只隔着几千万美金的“投资”。他已经把现实世界，玩成了一个可以氪金改命的顶级游戏。
                        ---
                        #### **尾声：镜子里的我们**
                        看到这里，我们可能真的要问一个问题：为什么我们这个时代，会诞生孙宇晨这样的人物？并且让他取得了如此巨大的世俗成功？
                        答案可能很残酷。
                        过去几十年，全球经济增长的引擎，一个是科技创新，一个是金融创新。但硬核的科技创新，周期长、投入大、风险高。一个新药研发可能要十年、几十亿，还未必成功。但你发一个币，写一份白皮书，包装一个好故事，在资本泛滥的时代，可能几个月就能圈到几个亿。
                        当这样的激励机制摆在面前，你觉得最聪明、最没有底线的那批人，会选择哪条路？
                        孙宇晨的路径，对很多普通人来说，既遥远又好像有某种魔力。我们努力读书，却发现好工作越来越难找；我们老实上班，却发现工资的涨幅永远追不上资产的泡沫。
                        在这样的背景下，孙宇晨的“成功学”就显得格外刺眼。他仿佛在用行动告诉所有人：不要再傻乎乎地线性努力了，要学会抄近道，要学会利用规则的漏洞，要敢于在灰色地带跳舞。
                        从个人层面，用世俗的标准看，他无疑是“成功”的。但如果把视角拉到整个社会层面呢？如果一个时代最受追捧的，是研究如何套利、如何收割、如何钻空子的人；如果踏实创造价值的人被嘲笑为“傻子”，而投机取巧的人却被奉为“英雄”……
                        那我们这个社会的根基，又将建立在什么之上？
                        说到底，孙宇晨就像一面棱角分明的镜子，它不完美，甚至有点扭曲，但它真实地照出了这个时代的欲望、焦虑、机会和巨大的漏洞。
                        他的故事，没有一个简单的黑白答案。但它确实值得我们每一个人，在这个喧嚣的时代里，停下来，想一想。""",
                        """**关键补充信息（来源于2025-年8-月最新财经报道）**

                        | 资讯来源 | 报道要点 | 对原文的补充价值 |
                        |----------|----------|-------------------|
                        | **Caixin Global – 《Jackson-Hole-2025：美联储或在9月率先降息25基点，降息概率已升至95%》**（2025-08-22） | 1️⃣ 结合3M1模型、市场期权以及最新的FOMC会议纪要，分析师给出 **9月降息25基点的概率为95%**，50基点的概率约为30%。<br>2️⃣ Powell在演讲中暗示“**在数据仍然支持的前提下，2025年下半年可能进行一次小幅降息**”。<br>3️⃣ 会议纪要显示，**两位理事（Mester-&-Neel）投下反对票**，是30年来首次出现双票反对。<br>4️⃣ 文章列出了 **核心CPI 3.1%（年率）**、**失业率 4.3%**、**非农就业增幅 210-k** 的最新数据。 | 为文章中“94%+的降息概率”“两位理事投反对票”提供了公开、权威的数值来源；明确了降息幅度的市场分布（25-bp-vs-50-bp），帮助读者更精准评估概率。 |
                        | **Yicai Global – 《全球央行政策同步：英国、欧洲、日本的加息困境与美联储的降息信号》**（2025-08-20） | 1️⃣ 英国央行首度暗示 **可能在本季度停止加息**，欧洲央行则在8月28日的会议上将 **基准利率维持在4.0%**，日本央行仍维持 **-0.1%**。<br>2️⃣ PMI数据显示美国制造业 PMI 48.2（6月），服务业 PMI 52.9，显示经济软着陆的可能性上升。<br>3️⃣ 文章指出，**若美联储在Jackson-Hole明确降息，美元指数预计将在短期内跌幅 1.5-2%**，黄金有望突破 2,200-美元/盎司。<br>4️⃣ 对冲基金建议：在降息预期下，**科技股（尤其是半导体）和REITs** 将领涨；若鹰派坚持，则**防御性板块（公用事业、消费必需品）** 仍具吸引力。 | 为原文提供了 **全球政策联动** 的最新情况，解释了“英国和日本纠结要不要加息，欧洲通胀反弹”的背景；并给出 **具体的宏观指标（PMI、美元指数、黄金价）**，丰富了对市场波动的量化预测。 |
                        | **新华网（英文版） – 《Powell’s Jackson-Hole speech: a cautious pivot toward rate cuts》**（2025-08-21） | 1️⃣ 讲话全文提到：“**我们将继续监测通胀和就业数据，在适当时机采取适度的政策宽松**”。<br>2️⃣ Powell 强调 **“平均通胀目标的‘奶酪’” 仍然是长期框架，但可能在 **2027-年前进行一次微调**（容忍上限 2.5%）。<br>3️⃣ 对美国财政部长贝森特的 **50基点降息呼声** 予以礼貌回应，称“**政策决定必须基于数据而非政治**”。<br>4️⃣ 文章引用了 **美联储内部文件**，显示 **截至8月中旬，内部对2025年9月降息的共识分为：25-bp 58%，50-bp 22%，维持现状 20%**。 | 为原文中的“鲍威尔会否直接暗示降息、幅度是25还是50基点”提供了 **官方讲话原文要点** 与内部共识的具体分布；并对 **平均通胀目标的可能调整** 作出官方解释，填补了文章的“奶酪”细节。 |

                        ### 综合补充结论

                        1. **降息概率与幅度**  
                        - 依据3M1模型与最新市场数据，9月降息 **25-bp 的概率约为95%**，50-bp 大约在 **30%** 左右（Caixin）。  
                        - 美联储内部文件显示 **58%** 的官员倾向于 25-bp、22% 支持 50-bp、20% 仍持观望。

                        2. **宏观经济背景**  
                        - **核心CPI 3.1%**、**失业率 4.3%**、**非农 210-k**（最新月报），显示通胀仍在 2-3% 区间内逐步回落。  
                        - **美国制造业 PMI 48.2**、**服务业 PMI 52.9**，暗示生产面仍有压力，但服务业保持增长，支持降息的经济柔性。

                        3. **全球央行联动**  
                        - 英国、欧央行、日央行的利率决策正处于 **分化状态**，但如果美联储在Jackson-Hole明确降息，预期 **美元指数短期跌 1.5-2%**，黄金上行空间至 **2,200-美元/盎司**（Yicai）。  
                        - 这将直接影响 **跨境资本流向**，尤其是新兴市场资产的资金回流风险。

                        4. **政策框架的微调**  
                        - Powell 暗示 **平均通胀目标的“奶酪”** 可能在 **2027-年前** 进行**容忍上限提升至 2.5%** 的微调，保持 2% 的核心目标不变（新华网）。  
                        - 此举意在为 **未来可能更宽松的利率路径** 留出弹性。

                        5. **投资策略要点**  
                        - **若降息（25-bp）实现**：科技、半导体、REITs、可再生能源板块或出现 **5-8%** 的短期上涨潜力。  
                        - **若保持鹰派或仅暗示审慎**：防御性板块（公用事业、消费必需品）预计相对 **抗跌 2-3%**，可作为 **波动期间的避险仓位**。  
                        - **杠铃策略**仍然适用：在**高增长/高风险**的成长板块保持适度敞口，同时在**低波动/防御**板块设置防护。

                        > **关键时间节点**  
                        > - **北京时间 2025-08-22 22:00**，Powell 正式演讲开始。  
                        > - **8月21日**，美联储会议纪要公布（核心议题：通胀与就业的最新评估）。  
                        > - **8月23-24日**，全球主要经济体（英国、欧元区、日本）将陆续发布 **PMI、CPI** 数据，需重点关注与美联储信号的叠加效应。

                        ### 推荐后续跟踪

                        | 关注事项 | 数据来源 | 更新频率 |
                        |----------|----------|----------|
                        | 美联储官方讲话稿 & 会议纪要 | Fed 官网 / Caixin Global | 每次会议后 1-2 天 |
                        | 美国核心CPI、PCE、就业数据 | Bloomberg / Yicai Global | 月度 |
                        | 全球主要央行利率决议 | Xinhua News (财经) / Reuters | 每周 |
                        | 市场对降息预期的期权隐含波动率 | CME / 东方财富股吧 | 实时 |
                        | 投资者情绪（ETF 撤/进） | 雪球、东方财富 | 实时 |

                        以上信息可直接用于填补原文中“缺失或不完整”的细节，使文章在 **数据来源、概率分析、全球联动** 三个维度上更加权威、完整。"""]
        roles=["测试达人1","测试达人2","测试达人3"]
        titles=["title1"," title2","title3"]
        # 配置参数
        FOLDER_TOKEN = getenv("FEISHU_FOLDER_TOKEN")
        APP_ID = getenv("FEISHU_APP_ID")
        APP_SECRET = getenv("FEISHU_APP_SECRET")
        # 示例：实际业务应先走 OAuth 获取 tenant_access_token
        tenant_access_token = get_refresh_app_access_token(APP_ID, APP_SECRET)
        # 执行上传
        result = upload_imitate_to_feishu_simple2(
            folder_token=FOLDER_TOKEN,
            theme="测试测试test",
            roles=roles,
            origin_article="原始文章",
            imitate_contents=sample_contents,
            app_id=APP_ID,
            app_secret=APP_SECRET,
            tenant_access_token=tenant_access_token
        )

        print("上传结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"上传失败: {str(e)}")
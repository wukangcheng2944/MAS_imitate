# 代码文件结构说明（保存版）  
## 1. 全流程主入口：`imitate.py`  
- 输入：文章正文或视频分享链接（哔哩哔哩/抖音/小红书/直链/YouTube-仅提取直链）。
- 流程：链接解析 → 转录（可选）→ 文本纠错 → 多角色仿写 → 本地输出。
- 关键：基于 `langgraph` 编排、`langchain` 客户端（OpenAI 兼容），支持流式输出与多回合代理。

## 2. 视频转文字：`v2t.py`
- 核心职责：将输入链接解析为公网直链，调用 DashScope `paraformer-v2` 进行异步批量转写，随后用 LLM 做全文纠错。
- 关键函数：
  - `transform_bilibili_url(url)`：调用 `link_parser/BiliLink_main/quick_convert.py` 将 B 站分享链接转公网直链。
  - `get_one_text_url(url)`/`get_text_url(url_list)`：提交 ASR 任务并轮询；返回转写结果 JSON URL。
  - `extract_text(transcrip_url)`：下载转写 JSON，提取 `file_url` 与 `text`。
  - `correct_text(llm, text_dict)`：对转写文本进行全文纠错。
  - `v2t(llm, url_list)`：端到端并行处理多个链接，返回纠错后的文本列表。
  - `_resolve_one_url(url)`：按平台分流解析（B 站/抖音/小红书/YouTube/直链）。

## 3. 链接解析模块：`link_parser/`
- `BiliLink_main/`：B 站解析与转换
  - `function.py`：
    - `parse_bilibili_share_link(url)`：从各种分享样式中解析 `bvid/p/t`，含短链 `b23.tv` 自动展开与“标题+链接”清洗。
    - `BiliAnalysis`/`getVideoInfo`：查询 `cid`、获取真实播放 URL，并随机切换 B 站 CDN。
    - `get_video_public_url(url)`：对外主入口，返回 `{bvid,page,public_url,time}`。
  - `quick_convert.py`：`quick_convert(url)` 返回公网直链（字符串），可脚本/模块调用。
  - `bilibili_link_converter.py`：交互/命令行工具，返回结构化结果并格式化打印。
  - `wbi.py`：B 站接口签名辅助。
- 其他解析：
  - `direct_link_extractor.py`：YouTube 直链提取（`yt-dlp`），带 UA/Referer 策略与格式筛选。
  - `douyin_parse.py`：抖音分享文案解析，返回视频直链或图文图片直链列表。
  - `xhs_extract_links.py`：小红书作品解析，支持 xhslink 短链与 explore 链接，返回视频/图片直链。
  - `youtube_url_extract_single_url.py`：YouTube 单链接提取（供 `v2t.py` 调用）。

## 4. 运行方式与导入建议
- 包方式运行（推荐）：确保当前目录在 `MAS/test/MAS_version_save` 的同级目录结构下
  - B 站演示：`python -m link_parser.bilibili_extract`
- 直接脚本运行：在对应目录执行 `python xxx.py`。
- 模块导入（示例）：
  - `from link_parser.BiliLink_main.quick_convert import quick_convert`
  - `public_url = asyncio.run(quick_convert(url))`

## 5. 依赖与环境
- 依赖（见 `requirements.txt` 保存版）：包含 `langsmith/pandas/openpyxl/weasyprint/reportlab` 等在保存版脚本中引用或预留的能力。
- Python 版本：建议 3.12+（推荐 3.13）。
- 多媒体工具：部分站点解析可能需要系统 `ffmpeg`（Windows: choco/scoop；Linux: apt/yum；macOS: brew）。

## 6. 注意事项
- B 站“标题+短链”输入已做清洗；自行调用解析函数时亦建议先正则提取首个 URL。
- 保存版脚本中启用了或预留了 LangSmith 追踪（`LANGCHAIN_TRACING_V2` 等）；按需在 `.env` 中配置或注释。
- 高并发时请关注 API 速率限制，合理调整 `Semaphore` 并发度与重试策略。

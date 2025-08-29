### MAS 文案仿写与视频转文字（保存版）

本目录为保存版，含更完整的示例与可选功能（如 LangSmith 追踪、Excel 导出等）。提供从视频链接转文字、文本纠错与总结、以及基于多角色模板的文案仿写与本地保存能力/飞书保存。

- 主要脚本：
  - `v2t.py`：将视频链接转录为文本（支持哔哩哔哩/抖音/小红书/直链；YouTube 受阿里云外网 CDN 限制，仅能提取直链，当前无法执行转写），并可用 LLM 进行纠错，可扩展导出至 `v2t_result/`。
  - `imitate.py`：基于 `template_list.py` 中的多角色模板对输入的文章或视频转写结果进行多轮仿写，可保存到本地或上传至飞书（需在 `.env` 配置）。
  - `template_list.py`：角色与模板库（不可用 f-string，模板中直接书写“对上一条内容进行修改”等提示）。
  - `text_summary.py`：对文本生成主题、摘要与大纲的异步工具函数（可在其他流程中复用）。

### 运行环境（Windows / Linux / macOS）

要求：
- Python 3.12+（建议 3.13）

安装方式三选一：

1) 使用 uv（推荐）

安装 uv：
- Windows（PowerShell）二选一：
  ```powershell
  pip install uv
  或
  powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- Linux/macOS（bash/zsh）二选一：
  ```bash
  pip install uv
  或
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

创建并激活虚拟环境：  
**首先cd到脚本文件夹所在目录**
- Windows（PowerShell）：
  ```powershell
  uv venv
  .\.venv\Scripts\Activate.ps1
  ```
- Linux/macOS（bash/zsh）：
  ```bash
  uv venv
  source .venv/bin/activate
  ```

安装依赖：
```bash
uv pip install -r requirements.txt
```

2) 使用 pip

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
```

3) 使用 conda（用于管理 Python 版本；依赖仍用 pip 安装）

```bash
conda create -n mas_save_py313 python=3.13 -y
conda activate mas_save_py313
pip install -r requirements.txt
```

### 环境变量与 .env 配置

所有脚本都会 `load_dotenv()`，支持在本目录放置 `.env` 文件（建议将现有的 `.env copy` 复制为 `.env` 并补齐值）。至少建议配置：

```ini
# LangSmith（可选，用于追踪；保存版脚本中示例已包含开关）
LANGSMITH_API_KEY=...

# OpenRouter（用于 LLM 纠错与部分对话）
OPENROUTER_API_KEY=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# DashScope（ASR 与/或 Qwen 对话）
DASH_SCOPE_API_KEY=...
DASH_SCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1


```

注意：
 - `v2t.py` 使用 DashScope ASR（`paraformer-v2`）转写，随后用 `OPENROUTER_*` 的 LLM 做纠错。
 - `imitate.py` 中默认仿写模型使用 `OPENROUTER_*`，可依 `.env` 切换。
 - 视频链接必须为公网可访问链接；脚本会自动解析哔哩哔哩/抖音/小红书等地址为可转写直链。YouTube 场景受阿里云外网 CDN 限制，目前仅能提取直链，无法执行转写。
 - 某些站点的多媒体解析可能需要系统安装 `ffmpeg`（Windows: choco/scoop；Linux: apt/yum；macOS: brew）。

### OpenAI 兼容 API 与更换 Key 指南

本项目内所有 LLM 客户端均采用“OpenAI 兼容”调用方式（即 `base_url + /v1/...` + `Authorization: Bearer <API_KEY>`）。若需要更换供应商或 Key：

- 只需在 `.env` 中调整对应的 `base_url` 与 `API_KEY`，并确保使用该供应商的模型名：
  - 更换纠错/仿写所用的 OpenAI 兼容服务：
    ```ini
    # 例：使用 OpenRouter（默认示例）
    OPENROUTER_API_KEY=sk-xxx
    OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

    # 切换到其他 OpenAI 兼容服务（示例）
    # OPENROUTER_API_KEY=your_other_key
    # OPENROUTER_BASE_URL=https://api.together.xyz/v1
    # OPENROUTER_BASE_URL=http://localhost:8000/v1   # vLLM/本地兼容服务
    ```
  - 更换 DashScope（Qwen 的 OpenAI 兼容入口）：
    ```ini
    DASH_SCOPE_API_KEY=dashscope_xxx
    DASH_SCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
    ```

- 若供应商变更，需要同步修改脚本中的模型名：
  - `imitate.py`：查找 `ChatOpenAI(... model_name=..., base_url=..., api_key=...)` 的位置，替换为供应商对应模型，例如：`google/gemini-2.5-flash-lite` → `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`（以实际可用模型为准）。
  - `v2t.py`：`ChatOpenAI(model=...)` 同理替换模型名；ASR 仍走 DashScope 的 `paraformer-v2`。

提示：如供应商提供 OpenAI 兼容入口（典型为 `.../v1`），即可按上述方式切换；否则需按该供应商的 SDK/路由规范修改代码。

### 脚本功能与用法

#### 1) v2t.py：视频转文字与纠错

交互式用法：
```bash
python v2t.py
# 依提示逐条粘贴视频链接，回车结束后开始转写
```

流程概览：
- 解析输入链接 → 获取可转写直链（YouTube 仅能提取直链，无法转写） → DashScope `paraformer-v2` 异步批量转写 → 拉取转写 JSON → 用 LLM 全文纠错 → `v2t_result/` 下导出 `v2t_result.xlsx`。

输出（可选示例）：
- `v2t_result/v2t_result.xlsx`（两列：`file_url`、`text`）。

#### 2) imitate.py：多角色模板仿写与保存/上传

交互式用法：
```bash
python imitate.py
# 先选择角色模板（直接回车默认全选），随后输入“文章正文”或“视频链接”
```

流程概览：
- 若输入为链接：先调用 `v2t.py` 的无摘要接口转写为文本；
- 基于 `template_list.py` 中的所选角色，为每个角色构建多节点 LangGraph，逐步仿写；
- 自动生成主题；
- 输出到本地 `result_store/主题.txt`、`result_store/主题.md`；

输出：
- `result_store/<主题>.txt` 与 `result_store/<主题>.md`（含原文与各角色仿写文本）。

#### 3) template_list.py：角色模板库

- 模板变量形如：`{"name": "角色名", "template": [模板内容1, 模板内容2, ...]}`。
- 文件末尾 `role_list = [...]` 为可选角色清单，`imitate.py` 的交互选择依赖该列表顺序。
- 新增模板后需将变量名添加进 `role_list`。

#### 4) text_summary.py：异步总结工具

提供两个函数：
- `summarize_one_text(llm, dict_item) -> dict`
- `summarize_all_text(llm, final_result_list:list) -> list`

最小示例：
```python
from langchain_openai import ChatOpenAI
from text_summary import summarize_all_text

llm = ChatOpenAI(
    model="google/gemini-2.5-flash-lite",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url=os.getenv("OPENROUTER_BASE_URL"),
)

items = [{"text": "待总结的文本一"}, {"text": "待总结的文本二"}]
results = asyncio.run(summarize_all_text(llm, items))
```

### 各平台注意事项

- Windows：
  - 建议使用 PowerShell 运行激活脚本；如遇到 `ExecutionPolicy` 限制，可在当前会话执行：`Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process`。
  - 若涉及 `yt-dlp` 的多媒体解析，某些站点可能依赖系统 `ffmpeg`（按需安装）。
- Linux：
  - 确保存在可写目录用于缓存与导出（本目录会自动创建 `result_store/` 与 `v2t_result/`）。
- macOS：
  - 如使用 zsh，请在终端中执行 `source .venv/bin/activate` 激活虚拟环境。

### 运行方式与导入

- 包方式运行（推荐）：确保当前目录在 `MAS/test/MAS_version_save` 的同级目录结构下
  ```bash
  python -m link_parser.bilibili_extract
  ```
- 模块调用：
  ```python
  from link_parser.BiliLink_main.quick_convert import quick_convert
  url = "https://www.bilibili.com/video/BV..."
  public_url = asyncio.run(quick_convert(url))
  ```

### 常见问题（FAQ）

- 转写失败或为空：
  - 确认链接为公网可访问；
  - 检查 `DASH_SCOPE_API_KEY` 是否有效；
  - 等待一段时间后重试（ASR 任务是异步轮询）。
- LLM 纠错或仿写无响应：
  - 检查 `OPENROUTER_API_KEY` 与 `OPENROUTER_BASE_URL`；
  - 网络需可访问对应 API。

### 目录与产物

- 输入：交互中粘贴的视频链接或原始文章
- 主要产物：
  - `v2t_result/v2t_result.xlsx`
  - `result/summary_result/<主题>.json`
  - `result/imitate_result/<主题>.txt`、`result/imitate_result/<主题>.md`

### 开发提示

- 若增添新角色模板：在 `template_list.py` 中新增模板变量，并将其变量名加入 `role_list`。
- 如需自定义仿写模型/纠错模型：调整 `imitate.py`/`v2t.py` 中的 `ChatOpenAI` 初始化参数或对应环境变量。



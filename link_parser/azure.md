# Azure 单 URL 异步转写 — 纯文本输出（README）

本仓库（或文件夹）包含一个用于 **将公网直链音/视频转写为纯文本** 的异步脚本：
- 脚本：`azure_plain_transcribe_async_single.py`
- 功能：提交给 Azure AI Speech 的 **Batch Transcription**，轮询完成后**仅打印纯文本到 stdout**（不落盘、不生成字幕）。
- 适用：服务器/CLI 批处理、作为库函数在你自己的协程中调用。

---

## 目录
- [快速开始](#快速开始)
- [你需要准备](#你需要准备)
- [安装依赖](#安装依赖)
- [用法](#用法)
  - [命令行模式（单 URL）](#命令行模式单-url)
  - [作为库函数调用](#作为库函数调用)
- [参数说明](#参数说明)
- [URL 检查清单](#url-检查清单)
- [输出与退出码](#输出与退出码)
- [常见问题 FAQ](#常见问题-faq)
- [故障排查](#故障排查)
- [最佳实践](#最佳实践)
- [安全与合规](#安全与合规)
- [变更记录](#变更记录)
- [许可](#许可)

---

## 快速开始

```bash
# 1) 配置凭据（也可用 --key/--region 传参）
export AZURE_SPEECH_KEY="你的Key"
export AZURE_SPEECH_REGION="eastus"

# 2) 安装依赖
pip install httpx python-dotenv

# 3) 运行（示例：中文识别）
python azure_plain_transcribe_async_single.py "https://example.com/video.mp4" --locale zh-CN
成功时，脚本会只向标准输出打印整段转写文本（纯文本，无额外装饰）。

你需要准备
一个 Azure 订阅，以及在门户中创建的 Speech（AI Speech）资源

获取 密钥（Key） 和 区域（Region）（端点形如 https://<region>.api.cognitive.microsoft.com）。

一条 可被 Azure 后端直接下载 的媒体直链（HTTP/HTTPS）

不能需要登录/Cookie/跳转脚本；不支持流媒体播放清单（如 .m3u8/DASH）。

可联网的运行环境（Python 3.8+）。

安装依赖
bash
复制代码
pip install httpx python-dotenv
python-dotenv 可选，仅为方便从 .env 读取 AZURE_SPEECH_KEY、AZURE_SPEECH_REGION。

用法
命令行模式（单 URL）
bash
复制代码
# 基本用法
python azure_plain_transcribe_async_single.py "<你的直链>" --locale zh-CN

# 指定名称、TTL（结果在 Azure 托管的保留时间）、更长轮询超时：
python azure_plain_transcribe_async_single.py "<你的直链>" \
  --locale zh-CN \
  --name "my-job" \
  --ttl 48 \
  --max-minutes 360

# 从命令行传入 key/region（不使用环境变量）
python azure_plain_transcribe_async_single.py "<你的直链>" \
  --locale zh-CN \
  --key "xxxxx" \
  --region "eastus"
标准错误（stderr）会打印进度日志（例如 [submitted] ...、[status] Running）。
如果不想看到日志，请加 --quiet。

作为库函数调用
python
复制代码
import asyncio
from azure_plain_transcribe_async_single import transcribe_url

async def main():
    key = "你的Key"
    region = "eastus"
    url = "https://example.com/a.mp4"
    text = await transcribe_url(
        key=key,
        region=region,
        url=url,
        locale="zh-CN",       # 语言地区，如 en-US / zh-CN
        name="job-1",
        ttl_hours=48,
        poll_interval=5.0,
        max_minutes=360,
        http2=True,
        log_status=False,     # 关闭进度日志
    )
    print(text)

asyncio.run(main())
参数说明
位置参数

url：单个媒体直链（必填）

可选参数

--locale：语言/地区（默认 zh-CN），例如 en-US

--name：显示名（默认 single-url-job）

--ttl：Azure 端结果存活时间（小时），默认 48（范围大致 6~744）

--interval：轮询间隔秒，默认 5.0

--max-minutes：最大轮询时长（分钟），默认 360

--no-http2：禁用 HTTP/2

--quiet：静默进度日志（stderr）

--key：Azure Speech 资源 Key（默认读 AZURE_SPEECH_KEY）

--region：Azure 区域（默认读 AZURE_SPEECH_REGION，如 eastus）

代码内置 REST API 版本：2024-11-15（可按需调整）。

URL 检查清单
✅ 直接 GET 可下载的 文件直链（HTTP/HTTPS）

❌ 需要登录/签名 Cookie/动态 JS 的链接

❌ 流式播放清单（.m3u8/DASH）

✅ 常见格式：wav, mp3, m4a/aac, flac, ogg/opus, webm，以及含音轨的视频容器（如 mp4）

实际可支持范围取决于后端编解码/容器解析能力；推荐无损或高码率音频以提升识别质量。

输出与退出码
标准输出（stdout）：仅包含纯文本的整段转写结果。

退出码

0：成功

2：缺少 key/region 等必需参数

其他非零：HTTP/API/超时等异常（stderr 会含错误信息）

常见问题 FAQ
Q1：能不能识别多语言混说？
A：脚本示例使用固定 --locale。若你的素材混合多语言，建议在上游做分段/语言识别，或在 Azure 端使用支持自动语种识别的设置（需要改造请求属性或改用实时/其他接口）。

Q2：能否区分说话人（diarization）？
A：为“纯文本输出”保持最简，示例未开启说话人分离。如有需要，可修改请求属性开启 diarizationEnabled 并在结果解析时输出带说话人标签的文本。

Q3：为什么长时间显示 Running？
A：批量转写是异步队列式任务，长音频/高并发时等候较久属正常。可适当提高 --max-minutes 与 --interval，或并行拆分任务在你自己的上层脚本中调度。

Q4：YouTube 网页链接可以直接用吗？
A：不行。必须是后端能直接下载的媒体文件直链。YouTube 页并非直链，且通常需要 Cookie/签名。如果你的业务允许，先将媒体下载到受控存储，再提供直链或 GCS/Blob URI（含授权）。

故障排查
400/415：检查 --locale 是否有效、媒体格式是否支持。

401/403：Key/Region 不匹配或权限不足；确认使用的是 Speech 资源的密钥与区域。

404：任务 ID 不存在（异常中断/清理），或区域端点写错。

429：配额/并发受限；降低并发、延长轮询间隔，或申请配额提升。

5xx：服务端暂时性错误；建议稍后重试。

一直 Running：素材过长或排队；增大 --max-minutes，或将长音频离线切片后分别提交。

最佳实践
音频优先：相同内容下，优先提交纯音频（如 wav/flac）而非整段视频，速度更快、成功率更高。

合理超时：长素材提高 --max-minutes，避免提前超时退出。

幂等与重试：上层调用建议实现失败重试、超时取消、以及结果落盘（若你需要存档）。

监控：将 stderr 日志汇聚到你的监控系统，便于追踪任务状态与错误分布。

安全与合规
敏感数据：若素材包含敏感内容，避免公开互联网上的匿名直链。可将文件存储在受控对象存储（如 Azure Blob）并使用短期 SAS 或托管身份授权的容器。

TTL：--ttl 控制 Azure 端结果存活时间；取回后如不再需要，建议删除任务或等待自动清理。

日志：生产环境中避免将密钥/敏感 URL 打到日志。
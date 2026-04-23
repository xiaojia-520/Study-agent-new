# Study Agent

Study Agent 是一个面向课堂学习场景的实时语音学习助手。系统支持课堂语音实时转写、按课程和课次保存学习记录、基于课堂内容进行 RAG 检索问答，并提供历史回顾、转写精修、课堂总结和习题生成等能力。

项目当前主要面向本地部署和演示场景，适合用于课堂录音转写、课程复习、知识追问和学习资料沉淀。

## 功能概览

- 实时语音转写：浏览器采集麦克风音频，通过 WebSocket 发送到后端，由 FunASR / Paraformer 完成中文语音识别。
- 课堂会话管理：每次录音自动创建 session，并绑定 course_id、lesson_id、subject 等上下文信息。
- 转写持久化：实时转写结果同时写入 SQLite 和 JSONL，方便前端查询、后续索引和离线处理。
- 实时 RAG 入库：最终转写片段会缓冲写入 Qdrant 向量库，支持准实时课堂内容检索。
- 课堂问答：前端可对当前课程或历史课程提问，后端按课程、课次、历史范围或全局范围进行检索。
- 带引用回答：开启 LLM 后，可基于检索片段生成带上下文依据的回答。
- 多模态课堂素材解析：支持上传 PDF、PPT、Word、HTML 和图片，经 MinerU 精准解析后抽取 Markdown/结构化文本并写入 RAG。
- 课件与转写联合检索：课件页、图片解析文本和实时语音转写会带 source_type、文件名、页码等元数据进入同一个 Qdrant 知识库。
- 历史回顾：支持查看历史课程、历史问答、原始转写和 LLM 精修后的转写。
- 学习生成：支持基于课堂转写生成课程总结、复习要点、重要概念和测验题。
- 本地优先：Embedding 模型、Qdrant 存储、ASR 模型均支持本地运行，便于离线演示和数据留存。

## 技术栈

后端：

- Python 3.10+
- FastAPI
- WebSocket
- FunASR / Paraformer
- Silero VAD
- LlamaIndex
- Qdrant
- SentenceTransformers
- SQLite
- MinerU API（用于课件、文档和图片解析）

前端：

- Vue 3
- TypeScript
- Vite
- Pinia
- Tailwind CSS

数据与模型：

- 语音识别模型：FunASR Paraformer 中文模型
- VAD 模型：FSMN VAD / Silero VAD
- 标点模型：CT-Transformer punctuation
- Embedding 模型：BAAI/bge-small-zh-v1.5
- LLM：OpenAI 兼容接口，默认可配置 DeepSeek
- 文档解析：MinerU 精准解析 API，可配置 `pipeline` / `vlm` 模式

## 项目结构

```text
.
├── config/                         # 全局配置和 Prompt
│   ├── settings.py                  # 路径、模型、RAG、LLM 等配置
│   └── prompts.py                   # RAG、总结、测验、转写精修 Prompt
├── scripts/                         # RAG 构建、查询、评测、模型下载脚本
├── src/
│   ├── application/                 # RAG 服务、语音流水线、离线转写
│   ├── core/                        # ASR、音频、知识库等核心逻辑
│   └── infrastructure/              # 模型加载、日志、存储适配
├── tests/                           # 后端单元测试和 RAG 测试夹具
├── web/
│   ├── backend/                     # FastAPI 后端入口和业务接口
│   └── frontend/                    # Vue 前端项目
├── models/                          # 本地模型目录，需通过脚本下载
├── data/                            # SQLite、转写、素材、MinerU 结果、Qdrant 本地数据
├── requirements-rag.txt             # Python 依赖
├── setup_model.bat                  # Windows 模型下载脚本
└── README_RAG.md                    # RAG 子模块说明
```

## 环境要求

基础环境：

- Windows 10/11、macOS 或 Linux
- Python 3.10+
- Node.js 20.19+ 或 22.12+
- npm
- Git

建议环境：

- 内存 16GB 以上
- 有独立显卡更好，但不是必须
- 浏览器使用 Chrome / Edge
- 本地演示时建议使用稳定网络，用于首次下载模型和调用 LLM API

可选依赖：

- FFmpeg：用于部分音视频文件处理场景
- CUDA 版本 PyTorch：如果需要 GPU 加速，可按机器环境单独安装对应版本

## 快速开始

以下命令默认在项目根目录执行。

### 1. 创建 Python 虚拟环境

PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
```

如果 PowerShell 不允许激活脚本，可先执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 2. 安装 Python 依赖

```powershell
python -m pip install -r requirements-rag.txt
python -m pip install huggingface_hub modelscope pytest
```

`requirements-rag.txt` 包含后端运行所需的主要依赖；`huggingface_hub` 和 `modelscope` 用于下载本地模型；`pytest` 用于运行测试。

### 3. 下载本地模型

Windows 可以直接执行：

```powershell
.\setup_model.bat
```

或者手动执行：

```powershell
python scripts/setup_models.py
```

脚本会下载并放置以下模型：

- `models/embedding/bge-small-zh-v1.5`
- `models/asr/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch`
- `models/vad/speech_fsmn_vad_zh-cn-16k-common-pytorch`
- `models/punc/punc_ct-transformer_cn-en-common-vocab471067-large`

如果需要使用前端里的 `paraformer-zh-streaming` 或 `paraformer-zh-streaming-2pass` 模式，还需要准备在线模型：

```text
models/asr/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online
```

可从 ModelScope 下载 `damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online` 到该目录。

### 4. 配置环境变量

项目默认读取 `config/.env`，也可以直接使用系统环境变量覆盖配置。

建议新建或修改 `config/.env`：

```env
# RAG / Qdrant
RAG_QDRANT_PREFER_LOCAL=true
RAG_QDRANT_COLLECTION=speech_transcript_chunks
RAG_REALTIME_INDEXING_ENABLED=true
RAG_REALTIME_FLUSH_RECORDS=3
RAG_REALTIME_FLUSH_CHARS=300
RAG_REALTIME_FLUSH_INTERVAL_SECONDS=20

# LLM，可选。不开启时仍可使用检索结果，但不会生成综合回答。
RAG_ENABLE_LLM=true
RAG_LLM_PROVIDER=deepseek
RAG_LLM_MODEL=deepseek-chat
RAG_LLM_API_KEY=你的_API_KEY
RAG_LLM_API_BASE=https://api.deepseek.com
RAG_LLM_TEMPERATURE=0.1
RAG_LLM_MAX_TOKENS=512

# MinerU，多模态课堂素材解析，可选。
# 不配置时实时语音、转写和普通 RAG 仍可使用，但无法上传课件解析。
MINERU_API_TOKEN=你的_MINERU_API_TOKEN
MINERU_MODEL_VERSION=vlm
MINERU_LANGUAGE=ch
MINERU_ENABLE_FORMULA=true
MINERU_ENABLE_TABLE=true
MINERU_IS_OCR=false
MINERU_AUTO_INDEX_ENABLED=true
```

注意：

- 不要把真实 API Key 提交到 Git 仓库。
- 如果只是演示检索能力，可以设置 `RAG_ENABLE_LLM=false`。
- 使用 OpenAI 兼容服务时，保持 `RAG_LLM_PROVIDER=openai` 或 `deepseek`，并配置对应的 `RAG_LLM_API_BASE`。
- `MINERU_MODEL_VERSION=vlm` 更适合包含图表、公式和复杂版式的课件；如需更轻量的解析可按 MinerU 官方文档切换为其他模型。
- 上传 `.html` 文件时，后端会自动使用 MinerU HTML 解析模式。
- MinerU API Key 属于敏感凭据，不要写入代码或提交到仓库。

## 本地开发部署

### 1. 启动后端

在项目根目录执行：

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn web.backend.main:app --host 127.0.0.1 --port 8000 --reload
```

启动成功后访问：

```text
http://127.0.0.1:8000/
```

正常返回：

```json
{"status":"ok"}
```

后端启动时会初始化 SQLite，并加载 ASR 模型。首次加载模型可能较慢。

### 2. 启动前端

打开新的 PowerShell 窗口：

```powershell
cd web\frontend
npm install
npm run dev
```

默认访问：

```text
http://127.0.0.1:5173/
```

如果后端地址不是 `http://127.0.0.1:8000`，可在 `web/frontend/.env.local` 中配置：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

### 3. 使用流程

1. 打开前端首页。
2. 允许浏览器使用麦克风。
3. 输入课程名称。
4. 选择 ASR 模型。
5. 点击“开始录音”。
6. 说话后查看实时转写结果。
7. 如需结合课件问答，可在“课堂素材”区域上传 PDF、PPT、Word、HTML 或图片。
8. 前端会显示素材状态，后端会提交 MinerU 解析、下载解析结果，并将解析出的文本按页写入 RAG。
9. 在问答区域输入问题，系统会基于当前课程转写和已入库课堂素材进行检索和回答。
10. 停止录音后，可进入“历史回顾”查看课程记录、历史问答和转写精修结果。

### 4. 多模态素材入库流程

上传课堂素材后，后端处理流程如下：

1. 将原文件保存到 `data/assets/{session_id}/`。
2. 在 SQLite 的 `lesson_assets` 表中记录素材状态、文件名、大小、MinerU batch_id、解析结果路径等信息。
3. 调用 MinerU 精准解析 API 申请上传 URL，并将文件上传到 MinerU。
4. 轮询 MinerU 解析状态，完成后下载结果 zip 到 `data/mineru_results/{asset_id}/`。
5. 优先读取 `*_content_list_v2.json` 或 `*_content_list.json`，没有结构化结果时回退读取 `full.md`。
6. 将解析文本按页或 Markdown 段落写入 `transcript_records`，并设置：
   - `source_type=document` / `slide` / `image`
   - `source_file=原文件名`
   - `metadata.asset_id`
   - `metadata.asset_file_name`
   - `metadata.page_no`
   - `metadata.mineru_batch_id`
7. 调用现有 RAG indexing service 写入 Qdrant，与实时语音转写共享同一个检索库。

因此，RAG 中保存的不是原始二进制文件，而是 MinerU 解析后的文本块和元数据。原始文件和 MinerU 输出文件会保存在本地运行目录中，便于后续做引用预览或重新索引。

## 生产或演示部署

当前项目没有内置 Dockerfile，推荐使用“后端服务 + 前端静态构建”的方式部署。

### 方案一：单机演示部署

适用于比赛、答辩、本地机房演示。

1. 在演示机器上安装 Python、Node.js 和依赖。
2. 预先执行 `setup_model.bat` 下载模型。
3. 预先配置 `config/.env`。
4. 后端使用固定端口启动：

```powershell
python -m uvicorn web.backend.main:app --host 0.0.0.0 --port 8000
```

5. 前端开发模式启动：

```powershell
cd web\frontend
npm run dev -- --host 0.0.0.0
```

6. 浏览器访问前端地址，并确保前端 `VITE_API_BASE_URL` 指向后端地址。

这种方式最适合现场演示，调试方便，但不适合作为长期线上服务。

### 方案二：前端静态构建 + 后端 API

构建前端：

```powershell
cd web\frontend
npm install
npm run build
```

构建产物位于：

```text
web/frontend/dist
```

部署方式：

- 后端：使用 `uvicorn`、`gunicorn + uvicorn worker` 或进程管理工具常驻运行。
- 前端：将 `web/frontend/dist` 放到 Nginx、Apache、Caddy 或其他静态文件服务器。
- API：通过 `VITE_API_BASE_URL` 指向后端服务地址。
- WebSocket：反向代理时需要开启 WebSocket 转发。

Nginx 反向代理时需要保留 WebSocket 升级头，示例：

```nginx
location /ws/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}

location /sessions {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
}
```

## 后端接口说明

主要 HTTP 接口：

```text
GET  /                         健康检查
POST /sessions                 创建课堂会话
GET  /sessions                 查看当前后端内存中的会话
GET  /sessions/history         查看历史课程列表
GET  /sessions/history/messages
GET  /sessions/history/transcripts
GET  /sessions/history/refined-transcripts
GET  /sessions/{session_id}/transcripts
GET  /sessions/{session_id}/messages
POST /sessions/{session_id}/assets
GET  /sessions/{session_id}/assets
GET  /sessions/assets/{asset_id}
POST /sessions/{session_id}/query
POST /sessions/{session_id}/summary
POST /sessions/{session_id}/quiz
```

实时音频 WebSocket：

```text
ws://127.0.0.1:8000/ws/audio/{session_id}
```

前端会自动创建 session 并连接 WebSocket，一般不需要手动调用。

素材上传接口使用 `multipart/form-data`：

```text
POST /sessions/{session_id}/assets
form field: file
```

支持的文件类型：

```text
.pdf .doc .docx .ppt .pptx .png .jpg .jpeg .jp2 .webp .gif .bmp .html
```

上传成功后接口会立即返回素材记录，解析和入库在后台继续执行。前端会轮询 `GET /sessions/assets/{asset_id}` 获取状态。

## RAG 脚本

构建索引：

```powershell
python scripts/rag_build_index.py --path data/transcripts/demo_session_for_check.jsonl --recreate
```

检索查询：

```powershell
python scripts/rag_query.py "这节课讲了什么？" --reindex-path data/transcripts/demo_session_for_check.jsonl --recreate
```

启用 LLM 回答：

```powershell
python scripts/rag_query.py "这节课讲了什么？" --with-llm
```

运行 RAG 评测：

```powershell
python scripts/rag_eval.py `
  --cases tests/fixtures/rag_eval_demo_cases.jsonl `
  --reindex-path tests/fixtures/rag_eval_demo_transcript.jsonl `
  --recreate
```

更多 RAG 细节可参考 `README_RAG.md`。

## 测试

安装测试依赖后，在项目根目录执行：

```powershell
python -m pytest -q
```

前端类型检查和构建：

```powershell
cd web\frontend
npm run build
```

常用验证顺序：

1. `python -m compileall -q config src web\backend`
2. `python -m pytest -q`
3. `cd web\frontend`
4. `npm run build`
5. 启动后端并访问 `/`
6. 启动前端并完成一次录音、提问、历史回顾流程

如果只验证 MinerU 素材解析链路，可先运行：

```powershell
python -m pytest tests/test_lesson_asset_service.py -q
```

## 数据存储

默认数据位置：

```text
data/study_agent.sqlite3              # SQLite 数据库
data/transcripts/                     # 转写 JSONL 文件
data/assets/                          # 上传的课堂素材原文件
data/mineru_results/                  # MinerU 解析结果 zip、Markdown 和 JSON
data/qdrant/                          # Qdrant 本地向量库
logs/                                 # 日志
```

这些目录属于运行时数据，通常不建议提交到 Git。

## 常见问题

### 1. 后端启动很慢

首次启动会加载 ASR、VAD、标点和 Embedding 模型，时间较长是正常现象。演示前建议提前启动并预热。

### 2. 提示模型路径不存在

先执行：

```powershell
.\setup_model.bat
```

并确认 `models/` 下对应模型目录存在且不为空。

### 3. 前端提示无法连接后端

检查：

- 后端是否启动在 `127.0.0.1:8000`
- `web/frontend/.env.local` 中的 `VITE_API_BASE_URL` 是否正确
- 浏览器控制台是否有 CORS、WebSocket 或网络错误

### 4. 浏览器无法录音

检查：

- 浏览器是否允许麦克风权限
- 页面是否通过 `localhost`、`127.0.0.1` 或 HTTPS 访问
- 系统麦克风是否被其他软件占用

### 5. LLM 回答不可用

检查：

- `RAG_ENABLE_LLM=true`
- `RAG_LLM_API_KEY` 已配置
- `RAG_LLM_API_BASE` 可访问
- API Key 余额和权限正常

如果不需要综合回答，可关闭 LLM，仅展示检索片段：

```env
RAG_ENABLE_LLM=false
```

### 6. RAG 检索不到内容

可能原因：

- 当前课程转写内容太少
- 实时索引还未 flush 到 Qdrant
- Qdrant 本地数据目录被清空
- 查询范围选错，例如只查当前课次但问题属于历史课次

可停止录音后再查询，或使用 RAG 脚本手动重建索引。

### 7. 课堂素材上传后一直解析失败

检查：

- `MINERU_API_TOKEN` 是否已配置且有效
- 网络是否能访问 `https://mineru.net`
- 文件大小是否超过 MinerU 精准解析限制
- 文件格式是否在支持列表中
- `data/assets/` 和 `data/mineru_results/` 是否有写入权限

### 8. 课件解析成功但问答搜不到

检查：

- 素材状态是否为 `done`
- `lesson_assets.record_count` 是否大于 0
- `MINERU_AUTO_INDEX_ENABLED=true`
- Qdrant 本地目录是否可写
- 问答范围是否选择当前课次或包含该课次的课程范围

课件内容会作为 `source_type=document`、`slide` 或 `image` 的文本记录进入 `transcript_records`，可先通过 `/sessions/{session_id}/transcripts` 查看是否已经写入。

## 参赛演示建议

如果用于比赛或答辩，建议提前准备：

- 一段 3 到 5 分钟的真实课堂语音演示流程
- 一份小型 PDF/PPT/图片课件，用于展示 MinerU 多模态素材解析和入库
- 一份已有历史课程数据，用于展示历史回顾和跨课次追问
- 几个固定问题，用于展示当前课次问答、历史课次问答、总结和测验生成
- 本地模型、Node 依赖、Python 依赖全部预安装
- LLM 和 MinerU API Key 不写入代码仓库，演示机器单独配置

推荐演示顺序：

1. 创建课堂并开始录音。
2. 展示实时转写。
3. 上传课件或图片，展示素材状态从上传、解析到入库。
4. 提问“课件里这个公式/图表和刚才老师讲的内容有什么关系？”展示转写和课件联合 RAG。
5. 提问“刚才讲了哪些重点？”展示 RAG 检索和回答。
6. 停止录音，展示历史记录沉淀。
7. 展示历史课程追问、转写精修、总结或测验生成。

## 安全注意

- 不要提交真实的 `.env`、API Key、数据库、日志和模型文件。
- 演示数据中如包含真实课堂内容，应确认不涉及隐私信息。
- 使用 MinerU 时，上传的课件、图片或文档会发送到 MinerU 云端解析；敏感材料请先脱敏或改用可控环境。
- 如果部署到公网，建议增加鉴权、访问控制、HTTPS 和接口限流。

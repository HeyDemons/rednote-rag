# rednote-rag

> 让小红书收藏，不再吃灰

把小红书的点赞 / 收藏内容，沉淀成一个可检索、可问答、可追溯来源的个人知识库。

<p align="center">
  <img src="./demo.png" alt="rednote-rag demo" width="100%" />
</p>

## What It Does

- Sync Xiaohongshu `likes` and `favorites`
- Cache note details locally
- Extract text from title, body, tags, metadata, and images
- Build a searchable vector index with source grounding
- Chat with your saved content and jump back to the original post

适合这些场景：

- 技术帖归档
- 实习 / 面经整理
- 保研经验沉淀
- 公开课复盘
- 长期知识收藏和回顾

## Highlights

- 小红书登录：支持浏览器 Cookie 导入和二维码登录
- 内容抽取：正文、标签、作者、元信息统一规范化
- 图片 OCR：图文帖中的图片文字也能进入索引
- RAG 检索：支持语义搜索、问答、来源回溯
- 流式回答：前端支持边生成边显示
- 增量同步：支持全量同步、增量同步、失败重试
- 本地优先：SQLite + ChromaDB，本地可控

## Demo

项目工作流：

1. 登录小红书
2. 同步 `likes` / `favorites`
3. 抓取 note 详情并写入本地缓存
4. 抽取正文与 OCR 文本
5. 构建向量索引
6. 检索、问答、回溯来源

## Tech Stack

- Backend: FastAPI
- Frontend: Next.js
- Database: SQLite
- Vector Store: ChromaDB
- LLM / Embedding / OCR: OpenAI-compatible API
- Xiaohongshu integration: `xiaohongshu-cli`

## Quick Start

### 1. Clone

```bash
git clone --recurse-submodules <your-repo-url>
cd rednote-rag
```

如果已经 clone 过：

```bash
git submodule update --init --recursive
```

### 2. Install

```bash
pip install -r requirements.txt
pip install -e provider/xiaohongshu-cli
```

前端依赖：

```bash
cd frontend
npm install
cd ..
```

### 3. Configure

```bash
cp .env.example .env
```

按需配置：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `LLM_MODEL`
- `EMBEDDING_MODEL`
- `OCR_ENABLED`
- `OCR_MODEL`

## Run

启动后端：

```bash
python -m uvicorn app.main:app --reload
```

启动前端：

```bash
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

访问地址：

- Frontend: `http://127.0.0.1:3001`
- API Docs: `http://127.0.0.1:8000/docs`

## Core Features

### 1. Authentication

- `POST /auth/login/browser`
- `POST /auth/login/qrcode`
- `GET /auth/login/qrcode/status/{login_id}`

### 2. Collections

- `GET /collections/list`
- `GET /collections/{source_type}/items`

### 3. Notes

- `POST /notes/{note_id}/cache`
- `GET /notes/{note_id}`
- `GET /notes/{note_id}/content`
- `GET /notes/{note_id}/ocr`

### 4. Knowledge Base

- `GET /knowledge/status`
- `POST /knowledge/sync`
- `GET /knowledge/sync/status/{task_id}`
- `POST /knowledge/search`
- `POST /knowledge/index`

### 5. Chat

- `POST /chat/search`
- `POST /chat/ask`
- `POST /chat/stream`

## OCR and Video Notes

- 图文帖支持 OCR，OCR 文本会进入检索和问答
- 视频帖目前只保留现有文字字段
- 当前不处理视频本身，不做音频转文字

## Sync Strategy

- 全量同步：优先同步正文和索引，默认跳过 OCR，加快首次导入
- 增量同步：正常执行 OCR
- 单条缓存：正常执行 OCR

## Project Structure

```text
rednote-rag/
├── app/
├── frontend/
├── provider/
├── scripts/
├── data/
├── demo.png
└── README.md
```

## Disclaimer

本项目仅供个人学习与技术研究使用。使用者需自行遵守相关平台协议、版权要求与法律法规。

## License

MIT

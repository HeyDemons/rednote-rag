# rednote-rag

> 让小红书收藏，不再吃灰

把小红书点赞 / 收藏，变成可检索、可对话、可追溯来源的**个人知识库**。  
适合：技术帖子 / 实习经验帖 / 保研经历整理 / 公开课复盘 / 知识总结 / 内容归档等。

> OCR · Search · RAG Chat · Source Grounding

---

## ✨ 功能一览

- ✅ 小红书登录（浏览器 Cookie / 二维码）
- ✅ 读取 `likes` / `favorites`
- ✅ 单条 note 详情抓取与本地缓存
- ✅ 正文、标签、作者、元信息规范化
- ✅ 图片 OCR 接入与清洗
- ✅ 向量检索（ChromaDB）
- ✅ RAG 问答
- ✅ 流式问答（SSE）
- ✅ 来源回溯，可跳回原帖
- ✅ 增量同步、快照记录、失败重试
- ✅ 本地 SQLite + ChromaDB 存储
- ✅ Next.js 前端工作台

---

## ⚡ 快速开始（3 步）

1. 安装依赖

如果你是通过 GitHub clone 项目，建议使用：

```bash
git clone --recurse-submodules <your-repo-url>
```

如果已经 clone 过，再执行：

```bash
git submodule update --init --recursive
```

然后安装依赖：

```bash
pip install -r requirements.txt
pip install -e provider/xiaohongshu-cli
```

2. 配置环境变量

```bash
cp .env.example .env
```

按需填写：
- DashScope / OpenAI 兼容接口配置
- Embedding 模型
- OCR 模型
- SQLite / Chroma 路径

3. 启动服务

```bash
python -m uvicorn app.main:app --reload
```

后端地址：
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

前端：

```bash
cd frontend
npm install
npm run dev -- --hostname 127.0.0.1 --port 3001
```

前端地址：
- `http://127.0.0.1:3001`

---

## 🧠 工作流程

1. 登录小红书
2. 同步 `likes` / `favorites`
3. 抓取 note 详情并写入 `note_cache`
4. 提取正文、标签、作者、元信息
5. 对图文 note 做 OCR，并合并到 `normalized_content`
6. 生成 embedding，写入 Chroma
7. 进行检索 / 问答
8. 返回来源，并支持跳回原帖

---

## 🖥️ 当前前端能力

Next 工作台已经支持：

- 登录
- 全量同步 / 增量同步 / 当前标签同步
- 浏览 `我的收藏` / `我的点赞`
- 检索帖子
- RAG 问答
- 流式回答
- 停止生成
- 来源窗口查看与跳转原帖

---

## 🔐 登录说明

当前项目支持两种登录方式：

1. 浏览器 Cookie 导入  
适合本机浏览器已经登录小红书的场景。

2. 二维码登录  
前端会拉起二维码登录流程，扫码后自动创建应用自己的 `session_id`。

底层内容获取依赖：
- `provider/xiaohongshu-cli`

---

## 🔎 OCR / 视频说明

### OCR

开启以下配置后，图文 note 会在抓取时尝试 OCR：

```bash
OCR_ENABLED=true
OCR_MODEL=qwen-vl-ocr-latest
```

OCR 结果会：
- 保存到 `note_cache.ocr_text`
- 参与 `normalized_content`
- 进入向量检索和问答

### 视频

当前**不处理视频本身**，也**不做音频转文字 / ASR**。  
视频帖只保留已有文字字段参与检索和问答。

---

## ⚠️ 同步策略说明

- `全量同步`
  - 默认跳过 OCR
  - 先优先把帖子详情、正文和索引同步进库，提升首次同步速度
- `增量同步`
  - 正常执行 OCR
- `单条缓存`
  - 正常执行 OCR

这意味着：
- 第一次全量同步会更快
- 后续增量或单条处理会把 OCR 逐步补回来

---

## 🧪 诊断脚本

本地向量召回诊断：

```bash
python scripts/query_rag.py "字节 大模型 面经" --k 10 --grouped
```

---

## 🧩 技术栈

- 后端：FastAPI
- 前端：Next.js
- 数据库：SQLite
- 向量库：ChromaDB
- LLM / Embedding / OCR：OpenAI 兼容接口（已验证 DashScope）
- 内容接入：`xiaohongshu-cli`

---

## 📂 目录结构（简版）

```text
rednote-rag/
├── app/                    # 后端逻辑
├── frontend/               # Next 前端工作台
├── data/                   # SQLite / Chroma 数据
├── provider/               # 第三方接入（含 xiaohongshu-cli）
├── scripts/                # 诊断与脚本
└── README.md
```

---

## ✅ 当前可用接口

认证：
- `POST /auth/login/browser`
- `POST /auth/login/qrcode`
- `GET /auth/login/qrcode/status/{login_id}`
- `GET /auth/status`
- `GET /auth/session/{session_id}`
- `POST /auth/logout`

来源与 note：
- `GET /collections/list`
- `GET /collections/{source_type}/items`
- `POST /notes/{note_id}/cache`
- `GET /notes/{note_id}`
- `GET /notes/{note_id}/content`
- `GET /notes/{note_id}/ocr`

知识库：
- `GET /knowledge/status`
- `POST /knowledge/index`
- `POST /knowledge/index/task`
- `GET /knowledge/index/status/{task_id}`
- `POST /knowledge/index/retry/{task_id}`
- `POST /knowledge/sync`
- `GET /knowledge/sync/status/{task_id}`
- `POST /knowledge/sync/retry/{task_id}`
- `POST /knowledge/search`

对话：
- `POST /chat/search`
- `POST /chat/ask`
- `POST /chat/stream`

---

## ⚠️ 免责声明

本项目仅供个人学习与技术研究使用。  
使用者需自行遵守相关平台协议、版权要求与法律法规，不得用于未授权的抓取、传播或商业用途。

---

## 📜 License

MIT

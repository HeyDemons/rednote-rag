# 🧠 rednote-rag

[中文 README](./README.md)

> Turn Xiaohongshu likes and favorites into a searchable, source-grounded personal knowledge base.

<p align="center">
  <img src="./demo.png" alt="rednote-rag demo" width="100%" />
</p>

## ⚙️ Overview

`rednote-rag` turns saved Xiaohongshu content into something you can actually reuse:

- sync `likes` and `favorites`
- extract note text, metadata, and OCR text from images
- build a searchable local knowledge base
- ask questions over your saved content
- trace every answer back to the original note

Good fit for:

- internship and interview notes
- technical posts
- postgraduate recommendation experiences
- course reviews
- long-term knowledge archiving

---

## ✨ Highlights

### 📦 Knowledge-oriented, not collection-oriented

Instead of just exporting saved posts, `rednote-rag` turns them into a reusable knowledge base.

### 🖼️ OCR for image-heavy posts

A lot of useful Xiaohongshu content lives inside images. OCR text is included in both retrieval and chat.

### 🔗 Source-grounded answers

Answers come with source notes, so you can inspect them and jump back to the original post.

### ♻️ Built for long-term use

Supports full sync, incremental sync, and retry workflows.

---

## 🔥 Core Features

- 🔐 Browser-cookie login and QR-code login
- 📥 Sync `likes` / `favorites`
- 📝 Normalize title, body, tags, author, and metadata
- 🖼️ OCR for image notes
- 🔎 Semantic search with ChromaDB
- 💬 RAG chat over saved content
- 🧷 Source traceability and jump-back links
- ⚡ Streaming answers

---

## 🚀 Workflow

1. Log in to Xiaohongshu
2. Sync `likes / favorites`
3. Cache note details locally
4. Extract text and OCR content
5. Build embeddings and vector index
6. Search, ask questions, and inspect sources

---

## ⚡ Quick Start

### 1. Clone

```bash
git clone --recurse-submodules <your-repo-url>
cd rednote-rag
```

If you already cloned the repo:

```bash
git submodule update --init --recursive
```

### 2. Install

```bash
pip install -r requirements.txt
pip install -e provider/xiaohongshu-cli
```

Frontend dependencies:

```bash
cd frontend
npm install
cd ..
```

### 3. Configure

```bash
cp .env.example .env
```

Configure these variables as needed:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `LLM_MODEL`
- `EMBEDDING_MODEL`
- `OCR_ENABLED`
- `OCR_MODEL`

### 4. Run

Backend:

```bash
python -m uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

Access:

- Frontend: `http://127.0.0.1:3001`
- API Docs: `http://127.0.0.1:8000/docs`

---

## 🗂️ API Overview

### 🔐 Auth

- `POST /auth/login/browser`
- `POST /auth/login/qrcode`
- `GET /auth/login/qrcode/status/{login_id}`

### 📚 Collections

- `GET /collections/list`
- `GET /collections/{source_type}/items`

### 📝 Notes

- `POST /notes/{note_id}/cache`
- `GET /notes/{note_id}`
- `GET /notes/{note_id}/content`
- `GET /notes/{note_id}/ocr`

### 🧠 Knowledge

- `GET /knowledge/status`
- `POST /knowledge/sync`
- `GET /knowledge/sync/status/{task_id}`
- `POST /knowledge/search`
- `POST /knowledge/index`

### 💬 Chat

- `POST /chat/search`
- `POST /chat/ask`
- `POST /chat/stream`

---

## 🔎 OCR and Video Notes

- OCR is applied to image notes and included in retrieval and chat
- Video notes currently keep only existing text fields
- No video processing or ASR for now

---

## 🔄 Sync Strategy

- **Full sync**
  skips OCR by default for faster initial import

- **Incremental sync**
  runs OCR normally for daily updates

- **Single-note cache**
  runs OCR normally for important notes

---

## 📁 Project Structure

```text
rednote-rag/
├── app/
├── frontend/
├── provider/
├── scripts/
├── data/
├── demo.png
├── README.md
└── README_EN.md
```

---

## 🧩 Tech Stack

- **Backend**: FastAPI
- **Frontend**: Next.js
- **Database**: SQLite
- **Vector Store**: ChromaDB
- **LLM / Embedding / OCR**: OpenAI-compatible API
- **Content Provider**: `xiaohongshu-cli`

---

## ⚠️ Disclaimer

This project is for personal learning and technical research only. Please comply with platform policies, copyright requirements, and applicable laws.

---

## 📜 License

MIT

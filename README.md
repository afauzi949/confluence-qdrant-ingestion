# Confluence → Qdrant ingest

workflow n8n `scheduler` (`MJb0dO56TIVpg0ew`). Workflow itu tetap source of truth
untuk skema payload dan urutan langkah.

## Alur (1x per hari)

1. `GET /rest/api/search` (CQL `lastmodified >= now("-3d")`, space `II`) → id halaman termodifikasi
2. `GET /api/v2/spaces/{id}/pages?status=trashed` → id halaman trashed
3. Purge Qdrant semua `pageId` trashed (`match.any`)
4. Tiap halaman modifikasi (kecuali yang trashed): fetch `GET /api/v2/pages/{id}?body-format=export_view`
   → Convert API (Docling) → chunk 6000/200 → embedding per chunk → purge `pageId` → upsert
5. Halaman yang 404 / bukan `current` hanya dipurge, tidak di-ingest

Sparse BM25 dihitung oleh Qdrant (inference object `qdrant/bm25`, `options.avg_len`), sama seperti workflow.

Payload per point: `text, chunk_index, token_count, word_count, pageId, title, spaceKey, url, createdAt, lastModified`.
Point id: UUID4 acak (sama seperti workflow).

## Beda dengan workflow n8n (sengaja)

- `get pages data` + `Fetch Page Body` digabung jadi satu request.
- Purge halaman modifikasi dilakukan **setelah** fetch/convert/chunk/embed sukses, tepat sebelum upsert.
  Di n8n purge jalan dulu; kalau langkah berikutnya gagal, vektor lama sudah hilang. Hasil akhir tetap sama.
- Halaman yang gagal dicatat, run lanjut ke halaman berikutnya, exit code 1 pada `--once`.
- Pagination memakai `_links.next` dan menangani beda format v1 (`/rest/api/...`) vs v2 (`/wiki/api/v2/...`).

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env     # isi CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN, EMBEDDING_API_KEY, QDRANT_API_KEY
```

## Menjalankan

```bash
.venv/bin/python -m ingest --dry-run   # hanya daftar id trashed/modified, tidak menulis apa pun
.venv/bin/python -m ingest --once      # 1x sync sekarang
.venv/bin/python -m ingest             # scheduler harian (SCHEDULE_HOUR/MINUTE/TIMEZONE)
```

Contoh systemd: `ExecStart=/path/.venv/bin/python -m ingest`, `WorkingDirectory=/path`, `Restart=always`.

## Tes

```bash
.venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest
```
Tes memakai mock HTTP (tanpa jaringan): skema payload, urutan purge→upsert, trashed tidak di-ingest,
pagination, dry-run, kegagalan per halaman.

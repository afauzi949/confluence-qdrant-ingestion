# Confluence → Qdrant ingest

Sinkronisasi harian halaman Confluence ke Qdrant (hybrid: dense + sparse BM25).
Mendukung **satu atau banyak space** dalam satu run.

## Alur (1x per hari)

1. `GET /api/v2/spaces?keys=II,ABC` → resolve space key menjadi space id.
   Gagal keras bila ada key yang tidak ketemu / tidak punya akses, supaya salah ketik
   tidak membuat sebuah space terlewat diam-diam.
2. `GET /rest/api/search` dengan CQL `space in ("II","ABC") AND lastmodified >= now("-1d")`
   → id halaman yang berubah.
3. `GET /api/v2/spaces/{id}/pages?status=trashed` untuk tiap space → id halaman trashed (digabung).
4. Purge Qdrant semua `pageId` trashed (`match.any`).
5. Tiap halaman yang berubah (kecuali yang trashed):
   `GET /api/v2/pages/{id}?body-format=export_view` → Convert API (Docling) → chunk 6000/200
   → embedding per chunk → purge `pageId` → upsert.
6. Halaman yang 404 / statusnya bukan `current` hanya dipurge, tidak di-ingest.

Semua space masuk ke **satu collection** (`QDRANT_COLLECTION`). Pemisahnya adalah field
`spaceKey` di payload, yang diambil per halaman dari URL halaman itu sendiri.

## Qdrant

- Vector: `dense` (embedding OpenAI-compatible) dan `sparse` (BM25 dihitung oleh Qdrant lewat
  inference object `qdrant/bm25`, `options.avg_len`).
- Payload per point: `text, chunk_index, token_count, word_count, pageId, title, spaceKey, url, createdAt, lastModified`.
- Point id: UUID4 acak. Karena itu update halaman dilakukan dengan purge `pageId` lalu upsert.

## Perilaku penting

- Purge halaman yang berubah dilakukan **setelah** fetch, convert, chunk, dan embed sukses, tepat
  sebelum upsert. Jika langkah sebelumnya gagal, vektor lama tetap utuh.
- Halaman yang gagal dicatat, run lanjut ke halaman berikutnya, dan exit code 1 pada `--once`.
- Halaman trashed tidak punya perubahan versi, jadi daftar trashed dibaca penuh setiap run (tanpa filter tanggal).
- `MODIFIED_WINDOW_DAYS` harus lebih besar dari interval scheduler agar tidak ada perubahan yang terlewat.
- Pagination memakai `_links.next` dan menangani beda format v1 (`/rest/api/...`) vs v2 (`/wiki/api/v2/...`).
- Request HTTP di-retry pada error jaringan dan 429/5xx (`HTTP_MAX_TRIES`, `HTTP_RETRY_WAIT_SECONDS`).

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Wajib diisi di `.env`: `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`, `EMBEDDING_API_KEY`, `QDRANT_API_KEY`.

### Konfigurasi utama

| Variabel | Keterangan |
| --- | --- |
| `CONFLUENCE_SPACE_KEYS` | Satu atau lebih space key, dipisah koma, contoh `II,SP`. Space id **tidak perlu** diisi, diambil otomatis dari API. `CONFLUENCE_SPACE_KEY` (tunggal) masih terbaca sebagai fallback. |
| `MODIFIED_WINDOW_DAYS` | Halaman dianggap berubah bila `lastmodified >= now(-N hari)`. |
| `QDRANT_COLLECTION` | Collection tujuan untuk semua space. |
| `CHUNK_MODE` | `api` (POST ke `CHUNK_API_URL`) atau `local` (tiktoken di proses ini). |
| `SCHEDULE_HOUR`, `SCHEDULE_MINUTE`, `SCHEDULE_TIMEZONE` | Jadwal harian. |
| `RUN_ON_START` | `true` untuk langsung sync sekali saat scheduler start. |

Daftar lengkap ada di [.env.example](.env.example).

### Menambah space

1. Tambahkan key ke `CONFLUENCE_SPACE_KEYS`, contoh `II,SP,HR`.
2. Cek dulu dengan `--dry-run` (lihat bagian bawah). Log akan menampilkan hasil resolve key → id
   dan daftar halaman yang akan diproses.
3. Restart proses scheduler agar config baru terbaca.

Akun pemilik API token harus punya akses baca ke space yang ditambahkan.

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

Tes memakai mock HTTP (tanpa jaringan): skema payload, urutan purge → upsert, trashed tidak di-ingest,
pagination, dry-run, kegagalan per halaman, resolve multi-space, dan space key yang tidak dikenal.

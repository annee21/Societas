<!-- Doc 05 — Artifact, Memory, Tools (§17–21)
     Bagian dari societas-full-product-spec. Urutan dokumen diatur di README.md.
     Nomor section dipertahankan; referensi silang antar-doc memakai nomor section (#N, 5A.x, 72A.x). -->

# 17. Artifact System

Output agent tidak boleh hanya dianggap sebagai text response.

Artifact adalah output yang dapat dipakai agent lain.

Contoh:

```text
research.md
architecture.md
benchmark.json
diagram.svg
decision.md
patch.diff
pull-request.md
test-report.md
```

## 17.1 Contract-First Integration (Generate-First, Gate-Second, Prompt-Last)

Agen dilarang menulis fungsi fetch/call Web3 atau API dari nol secara manual. Alur serah terima backend/smart contract ke frontend:

1. **Pinning Kontrak:** task frontend wajib mengunci `contract_hash` (SHA256 dari OpenAPI spec / Contract ABI). Jika spec berubah, Orchestrator menerbitkan `task.contract_changed` (`phase: invalidated`) dan menetapkan `contract_status: stale` — freshness terpisah dari status eksekusi. Dispatch/resume, review, approval, dan completion ditahan sampai re-pin + codegen terhadap spec terbaru; gate/review/approval lama tidak valid. Re-pin sukses direkam sebagai `phase: repinned`; task terminal tidak dibuka kembali. Lifecycle kanonik di 72A.6/72A.8.
2. **Codegen Otomatis:** Go runtime men-generate client TypeScript/Rust binding via CLI tool (`orval`, `wagmi` typegen, `viem`) sebelum agen bekerja.
3. **Strict Usage:** agen hanya boleh mengimpor dan memanggil fungsi hasil generate tersebut.
4. **Token-Saver Lookup:** agen tidak menerima seluruh spec OpenAPI/ABI ke prompt. Disediakan tool deterministik `contract.lookup(operation_id)` yang mengembalikan potongan spec relevan saja — tanpa vector search.

Artifact memiliki:

- ID
- owner
- creator
- task
- type
- path
- checksum
- created_at
- updated_at
- metadata

---

# 18. Artifact Flow

```text
Research Agent
      |
      v
research.md
      |
      v
CEO
      |
      v
architecture task
      |
      v
CTO
      |
      v
architecture.md
      |
      v
Engineer
      |
      v
code + tests
      |
      v
Reviewer
      |
      v
review.md
```

---

# 19. Memory System

Memory dibagi menjadi beberapa level dan disimpan sesuai sifatnya pada dua pilar penyimpanan (Dual-Storage Architecture, lihat #37):

- Data terstruktur/operasional (task state, run history, approval, akumulasi budget) -> **Operational Store** (SQLite)
- Representasi semantik (embedding artifact, ringkasan riset, koordinat memori masa lalu) -> **Cognitive Store** (Embedded Vector DB)

## 19.1 Agent Memory

Informasi khusus agent.

Contoh:

```text
CTO preferences
Engineering decisions
Technical context
Past reviews
```

## 19.2 Workspace Memory

Informasi seluruh organisasi.

Contoh:

```text
Architecture decisions
Project direction
Company rules
Important findings
```

## 19.3 Task Memory

Context yang hanya relevan terhadap satu task.

## 19.4 Run Memory

Context selama satu execution.

## 19.5 Memory Storage Mapping

Setiap level memory di atas di-map ke pilar penyimpanan:

- Agent Memory & Workspace Memory: entry terstruktur (sumber, timestamp, scope) di SQLite; hanya narasi yang lolos admission guard #19.6 boleh di-embed ke Vector DB.
- Task Memory: relasi task -> artifact/memory disimpan di SQLite; ringkasan tidak otomatis di-embed dan tetap melewati admission guard #19.6.
- Run Memory: append-only di event log SQLite; tidak di-embed (ephemeral).

Retrieval semantik selalu melewati Vector DB dan mengembalikan ID referensi ([5A.25 — Semantic Retrieval](02-ai-control-plane.md#5a25-semantic-retrieval)) — bukan pencarian teks mentah di SQLite.

## 19.6 Memory Curation (Anti Semantic Drift / Zombie Memory)

Vector DB bekerja berdasarkan kemiripan teks (cosine similarity), **bukan status kebenaran atau recency**. Ia tidak tahu dokumen mana yang sudah basi — `architecture_v1.md` (nullifier 2 status) dan `nullifier_v2.md` (4 status) bisa sama-sama ter-retrieve karena kemiripannya hampir sama, sehingga agen menerima dua fakta kontradiktif dan bisa "ketularan" keputusan lama yang sudah dibatalkan. Semakin tua proyek, makin banyak zombie memory: keputusan dibatalkan, bug log yang sudah di-patch, nama fungsi yang sudah deprecated.

Lima aturan kurasi deterministik di Go + SQLite — tanpa algoritma AI tambahan:

1. **Filter pintu masuk — jangan embed semua hal.** Keputusan/spec hanya boleh di-embed setelah human approval untuk versi yang terikat, Semantic Rebase `PASS` (#60.4), dan merge receipt resmi ke `main` terkonfirmasi (I19). Approval abstrak atau Git rebase bersih saja tidak cukup. Dokumentasi final harus berasal dari kode yang sudah merge. Chat/debat/transkrip arbitrase, keputusan kandidat belum merge, log error/test gagal, draft, proposal kalah, dan putusan lead yang belum lolos pipeline dilarang di-embed.
2. **Pola Supersede (tombstone di SQLite).** Tabel `artifacts` memiliki kolom `superseded_by` (ID artifact pengganti). Saat keputusan baru menggantikan yang lama, record lama ditandai — bukan dihapus. Setiap ID hasil retrieval Vector DB wajib di-filter ulang ke SQLite: `superseded_by != NULL -> skip`. Dokumen basi tidak pernah masuk context LLM lagi.
3. **Time-decay scoring.** Skor akhir retrieval = `vector_similarity x faktor_umur` (mis. dokumen minggu ini x1.0, 3 bulan x0.5), dihitung deterministik di Go — dokumen lama yang kebetulan mirip kalah dari dokumen baru yang relevan.
4. **Ikat memori ke git commit / path.** Setiap entry memori menyimpan metadata `source_path` (mis. `crates/storage/src/nullifier.rs`) dan commit hash. Background GC mengecek via git: jika file/fungsi sudah dihapus atau di-rename di `main`, memori ditandai `stale` dan dibersihkan dari Vector DB.
5. **Semantic admission guard.** Sebelum embedding, Go mencocokkan approval ID/hash dan snapshot version, semantic evidence version/checksum, serta merge receipt terkonfirmasi. Ketiganya harus mengikat workspace/run/task, base/candidate commit/tree, recipe/policy, dan decision artifact versions/checksums yang sama. Periksa status/tombstone/freshness di SQLite; saat conflict, inconclusive, approval pending, atau receipt belum direkonsiliasi, simpan artifact di Operational Store/quarantine saja. `task.completed`, ringkasan LLM, atau verdict lead bukan merge receipt dan agent tidak dapat memberi flag `passed` sendiri.

### Penyimpanan Batasan Negatif (Anti-Pattern)

Keputusan atau proposal arsitektur yang didebat lalu ditolak (misal via `decision.md` hasil arbitrase atau penolakan human) **tidak dibuang**. Ringkasan kondisi batasannya diekstraksi ke Vector DB (Cognitive Store) dengan:

- Metadata `cognitive_guardrail: true` — menandai entry sebagai batasan validasi, bukan contoh untuk ditiru
- Tag `anti-pattern` — membedakan dari best practice yang boleh diikuti
- Ringkasan fokus pada **alasan penolakan** dan **kondisi yang menyebabkan kegagalan**, bukan implementasi detail yang salah

Contoh anti-pattern yang disimpan:
- Arsitektur yang menembus adapter boundary (ditolak karena violation)
- Kontrak API yang tidak versioning (ditolak karena breaking change risk)
- Pola concurrency yang menyebabkan race condition (ditolak karena deadlock evidence)

Anti-pattern ini tetap di-retrieval saat ada konteks serupa, tetapi **diisolasi secara struktural** di prompt LLM (lihat 5A.4) agar model memperlakukannya sebagai penalti/filter validasi akhir, bukan contoh kode yang harus ditiru.

Prinsip: Vector DB adalah **perpustakaan buku yang sudah lulus kurasi** — bukan tempat sampah. Edisi lama ditarik dari rak saat revisi terbit.

Semantic triage mengambil exact-version Git/SQLite/artifact sebagai input; dilarang mengambil proposal dari Vector DB atau memakai similarity untuk menghidupkan zombie memory. Setelah replacement valid admitted, tombstone/supersede menarik versi lama lewat mekanisme existing. Provenance fingerprint/freshness lintas source dan non-Git admission dijelaskan di [DEC-005] W15 (Non-Git Memory Admission Protocol).

---

# 20. Memory Rules

Memory harus memiliki:

- source
- timestamp
- confidence
- scope
- owner

Jangan memasukkan semua chat ke memory secara otomatis — hanya keputusan/spec ter-approve + semantic pass + merge receipt terkonfirmasi yang boleh di-embed (#19.6).

Memory harus memiliki lifecycle.

Contoh:

```text
raw event
    |
    v
candidate memory
    |
    v
validated memory
    |
    v
persistent memory
    |
    v
superseded / stale  (tombstone di SQLite — tidak pernah kembali ke context, #19.6)
```

---

# 21. Tools

Agent dapat memiliki tools.

Contoh:

```text
filesystem
shell
git
browser
search
http
database
terminal
python
docker
kubernetes
```

Tool access harus configurable per agent.

Capability retry setiap tool disimpan dalam konfigurasi tepercaya Tool Runtime, bukan ditentukan oleh agen atau sekadar keberadaan field di input:

```yaml
tool_capabilities:
  filesystem.read:
    idempotent: true
    operation_key_enforced: false
  external.mutate:
    idempotent: false
    operation_key_enforced: false  # true hanya jika penyedia menjamin deduplikasi
```

Field yang tidak diisi berarti `false`. Untuk tool non-idempotent dengan `operation_key_enforced: true`, runtime membuat dan menyimpan `operation_key` sebelum dispatch pertama, mempertahankannya beserta argumen yang sama untuk seluruh retry, dan hanya retry selama jaminan deduplikasi penyedia masih berlaku. Tidak menambahkan field ini ke argumen MCP bila provider tidak mendukungnya. Timeout/network putus sesudah dispatch berarti `outcome_unknown`, bukan bukti tool belum berjalan. Tanpa jaminan idempotency/deduplikasi, rekonsiliasi atau keputusan human yang menyebut risiko duplikasi wajib mendahului percobaan lain (I16, 72A.8–10). Tool dengan hasil gagal logis memakai `tool.call_completed` `status: error`; tool pasti belum dispatch memakai `tool.call_failed` `outcome: not_started`.

## 21.1 Tool Interface — MCP Client

Antarmuka tool agen menggunakan arsitektur **MCP Client**: Tool Runtime di backend Go bertindak sebagai client yang terhubung ke MCP server internal maupun eksternal (filesystem, shell, git, search, dst). Tool baru ditambahkan dengan mendaftarkan server MCP — bukan mengubah kode agen. Permission tetap di-gate deterministik oleh Policy Engine (#22) sebelum call diteruskan ke MCP server.

---

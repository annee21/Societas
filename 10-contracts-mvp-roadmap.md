<!-- Doc 10 — Contracts 72A + MVP & Roadmap (§72A–105)
     Bagian dari societas-full-product-spec. Urutan dokumen diatur di README.md.
     Nomor section dipertahankan; referensi silang antar-doc memakai nomor section (#N, 5A.x, 72A.x). -->

# 72A. Contracts & Schemas (Source of Truth)

Section ini adalah **satu-satunya definisi kanonik** bentuk data yang dipertukarkan di dalam Societas: envelope, event, task, budget, usage, artifact, summary, tool call, approval, dan error.

Jika contoh di section lain (misalnya #7, #10, #11, #63) berbeda dengan section ini, **Section 72A yang berlaku**.

Format: JSON Schema (draft 2020-12), netral terhadap bahasa. Implementasi (Go, TypeScript, dll.) sebaiknya **generate type dari schema ini** atau memvalidasinya saat runtime, bukan menulis ulang tangan.

Contoh di section ini divalidasi terhadap schema yang sama (lihat 72A.13).

## 72A.1 Aturan Dasar (Invariants)

Aturan ini ditegakkan oleh runtime, bukan oleh prompt agent.

| # | Aturan | Ditegakkan oleh |
|---|--------|-----------------|
| I1 | Agent **tidak memanggil agent lain secara langsung**. Semua pesan lewat Event Bus yang dimediasi Control Plane. | Event Bus + Policy Engine |
| I2 | Agent hanya boleh **meminta** pembuatan task (`task.delegate_requested`). Hanya Orchestrator yang membuat dan meng-assign task. | Orchestrator |
| I3 | Budget yang diberikan ke anak tidak boleh melebihi sisa budget parent. Total budget semua anak aktif tidak boleh melebihi sisa budget parent. | Budget Manager |
| I4 | Tidak ada model call tanpa `budget.reserved` dan keputusan policy `allow`. Setiap model call harus di-settle (`budget.settled`) dengan usage nyata. | Token Guard (5A.15) |
| I5 | Konten inline dibatasi atas **seluruh payload JSON terserialisasi**, termasuk semua field dan nested object, dalam byte UTF-8: default 8.000 byte untuk event selain `tool.call_completed`, dan 16.000 byte untuk `tool.call_completed`. Batas string pada schema tetap berlaku secara terpisah. Yang lebih besar harus menjadi artifact + summary. | Event Bus (guard di boundary sebelum persistence/delivery) |
| I6 | Event bersifat immutable dan append-only. Event store memberi `seq` yang naik monoton per run. | Event Store |
| I7 | `idempotency_key` yang sama dalam satu run diabaikan dan dijawab dengan hasil sebelumnya. | Event Bus |
| I8 | Setiap event punya `correlation_id` (konstan per permintaan user) dan `causation_id` (event penyebab), kecuali event root (`run.created`). | Event Bus |
| I9 | `type` tidak dikenal, atau payload yang tidak lolos schema, ditolak dengan `SCHEMA_VALIDATION_FAILED`. | Validator di boundary |
| I10 | Output LLM yang harus terstruktur (delegation, tool call) diparse sebagai JSON dan divalidasi. Jika gagal, agent diminta memperbaiki maksimal 2 kali, dihitung dalam retry budget. | Agent Runtime |
| I11 | Status task terminal (`completed`, `failed`, `cancelled`) bersifat final. Retry dilakukan lewat `running → ready`, bukan membuka task yang sudah `failed`. | Orchestrator |
| I12 | Pengecekan fan-out, depth, dan iterasi dilakukan saat `task.delegate_requested` diproses, sebelum task dibuat. | Orchestrator |
| I13 | Setiap run diakhiri tepat satu `run.stopped` dengan `reason` yang jelas. | Orchestrator |
| I14 | Agent tidak dapat mengubah budget, policy, atau limit miliknya sendiri. Hanya human (lewat approval) yang dapat menaikkannya. | Budget Manager + Policy Engine |
| I15 | Event wajib ter-commit ke Event Store (SQLite) **sebelum** disalurkan ke subscriber (transactional outbox, #42.1). Tidak ada delivery dari memory saja. | Event Bus + Event Store |
| I16 | Retry tool yang mungkin sudah berjalan hanya boleh jika tool dinyatakan `idempotent` di capability tepercaya (#21) atau request membawa `operation_key` stabil yang deduplikasinya ditegakkan provider tool. Kegagalan dengan hasil tidak diketahui (`outcome_unknown`) pada tool non-idempotent wajib rekonsiliasi atau keputusan human — tidak auto-retry. | Tool Runtime + Policy Engine |
| I17 | Approval mengikat snapshot input berversi melalui `sha256(JCS(snapshot))`. Merge hanya memakai kandidat final sesudah rebase + gate + Semantic Rebase `PASS` + review; semantic conflict/inconclusive memblokir integrasi dan dieskalasi. Perubahan base/kandidat/input terikat membatalkan approval dan evidence terkait. Update target memakai expected-base CAS, bukan merge commit baru sesudah approval. | Policy Engine + Orchestrator + Git executor |
| I18 | Digest hanya menggabungkan presentasi/klik human, bukan otorisasi. Tiap item high diperiksa dan di-grant terpisah terhadap snapshot-nya; critical tidak pernah masuk digest. Unique key `(workspace_id, run_id, batch_hash, approval_id)` menghasilkan satu durable receipt/outcome per item. Menunggu approval melepaskan worker dan tidak mengeksekusi mutasi lebih awal. | Policy Engine + Approval Center + Orchestrator |
| I19 | Merge memerlukan semantic evidence `pass` yang terikat base/kandidat yang sama sesudah deterministic gate dan sebelum review/approval. Conflict atau hasil inconclusive memblokir integrasi; arbitrase/refactor mengulang rebase, gate, semantic, review, dan approval. Keputusan/spec baru tidak di-embed sebelum approval, semantic pass, dan merge receipt terkonfirmasi serta direkonsiliasi. | Merge Queue + Reviewer + Memory Curator |
| I20 | Compiler Gate & Local Toolchain menggunakan **log inactivity timeout** (5 menit tanpa output baru pada `stdout`/`stderr`) untuk mendeteksi deadlock/infinite loop, bukan hard execution timeout durasi total, karena performa kompilasi bervariasi drastis per hardware. Kegagalan build/lint dibatasi maksimal 3 iterasi perbaikan; setelah itu task dibekukan (`status: blocked`) dan dieskalasi ke `escalation_lead` atau manusia. | Tool Runtime + Orchestrator |
| I21 | Penanganan jaringan terputus menggunakan pendekatan **murni deterministik di Go Runtime** (0 token). Tolak fallback router offline berbasis ONNX/regex. Deteksi jaringan sepenuhnya tugas Go Runtime melalui healthcheck deterministik cepat (socket ping/HEAD request ke DNS publik). Jika internet terkonfirmasi putus, Go Runtime memicu auto-pause via CAS pada SQLite, menyimpan checkpoint dan deadline, lalu melepaskan worker pool. Background daemon memantau pemulihan koneksi dan menerbitkan `task.resumed` saat online kembali tanpa duplikasi event. | Go Runtime + Orchestrator |
| I22 | Anti-pattern memory disimpan di Vector DB dengan metadata `cognitive_guardrail: true` dan tag `anti-pattern` (keputusan yang ditolak tidak dibuang). Context Manager wajib mengisolasi memori secara struktural menggunakan blok XML saat merakit prompt LLM: rekomendasi positif di `<historical_success>` dan batasan negatif di `<confirmed_blacklist>` di bagian paling bawah. Struktur ini mengunci mekanisme atensi model agar memperlakukan batasan negatif sebagai penalti/filter validasi akhir, bukan contoh untuk ditiru. | Context Manager + Memory Curator |
| I23 | **Sumber utama Session Policy.** Konfigurasi di `workspace.yaml` (#36) memakai `sticky_until_done` (default) atau `stateless_step`. Mode sticky mempertahankan thread/sesi provider selama task `running`. Hierarki prompt statis ke dinamis: `System Prompt & Role` → `Tool Schemas` → `PROJECT_MAP.md` → `Recent History` → `Input Baru`; usage cache diukur lewat `cached_input_tokens` (72A.5). Sesi wajib di-flush dan ditutup saat task terminal (`completed`, `failed`, `cancelled`) atau parked (`awaiting_approval`, `paused`, `interrupted`, `blocked`): ringkasan/checkpoint dipersist ke SQLite dan worker dilepas (#40.1). Saat mencapai `max_turns_before_flush`, Summarizer menyimpan ringkasan ke SQLite lalu sesi di-reset untuk mencegah context rot dan biaya O(N²). Mode stateless merakit ulang context per turn dan menutup sesi setiap selesai satu panggilan model. | Context Manager + Orchestrator |

## 72A.2 Identifier & Addressing

| Jenis | Format | Contoh |
|-------|--------|--------|
| Workspace | `ws_<slug>` | `ws_acme` |
| Run | `RUN-<nomor>` | `RUN-001` |
| Task | `TASK-<nomor>` | `TASK-002` |
| Event | `evt_<ULID>` | `evt_01J9Z3K4M5N6P7Q8R9S0T1V2W3` |
| Message | `msg_<ULID>` | |
| Conversation | `conv_<ULID>` | |
| Artifact | `art_<ULID>` | |
| Summary | `sum_<ULID>` | |
| Tool call | `tc_<ULID>` | |
| Approval | `apr_<ULID>` | |
| Correlation | `cor_<ULID>` | |
| Agent | slug huruf kecil | `ceo`, `research` |

Nomor `RUN-` dan `TASK-` berurutan per workspace dan mudah dibaca manusia. ID lainnya memakai ULID (26 karakter Crockford base32) supaya urut waktu dan unik tanpa koordinasi.

Alamat (`from` / `to`) memakai format `<jenis>:<nama>`:

| Alamat envelope | Bentuk singkat di UI (#50) |
|-----------------|-------------------------------|
| `agent:ceo` | `@ceo` |
| `human:user` | pengguna |
| `system:orchestrator` | komponen Control Plane |
| `topic:all` | `@all` |
| (task) | `#TASK-001` (field `task_id`) |

Komponen `system:*` yang dikenal: `orchestrator`, `scheduler`, `budget`, `policy`, `context`, `router`, `summarizer`, `tool_runtime`, `event_bus`.

## 72A.3 Envelope

Semua pesan memakai satu envelope yang sama. Perbedaan hanya ada pada `type` dan `payload`.

<!-- schema:envelope -->
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:societas:1:envelope",
  "title": "Envelope",
  "type": "object",
  "additionalProperties": false,
  "required": ["protocol_version", "schema_version", "id", "type", "ts",
               "workspace_id", "run_id", "correlation_id", "from", "to", "payload"],
  "properties": {
    "protocol_version": { "const": "societas/1" },
    "schema_version": { "type": "string", "pattern": "^[0-9]+$" },
    "id": { "$ref": "urn:societas:1:common#/$defs/evt_id" },
    "type": { "type": "string", "pattern": "^[a-z]+(\\.[a-z_]+)+$" },
    "ts": { "$ref": "urn:societas:1:common#/$defs/ts" },
    "seq": { "type": "integer", "minimum": 1,
             "description": "Diisi Event Store, bukan pengirim." },
    "workspace_id": { "type": "string", "pattern": "^ws_[a-z0-9_-]{1,32}$" },
    "run_id": { "$ref": "urn:societas:1:common#/$defs/run_id" },
    "task_id": { "$ref": "urn:societas:1:common#/$defs/task_id" },
    "correlation_id": { "$ref": "urn:societas:1:common#/$defs/cor_id" },
    "causation_id": { "$ref": "urn:societas:1:common#/$defs/evt_id" },
    "idempotency_key": { "type": "string", "minLength": 1, "maxLength": 128 },
    "trace_id": { "type": "string", "pattern": "^[0-9a-f]{32}$" },
    "from": { "$ref": "urn:societas:1:common#/$defs/actor" },
    "to": { "$ref": "urn:societas:1:common#/$defs/address" },
    "payload": { "type": "object" }
  }
}
```

Catatan:

- `protocol_version`, `message_type`, dan `schema_version` pada #72 dipetakan ke `protocol_version`, `type`, dan `schema_version`.
- Frame transport pada #71 (`HELLO`, `AUTH`, `PUBLISH`, dst.) berada di bawah envelope ini. Envelope adalah isi dari frame `PUBLISH`, `TASK`, `MESSAGE`, dan `TOOL`.
- `payload` divalidasi lagi terhadap schema sesuai `type` (lihat registry di 72A.7).
- Ukuran payload terserialisasi agregat dibatasi (I5) — kelebihan wajib menjadi artifact. Schema saja tidak menegakkan batas byte nested object; aturan boundary di 72A.12 wajib dijalankan.

## 72A.4 Common Definitions

<!-- schema:common -->
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:societas:1:common",
  "$defs": {
    "run_id":  { "type": "string", "pattern": "^RUN-[0-9]{3,}$" },
    "task_id": { "type": "string", "pattern": "^TASK-[0-9]{3,}$" },
    "evt_id":  { "type": "string", "pattern": "^evt_[0-9A-HJKMNP-TV-Z]{26}$" },
    "msg_id":  { "type": "string", "pattern": "^msg_[0-9A-HJKMNP-TV-Z]{26}$" },
    "conv_id": { "type": "string", "pattern": "^conv_[0-9A-HJKMNP-TV-Z]{26}$" },
    "art_id":  { "type": "string", "pattern": "^art_[0-9A-HJKMNP-TV-Z]{26}$" },
    "sum_id":  { "type": "string", "pattern": "^sum_[0-9A-HJKMNP-TV-Z]{26}$" },
    "tc_id":   { "type": "string", "pattern": "^tc_[0-9A-HJKMNP-TV-Z]{26}$" },
    "apr_id":  { "type": "string", "pattern": "^apr_[0-9A-HJKMNP-TV-Z]{26}$" },
    "cor_id":  { "type": "string", "pattern": "^cor_[0-9A-HJKMNP-TV-Z]{26}$" },
    "agent_id": { "type": "string", "pattern": "^[a-z][a-z0-9_-]{1,31}$" },
    "actor":   { "type": "string", "pattern": "^(agent|human|system):[a-z][a-z0-9_.-]{0,31}$" },
    "address": { "type": "string", "pattern": "^(agent|human|system|topic):[a-z][a-z0-9_.-]{0,31}$" },
    "ts":      { "type": "string", "format": "date-time" },
    "sha256":  { "type": "string", "pattern": "^sha256:[0-9a-f]{64}$" },
    "priority": { "enum": ["low", "normal", "high", "critical"] },
    "tier":    { "enum": ["cheap", "medium", "strong"] },
    "scope":   { "enum": ["workspace", "run", "task", "agent", "tool"] },
    "tool_name": { "type": "string", "pattern": "^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$" }
  }
}
```

Label tampilan bukan nilai wire: `thinking` → tier `strong`; Flash tier adalah label jalur murah yang dipetakan ke tier wire `cheap`, bukan tier baru. Policy/risk routing tetap berlaku, termasuk model escalation untuk task critical. Label Reviewer `PASS`/`PASS_WITH_WARNINGS` → verdict `approve` (warnings hanya advisory), `REQUEST_CHANGES` → `request_changes`; Semantic Rebase memakai `result: pass|conflict|inconclusive`, bukan verdict review. `reject` menolak hasil review tetapi tidak otomatis membuat task terminal. Label legacy `BLOCKED` belum punya mapping default: arti menunggu dependency/policy vs penolakan final harus diputuskan sebelum adapter memprosesnya (#29, keputusan I01).

## 72A.5 Core Objects

### Budget

Batas yang boleh diberikan ke workspace, run, task, atau agent. Semua field opsional. Field yang tidak ada berarti "ikut batas parent". Mengacu ke 5A.2, 5A.13, 5A.14, dan [5A.20 — Maximum Iterations](02-ai-control-plane.md#5a20-maximum-iterations). Batas koreksi lokal pada Compiler Gate (maksimal 3 iterasi, I20) juga mengikuti prinsip retry budget.

<!-- schema:budget -->
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:societas:1:budget",
  "title": "Budget",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "max_input_tokens":    { "type": "integer", "minimum": 0 },
    "max_output_tokens":   { "type": "integer", "minimum": 0 },
    "max_total_tokens":    { "type": "integer", "minimum": 0 },
    "max_model_calls":     { "type": "integer", "minimum": 0 },
    "max_tool_calls":      { "type": "integer", "minimum": 0 },
    "max_agent_messages":  { "type": "integer", "minimum": 0 },
    "max_time_seconds":    { "type": "integer", "minimum": 0 },
    "max_cost_usd":        { "type": "number",  "minimum": 0 },
    "max_parallel_agents": { "type": "integer", "minimum": 0 },
    "max_child_tasks":     { "type": "integer", "minimum": 0 },
    "max_depth":           { "type": "integer", "minimum": 0 },
    "max_agent_iterations": { "type": "integer", "minimum": 0 },
    "max_task_iterations":  { "type": "integer", "minimum": 0 },
    "max_rebuttals":       { "type": "integer", "minimum": 0,
                             "description": "batas putaran sanggahan per task (#48); counter disimpan di SQLite dan bertahan atas retry/restart" },
    "retry": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "max_attempts": { "type": "integer", "minimum": 0 },
        "max_total_retry_cost_usd": { "type": "number", "minimum": 0 }
      }
    }
  }
}
```

Aturan pemakaian budget:

- **Reserve lalu settle.** Sebelum model call, Budget Manager me-reserve batas atas (token dan biaya). Setelah selesai, usage nyata di-settle dan sisa reservasi dikembalikan.
- Budget bersifat hierarkis (5A.3): `workspace > run > task > agent > tool`.
- Peringatan dikirim saat 80% terpakai (`budget.warning`). Saat limit tercapai: `budget.exceeded`, lalu stop atau approval ([5A.21 — Approval Escalation](02-ai-control-plane.md#5a21-approval-escalation)).

### Usage

Pemakaian satu model call. Dicatat oleh Cost Tracker (5A.10).

<!-- schema:usage -->
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:societas:1:usage",
  "title": "Usage",
  "type": "object",
  "additionalProperties": false,
  "required": ["model", "input_tokens", "output_tokens", "duration_ms", "estimated_cost_usd"],
  "properties": {
    "provider": { "type": "string" },
    "model": { "type": "string" },
    "input_tokens": { "type": "integer", "minimum": 0 },
    "output_tokens": { "type": "integer", "minimum": 0 },
    "cached_input_tokens": { "type": "integer", "minimum": 0,
                        "description": "token input yang di-cache oleh provider dari session sticky (session_policy.mode: sticky_until_done, #36); 0 jika stateless_step atau cache miss" },
    "duration_ms": { "type": "integer", "minimum": 0 },
    "estimated_cost_usd": { "type": "number", "minimum": 0 }
  }
}
```

### Usage Totals

Akumulasi pemakaian per scope (task, run, workspace).

<!-- schema:usage_totals -->
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:societas:1:usage_totals",
  "title": "UsageTotals",
  "type": "object",
  "additionalProperties": false,
  "required": ["input_tokens", "output_tokens", "model_calls", "tool_calls", "estimated_cost_usd"],
  "properties": {
    "input_tokens": { "type": "integer", "minimum": 0 },
    "output_tokens": { "type": "integer", "minimum": 0 },
    "model_calls": { "type": "integer", "minimum": 0 },
    "tool_calls": { "type": "integer", "minimum": 0 },
    "agent_messages": { "type": "integer", "minimum": 0 },
    "retries": { "type": "integer", "minimum": 0 },
    "estimated_cost_usd": { "type": "number", "minimum": 0 },
    "elapsed_seconds": { "type": "number", "minimum": 0 }
  }
}
```

### Error

Satu bentuk error untuk semua event gagal. Katalog kode ada di 72A.9.

<!-- schema:error -->
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:societas:1:error",
  "title": "Error",
  "type": "object",
  "additionalProperties": false,
  "required": ["code", "category", "message", "retryable"],
  "properties": {
    "code": { "type": "string", "pattern": "^[A-Z][A-Z0-9_]+$" },
    "category": { "enum": ["MODEL_ERROR", "TOOL_ERROR", "NETWORK_ERROR", "TIMEOUT",
                           "PERMISSION_DENIED", "INVALID_OUTPUT", "DEPENDENCY_FAILED",
                           "BUDGET_ERROR", "LIMIT_ERROR"] },
    "message": { "type": "string", "maxLength": 1000 },
    "retryable": { "type": "boolean" },
    "retry_after_ms": { "type": "integer", "minimum": 0 },
    "details": { "type": "object" }
  }
}
```

### Task

Bentuk lengkap task (memperluas #7).

<!-- schema:task -->
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:societas:1:task",
  "title": "Task",
  "type": "object",
  "additionalProperties": false,
  "required": ["id", "run_id", "parent_task_id", "title", "goal", "owner", "created_by",
               "priority", "status", "depth", "attempt", "expected_output", "budget",
               "working_directory", "created_at", "updated_at"],
  "properties": {
    "id": { "$ref": "urn:societas:1:common#/$defs/task_id" },
    "run_id": { "$ref": "urn:societas:1:common#/$defs/run_id" },
    "parent_task_id": { "oneOf": [ { "$ref": "urn:societas:1:common#/$defs/task_id" }, { "type": "null" } ] },
    "title": { "type": "string", "minLength": 1, "maxLength": 200 },
    "goal": { "type": "string", "minLength": 1, "maxLength": 4000 },
    "owner": { "$ref": "urn:societas:1:common#/$defs/agent_id" },
    "created_by": { "$ref": "urn:societas:1:common#/$defs/actor" },
    "priority": { "$ref": "urn:societas:1:common#/$defs/priority" },
    "status": { "enum": ["pending", "ready", "running", "pausing", "paused", "interrupted",
                         "blocked", "awaiting_approval", "completed", "failed", "cancelled"] },
    "dependencies": { "type": "array", "items": { "$ref": "urn:societas:1:common#/$defs/task_id" }, "uniqueItems": true },
    "deadline": { "oneOf": [ { "$ref": "urn:societas:1:common#/$defs/ts" }, { "type": "null" } ] },
    "depth": { "type": "integer", "minimum": 0 },
    "attempt": { "type": "integer", "minimum": 1 },
    "expected_output": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind"],
      "properties": {
        "kind": { "enum": ["artifact", "summary", "decision", "patch"] },
        "format": { "type": "string", "maxLength": 64 }
      }
    },
    "budget": {
      "type": "object",
      "additionalProperties": false,
      "required": ["granted", "used"],
      "properties": {
        "granted": { "$ref": "urn:societas:1:budget" },
        "used": { "$ref": "urn:societas:1:usage_totals" }
      }
    },
    "artifact_ids": { "type": "array", "items": { "$ref": "urn:societas:1:common#/$defs/art_id" } },
    "working_directory": { "type": "string", "minLength": 1, "maxLength": 512,
                          "description": "Path direktori kerja yang di-assign oleh Orchestrator untuk task ini. Agent menyimpan output di path ini secara relative. Pattern: /workspace/artifacts/{run_id}/{task_id}/" },
    "risk_tier": { "enum": ["low", "normal", "high", "critical"], "default": "normal",
             "description": "Tier risiko dari evaluasi dinamis workspace.yaml (#23.1, #36); 'high' yang memerlukan approval masuk delivery batch, sedangkan 'critical' memicu synchronous halt dan kunci mutasi hingga human approval (5A.8)." },
    "risk_tags": { "type": "array", "items": { "type": "string", "maxLength": 64 }, "uniqueItems": true,
                   "description": "Tag penyebab klasifikasi, mis. 'path:migrations/**', 'intent:deploy'." },
    "blocked_reason": { "enum": ["semantic_conflict", "semantic_inconclusive"],
              "description": "Alasan task berstatus blocked karena semantic rebase menemukan konflik atau hasil yang belum dapat dipastikan (#48, #60.4); wajib menunjuk blocked_evidence." },
    "blocked_evidence": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version",
                "description": "Ref artifact immutable untuk semantic conflict/inconclusive evidence; required bersama blocked_reason." },
    "contract_hash": { "oneOf": [ { "$ref": "urn:societas:1:common#/$defs/sha256" }, { "type": "null" } ],
                       "description": "Pin SHA256 dari OpenAPI spec / Contract ABI untuk task contract-first (#17.1); task ditandai stale jika spec berubah." },
    "contract_status": { "enum": ["current", "stale"], "default": "current",
                         "description": "freshness kontrak terpisah dari status eksekusi; stale memblokir dispatch, review, approval, dan completion sampai re-pin + re-codegen (#17.1)" },
    "pause_deadline": { "$ref": "urn:societas:1:common#/$defs/ts",
                        "description": "deadline absolut pause yang dipersist; wajib saat pausing/paused dan tetap disimpan setelah interrupted sampai pause diselesaikan atau dibatalkan" },
    "created_at": { "$ref": "urn:societas:1:common#/$defs/ts" },
    "updated_at": { "$ref": "urn:societas:1:common#/$defs/ts" }
  },
  "allOf": [
    {
      "if": { "properties": { "status": { "enum": ["pausing", "paused"] } }, "required": ["status"] },
      "then": { "required": ["pause_deadline"] }
    },
    {
      "if": { "properties": { "blocked_reason": { "enum": ["semantic_conflict", "semantic_inconclusive"] } }, "required": ["blocked_reason"] },
      "then": { "properties": { "status": { "const": "blocked" } }, "required": ["status", "blocked_evidence"] }
    },
    {
      "if": { "properties": { "contract_hash": { "type": "string" } }, "required": ["contract_hash"] },
      "then": { "required": ["contract_status"] }
    }
  ]
}
```

### Artifact Reference

Yang dikirim antar-agent adalah referensi, bukan isi (5A.6). Memperluas #17.

<!-- schema:artifact_ref -->
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:societas:1:artifact_ref",
  "title": "ArtifactRef",
  "type": "object",
  "additionalProperties": false,
  "required": ["id", "name", "kind", "checksum", "size_bytes", "version", "task_id", "created_by", "created_at"],
  "properties": {
    "id": { "$ref": "urn:societas:1:common#/$defs/art_id" },
    "name": { "type": "string", "minLength": 1, "maxLength": 255 },
    "kind": { "type": "string", "maxLength": 64,
          "description": "mis. markdown, json, diff, svg, text, approval_batch; approval_batch memvalidasi content dengan schema ApprovalBatch" },
    "path": { "type": "string", "maxLength": 1024 },
    "checksum": { "$ref": "urn:societas:1:common#/$defs/sha256" },
    "size_bytes": { "type": "integer", "minimum": 0 },
    "version": { "type": "integer", "minimum": 1 },
    "task_id": { "$ref": "urn:societas:1:common#/$defs/task_id" },
    "created_by": { "$ref": "urn:societas:1:common#/$defs/actor" },
    "created_at": { "$ref": "urn:societas:1:common#/$defs/ts" },
    "superseded_by": { "$ref": "urn:societas:1:common#/$defs/art_id",
                     "description": "opsional — tombstone #19.6; artifact basi, tidak boleh masuk context" },
    "staleness": { "type": "string", "enum": ["fresh", "stale"], "default": "fresh",
                   "description": "stale jika source_path/commit sudah tidak ada di main (#19.6)" },
    "source_path": { "type": "string", "maxLength": 1024,
                     "description": "path file repo sumber memori (#19.6)" },
    "source_commit": { "type": "string", "maxLength": 64 },
    "metadata": {
      "type": "object",
      "properties": {
        "merge_evidence": { "$ref": "urn:societas:1:merge_evidence" },
        "semantic_decision_index": { "$ref": "urn:societas:1:semantic_decision_index" },
        "approval_batch": { "$ref": "urn:societas:1:approval_batch" },
        "approval_batch_item_receipt": { "$ref": "urn:societas:1:approval_batch_item_receipt" },
        "merge_receipt": { "$ref": "urn:societas:1:merge_receipt" },
        "semantic_arbitration_decision": { "$ref": "urn:societas:1:semantic_arbitration_decision" }
      }
    }
  }
}
```

### Summary

Representasi ringkas dari artifact besar (5A.7). Wajib menunjuk artifact asli dan versinya.

<!-- schema:summary -->
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:societas:1:summary",
  "title": "Summary",
  "type": "object",
  "additionalProperties": false,
  "required": ["id", "artifact_id", "artifact_version", "token_estimate", "generated_by", "model", "body"],
  "properties": {
    "id": { "$ref": "urn:societas:1:common#/$defs/sum_id" },
    "artifact_id": { "$ref": "urn:societas:1:common#/$defs/art_id" },
    "artifact_version": { "type": "integer", "minimum": 1 },
    "token_estimate": { "type": "integer", "minimum": 0 },
    "generated_by": { "$ref": "urn:societas:1:common#/$defs/actor" },
    "model": { "type": "string" },
    "body": {
      "type": "object",
      "additionalProperties": false,
      "required": ["text"],
      "properties": {
        "text": { "type": "string", "maxLength": 8000 },
        "findings": { "type": "array", "items": { "type": "string" } },
        "risks": { "type": "array", "items": { "type": "string" } },
        "recommendation": { "type": "string" },
        "sources": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

## 72A.6 Task State Machine

Status task:

```text
pending            dibuat, menunggu dependency atau scheduler
ready              dependency selesai, budget sudah di-reserve, menunggu slot agent
running            agent sedang bekerja
pausing            transisi menuju paused; menunggu LLM/tool call in-flight selesai (cooperative pause)
paused             dijeda oleh pengguna; context terakhir dipertahankan untuk resume
interrupted        task berstatus running atau pausing saat boot; menunggu evaluasi Orchestrator
blocked            menunggu child task atau dependency saat berjalan
awaiting_approval  menunggu keputusan human
completed          selesai (terminal)
failed             gagal permanen (terminal)
cancelled          dibatalkan (terminal)
```

Transisi yang diizinkan (selain ini ditolak):

| Dari | Ke | Pemicu | Event |
|------|----|--------|-------|
| `pending` | `ready` | dependency selesai dan budget di-reserve | `task.assigned` |
| `pending` | `failed` | dependency gagal (`DEPENDENCY_FAILED`) | `task.failed` |
| `pending` | `cancelled` | dibatalkan | `task.cancelled` |
| `ready` | `running` | agent mulai | `task.started` |
| `ready` | `cancelled` | dibatalkan | `task.cancelled` |
| `running` | `blocked` | menunggu child/dependency, atau Semantic Rebase menemukan disonansi arsitektur/logika | `task.blocked` atau `task.semantic_conflict` |
| `running` | `awaiting_approval` | policy meminta approval; task diparkir, worker dilepas (step function, #40.1) | `approval.requested` |
| `running` | `paused` | klik pause di UI atau command tag `#TASK-xxx pause` (tanpa call in-flight) | `task.paused` |
| `running` | `pausing` | klik pause saat LLM/tool call masih in-flight | `task.paused` |
| `pausing` | `paused` | call in-flight selesai/di-settle | `task.paused` |
| `pausing` | `running` | pause dibatalkan sebelum settle | `task.resumed` |
| `pausing` | `interrupted` | proses restart saat call in-flight hilang (startup recovery) | `task.interrupted` |
| `pausing` | `failed` | call in-flight selesai dengan error fatal | `task.failed` |
| `pausing` | `cancelled` | dibatalkan | `task.cancelled` |
| `paused` | `running` | klik resume di UI atau command tag `#TASK-xxx resume` | `task.resumed` |
| `paused` | `cancelled` | dibatalkan atau TTL paused habis | `task.cancelled` |
| `running` | `interrupted` | startup recovery saat boot | `task.interrupted` |
| `interrupted` | `running` | resume disetujui Orchestrator (CAS pada status stored) | `task.resumed` |
| `interrupted` | `ready` | dijadwalkan ulang oleh Orchestrator | `task.retry_scheduled` |
| `interrupted` | `failed` | tidak dapat dilanjutkan | `task.failed` |
| `interrupted` | `cancelled` | dibatalkan | `task.cancelled` |
| `running` | `completed` | output diterima | `task.completed` |
| `running` | `ready` | error yang bisa di-retry, masih ada retry budget (`attempt + 1`) | `task.retry_scheduled` |
| `running` | `failed` | error final atau retry habis | `task.failed` |
| `running` | `cancelled` | dibatalkan | `task.cancelled` |
| `blocked` | `running` | child refactor/dependency semantic selesai dan kandidat kembali dijadwalkan | `task.started` |
| `blocked` | `failed` | yang ditunggu gagal | `task.failed` |
| `blocked` | `cancelled` | dibatalkan | `task.cancelled` |
| `awaiting_approval` | `ready` | approval granted + `bound_hash` valid; CAS lalu reschedule (#40.1, #40.2) | `approval.granted` |
| `awaiting_approval` | `ready` | approval invalidated; reschedule untuk refresh input/evidence, bukan izin eksekusi | `approval.invalidated` |
| `awaiting_approval` | `failed` | rejected atau timeout | `task.failed` |
| `awaiting_approval` | `cancelled` | dibatalkan | `task.cancelled` |

Resumption context: saat `paused -> running`, task **tidak dibuat ulang** — `id` tetap sama, budget tracking melanjutkan `budget.used` sebelumnya, dan Context Manager mengambil progress terakhir dari artefak tersimpan di Operational Store (SQLite, #37.1).

**Cooperative pause (`pausing`):** pause tidak memotong LLM/tool call yang sedang in-flight — call dibiarkan settle dulu (usage-nya tetap dicatat), baru status menjadi `paused`. Ini menjaga konsistensi `budget.reserved`/`budget.settled` (I4). Permintaan pause dan penyelesaian pause adalah dua fase berbeda pada `task.paused` (`phase: requested` dari `human:user`, `phase: completed` dari `system:orchestrator`). Permintaan tidak langsung mengubah state; Orchestrator memvalidasinya, menyimpan deadline absolut `pause_deadline` di Task/SQLite dan masuk `pausing`. Tanpa call in-flight, penyelesaian langsung menghasilkan `paused`. Event `phase: completed` baru terbit setelah settle. `task.resumed` tidak berasal langsung dari human: backend memvalidasi command resume lalu Orchestrator menerbitkan event.

**Startup recovery (`interrupted`):** saat boot, semua task berstatus `running` **dan `pausing`** di SQLite diubah menjadi `interrupted`, dan perubahan direkam sebagai event `task.interrupted` dengan `previous_status`. Task yang sudah terminal tidak diubah. Deadline pause tetap dipertahankan. Call tool yang sedang in-flight saat crash dianggap `outcome_unknown` (I16); jalur resume/retry wajib melewati pemeriksaan keamanan retry dan accounting I4. Orchestrator mengevaluasi tiap task — resume, retry ke `ready`, atau `failed` — memakai CAS pada status stored agar tidak bentrok dengan writer lain. Resume tidak mengulang mutasi yang belum diketahui hasilnya.

**Network failure auto-pause (I21):** ketika Go Runtime mendeteksi jaringan terputus melalui healthcheck deterministik (socket ping/HEAD request ke DNS publik), semua task aktif diubah menjadi `paused` via CAS pada SQLite dengan `phase: requested` dan `pause_deadline` disimpan. Worker pool dilepas untuk menghemat resource. Background daemon Go memantau pemulihan koneksi; begitu online kembali, Orchestrator menerbitkan `task.resumed` dan melanjutkan task dari checkpoint tersimpan tanpa duplikasi event. Tidak ada fallback router offline atau LLM yang dipanggil untuk diagnosa koneksi.

**Paused TTL:** deadline absolut berlaku bagi `pausing`, `paused`, dan `interrupted` yang masih membawa permintaan pause. Setelah deadline lewat -> `cancelled` via `task.cancelled`, termasuk saat startup. Cancel/TTL tidak membuktikan call in-flight batal atau belum berjalan; accounting dan rekonsiliasi efek tetap wajib. Resume yang sah membatalkan permintaan pause dan menghapus `pause_deadline`.

**Invalidasi kontrak (#17.1):** pada perubahan spec yang dipin, Orchestrator menerbitkan `task.contract_changed` untuk task nonterminal dengan `old_hash` = pin tersimpan dan `new_hash` = hash spec sekarang. Task menjadi `contract_status: stale`; tidak menambah status eksekusi baru. Call in-flight boleh settle, tetapi hasilnya tidak boleh dianggap output kontrak baru. Dispatch/resume, review, approval, dan `task.completed` ditolak selama stale. Gate/review/approval dengan hash lama tidak lagi valid. Runtime re-pin ke spec terbaru dan menjalankan codegen sebelum `contract_status` kembali `current`; review/approval yang diperlukan dijalankan ulang. Event `phase: repinned` merekam pin baru agar replay tidak bergantung pada nilai RAM. Jika spec berubah lagi selama codegen, tetap stale dan ulangi terhadap hash terbaru. Task terminal tidak dibuka kembali; pekerjaan lanjutan memakai task baru.

**Invalidasi approval:** `approval.invalidated` menutup request/grant lama di record approval SQLite tanpa menghapus event historis. ID approval tidak boleh di-rebind. Task yang diparkir dapat kembali `ready` untuk membangun input/evidence baru; event ini bukan grant dan tidak mengizinkan mutasi. Grant terlambat pada ID yang invalidated ditolak. Task terminal tidak dibuka kembali; perubahan sesudah aksi yang sudah terkonfirmasi bukan invalidasi retroaktif/rollback.

## 72A.7 Event Registry

Memperluas daftar event di #11. Setiap `type` punya tepat satu schema payload. Event di luar tabel ini ditolak (I9).

| `type` | Schema payload | Dari → Ke |
|--------|----------------|-----------|
| `workspace.created` | `workspace_created` | `system:*` → `topic:all` |
| `agent.created` | `agent_lifecycle` | `system:orchestrator` → `topic:all` |
| `agent.started` | `agent_lifecycle` | `system:scheduler` → `topic:all` |
| `agent.stopped` | `agent_lifecycle` | `system:scheduler` → `topic:all` |
| `run.created` | `run_created` | `human` → `system:orchestrator` |
| `run.stopped` | `run_stopped` | `system:orchestrator` → `human` |
| `task.delegate_requested` | `delegate_requested` | `agent` → `system:orchestrator` |
| `task.delegate_rejected` | `delegate_rejected` | `system:orchestrator` → `agent` |
| `task.created` | `task_created` | `system:orchestrator` → `agent` (owner) |
| `task.assigned` | `task_assigned` | `system:scheduler` → `agent` |
| `task.started` | `task_started` | `agent` → `system:orchestrator` |
| `task.blocked` | `task_blocked` | `agent` → `system:orchestrator` |
| `task.semantic_conflict` | `task_semantic_conflict` | `system:orchestrator` → `agent` (owner) + `agent` (escalation_lead) / `human:user` |
| `task.paused` | `task_paused` | phase=`requested`: `human:user` → `system:orchestrator`; phase=`completed`: `system:orchestrator` → `topic:all` |
| `task.resumed` | `task_resumed` | `system:orchestrator` → `agent` |
| `task.interrupted` | `task_interrupted` | `system:orchestrator` → `topic:all` |
| `task.rebase_conflict` | `task_rebase_conflict` | `system:orchestrator` → `agent` (owner) |
| `task.contract_changed` | `task_contract_changed` | `system:orchestrator` → `agent` (owner) |
| `task.completed` | `task_completed` | `agent` → `system:orchestrator` |
| `task.failed` | `task_failed` | `system:orchestrator` → `topic:all` |
| `task.cancelled` | `task_cancelled` | `system:orchestrator` → `topic:all` |
| `task.retry_scheduled` | `task_retry_scheduled` | `system:orchestrator` → `agent` |
| `message.sent` | `message_sent` | `agent` → `agent` (dimediasi Event Bus) |
| `message.received` | `message_received` | `agent` → `system:event_bus` |
| `context.built` | `context_built` | `system:context` → `agent` |
| `model.selected` | `model_selected` | `system:router` → `agent` |
| `model.call_started` | `model_call_started` | `system:router` → `topic:all` |
| `model.call_completed` | `model_call_completed` | `system:router` → `agent` |
| `model.call_failed` | `model_call_failed` | `system:router` → `agent` |
| `budget.reserved` | `budget_reserved` | `system:budget` → `topic:all` |
| `budget.settled` | `budget_settled` | `system:budget` → `topic:all` |
| `budget.warning` | `budget_warning` | `system:budget` → `human` |
| `budget.exceeded` | `budget_exceeded` | `system:budget` → `system:orchestrator` |
| `policy.evaluated` | `policy_evaluated` | `system:policy` → `topic:all` |
| `tool.call_requested` | `tool_call_requested` | `agent` → `system:tool_runtime` |
| `tool.call_started` | `tool_call_started` | `system:tool_runtime` → `topic:all` |
| `tool.call_completed` | `tool_call_completed` | `system:tool_runtime` → `agent` |
| `tool.call_failed` | `tool_call_failed` | `system:tool_runtime` → `agent` |
| `artifact.created` | `artifact_created` | `agent` → `topic:all` |
| `artifact.updated` | `artifact_updated` | `agent` → `topic:all` |
| `summary.created` | `summary_created` | `system:summarizer` → `topic:all` |
| `review.requested` | `review_requested` | `agent` → `system:orchestrator` |
| `review.completed` | `review_completed` | `agent` → `system:orchestrator` |
| `approval.requested` | `approval_requested` | `system:policy` → `human` |
| `approval.granted` | `approval_granted` | `human` → `system:policy` |
| `approval.rejected` | `approval_rejected` | `human` → `system:policy` |
| `approval.invalidated` | `approval_invalidated` | `system:orchestrator` → `human:user` |
| `approval.batch_submitted` | `approval_batch_submitted` | `human:user` → `system:orchestrator` |

## 72A.8 Payload Schemas

### Run

<!-- schemas:run -->
```json
[
  {
    "$id": "urn:societas:1:run_created",
    "type": "object", "additionalProperties": false, "required": ["goal"],
    "properties": {
      "goal": { "type": "string", "minLength": 1, "maxLength": 4000 },
      "entry_agent": { "$ref": "urn:societas:1:common#/$defs/agent_id" },
      "budget_request": { "$ref": "urn:societas:1:budget" }
    }
  },
  {
    "$id": "urn:societas:1:run_stopped",
    "type": "object", "additionalProperties": false, "required": ["reason", "totals"],
    "properties": {
      "reason": { "enum": ["success", "budget_exhausted", "timeout", "human_rejected",
                           "critical_tool_failure", "dependency_failed",
                           "max_iterations", "cancelled_by_user"] },
      "totals": { "$ref": "urn:societas:1:usage_totals" },
      "result_artifact_id": { "$ref": "urn:societas:1:common#/$defs/art_id" },
      "error": { "$ref": "urn:societas:1:error" }
    }
  },
  {
    "$id": "urn:societas:1:workspace_created",
    "type": "object", "additionalProperties": false, "required": ["name"],
    "properties": { "name": { "type": "string", "minLength": 1, "maxLength": 100 } }
  },
  {
    "$id": "urn:societas:1:agent_lifecycle",
    "type": "object", "additionalProperties": false, "required": ["agent_id"],
    "properties": {
      "agent_id": { "$ref": "urn:societas:1:common#/$defs/agent_id" },
      "reason": { "type": "string", "maxLength": 500 }
    }
  }
]
```

### Delegation

Agent hanya **meminta**. `budget_request` adalah permintaan, bukan pemberian. Budget yang sebenarnya muncul di `task.created` (`task.budget.granted`), dan tidak pernah lebih besar dari sisa parent (I3).

`rationale` wajib. Ini yang membuat workflow bisa menjawab "mengapa agent ini dipanggil" (lihat #105).

<!-- schemas:delegation -->
```json
[
  {
    "$id": "urn:societas:1:delegate_requested",
    "type": "object", "additionalProperties": false,
    "required": ["title", "goal", "rationale", "expected_output", "priority"],
    "properties": {
      "title": { "type": "string", "minLength": 1, "maxLength": 200 },
      "goal": { "type": "string", "minLength": 1, "maxLength": 4000 },
      "rationale": { "type": "string", "minLength": 1, "maxLength": 1000 },
      "requested_assignee": {
        "oneOf": [
          { "$ref": "urn:societas:1:common#/$defs/agent_id" },
          { "type": "null" }
        ],
        "description": "ID agen tujuan — divalidasi terhadap enum dinamis ID agen aktif workspace.yaml (constrained decoding, 5A.8). null = Blind Delegation: sistem yang menentukan eksekutor terbaik via Jev AI (72A.10)."
      },
      "expected_output": {
        "type": "object", "additionalProperties": false, "required": ["kind"],
        "properties": {
          "kind": { "enum": ["artifact", "summary", "decision", "patch"] },
          "format": { "type": "string", "maxLength": 64 }
        }
      },
      "priority": { "$ref": "urn:societas:1:common#/$defs/priority" },
      "complexity_hint": { "enum": ["low", "medium", "high"] },
      "dependencies": { "type": "array", "uniqueItems": true,
                        "items": { "$ref": "urn:societas:1:common#/$defs/task_id" } },
      "deadline": { "$ref": "urn:societas:1:common#/$defs/ts" },
      "context_hints": {
        "type": "object", "additionalProperties": false,
        "properties": {
          "artifact_ids": { "type": "array", "items": { "$ref": "urn:societas:1:common#/$defs/art_id" } },
          "memory_queries": { "type": "array", "maxItems": 5, "items": { "type": "string", "maxLength": 200 } }
        }
      },
      "budget_request": { "$ref": "urn:societas:1:budget" }
    }
  },
  {
    "$id": "urn:societas:1:delegate_rejected",
    "type": "object", "additionalProperties": false, "required": ["request_event_id", "error"],
    "properties": {
      "request_event_id": { "$ref": "urn:societas:1:common#/$defs/evt_id" },
      "error": { "$ref": "urn:societas:1:error" }
    }
  },
  {
    "$id": "urn:societas:1:task_created",
    "type": "object", "additionalProperties": false, "required": ["task"],
    "properties": { "task": { "$ref": "urn:societas:1:task" } }
  },
  {
    "$id": "urn:societas:1:task_assigned",
    "type": "object", "additionalProperties": false, "required": ["task_id", "agent_id"],
    "properties": {
      "task_id": { "$ref": "urn:societas:1:common#/$defs/task_id" },
      "agent_id": { "$ref": "urn:societas:1:common#/$defs/agent_id" }
    }
  }
]
```

### Task Lifecycle

<!-- schemas:task_lifecycle -->
```json
[
  {
    "$id": "urn:societas:1:task_started",
    "type": "object", "additionalProperties": false, "required": ["attempt"],
    "properties": { "attempt": { "type": "integer", "minimum": 1 } }
  },
  {
    "$id": "urn:societas:1:task_blocked",
    "type": "object", "additionalProperties": false, "required": ["waiting_on"],
    "properties": {
      "waiting_on": {
        "type": "array", "minItems": 1,
        "items": { "oneOf": [ { "$ref": "urn:societas:1:common#/$defs/task_id" },
                              { "$ref": "urn:societas:1:common#/$defs/apr_id" } ] }
      }
    }
  },
  {
    "$id": "urn:societas:1:task_semantic_conflict",
    "type": "object", "additionalProperties": false,
    "required": ["outcome", "semantic_evidence", "blocked_evidence", "decision_refs", "conflict_summary", "escalation_lead"],
    "properties": {
      "outcome": { "enum": ["conflict", "inconclusive"] },
      "semantic_evidence": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
      "blocked_evidence": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
      "decision_refs": {
        "type": "array", "minItems": 2, "uniqueItems": true,
        "items": {
          "type": "object", "additionalProperties": false,
          "required": ["role", "artifact_ref"],
          "properties": {
            "role": { "enum": ["base", "candidate"] },
            "artifact_ref": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" }
          }
        }
      },
      "conflict_summary": { "type": "string", "minLength": 1, "maxLength": 2000 },
      "escalation_lead": { "oneOf": [
        { "$ref": "urn:societas:1:common#/$defs/agent_id" },
        { "const": "human" }
      ] }
    },
    "allOf": [
      { "properties": { "decision_refs": { "contains": { "properties": { "role": { "const": "base" } }, "required": ["role"] } } } },
      { "properties": { "decision_refs": { "contains": { "properties": { "role": { "const": "candidate" } }, "required": ["role"] } } } }
    ]
  },
  {
    "$id": "urn:societas:1:task_paused",
    "type": "object", "additionalProperties": false,
    "required": ["phase", "initiated_by", "pause_deadline"],
    "properties": {
      "phase": { "enum": ["requested", "completed"],
                 "description": "requested = command pause dari human; completed = pause settle oleh Orchestrator setelah call in-flight selesai (#40.1)" },
      "initiated_by": { "const": "human:user" },
      "reason": { "type": "string", "maxLength": 500 },
      "in_flight_call_id": { "$ref": "urn:societas:1:common#/$defs/tc_id",
                             "description": "call yang ditunggu settle saat phase=requested (pause kooperatif)" },
      "pause_deadline": { "$ref": "urn:societas:1:common#/$defs/ts",
                          "description": "TTL paused, dipersist di SQLite — bukan timer RAM (W02)" }
    }
  },
  {
    "$id": "urn:societas:1:task_resumed",
    "type": "object", "additionalProperties": false,
    "required": ["initiated_by", "from_status"],
    "properties": {
      "initiated_by": { "enum": ["human:user", "system:orchestrator"],
                        "description": "human:user (klik resume) atau system:orchestrator (recovery)" },
      "reason": { "type": "string", "maxLength": 500 },
      "from_status": { "enum": ["pausing", "paused", "interrupted"],
                       "description": "state sebelum resume — dipakai rekonsiliasi call in-flight (W02)" }
    }
  },
  {
    "$id": "urn:societas:1:task_interrupted",
    "type": "object", "additionalProperties": false,
    "required": ["previous_status", "reason"],
    "properties": {
      "previous_status": { "enum": ["running", "pausing"] },
      "reason": { "type": "string", "maxLength": 500 },
      "in_flight_call_id": { "$ref": "urn:societas:1:common#/$defs/tc_id",
                             "description": "call tool yang hilang saat crash — direkonsiliasi sebelum resume (I16); model call diidentifikasi lewat record reservasi/event terkait" }
    }
  },
  {
    "$id": "urn:societas:1:task_rebase_conflict",
    "type": "object", "additionalProperties": false,
    "required": ["conflict_files", "base_ref"],
    "properties": {
      "conflict_files": { "type": "array", "minItems": 1,
                          "items": { "type": "string", "maxLength": 1024 } },
      "base_ref": { "type": "string", "maxLength": 128,
                    "description": "ref base saat rebase dicoba (#60.4)" }
    }
  },
  {
    "$id": "urn:societas:1:task_contract_changed",
    "type": "object", "additionalProperties": false,
    "required": ["phase", "old_hash", "new_hash"],
    "properties": {
      "phase": { "enum": ["invalidated", "repinned"] },
      "old_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
      "new_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
      "required_actions": { "type": "array", "minItems": 1, "uniqueItems": true,
                            "items": { "enum": ["recodegen", "rereview", "reapproval"] } }
    },
    "if": { "properties": { "phase": { "const": "invalidated" } }, "required": ["phase"] },
    "then": {
      "required": ["required_actions"],
      "properties": { "required_actions": { "contains": { "const": "recodegen" } } }
    },
    "else": { "not": { "required": ["required_actions"] } }
  },
  {
    "$id": "urn:societas:1:task_completed",
    "type": "object", "additionalProperties": false, "required": ["result_status"],
    "properties": {
      "result_status": { "enum": ["success", "partial"] },
      "artifact_ids": { "type": "array", "items": { "$ref": "urn:societas:1:common#/$defs/art_id" } },
      "summary_ids": { "type": "array", "items": { "$ref": "urn:societas:1:common#/$defs/sum_id" } },
      "usage": { "$ref": "urn:societas:1:usage_totals" }
    }
  },
  {
    "$id": "urn:societas:1:task_failed",
    "type": "object", "additionalProperties": false, "required": ["error"],
    "properties": {
      "error": { "$ref": "urn:societas:1:error" },
      "usage": { "$ref": "urn:societas:1:usage_totals" }
    }
  },
  {
    "$id": "urn:societas:1:task_cancelled",
    "type": "object", "additionalProperties": false, "required": ["cancelled_by"],
    "properties": {
      "cancelled_by": { "$ref": "urn:societas:1:common#/$defs/actor" },
      "reason": { "type": "string", "maxLength": 500 }
    }
  },
  {
    "$id": "urn:societas:1:task_retry_scheduled",
    "type": "object", "additionalProperties": false, "required": ["attempt", "delay_ms", "error"],
    "properties": {
      "attempt": { "type": "integer", "minimum": 2 },
      "delay_ms": { "type": "integer", "minimum": 0 },
      "error": { "$ref": "urn:societas:1:error" }
    }
  }
]
```

### Messaging

Percakapan antar-agent (#16) tetap ada, tetapi dimediasi Event Bus (I1), dibatasi `max_agent_messages`, dan konten besar harus menjadi artifact (I5).

<!-- schemas:messaging -->
```json
[
  {
    "$id": "urn:societas:1:message_sent",
    "type": "object", "additionalProperties": false,
    "required": ["message_id", "conversation_id", "text"],
    "properties": {
      "message_id": { "$ref": "urn:societas:1:common#/$defs/msg_id" },
      "conversation_id": { "$ref": "urn:societas:1:common#/$defs/conv_id" },
      "text": { "type": "string", "minLength": 1, "maxLength": 8000 },
      "priority": { "$ref": "urn:societas:1:common#/$defs/priority" },
      "artifact_ids": { "type": "array", "items": { "$ref": "urn:societas:1:common#/$defs/art_id" } },
      "reply_to": { "$ref": "urn:societas:1:common#/$defs/msg_id" },
      "expects_reply": { "type": "boolean" }
    }
  },
  {
    "$id": "urn:societas:1:message_received",
    "type": "object", "additionalProperties": false, "required": ["message_id"],
    "properties": { "message_id": { "$ref": "urn:societas:1:common#/$defs/msg_id" } }
  }
]
```

### Control Plane

<!-- schemas:control_plane -->
```json
[
  {
    "$id": "urn:societas:1:context_built",
    "type": "object", "additionalProperties": false,
    "required": ["agent_id", "token_budget", "tokens_used", "items"],
    "properties": {
      "agent_id": { "$ref": "urn:societas:1:common#/$defs/agent_id" },
      "token_budget": { "type": "integer", "minimum": 1 },
      "tokens_used": { "type": "integer", "minimum": 0 },
      "items": {
        "type": "array",
        "items": {
          "type": "object", "additionalProperties": false,
          "required": ["kind", "ref", "tokens", "reason"],
          "properties": {
            "kind": { "enum": ["system_prompt", "role", "task", "memory", "artifact", "message", "tool_result"] },
            "ref": { "type": "string", "maxLength": 200 },
            "tokens": { "type": "integer", "minimum": 0 },
            "reason": { "type": "string", "maxLength": 300 }
          }
        }
      },
      "dropped": {
        "type": "array",
        "items": {
          "type": "object", "additionalProperties": false,
          "required": ["kind", "ref", "reason"],
          "properties": {
            "kind": { "type": "string" },
            "ref": { "type": "string", "maxLength": 200 },
            "reason": { "enum": ["over_budget", "low_relevance", "duplicate", "untrusted"] }
          }
        }
      }
    }
  },
  {
    "$id": "urn:societas:1:model_selected",
    "type": "object", "additionalProperties": false,
    "required": ["agent_id", "model", "tier", "reason"],
    "properties": {
      "agent_id": { "$ref": "urn:societas:1:common#/$defs/agent_id" },
      "model": { "type": "string" },
      "tier": { "$ref": "urn:societas:1:common#/$defs/tier" },
      "reason": { "type": "string", "maxLength": 300 },
      "escalated_from": { "type": ["string", "null"] }
    }
  },
  {
    "$id": "urn:societas:1:model_call_started",
    "type": "object", "additionalProperties": false, "required": ["model", "tier", "reservation_id"],
    "properties": {
      "model": { "type": "string" },
      "tier": { "$ref": "urn:societas:1:common#/$defs/tier" },
      "reservation_id": { "type": "string" }
    }
  },
  {
    "$id": "urn:societas:1:model_call_completed",
    "type": "object", "additionalProperties": false, "required": ["usage", "finish_reason"],
    "properties": {
      "usage": { "$ref": "urn:societas:1:usage" },
      "finish_reason": { "enum": ["stop", "length", "tool_use", "error"] },
      "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
    }
  },
  {
    "$id": "urn:societas:1:model_call_failed",
    "type": "object", "additionalProperties": false, "required": ["error", "executed"],
    "properties": {
      "error": { "$ref": "urn:societas:1:error" },
      "executed": { "type": "boolean",
                    "description": "false jika Token Guard menolak sebelum model dipanggil." }
    }
  },
  {
    "$id": "urn:societas:1:budget_reserved",
    "type": "object", "additionalProperties": false,
    "required": ["scope", "scope_id", "reservation_id", "max_tokens", "max_cost_usd"],
    "properties": {
      "scope": { "$ref": "urn:societas:1:common#/$defs/scope" },
      "scope_id": { "type": "string" },
      "reservation_id": { "type": "string" },
      "max_tokens": { "type": "integer", "minimum": 0 },
      "max_cost_usd": { "type": "number", "minimum": 0 }
    }
  },
  {
    "$id": "urn:societas:1:budget_settled",
    "type": "object", "additionalProperties": false,
    "required": ["scope", "scope_id", "reservation_id", "usage", "remaining"],
    "properties": {
      "scope": { "$ref": "urn:societas:1:common#/$defs/scope" },
      "scope_id": { "type": "string" },
      "reservation_id": { "type": "string" },
      "usage": { "$ref": "urn:societas:1:usage" },
      "remaining": {
        "type": "object", "additionalProperties": false,
        "properties": {
          "total_tokens": { "type": "integer", "minimum": 0 },
          "cost_usd": { "type": "number", "minimum": 0 },
          "model_calls": { "type": "integer", "minimum": 0 }
        }
      }
    }
  },
  {
    "$id": "urn:societas:1:budget_warning",
    "type": "object", "additionalProperties": false,
    "required": ["scope", "scope_id", "threshold", "used_ratio"],
    "properties": {
      "scope": { "$ref": "urn:societas:1:common#/$defs/scope" },
      "scope_id": { "type": "string" },
      "threshold": { "type": "number", "minimum": 0, "maximum": 1 },
      "used_ratio": { "type": "number", "minimum": 0 }
    }
  },
  {
    "$id": "urn:societas:1:budget_exceeded",
    "type": "object", "additionalProperties": false,
    "required": ["scope", "scope_id", "limit", "error"],
    "properties": {
      "scope": { "$ref": "urn:societas:1:common#/$defs/scope" },
      "scope_id": { "type": "string" },
      "limit": { "type": "string", "pattern": "^max_[a-z_]+$" },
      "error": { "$ref": "urn:societas:1:error" }
    }
  },
  {
    "$id": "urn:societas:1:policy_evaluated",
    "type": "object", "additionalProperties": false,
    "required": ["action", "decision", "rule_id", "reason"],
    "properties": {
      "action": { "type": "string", "maxLength": 200,
                  "description": "mis. tool.call:shell.exec, agent.create, network.access" },
      "decision": { "enum": ["allow", "require_approval", "deny"] },
      "rule_id": { "type": "string", "maxLength": 100 },
      "reason": { "type": "string", "maxLength": 500 },
      "approval_id": { "$ref": "urn:societas:1:common#/$defs/apr_id" }
    }
  }
]
```

### Tool Call

Memperluas #63. Output besar tidak boleh inline: simpan sebagai artifact dan isi `output_artifact_id`.

Capability tepercaya per tool memiliki dua boolean: `idempotent` dan `operation_key_enforced`, keduanya default `false` bila tidak dikonfigurasi (#21). Ini bukan deklarasi agen atau field payload. `operation_key_enforced: true` hanya sah dengan jaminan penyedia yang diketahui runtime, termasuk periode retensinya. Runtime menyimpan key sebelum dispatch pertama dan memakai key + argumen yang sama pada retry; setelah masa jaminan habis, rekonsiliasi/human diperlukan. Key dibatasi ke provider/principal/operasi yang benar dan tidak boleh dipakai ulang untuk argumen berbeda. Key yang baru ditambahkan sesudah timeout tidak melindungi dispatch pertama.

<!-- schemas:tool -->
```json
[
  {
    "$id": "urn:societas:1:tool_call_requested",
    "type": "object", "additionalProperties": false,
    "required": ["tool_call_id", "tool", "arguments"],
    "properties": {
      "tool_call_id": { "$ref": "urn:societas:1:common#/$defs/tc_id" },
      "tool": { "$ref": "urn:societas:1:common#/$defs/tool_name" },
      "arguments": { "type": "object" },
      "timeout_ms": { "type": "integer", "minimum": 1 },
      "operation_key": { "type": "string", "minLength": 1, "maxLength": 128,
                         "description": "kunci deduplikasi stabil sejak percobaan pertama; hanya menjamin retry jika provider benar-benar menegakkan deduplikasi (I16)" }
    }
  },
  {
    "$id": "urn:societas:1:tool_call_started",
    "type": "object", "additionalProperties": false, "required": ["tool_call_id"],
    "properties": { "tool_call_id": { "$ref": "urn:societas:1:common#/$defs/tc_id" } }
  },
  {
    "$id": "urn:societas:1:tool_call_completed",
    "type": "object", "additionalProperties": false,
    "required": ["tool_call_id", "status", "duration_ms"],
    "properties": {
      "tool_call_id": { "$ref": "urn:societas:1:common#/$defs/tc_id" },
      "status": { "enum": ["ok", "error"] },
      "output": { "type": ["string", "object"], "maxLength": 16000,
                  "description": "string atau object; seluruh payload harus <=16.000 byte UTF-8 setelah serialisasi 72A.12, termasuk overhead JSON — maxLength saja tidak membatasi object" },
      "output_artifact_id": { "$ref": "urn:societas:1:common#/$defs/art_id" },
      "truncated": { "type": "boolean" },
      "duration_ms": { "type": "integer", "minimum": 0 },
      "error": { "$ref": "urn:societas:1:error" }
    },
    "if": { "properties": { "status": { "const": "error" } }, "required": ["status"] },
    "then": { "required": ["error"] }
  },
  {
    "$id": "urn:societas:1:tool_call_failed",
    "type": "object", "additionalProperties": false, "required": ["tool_call_id", "error", "outcome"],
    "properties": {
      "tool_call_id": { "$ref": "urn:societas:1:common#/$defs/tc_id" },
      "error": { "$ref": "urn:societas:1:error" },
      "outcome": { "enum": ["not_started", "outcome_unknown"],
                   "description": "not_started = tool pasti belum berjalan; outcome_unknown = request mungkin sudah dieksekusi tapi response hilang (I16)" },
      "duration_ms": { "type": "integer", "minimum": 0 }
    }
  }
]
```

Tiga outcome kegagalan tool, dan konsekuensinya (I16):

- **`completed`** — tool berjalan dan mengembalikan hasil gagal secara logis (exit code non-nol, hasil error) -> `tool.call_completed` dengan `status: "error"`.
- **`not_started`** — tool pasti belum berjalan (ditolak policy, input invalid, sandbox gagal start) -> `tool.call_failed` `outcome: not_started`. Aman di-retry sesuai katalog 72A.9.
- **`outcome_unknown`** — request mungkin sudah dieksekusi tapi response hilang (`TOOL_TIMEOUT`, `NETWORK_ERROR`) -> `tool.call_failed` `outcome: outcome_unknown`. **Retry otomatis dilarang** kecuali capability tool tepercaya menyatakan `idempotent` atau provider menegakkan `operation_key` yang sama sejak dispatch pertama. Tanpa jaminan itu: rekonsiliasi atau keputusan human yang menjelaskan risiko duplikasi, bukan retry buta. `error.retryable: true` tidak dapat mengalahkan I16; flag itu hanya kelayakan kandidat retry dan tetap tunduk pada policy/budget. Deduplikasi I7 hanya melindungi event internal, bukan server tool.

### Artifact, Summary, Review

<!-- schemas:artifact_review -->
```json
[
  {
    "$id": "urn:societas:1:artifact_created",
    "type": "object", "additionalProperties": false, "required": ["artifact"],
    "properties": { "artifact": { "$ref": "urn:societas:1:artifact_ref" } }
  },
  {
    "$id": "urn:societas:1:artifact_updated",
    "type": "object", "additionalProperties": false, "required": ["artifact", "previous_version"],
    "properties": {
      "artifact": { "$ref": "urn:societas:1:artifact_ref" },
      "previous_version": { "type": "integer", "minimum": 1 }
    }
  },
  {
    "$id": "urn:societas:1:summary_created",
    "type": "object", "additionalProperties": false, "required": ["summary"],
    "properties": { "summary": { "$ref": "urn:societas:1:summary" } }
  },
  {
    "$id": "urn:societas:1:review_requested",
    "type": "object", "additionalProperties": false, "required": ["artifact_ids"],
    "properties": {
      "artifact_ids": { "type": "array", "minItems": 1, "items": { "$ref": "urn:societas:1:common#/$defs/art_id" } },
      "criteria": { "type": "array", "items": { "type": "string", "maxLength": 300 } },
      "merge_binding": { "$ref": "urn:societas:1:approval_snapshot#/$defs/merge_binding" }
    }
  },
  {
    "$id": "urn:societas:1:review_completed",
    "type": "object", "additionalProperties": false, "required": ["verdict"],
    "properties": {
      "verdict": { "enum": ["approve", "request_changes", "reject"] },
      "findings": {
        "type": "array",
        "items": {
          "type": "object", "additionalProperties": false, "required": ["severity", "text"],
          "properties": {
            "severity": { "enum": ["info", "minor", "major", "blocker"] },
            "text": { "type": "string", "maxLength": 1000 }
          }
        }
      },
      "artifact_id": { "$ref": "urn:societas:1:common#/$defs/art_id" },
      "merge_binding": { "$ref": "urn:societas:1:approval_snapshot#/$defs/merge_binding" }
    }
  }
]
```

### Approval

Memperluas #23 dan [5A.21 — Approval Escalation](02-ai-control-plane.md#5a21-approval-escalation). Pilihan human dipetakan ke `scope`:

| Pilihan di UI | `decision` | `scope` |
|---------------|-----------|---------|
| Approve Once | `approval.granted` | `once` (hanya aksi ini) |
| Approve For Task | `approval.granted` | `task` (aksi sejenis dalam task ini) |
| Approve | `approval.granted` | `run` (aksi sejenis dalam run ini) |
| Reject | `approval.rejected` | n/a |

Untuk approval yang dipicu budget, human boleh menyertakan `budget_override`. Hanya jalur ini yang dapat menaikkan budget (I14).

### Digest Approval (I18)

Policy Engine menentukan `risk` dan `delivery_mode`; agen tidak dapat memilih jalur approval. Task `risk_tier: normal` dipetakan ke wire `risk: medium`; `critical` tetap literal `critical`. Critical selalu `delivery_mode: immediate` dan menghentikan mutasi/dependency yang terdampak, bukan menghentikan seluruh workspace. Hanya request high yang boleh memakai `delivery_mode: digest`; low/medium dan mode immediate tetap diputus individual. Mode ini mengatur penyajian/atensi, tidak mengubah permission, sandbox, snapshot binding, atau kondisi dispatch.

Digest adalah artifact `kind: approval_batch`, content tervalidasi schema `approval_batch`, dengan bytes JCS immutable per workspace/run. `batch_hash = "sha256:" + hex_lower(SHA256(JCS(batch)))`; `batch_ref.checksum` wajib sama dengan `batch_hash`. Item diurutkan naik berdasarkan UTF-16 `approval_id`; ID approval duplikat ditolak. `metadata.approval_batch` hanya indeks konten artifact yang sama, bukan sumber otorisasi lain. Summary Manager membentuk kartu dari manifest dan snapshot tersimpan; ringkasan LLM hanya teks penjelas. Item baru/perubahan membership memerlukan artifact, hash, dan klik baru.

**Approve All Validated** mengirim `approval.batch_submitted` dengan hash dan versi manifest yang ditampilkan. Backend memvalidasi artifact/hash/JCS/schema, workspace/run dan principal sebelum memproses item; manifest hilang, tampered, duplikat, atau foreign ditolak sebagai satu command tanpa grant. Setiap item kemudian dicek sendiri: request tersimpan, ID/hash/snapshot_ref/task cocok; `risk: high`, `delivery_mode: digest`, policy masih high/digest, status pending; expiry, task nonterminal/current, live input, policy, contract, dan evidence masih cocok. Item invalid/expired/stale/already-granted atau berubah menjadi critical dilewati (binding berubah memicu invalidation), bukan auto-approved atau fallback ke immediate. Item valid menghasilkan `approval.granted` normal dengan ID/hash aslinya, `scope: once`, `granted_by: human:user`, dan causation ke command batch. CAS `awaiting_approval → ready` dan dispatch tetap per item; hasil parsial menampilkan status/alasan setiap item.

Replay/double-click memakai I7, binding ID/hash, dan receipt durable per item; pemrosesan ulang tidak boleh memberi grant atau mengeksekusi aksi dua kali. Tidak ada merge lock yang ditahan selama digest/grant. Dua merge yang disetujui dalam satu digest tetap bersaing pada expected-base CAS; kandidat kedua yang stale harus mengulang gate/review/approval. Interval/akhir siklus hanya pemicu digest, bukan perpanjangan expiry atau approval implisit. Receipt pemrosesan tahan-crash lintas event/SQLite masih bagian keputusan recovery W06, bukan klaim sudah terimplementasi.

### Snapshot Input Approval (I17)

Snapshot disusun runtime tepercaya, bukan teks keputusan agen. `action` adalah identifier mesin; `reason`/`details` pada request hanya tampilan dan tidak dapat menggantikan input snapshot.

<!-- schemas:approval_binding -->
```json
[
  {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:societas:1:approval_snapshot",
    "type": "object", "additionalProperties": false,
    "required": ["snapshot_version", "workspace_id", "run_id", "task_id", "action",
                 "policy_hash", "contract_hash", "inputs"],
    "properties": {
      "snapshot_version": { "const": "approval-snapshot/1" },
      "workspace_id": { "$ref": "urn:societas:1:envelope#/properties/workspace_id" },
      "run_id": { "$ref": "urn:societas:1:common#/$defs/run_id" },
      "task_id": { "oneOf": [
        { "$ref": "urn:societas:1:common#/$defs/task_id" }, { "type": "null" }
      ] },
      "action": { "enum": ["git.merge", "tool.execute", "budget.increase"] },
      "policy_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
      "contract_hash": { "$ref": "#/$defs/nullable_hash" },
      "inputs": { "type": "object" }
    },
    "allOf": [
      {
        "if": { "properties": { "action": { "const": "git.merge" } }, "required": ["action"] },
        "then": { "properties": {
          "task_id": { "$ref": "urn:societas:1:common#/$defs/task_id" },
          "inputs": { "$ref": "#/$defs/merge_inputs" }
        } }
      },
      {
        "if": { "properties": { "action": { "const": "tool.execute" } }, "required": ["action"] },
        "then": { "properties": {
          "task_id": { "$ref": "urn:societas:1:common#/$defs/task_id" },
          "inputs": { "$ref": "#/$defs/tool_inputs" }
        } }
      },
      {
        "if": { "properties": { "action": { "const": "budget.increase" } }, "required": ["action"] },
        "then": { "properties": { "inputs": { "$ref": "#/$defs/budget_inputs" } } }
      }
    ],
    "$defs": {
      "nullable_hash": { "oneOf": [
        { "$ref": "urn:societas:1:common#/$defs/sha256" }, { "type": "null" }
      ] },
      "artifact_version": {
        "type": "object", "additionalProperties": false,
        "required": ["artifact_id", "version", "checksum"],
        "properties": {
          "artifact_id": { "$ref": "urn:societas:1:common#/$defs/art_id" },
          "version": { "type": "integer", "minimum": 1 },
          "checksum": { "$ref": "urn:societas:1:common#/$defs/sha256" }
        }
      },
      "git_oid": { "type": "string", "pattern": "^([0-9a-f]{40}|[0-9a-f]{64})$" },
      "merge_candidate": {
        "type": "object", "additionalProperties": false,
        "required": ["repo_id", "target_ref", "expected_base", "candidate_commit",
                     "candidate_tree", "gate_recipe_hash"],
        "properties": {
          "repo_id": { "type": "string", "minLength": 1, "maxLength": 128 },
          "target_ref": { "type": "string", "pattern": "^refs/heads/.+", "maxLength": 256 },
          "expected_base": { "$ref": "#/$defs/git_oid" },
          "candidate_commit": { "$ref": "#/$defs/git_oid" },
          "candidate_tree": { "$ref": "#/$defs/git_oid" },
          "gate_recipe_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" }
        }
      },
      "merge_binding": {
        "type": "object", "additionalProperties": false,
        "required": ["workspace_id", "run_id", "task_id", "policy_hash", "contract_hash", "candidate"],
        "properties": {
          "workspace_id": { "$ref": "urn:societas:1:envelope#/properties/workspace_id" },
          "run_id": { "$ref": "urn:societas:1:common#/$defs/run_id" },
          "task_id": { "$ref": "urn:societas:1:common#/$defs/task_id" },
          "policy_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
          "contract_hash": { "$ref": "#/$defs/nullable_hash" },
          "candidate": { "$ref": "#/$defs/merge_candidate" }
        }
      },
      "merge_inputs": {
        "type": "object", "additionalProperties": false,
        "required": ["candidate", "semantic_evidence", "gate_evidence", "review_evidence"],
        "properties": {
          "candidate": { "$ref": "#/$defs/merge_candidate" },
          "semantic_evidence": { "$ref": "#/$defs/artifact_version" },
          "gate_evidence": { "$ref": "#/$defs/artifact_version" },
          "review_evidence": { "$ref": "#/$defs/artifact_version" }
        }
      },
      "tool_inputs": {
        "type": "object", "additionalProperties": false,
        "required": ["tool_call_id", "tool", "arguments", "operation_key", "resources"],
        "properties": {
          "tool_call_id": { "$ref": "urn:societas:1:common#/$defs/tc_id" },
          "tool": { "$ref": "urn:societas:1:common#/$defs/tool_name" },
          "arguments": { "type": "object" },
          "operation_key": { "oneOf": [
            { "type": "string", "minLength": 1, "maxLength": 128 }, { "type": "null" }
          ] },
          "resources": {
            "type": "array", "uniqueItems": true,
            "items": {
              "type": "object", "additionalProperties": false,
              "required": ["resource_id", "version"],
              "properties": {
                "resource_id": { "type": "string", "minLength": 1, "maxLength": 1024 },
                "version": { "type": "string", "minLength": 1, "maxLength": 256 }
              }
            }
          }
        }
      },
      "budget_inputs": {
        "type": "object", "additionalProperties": false,
        "required": ["scope", "target_id", "current_limits", "proposed_limits"],
        "properties": {
          "scope": { "$ref": "urn:societas:1:common#/$defs/scope" },
          "target_id": { "type": "string", "minLength": 1, "maxLength": 128 },
          "current_limits": { "$ref": "urn:societas:1:budget" },
          "proposed_limits": { "$ref": "urn:societas:1:budget", "minProperties": 1 }
        }
      }
    }
  },
  {
    "$id": "urn:societas:1:semantic_decision_index",
    "type": "object", "additionalProperties": false,
    "required": ["index_version", "workspace_id", "run_id", "repo_id", "target_ref", "base_commit", "candidate_commit", "base_decision_count", "base_decisions", "candidate_decision_count", "candidate_decisions", "registry_hash", "generated_by", "generated_at"],
    "properties": {
      "index_version": { "const": "semantic-decision-index/1" },
      "workspace_id": { "$ref": "urn:societas:1:envelope#/properties/workspace_id" },
      "run_id": { "$ref": "urn:societas:1:common#/$defs/run_id" },
      "repo_id": { "type": "string", "minLength": 1, "maxLength": 128 },
      "target_ref": { "type": "string", "pattern": "^refs/heads/.+", "maxLength": 256 },
      "base_commit": { "$ref": "urn:societas:1:approval_snapshot#/$defs/git_oid" },
      "candidate_commit": { "$ref": "urn:societas:1:approval_snapshot#/$defs/git_oid" },
      "base_decision_count": { "type": "integer", "minimum": 0 },
      "base_decisions": { "type": "array", "uniqueItems": true, "items": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" } },
      "candidate_decision_count": { "type": "integer", "minimum": 0 },
      "candidate_decisions": { "type": "array", "uniqueItems": true, "items": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" } },
      "registry_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
      "generated_by": { "const": "system:orchestrator" },
      "generated_at": { "$ref": "urn:societas:1:common#/$defs/ts" }
    },
    "allOf": [
      {
        "if": { "properties": { "base_decision_count": { "const": 0 } }, "required": ["base_decision_count"] },
        "then": { "properties": { "base_decisions": { "maxItems": 0 } } },
        "else": { "properties": { "base_decisions": { "minItems": 1 } } }
      },
      {
        "if": { "properties": { "candidate_decision_count": { "const": 0 } }, "required": ["candidate_decision_count"] },
        "then": { "properties": { "candidate_decisions": { "maxItems": 0 } } },
        "else": { "properties": { "candidate_decisions": { "minItems": 1 } } }
      }
    ]
  },
  {
    "$id": "urn:societas:1:merge_evidence",
    "type": "object", "additionalProperties": false,
    "required": ["kind", "binding", "result"],
    "properties": {
      "kind": { "enum": ["semantic_rebase", "gate", "review"] },
      "binding": { "$ref": "urn:societas:1:approval_snapshot#/$defs/merge_binding" },
      "result": { "enum": ["pass", "fail", "approve", "request_changes", "reject", "conflict", "inconclusive"] },
      "evaluator_tier": { "enum": ["cheap", "medium", "strong"], "description": "Nilai tier wire kanonik. Label tampilan Flash dipetakan ke cheap; policy/risk dapat menaikkan tier termasuk ke strong untuk task critical." },
      "semantic_recipe_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
      "decision_index_ref": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
      "decision_refs": {
        "type": "array", "uniqueItems": true,
        "items": {
          "type": "object", "additionalProperties": false,
          "required": ["role", "artifact_ref"],
          "properties": {
            "role": { "enum": ["base", "candidate"] },
            "artifact_ref": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" }
          }
        }
      },
      "findings_ref": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
      "findings": {
        "type": "array", "maxItems": 64,
        "items": {
          "type": "object", "additionalProperties": false,
          "required": ["code", "severity", "summary"],
          "properties": {
            "code": { "enum": ["logic_contradiction", "architecture_boundary", "insufficient_evidence", "input_unavailable", "evaluation_error"] },
            "severity": { "enum": ["info", "conflict", "inconclusive"] },
            "summary": { "type": "string", "minLength": 1, "maxLength": 2000 }
          }
        }
      }
    },
    "if": { "properties": { "kind": { "const": "gate" } }, "required": ["kind"] },
    "then": { "properties": { "result": { "enum": ["pass", "fail"] } } },
    "else": {
      "if": { "properties": { "kind": { "const": "review" } }, "required": ["kind"] },
      "then": { "properties": { "result": { "enum": ["approve", "request_changes", "reject"] } } },
      "else": {
        "required": ["evaluator_tier", "semantic_recipe_hash", "decision_index_ref", "decision_refs"],
        "properties": { "result": { "enum": ["pass", "conflict", "inconclusive"] } },
        "allOf": [
          {
            "if": { "properties": { "result": { "const": "conflict" } }, "required": ["result"] },
            "then": {
              "properties": { "decision_refs": { "minItems": 2 } },
              "allOf": [
                { "properties": { "decision_refs": { "contains": { "properties": { "role": { "const": "base" } }, "required": ["role"] } } } },
                { "properties": { "decision_refs": { "contains": { "properties": { "role": { "const": "candidate" } }, "required": ["role"] } } } }
              ]
            }
          },
          {
            "if": { "properties": { "result": { "enum": ["conflict", "inconclusive"] } }, "required": ["result"] },
            "then": {
              "anyOf": [
                { "properties": { "findings": { "minItems": 1 } }, "required": ["findings"] },
                { "required": ["findings_ref"] }
              ]
            }
          }
        ]
      }
    }
  },
  {
    "$id": "urn:societas:1:approval_batch_item_receipt",
    "type": "object", "additionalProperties": false,
    "required": ["workspace_id", "run_id", "batch_hash", "batch_ref", "approval_id", "bound_hash", "outcome", "processed_at"],
    "properties": {
      "workspace_id": { "$ref": "urn:societas:1:envelope#/properties/workspace_id" },
      "run_id": { "$ref": "urn:societas:1:common#/$defs/run_id" },
      "batch_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
      "batch_ref": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
      "approval_id": { "$ref": "urn:societas:1:common#/$defs/apr_id" },
      "bound_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
      "outcome": { "enum": ["granted", "skipped"] },
      "reason": { "enum": ["stale", "expired", "rejected", "already_granted", "risk_changed", "policy_changed", "binding_changed", "dispatch_blocked"] },
      "grant_event_id": { "$ref": "urn:societas:1:common#/$defs/evt_id" },
      "scope": { "const": "once" },
      "processed_at": { "$ref": "urn:societas:1:common#/$defs/ts" }
    },
    "allOf": [
      {
        "if": { "properties": { "outcome": { "const": "granted" } }, "required": ["outcome"] },
        "then": { "required": ["grant_event_id", "scope"] }
      },
      {
        "if": { "properties": { "outcome": { "const": "skipped" } }, "required": ["outcome"] },
        "then": { "required": ["reason"], "not": { "anyOf": [{ "required": ["grant_event_id"] }, { "required": ["scope"] }] } }
      }
    ]
  },
  {
    "$id": "urn:societas:1:merge_receipt",
    "type": "object", "additionalProperties": false,
    "required": ["receipt_version", "confirmed", "workspace_id", "run_id", "task_id", "repo_id", "target_ref", "expected_base", "merged_commit", "merged_tree", "approval", "semantic_evidence", "gate_evidence", "review_evidence", "validated_at", "confirmed_at"],
    "properties": {
      "receipt_version": { "const": "merge-receipt/1" },
      "confirmed": { "const": true },
      "workspace_id": { "$ref": "urn:societas:1:envelope#/properties/workspace_id" },
      "run_id": { "$ref": "urn:societas:1:common#/$defs/run_id" },
      "task_id": { "$ref": "urn:societas:1:common#/$defs/task_id" },
      "repo_id": { "type": "string", "minLength": 1, "maxLength": 128 },
      "target_ref": { "type": "string", "pattern": "^refs/heads/.+", "maxLength": 256 },
      "expected_base": { "$ref": "urn:societas:1:approval_snapshot#/$defs/git_oid" },
      "merged_commit": { "$ref": "urn:societas:1:approval_snapshot#/$defs/git_oid" },
      "merged_tree": { "$ref": "urn:societas:1:approval_snapshot#/$defs/git_oid" },
      "approval": {
        "type": "object", "additionalProperties": false,
        "required": ["approval_id", "bound_hash", "snapshot_ref", "grant_event_id"],
        "properties": {
          "approval_id": { "$ref": "urn:societas:1:common#/$defs/apr_id" },
          "bound_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
          "snapshot_ref": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
          "grant_event_id": { "$ref": "urn:societas:1:common#/$defs/evt_id" }
        }
      },
      "semantic_evidence": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
      "gate_evidence": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
      "review_evidence": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
      "validated_at": { "$ref": "urn:societas:1:common#/$defs/ts" },
      "confirmed_at": { "$ref": "urn:societas:1:common#/$defs/ts" }
    }
  },
  {
    "$id": "urn:societas:1:semantic_arbitration_decision",
    "type": "object", "additionalProperties": false,
    "required": ["decision_version", "workspace_id", "run_id", "task_id", "semantic_evidence", "issued_by", "selected_decision_refs", "refactor_task_ids", "rationale", "acceptance_constraints", "created_at"],
    "properties": {
      "decision_version": { "const": "semantic-arbitration/1" },
      "workspace_id": { "$ref": "urn:societas:1:envelope#/properties/workspace_id" },
      "run_id": { "$ref": "urn:societas:1:common#/$defs/run_id" },
      "task_id": { "$ref": "urn:societas:1:common#/$defs/task_id" },
      "semantic_evidence": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
      "issued_by": { "oneOf": [{ "$ref": "urn:societas:1:common#/$defs/agent_id" }, { "const": "human" }] },
      "selected_decision_refs": { "type": "array", "minItems": 1, "uniqueItems": true, "items": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" } },
      "refactor_task_ids": { "type": "array", "uniqueItems": true, "items": { "$ref": "urn:societas:1:common#/$defs/task_id" } },
      "rationale": { "type": "string", "minLength": 1, "maxLength": 4000 },
      "acceptance_constraints": { "type": "array", "minItems": 1, "items": { "type": "string", "minLength": 1, "maxLength": 1000 } },
      "created_at": { "$ref": "urn:societas:1:common#/$defs/ts" }
    }
  }
]
```

**Pembentukan digest:** validasi snapshot terlebih dahulu, lalu `bound_hash = "sha256:" + hex_lower(SHA256(JCS(snapshot)))`. JCS mengikuti RFC 8785, menghasilkan byte UTF-8 tanpa BOM/newline; bukan JSON pretty-print dan bukan checksum commit Git. Tolak duplicate key, NaN/Infinity, string Unicode invalid, serta angka yang tidak dapat direpresentasikan losslessly pada domain IEEE-754 binary64/I-JSON; identifier besar disimpan sebagai string. `null` berbeda dari field hilang, array mempertahankan urutan, Unicode tidak dinormalisasi diam-diam. Hash mencakup **seluruh** snapshot, tidak termasuk envelope event, approval ID, reason, risk, atau details. Risk/detail tampilan wajib berasal dari policy/input tepercaya yang sama; jangan tampilkan aksi berbeda dari snapshot.

**Snapshot artifact:** persist JCS bytes sebagai artifact immutable sebelum `approval.requested`. `snapshot_ref` mengikat ID **dan versi dan checksum**, dengan `snapshot_ref.checksum == bound_hash`. Runtime membaca versi tepat itu, mengecek checksum, parse/validasi snapshot, lalu menghitung digest ulang; tidak memakai “latest version”. Snapshot artifact adalah bukti operasional, tidak otomatis eligible untuk Vector DB (#19.6). Artifact hilang/tampered atau schema/profile tidak dikenal → tidak ada grant/dispatch. Aksi tambahan memerlukan profil snapshot kanonik berversi; tidak boleh memakai object bebas sebagai bypass.

**Input per aksi:**
- `git.merge`: `repo_id` adalah ID repo konfigurasi tepercaya (bukan path pilihan agen), `target_ref` adalah full local branch ref, `expected_base`/`candidate_commit`/`candidate_tree` adalah full lowercase object ID dengan format repo yang sama. Gate recipe hash mengikat toolchain/config/command yang benar-benar dijalankan. Semantic, gate, dan review masing-masing menunjuk artifact version/checksum yang memiliki `metadata.merge_evidence` valid; binding-nya sama persis dengan workspace/run/task/policy/contract/candidate snapshot. Semantic evidence wajib `kind: semantic_rebase`, `result: pass`, `semantic_recipe_hash`, evaluator tier, findings, serta refs base/candidate masing-masing dengan role + artifact ID/version/checksum yang cocok dengan content artifact. Recipe mengikat evaluator/provider/tier/prompt-schema version, policy, dan exact input refs. Gate wajib `pass`, review wajib `approve`. Evidence ID/versi yang berbeda menghasilkan snapshot/hash berbeda.
- `tool.execute`: adapter tepercaya menormalisasi argumen (termasuk default dan resource identity) sebelum hash; **argumen hasil normalisasi itulah yang dieksekusi**, tidak dibentuk ulang setelah approval. `resources` memuat seluruh precondition/resource version yang dilindungi aksi; ID harus unik dan diurutkan naik menurut code unit UTF-16 `resource_id` (aturan sort string JCS) sebelum JCS. Tanpa resources, array kosong eksplisit. Adapter menentukan fingerprint/version secara deterministik dan mengecek ulang saat dispatch; tidak boleh menghilangkan resource relevan hanya karena versi sulit diperoleh. Bila precondition tidak bisa dijamin saat mutasi, fail closed. `operation_key` mengikuti I16, null bila tidak berlaku; bukan jaminan retry hanya karena ada di snapshot.
- `budget.increase`: scope/target mengikat level budget yang diminta, `current_limits` adalah konfigurasi tersimpan pada target saat request dan `proposed_limits` adalah override yang persis disetujui. `budget_override` pada grant, bila disertakan, wajib sama dengan `proposed_limits`; bila tidak disertakan, aksi tetap memakai proposed_limits yang terikat. Perubahan pilihan human membuat request/hash baru. Ini **tidak** menetapkan ledger, lease recovery, finite defaults, atau formula inheritance baru (W05 masih terbuka).

`policy_hash` mengikat versi konfigurasi policy/permission yang berlaku untuk aksi, bukan output teks Jev; perubahan konfigurasi terikat memerlukan evaluasi dan approval ulang. `contract_hash` adalah pin aktif atau null eksplisit bila tidak ada kontrak. Scope/task identity dan policy tetap dicek menurut aturan akses existing; snapshot bukan kredensial dan tidak menyelesaikan desain autentikasi event.

<!-- schemas:approval -->
```json
[
  {
    "$id": "urn:societas:1:approval_requested",
    "type": "object", "additionalProperties": false,
    "required": ["approval_id", "action", "reason", "trigger", "risk", "delivery_mode", "bound_hash", "snapshot_ref"],
    "properties": {
      "approval_id": { "$ref": "urn:societas:1:common#/$defs/apr_id" },
      "action": { "enum": ["git.merge", "tool.execute", "budget.increase"] },
      "reason": { "type": "string", "maxLength": 1000 },
      "trigger": { "enum": ["policy", "budget"] },
      "risk": { "enum": ["low", "medium", "high", "critical"],
            "description": "Risk wire; task risk_tier normal dipetakan ke medium. Critical tidak pernah digest (I18)." },
      "delivery_mode": { "enum": ["immediate", "digest"],
             "description": "Immediate menghentikan aksi untuk keputusan individual; digest hanya mengatur presentasi antrean high dan tidak memberi otorisasi (I18)." },
      "bound_hash": { "$ref": "urn:societas:1:common#/$defs/sha256",
                      "description": "sha256: + hex lowercase SHA-256 atas byte JCS seluruh ApprovalSnapshot, bukan commit SHA Git mentah (I17)." },
      "snapshot_ref": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
      "details": { "type": "object" },
      "expires_at": { "$ref": "urn:societas:1:common#/$defs/ts" }
    },
    "allOf": [
      {
        "if": { "properties": { "delivery_mode": { "const": "digest" } }, "required": ["delivery_mode"] },
        "then": { "properties": { "risk": { "const": "high" } } }
      },
      {
        "if": { "properties": { "risk": { "const": "critical" } }, "required": ["risk"] },
        "then": { "properties": { "delivery_mode": { "const": "immediate" } } }
      }
    ]
  },
  {
    "$id": "urn:societas:1:approval_granted",
    "type": "object", "additionalProperties": false,
    "required": ["approval_id", "bound_hash", "scope", "granted_by"],
    "properties": {
      "approval_id": { "$ref": "urn:societas:1:common#/$defs/apr_id" },
      "bound_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
      "scope": { "enum": ["once", "task", "run"] },
      "granted_by": { "$ref": "urn:societas:1:common#/$defs/actor" },
      "budget_override": { "$ref": "urn:societas:1:budget" }
    }
  },
  {
    "$id": "urn:societas:1:approval_rejected",
    "type": "object", "additionalProperties": false, "required": ["approval_id"],
    "properties": {
      "approval_id": { "$ref": "urn:societas:1:common#/$defs/apr_id" },
      "rejected_by": { "$ref": "urn:societas:1:common#/$defs/actor" },
      "reason": { "type": "string", "maxLength": 1000 }
    }
  },
  {
    "$id": "urn:societas:1:approval_invalidated",
    "type": "object", "additionalProperties": false,
    "required": ["approval_id", "bound_hash", "reason"],
    "properties": {
      "approval_id": { "$ref": "urn:societas:1:common#/$defs/apr_id" },
      "bound_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
      "reason": { "enum": ["base_changed", "candidate_changed", "policy_changed",
                           "contract_changed", "evidence_changed", "input_changed",
                           "snapshot_unavailable", "expired"] }
    }
  },
  {
    "$id": "urn:societas:1:approval_batch",
    "type": "object", "additionalProperties": false,
    "required": ["batch_version", "workspace_id", "run_id", "items"],
    "properties": {
      "batch_version": { "const": "approval-batch/1" },
      "workspace_id": { "$ref": "urn:societas:1:envelope#/properties/workspace_id" },
      "run_id": { "$ref": "urn:societas:1:common#/$defs/run_id" },
      "items": {
        "type": "array", "minItems": 1, "uniqueItems": true,
        "items": {
          "type": "object", "additionalProperties": false,
          "required": ["approval_id", "bound_hash", "snapshot_ref", "task_id"],
          "properties": {
            "approval_id": { "$ref": "urn:societas:1:common#/$defs/apr_id" },
            "bound_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
            "snapshot_ref": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" },
            "task_id": { "oneOf": [
              { "$ref": "urn:societas:1:common#/$defs/task_id" }, { "type": "null" }
            ] }
          }
        }
      }
    }
  },
  {
    "$id": "urn:societas:1:approval_batch_submitted",
    "type": "object", "additionalProperties": false,
    "required": ["batch_hash", "batch_ref"],
    "properties": {
      "batch_hash": { "$ref": "urn:societas:1:common#/$defs/sha256" },
      "batch_ref": { "$ref": "urn:societas:1:approval_snapshot#/$defs/artifact_version" }
    }
  }
]
```

**Request/grant binding:** satu `approval_id` mengikat satu snapshot/hash selama hidupnya; ID tidak dapat dipakai ulang untuk snapshot baru. Backend menyimpan binding dalam SQLite sebelum menawarkan pilihan ke human. Grant wajib menggemakan hash request; setelah restart, lookup dilakukan pada ID/hash/artifact version tersimpan, bukan nilai RAM. Pada grant, resume, **dan tepat sebelum dispatch**, runtime membangun ulang input aktual terikat dan membandingkan JCS/digest dengan request serta memeriksa expiry, policy, contract freshness, dan evidence. Mismatch → `approval.invalidated`, tanpa eksekusi; request baru memakai ID baru. Rejection/expiry/invalidation tidak pernah otomatis berubah menjadi approval. `scope` sekali/task/run tidak membebaskan binding ini dan tidak mengotorisasi kandidat baru; predicate reuse/atomic once-consumption lintas aksi tetap keputusan desain terpisah.

**Digest receipts (I18):** idempotency key item adalah tuple unik `(workspace_id, run_id, batch_hash, approval_id)`. Setelah manifest diverifikasi, tiap item berulang-kali boleh direvalidasi, tetapi hasil final tersimpan sekali. Untuk item grant, dalam satu transaksi Operational Store lakukan CAS request `pending → granted`, catat `approval.granted` di outbox dan simpan `approval_batch_item_receipt` berisi ID/hash/manifest refs/outcome/event ID sebelum event dikirim. Item skip juga mendapat receipt dengan reason. Replay command dengan key sama mengembalikan receipt tersimpan tanpa grant atau side effect kedua; manifest hash/ID sama dengan isi berbeda ditolak. Hasil kartu dibentuk dari receipt per item, bukan respons RAM. Ini aturan durable per-item; recovery lintas subsistem/event store yang tidak satu transaksi tetap W06.

## 72A.9 Error Catalog

Menggabungkan kategori di #44 dengan kode di 5A.15. Satu kode punya satu kategori, status `retryable`, dan satu aksi default. Retry selalu dihitung dalam retry budget (5A.13).

| Kode | Kategori | `retryable` | Aksi default |
|------|----------|-------------|--------------|
| `BUDGET_EXCEEDED` | `BUDGET_ERROR` | tidak | Model call tidak dijalankan. Emit `budget.exceeded` (`details.scope` menunjukkan level), lalu stop atau minta approval. |
| `CONTEXT_TOO_LARGE` | `LIMIT_ERROR` | tidak | Context Manager menyusun ulang dengan seleksi lebih ketat, maksimal 1 kali. Jika masih gagal, task gagal. |
| `RATE_LIMITED` | `LIMIT_ERROR` | ya | Tunggu `retry_after_ms`, retry terbatas. |
| `POLICY_DENIED` | `PERMISSION_DENIED` | tidak | Jangan retry. Agent diberi tahu dan dapat memilih jalur lain. |
| `APPROVAL_REJECTED` | `PERMISSION_DENIED` | tidak | Task `failed` atau agent mengambil jalur alternatif. |
| `APPROVAL_TIMEOUT` | `TIMEOUT` | tidak | Task `failed`. Human dapat memulai ulang. |
| `APPROVAL_BINDING_INVALID` | `PERMISSION_DENIED` | tidak | Tolak grant/dispatch pada ID/hash/input/evidence yang tidak cocok atau invalidated; refresh evidence dan request dengan ID baru, bukan retry aksi lama. |
| `FANOUT_LIMIT_EXCEEDED` | `LIMIT_ERROR` | tidak | `task.delegate_rejected`. Agent harus menggabungkan pekerjaan. |
| `MAX_DEPTH_EXCEEDED` | `LIMIT_ERROR` | tidak | `task.delegate_rejected`. |
| `MAX_ITERATIONS_EXCEEDED` | `LIMIT_ERROR` | tidak | Task `failed`. Run dapat berhenti dengan `max_iterations`. |
| `MODEL_TIMEOUT` | `TIMEOUT` | ya | Retry terbatas, boleh escalate model. |
| `MODEL_UNAVAILABLE` | `MODEL_ERROR` | ya | Retry terbatas atau fallback ke provider/model lain. Go Runtime melakukan ping ke DNS publik (`1.1.1.1`) untuk membedakan network outage vs provider outage. Jika ping gagal → internet putus total → auto-pause (I21). Jika ping lolos → internet hidup, provider down → Model Router mengeksekusi fallback transparan ke provider alternatif yang terdaftar (misal Gemini, Anthropic) tanpa menjeda task. Auto-pause hanya dipicu jika seluruh rantai fallback provider gagal. |
| `INVALID_OUTPUT` | `INVALID_OUTPUT` | ya | Agent correction, maksimal 2 kali (I10). |
| `TOOL_INPUT_INVALID` | `INVALID_OUTPUT` | ya | Agent correction dengan pesan error dari tool schema. |
| `TOOL_FAILED` | `TOOL_ERROR` | tergantung tool | Retry mengikuti outcome dan capability I16; gagal logis yang diketahui bukan alasan mengulang mutasi secara buta. |
| `TOOL_TIMEOUT` | `TIMEOUT` | tergantung tool | `outcome_unknown` — retry hanya jika tool `idempotent` atau `operation_key` ditegakkan provider (I16); jika tidak, rekonsiliasi atau keputusan human. Untuk compiler/test di Local Toolchain ([5A.22 — Compiler Gate](02-ai-control-plane.md#compiler-gate-sebelum-reviewer-dipanggil), 60.2), timeout menggunakan **log inactivity monitoring** (5 menit tanpa output baru) karena performa kompilasi bervariasi drastis per hardware; bukan hard execution timeout durasi total. |
| `NETWORK_ERROR` | `NETWORK_ERROR` | tergantung operasi | Pada tool: `outcome_unknown` kecuali ada bukti belum dispatch; I16 wajib. Pada model call: ikuti guard dan accounting I4, bukan asumsi call gratis. |
| `SEARCH_BLOCK_NOT_FOUND` | `TOOL_ERROR` | tidak | Bukan retry runtime — error dikembalikan ke agent; agent wajib membaca ulang file asli sebelum mengirim blok baru (#60.3). |
| `SEARCH_BLOCK_AMBIGUOUS` | `TOOL_ERROR` | tidak | Blok `SEARCH` cocok di lebih dari satu lokasi — perubahan **tidak diterapkan**; agent harus memperlebar konteks blok (#60.3). |
| `REBASE_CONFLICT` | `DEPENDENCY_FAILED` | tidak | Diterjemahkan menjadi `task.rebase_conflict` ke Engineer (#60.4); task tetap nonterminal, bukan retry otomatis atau kegagalan dependency terminal. |
| `DEPENDENCY_FAILED` | `DEPENDENCY_FAILED` | tidak | Task `failed` dengan referensi task yang gagal di `details`. |
| `SCHEMA_VALIDATION_FAILED` | `INVALID_OUTPUT` | tidak | Pesan ditolak di boundary. Ini bug pengirim, bukan masalah sementara. |

Aturan:

- Kode baru wajib ditambahkan ke tabel ini sebelum dipakai.
- `retryable: true` hanya berarti kandidat retry. Keputusan akhir tetap di Orchestrator berdasarkan keamanan efek (I16), policy, dan retry budget.
- `INVALID_OUTPUT` pada model yang murah boleh memicu model escalation (5A.9) sebelum menghabiskan batas koreksi.

## 72A.10 Alur Baku

Urutan di bawah ini adalah kontrak perilaku. Urutan event harus sesuai.

### Model call (Token Guard, 5A.15)

```text
1. Agent Runtime butuh model call untuk task T
2. context.built          Context Manager menyusun context sesuai token_budget
3. check_budget           (gagal -> model.call_failed BUDGET_EXCEEDED, executed=false)
4. check_context_size     (gagal -> model.call_failed CONTEXT_TOO_LARGE, executed=false)
5. check_rate_limit       (gagal -> model.call_failed RATE_LIMITED, executed=false)
6. policy.evaluated       action="model.call", decision harus allow
7. model.selected         Model Router memilih tier dan model, dengan reason
8. budget.reserved        batas atas token dan biaya di-reserve
9. model.call_started
10. model.call_completed  (atau model.call_failed dengan executed=true)
11. budget.settled        usage nyata di-settle, sisa reservasi dikembalikan
12. (jika used_ratio >= 0.8) budget.warning
```

### Delegation (5A.1, I2, I12)

```text
1. Agent menghasilkan JSON delegasi, divalidasi sebagai delegate_requested (I10)
2. Event task.delegate_requested: agent -> system:orchestrator
3. Orchestrator memeriksa berurutan:
     a. fan-out    jumlah anak < max_child_tasks     (FANOUT_LIMIT_EXCEEDED)
     b. depth      depth parent + 1 <= max_depth     (MAX_DEPTH_EXCEEDED)
     c. dependency valid dan tidak membentuk siklus  (SCHEMA_VALIDATION_FAILED)
     d. policy     agent.create / assignment diizinkan (POLICY_DENIED)
     e. budget     grant <= sisa parent, lalu reserve  (BUDGET_EXCEEDED)
4. Memilih assignee:
     a. `requested_assignee` terisi valid (lolos enum dinamis)
        -> langsung task.created ke agen itu, tanpa LLM router (0 token)
     b. `requested_assignee` = null (Blind Delegation)
        -> Orchestrator memanggil Jev AI (Choice, ~150ms) untuk memilih
           agen paling cocok dari squad aktif
     c. `task.delegate_rejected` hanya rem darurat saat limit
        (fan-out/depth/budget) terlampaui — BUKAN karena salah nama agen
        (enum dinamis + constrained decoding membuatnya mustahil, 5A.8)
5. Sukses: task.created (budget granted terisi) lalu task.assigned
   Gagal:  task.delegate_rejected ke pengirim, dengan Error dari katalog
```

### Tool call

```text
1. tool.call_requested   agent -> system:tool_runtime
2. policy.evaluated      Jev AI mengevaluasi risiko tindakan -> (allow | require_approval | deny)
     deny             -> tool.call_failed POLICY_DENIED
     require_approval -> approval.requested, task awaiting_approval
                         granted  -> lanjut ke langkah 3
                         rejected -> tool.call_failed APPROVAL_REJECTED
3. tool.call_started
4. tool.call_completed | tool.call_failed
   call_failed dengan outcome=not_started  -> aman, ikuti katalog error
   call_failed dengan outcome=outcome_unknown -> I16: tidak auto-retry;
        rekonsiliasi/approval untuk tool non-idempotent tanpa operation_key
5. Output di atas batas inline (serialized agregat, I5) -> simpan artifact, isi output_artifact_id
```

### Approval Digest (I18, #23.2/#33.7/#40.1)

```text
1. Summary Manager membentuk manifest approval_batch/1 immutable dari request high/digest yang eligible pada workspace/run; item diurutkan approval_id UTF-16.
2. Human mengirim approval.batch_submitted dengan artifact version + batch_hash yang ditampilkan.
3. Event Bus memvalidasi envelope; Orchestrator membaca versi tepat lalu memvalidasi JCS/hash/schema/checksum/workspace/run/urutan/ID unik.
  manifest invalid, duplikat ID, atau foreign scope -> tolak seluruh command, tanpa grant.
4. Untuk setiap item, lookup approval tersimpan dan cek ID/hash/snapshot_ref/task,
   risk=high + delivery_mode=digest, policy high/digest masih berlaku, status pending,
   expiry, task current/nonterminal, contract, snapshot dan live input.
  invalid/stale/expired/already processed/risk changed -> simpan receipt skipped + reason.
5. Item eligible -> transaksi SQLite: CAS request pending->granted, append approval.granted ke outbox,
   simpan receipt granted (scope=once, grant_event_id) dengan unique key
   (workspace_id, run_id, batch_hash, approval_id); commit sebelum delivery (I15).
6. Retry/double-click dengan key sama mengembalikan receipt yang ada; tidak membuat grant/event/aksi kedua.
7. Approval Center menyusun hasil parsial dari receipts persisted; item baru sesudah manifest dibuat
   perlu manifest/hash/klik baru. Dispatch melakukan recheck; merge tetap expected-base CAS.
```

Receipt skipped tidak memuat grant; duplicate key dengan payload berbeda ditolak, bukan di-rebind. Kegagalan persistence tidak menghasilkan jawaban sukses. Recovery yang melintasi SQLite/Event Store terpisah mengikuti W06; langkah ini tidak mengklaim transaksi lintas database.

### Review (Local Compiler Gate, [5A.22](02-ai-control-plane.md#compiler-gate-sebelum-reviewer-dipanggil))

```text
1. Engineer selesai -> artifact.created (patch/code)
2. backend Go menjalankan build/linter lokal (0 token):
     gagal -> task kembali ke Engineer dengan error log (tanpa LLM review)
3. lolos  -> review_requested -> Reviewer LLM
4. review_completed (approve | request_changes | reject)
     request_changes -> rebuttal max 2 putaran (#48)
```

### Serial Merge: Final Candidate Binding (I17, #60.4)

```text
1. Ambil base = full OID target_ref dari repo tepercaya.
2. Rebase branch task ke base; conflict -> task.rebase_conflict -> Engineer.
3. Sesudah resolve, ulangi rebase/validasi base; regenerate PROJECT_MAP pada kandidat.
4. Freeze candidate commit + tree; index/worktree input gate bersih dan cocok dengan tree.
5. Gate build/lint/test pada kandidat tepat itu; persist MergeEvidence kind=gate/result=pass.
6. Semantic Rebase PASS sesudah gate pada kandidat tepat itu; persist MergeEvidence kind=semantic_rebase/result=pass.
  CONFLICT/INCONCLUSIVE -> task.blocked (blocked_reason + immutable blocked_evidence ref),
  task.semantic_conflict dengan semantic evidence + decision refs ke escalation_lead; jangan merge.
7. review.requested/completed membawa merge_binding yang sama;
   hanya approve yang menghasilkan MergeEvidence kind=review/result=approve.
8. Persist snapshot JCS berisi base/kandidat/recipe/policy/contract + semantic/gate/review evidence refs.
   approval.requested -> human -> approval.granted dengan ID/hash yang sama.
9. Tepat sebelum integrasi, ambil hak serial per repo/target, baca ulang input terikat:
   task masih nonterminal/current, grant tidak invalidated/rejected/expired,
  base masih expected_base, kandidat/tree/gate+semantic+review evidence/recipe/policy/contract masih sama.
10. Verifikasi candidate_commit turunan expected_base dan tree commit cocok.
   Atomic expected-old update target_ref -> candidate_commit (fast-forward).
11. Persist merge_receipt setelah update ref direkonsiliasi: approval snapshot + semantic/gate/review refs + base/commit/tree target.
12. Post-merge PROJECT_MAP regen hanya memverifikasi tree yang disetujui, bukan menambah perubahan tak direview.
```

Approval menunggu human dengan task parked, **tidak memegang goroutine/lock antrean**. Task lain boleh masuk lebih dulu; saat target maju, approval task yang menunggu menjadi invalid. Engineer tidak mengubah frozen candidate ketika approval masih valid. Edit, cherry-pick, rebase, atau regenerasi code/map yang menghasilkan tree/commit baru wajib membuat kandidat baru dan mengulang gate → Semantic Rebase → review → approval. Evidence lama tidak diwariskan walaupun patch terlihat identik. Tidak ada `git merge`/squash/rebase yang membuat commit baru **sesudah** approval; bila ingin merge commit, commit itu harus sudah menjadi kandidat yang digate/semantic-pass/review/disetujui.

Evidence artifact menyimpan JSON `MergeEvidence` sebagai konten; `metadata.merge_evidence` adalah indeks dari konten yang sama, bukan sumber alternatif yang boleh diubah terpisah. Bind seluruh workspace/run/task/policy/contract/candidate; `review.completed` untuk merge wajib membawa `merge_binding` dan `artifact_id`, dengan verdict/evidence yang cocok. Semantic evidence menyertakan recipe hash + exact base/candidate decision refs; refs tidak boleh di-resolve ke "latest". Recipe gate mencakup command/config/toolchain yang menguji candidate tree. Gate berjalan dalam sandbox dari tree immutable (termasuk input tracked/generated yang memengaruhi hasil); perubahan input atau dependensi/toolchain/decision ref yang terikat mengubah recipe/binding dan membatalkan hasil. Working tree kotor atau input tak dapat dipin → tidak lanjut approval.

Semantic recipe hash mengikat evaluator/provider/model tier, prompt/schema version, policy, dan exact decision refs (role base/candidate + artifact ID/version/checksum). Hash tidak mengklaim kebenaran model; ia memungkinkan pemeriksaan bahwa evidence mengacu input yang sama. `merge_receipt` adalah bukti provenance hanya setelah expected-base update berhasil dan target Git ref direkonsiliasi ke commit/tree yang disetujui. Receipt mengikat workspace/run/task/repo/ref/base/merged commit/tree, approval ID/hash/snapshot ref, serta semantic/gate/review refs. `task.completed`, approval grant, `HEAD` yang berubah sendiri, atau tulisan agen tidak menggantikan receipt.

**CAS ref:** perbandingan dan update tidak boleh menjadi dua operasi “read lalu merge” yang terpisah. Primitive lokal, bila executor diizinkan policy/sandbox dan target bukan symbolic ref:

```text
git update-ref --no-deref <target_ref> <candidate_commit> <expected_base>
```

Argumen berasal dari snapshot tervalidasi, bukan command string agen; `repo_id` resolved dari konfigurasi tepercaya. Validasi full ref melalui Git (schema regex bukan pengganti `check-ref-format`), format OID repo, objek commit/tree, ancestry, dan target branch/direct ref. Serialisasi mencakup pemeriksaan final + operasi ref; expected-old Git tetap wajib untuk writer eksternal yang tidak ikut antrean. CAS gagal → tidak merge, `approval.invalidated` `reason: base_changed`, lalu base baru → rebase → gate → review → request baru. Jangan overwrite target atau retry tanpa expected base.

CAS hanya menjamin atomisitas **Git ref**, bukan transaksi lintas Git + SQLite atau konsistensi checkout/index. Executor wajib menjaga target checkout/materialisasi konsisten tanpa memperluas writable shared metadata; model isolasinya tetap keputusan W14. Bila response update hilang/crash sesudah dispatch, ikuti I16: rekonsiliasi ref dengan durable intent/receipt sebelum retry/rebase; ref yang sudah maju mungkin efek aksi sendiri, bukan alasan mengulang merge. Recovery intent/receipt + state/event/outbox lintas subsistem masih W06, tidak dianggap solved oleh CAS. Sesudah merge, task terminal tidak dibuka kembali; bila pekerjaan integration dipisahkan dari task output yang sudah terminal, gunakan task nonterminal terpisah sesuai keputusan semantik completed yang masih terbuka.

Referensi primitive: [git-update-ref](https://git-scm.com/docs/git-update-ref). Referensi encoding: [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785).

### Output besar (5A.6, 5A.7)

```text
1. Agent selesai menulis output besar -> artifact.created
2. system:summarizer (model cheap) membuat ringkasan -> summary.created
3. Agent lain menerima summary + artifact_id, bukan isi penuh
4. Isi artifact hanya diambil jika benar-benar diperlukan
```

### Approval karena budget ([5A.21 — Approval Escalation](02-ai-control-plane.md#5a21-approval-escalation))

```text
1. budget.exceeded
2. approval.requested (trigger="budget")
3. Human memilih:
     approval.granted (+ budget_override opsional) -> lanjut
     approval.rejected                             -> task failed, run.stopped (human_rejected)
```

## 72A.11 Walkthrough End-to-End

Skenario dari [5A.23 — Example Token-Efficient Workflow](02-ai-control-plane.md#5a23-example-token-efficient-workflow). User meminta: *"CEO, evaluasi apakah kita perlu menambahkan fitur baru."*

Urutan event (ringkas):

| # | Event | Dari → Ke | Keterangan |
|---|-------|-----------|------------|
| 1 | `run.created` | `human:user` → `system:orchestrator` | Run dimulai dengan budget $1.00 |
| 2 | `task.created` (TASK-001) | `system:orchestrator` → `agent:ceo` | Task root, budget granted |
| 3 | `context.built` | `system:context` → `agent:ceo` | Hanya item relevan, ada yang di-drop |
| 4 | `policy.evaluated`, `model.selected`, `budget.reserved`, `model.call_started` | `system:*` | Token Guard lolos, tier `strong` |
| 5 | `model.call_completed`, `budget.settled` | `system:router` / `system:budget` | Usage tercatat |
| 6 | `task.delegate_requested` | `agent:ceo` → `system:orchestrator` | CEO meminta task riset |
| 7 | `task.created` (TASK-002), `task.assigned` | `system:orchestrator` → `agent:research` | Budget child $0.20 dari sisa $1.00 |
| 8 | `tool.call_requested` → `tool.call_completed` | `agent:research` ↔ `system:tool_runtime` | Pencarian web |
| 9 | `artifact.created` | `agent:research` → `topic:all` | `research.md` |
| 10 | `summary.created` | `system:summarizer` → `topic:all` | Ringkasan sekitar 800 token memakai model cheap |
| 11 | `task.completed` (TASK-002) | `agent:research` → `system:orchestrator` | Mengirim referensi, bukan isi penuh |
| 12 | (CTO mengikuti pola yang sama dengan langkah 6-11) | | |
| 13 | CEO sintesis, `task.completed` (TASK-001) | | |
| 14 | `run.stopped` (`success`) | `system:orchestrator` → `human:user` | Totals dilaporkan |

Payload lengkap untuk langkah-langkah penting:

**1. `run.created`**

<!-- example:run.created -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZBMN0V2JVCVJQ5HS63JFDS",
  "type": "run.created",
  "ts": "2026-10-06T09:00:00Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "idempotency_key": "web-7f3a-001",
  "from": "human:user",
  "to": "system:orchestrator",
  "payload": {
    "goal": "Evaluasi apakah kita perlu menambahkan fitur baru.",
    "entry_agent": "ceo",
    "budget_request": { "max_total_tokens": 60000, "max_cost_usd": 1.00 }
  }
}
```

**2. `task.created` (task root untuk CEO)**

<!-- example:task.created -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZBJTD64PV176RGBNC6D0EC",
  "type": "task.created",
  "ts": "2026-10-06T09:00:01Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "task_id": "TASK-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBMN0V2JVCVJQ5HS63JFDS",
  "from": "system:orchestrator",
  "to": "agent:ceo",
  "payload": {
    "task": {
      "id": "TASK-001",
      "run_id": "RUN-001",
      "parent_task_id": null,
      "title": "Evaluasi penambahan fitur baru",
      "goal": "Putuskan apakah fitur baru perlu ditambahkan, lengkap dengan alasan dan risiko.",
      "owner": "ceo",
      "created_by": "human:user",
      "priority": "high",
      "status": "ready",
      "dependencies": [],
      "deadline": null,
      "depth": 0,
      "attempt": 1,
      "expected_output": { "kind": "decision", "format": "markdown" },
      "budget": {
        "granted": {
          "max_total_tokens": 60000,
          "max_cost_usd": 1.00,
          "max_model_calls": 30,
          "max_child_tasks": 5,
          "max_depth": 4,
          "max_parallel_agents": 4,
          "max_agent_iterations": 8,
          "retry": { "max_attempts": 2, "max_total_retry_cost_usd": 0.10 }
        },
        "used": { "input_tokens": 0, "output_tokens": 0, "model_calls": 0, "tool_calls": 0, "estimated_cost_usd": 0 }
      },
      "working_directory": "/workspace/artifacts/RUN-001/TASK-001",
      "created_at": "2026-10-06T09:00:01Z",
      "updated_at": "2026-10-06T09:00:01Z"
    }
  }
}
```

**3. `context.built`** (menunjukkan *mengapa* context tertentu diberikan, dan apa yang dibuang)

<!-- example:context.built -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZB8AXX885QPDR9R48STZ2S",
  "type": "context.built",
  "ts": "2026-10-06T09:00:02Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "task_id": "TASK-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBJTD64PV176RGBNC6D0EC",
  "from": "system:context",
  "to": "agent:ceo",
  "payload": {
    "agent_id": "ceo",
    "token_budget": 12000,
    "tokens_used": 2250,
    "items": [
      { "kind": "system_prompt", "ref": "prompt:ceo", "tokens": 900, "reason": "wajib" },
      { "kind": "role", "ref": "role:ceo", "tokens": 250, "reason": "wajib" },
      { "kind": "task", "ref": "TASK-001", "tokens": 400, "reason": "task saat ini" },
      { "kind": "memory", "ref": "mem:arch-decision-transport", "tokens": 700, "reason": "keputusan transport sebelumnya relevan" }
    ],
    "dropped": [
      { "kind": "memory", "ref": "mem:finance-notes-2026q2", "reason": "low_relevance" }
    ]
  }
}
```

**5. `model.call_completed`**

<!-- example:model.call_completed -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZBC0AKZ3BBK8KA370CFV44",
  "type": "model.call_completed",
  "ts": "2026-10-06T09:00:08Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "task_id": "TASK-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZB8AXX885QPDR9R48STZ2S",
  "from": "system:router",
  "to": "agent:ceo",
  "payload": {
    "usage": {
      "model": "strong-model",
      "input_tokens": 2250,
      "output_tokens": 410,
      "duration_ms": 5120,
      "estimated_cost_usd": 0.031
    },
    "finish_reason": "stop",
    "confidence": 0.82
  }
}
```

**6. `task.delegate_requested`** (CEO meminta, tidak membuat task sendiri)

<!-- example:task.delegate_requested -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZB3G6A2NYNE5P9B4T3RTEA",
  "type": "task.delegate_requested",
  "ts": "2026-10-06T09:00:09Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "task_id": "TASK-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBC0AKZ3BBK8KA370CFV44",
  "idempotency_key": "TASK-001-delegate-research-1",
  "from": "agent:ceo",
  "to": "system:orchestrator",
  "payload": {
    "title": "Riset gRPC vs REST untuk transport agent",
    "goal": "Bandingkan latency, reliability, dan kompleksitas implementasi gRPC vs REST. Berikan rekomendasi singkat dan sumber.",
    "rationale": "Keputusan butuh data pembanding terbaru. Memory CEO tidak memiliki benchmark.",
    "requested_assignee": "research",
    "expected_output": { "kind": "artifact", "format": "markdown" },
    "priority": "high",
    "complexity_hint": "medium",
    "context_hints": { "memory_queries": ["gRPC benchmark", "REST implementation"] },
    "budget_request": { "max_total_tokens": 12000, "max_cost_usd": 0.20 }
  }
}
```

**7. `task.created`** (Orchestrator memberi budget; di sini $0.20 dari sisa $0.969 milik parent)

<!-- example:task.created -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZBHB2DZKSXQ0S74ER1KKPW",
  "type": "task.created",
  "ts": "2026-10-06T09:00:10Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "task_id": "TASK-002",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZB3G6A2NYNE5P9B4T3RTEA",
  "from": "system:orchestrator",
  "to": "agent:research",
  "payload": {
    "task": {
      "id": "TASK-002",
      "run_id": "RUN-001",
      "parent_task_id": "TASK-001",
      "title": "Riset gRPC vs REST untuk transport agent",
      "goal": "Bandingkan latency, reliability, dan kompleksitas implementasi gRPC vs REST. Berikan rekomendasi singkat dan sumber.",
      "owner": "research",
      "created_by": "agent:ceo",
      "priority": "high",
      "status": "ready",
      "dependencies": [],
      "deadline": null,
      "depth": 1,
      "attempt": 1,
      "expected_output": { "kind": "artifact", "format": "markdown" },
      "budget": {
        "granted": {
          "max_total_tokens": 12000,
          "max_cost_usd": 0.20,
          "max_model_calls": 10,
          "max_tool_calls": 20,
          "max_time_seconds": 300
        },
        "used": { "input_tokens": 0, "output_tokens": 0, "model_calls": 0, "tool_calls": 0, "estimated_cost_usd": 0 }
      },
      "working_directory": "/workspace/artifacts/RUN-001/TASK-002",
      "created_at": "2026-10-06T09:00:10Z",
      "updated_at": "2026-10-06T09:00:10Z"
    }
  }
}
```

**8. Tool call**

<!-- example:tool.call_requested -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZB0P08MESD27WWF0X2GTAX",
  "type": "tool.call_requested",
  "ts": "2026-10-06T09:00:20Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "task_id": "TASK-002",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBHB2DZKSXQ0S74ER1KKPW",
  "from": "agent:research",
  "to": "system:tool_runtime",
  "payload": {
    "tool_call_id": "tc_01J9ZBGP79PCNF7AHK55JHQBKY",
    "tool": "web.search",
    "arguments": { "query": "gRPC vs REST latency benchmark" },
    "timeout_ms": 20000
  }
}
```

<!-- example:tool.call_completed -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZBJ658J92SADYG3P19CST8",
  "type": "tool.call_completed",
  "ts": "2026-10-06T09:00:22Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "task_id": "TASK-002",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZB0P08MESD27WWF0X2GTAX",
  "from": "system:tool_runtime",
  "to": "agent:research",
  "payload": {
    "tool_call_id": "tc_01J9ZBGP79PCNF7AHK55JHQBKY",
    "status": "ok",
    "output": "8 hasil ditemukan.",
    "truncated": false,
    "duration_ms": 1840
  }
}
```

**9-10. Artifact dan summary** (yang dikirim ke agent lain adalah summary + referensi)

<!-- example:artifact.created -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZBMWFA97DP1VJ770C2Y52A",
  "type": "artifact.created",
  "ts": "2026-10-06T09:01:30Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "task_id": "TASK-002",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBJ658J92SADYG3P19CST8",
  "from": "agent:research",
  "to": "topic:all",
  "payload": {
    "artifact": {
      "id": "art_01J9ZB97J90P9MH8TKCE9C9KF3",
      "name": "research.md",
      "kind": "markdown",
      "path": "artifacts/RUN-001/TASK-002/research.md",
      "checksum": "sha256:66f62d1807d3821a3865f2573b69c74be033f1341240ac861fefc6d430bff5e0",
      "size_bytes": 18420,
      "version": 1,
      "task_id": "TASK-002",
      "created_by": "agent:research",
      "created_at": "2026-10-06T09:01:30Z"
    }
  }
}
```

<!-- example:summary.created -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZBMB07Y7X7H238CJYHN9V9",
  "type": "summary.created",
  "ts": "2026-10-06T09:01:34Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "task_id": "TASK-002",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBMWFA97DP1VJ770C2Y52A",
  "from": "system:summarizer",
  "to": "topic:all",
  "payload": {
    "summary": {
      "id": "sum_01J9ZB75QCACYADGWFKD86P7W1",
      "artifact_id": "art_01J9ZB97J90P9MH8TKCE9C9KF3",
      "artifact_version": 1,
      "token_estimate": 780,
      "generated_by": "system:summarizer",
      "model": "cheap-model",
      "body": {
        "text": "gRPC unggul pada performa dan type-safety. REST lebih sederhana dan lebih matang tooling-nya.",
        "findings": ["gRPC mengurangi latency pada high-throughput calls", "REST cukup untuk mode lokal"],
        "risks": ["Kompleksitas implementasi gRPC lebih tinggi"],
        "recommendation": "Mulai dengan HTTP/REST. Evaluasi gRPC ketika throughput menjadi bottleneck.",
        "sources": ["research.md#benchmark", "research.md#risiko"]
      }
    }
  }
}
```

**11. `task.completed`**

<!-- example:task.completed -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZB8MHE3A7GDTXS0TWR5FQ3",
  "type": "task.completed",
  "ts": "2026-10-06T09:01:40Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "task_id": "TASK-002",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBMWFA97DP1VJ770C2Y52A",
  "from": "agent:research",
  "to": "system:orchestrator",
  "payload": {
    "result_status": "success",
    "artifact_ids": ["art_01J9ZB97J90P9MH8TKCE9C9KF3"],
    "summary_ids": ["sum_01J9ZB75QCACYADGWFKD86P7W1"],
    "usage": {
      "input_tokens": 9120,
      "output_tokens": 2240,
      "model_calls": 3,
      "tool_calls": 2,
      "estimated_cost_usd": 0.087
    }
  }
}
```

**Contoh penolakan: fan-out melebihi batas** (I12)

<!-- example:task.delegate_rejected -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZB2SAX2698XVPBEKQRRRP6",
  "type": "task.delegate_rejected",
  "ts": "2026-10-06T09:05:00Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "task_id": "TASK-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBD8Y6K6M8JYG02EPDVJ2G",
  "from": "system:orchestrator",
  "to": "agent:ceo",
  "payload": {
    "request_event_id": "evt_01J9ZBD8Y6K6M8JYG02EPDVJ2G",
    "error": {
      "code": "FANOUT_LIMIT_EXCEEDED",
      "category": "LIMIT_ERROR",
      "message": "TASK-001 sudah memiliki 5 child task aktif (batas 5). Gabungkan pekerjaan atau tunggu salah satu selesai.",
      "retryable": false,
      "details": { "max_child_tasks": 5, "current_children": 5 }
    }
  }
}
```

**Contoh eskalasi budget** ([5A.21 — Approval Escalation](02-ai-control-plane.md#5a21-approval-escalation), I14)

<!-- example:budget.exceeded -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZBS1VHX1W4W4AGPX1QYFDC",
  "type": "budget.exceeded",
  "ts": "2026-10-06T09:20:00Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBC0AKZ3BBK8KA370CFV44",
  "from": "system:budget",
  "to": "system:orchestrator",
  "payload": {
    "scope": "run",
    "scope_id": "RUN-001",
    "limit": "max_cost_usd",
    "error": {
      "code": "BUDGET_EXCEEDED",
      "category": "BUDGET_ERROR",
      "message": "Budget biaya run RUN-001 tercapai.",
      "retryable": false,
      "details": { "scope": "run", "used": 1.0, "limit": 1.0 }
    }
  }
}
```

### Approval Snapshot Test Vectors

OID/ID/policy/recipe di fixture ini sintetis, bukan bukti Git runtime. Konten artifact adalah JCS dari JSON di bawah (tanpa newline); checksum bukan hash Markdown fence. Fixture evidence mengikuti `MergeEvidence`, dan indeks metadata harus identik dengan konten. Snapshot budget memakai `task_id: null` sesuai contoh request run-level.

<!-- fixture:approval_budget -->
```json
{
  "snapshot_version": "approval-snapshot/1",
  "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": null,
  "action": "budget.increase",
  "policy_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "contract_hash": null,
  "inputs": {
    "scope": "run", "target_id": "RUN-001",
    "current_limits": { "max_cost_usd": 1.0 },
    "proposed_limits": { "max_cost_usd": 1.3 }
  }
}
```

<!-- fixture:merge_gate -->
```json
{
  "kind": "gate", "result": "pass",
  "binding": {
    "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
    "policy_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "contract_hash": null,
    "candidate": {
      "repo_id": "repo_societas", "target_ref": "refs/heads/main",
      "expected_base": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "candidate_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "candidate_tree": "dddddddddddddddddddddddddddddddddddddddd",
      "gate_recipe_hash": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
  }
}
```

<!-- fixture:merge_semantic_rebase -->
```json
{
  "kind": "semantic_rebase", "result": "pass",
  "evaluator_tier": "cheap",
  "semantic_recipe_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "decision_index_ref": {
    "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVX1", "version": 1,
    "checksum": "sha256:f94f2497b75d933957d86ee8b7b9863df542bcf78a76c4843c9cf6d6e47a1efe"
  },
  "decision_refs": [
    {
      "role": "base",
      "artifact_ref": {
        "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKA", "version": 1,
        "checksum": "sha256:a3bb507549b094308983e36996697e5636b199557cdfa11eef46eb0a1901aaee"
      }
    },
    {
      "role": "candidate",
      "artifact_ref": {
        "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKB", "version": 2,
        "checksum": "sha256:da617e4b1c18a341b284f0137b8e53492cd8be8fcdf58ee289052e0c3239c91d"
      }
    }
  ],
  "binding": {
    "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
    "policy_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "contract_hash": null,
    "candidate": {
      "repo_id": "repo_societas", "target_ref": "refs/heads/main",
      "expected_base": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "candidate_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "candidate_tree": "dddddddddddddddddddddddddddddddddddddddd",
      "gate_recipe_hash": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
  }
}
```

<!-- fixture:semantic_decision_base -->
```json
{
  "source_role": "base",
  "decision": "Keep transport calls behind the adapter boundary.",
  "source_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

<!-- fixture:semantic_conflict_evidence -->
```json
{
  "kind": "semantic_rebase", "result": "conflict",
  "evaluator_tier": "cheap",
  "semantic_recipe_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "decision_index_ref": {
    "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVX1", "version": 1,
    "checksum": "sha256:f94f2497b75d933957d86ee8b7b9863df542bcf78a76c4843c9cf6d6e47a1efe"
  },
  "decision_refs": [
    {
      "role": "base",
      "artifact_ref": {
        "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKA", "version": 1,
        "checksum": "sha256:a3bb507549b094308983e36996697e5636b199557cdfa11eef46eb0a1901aaee"
      }
    },
    {
      "role": "candidate",
      "artifact_ref": {
        "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKB", "version": 2,
        "checksum": "sha256:da617e4b1c18a341b284f0137b8e53492cd8be8fcdf58ee289052e0c3239c91d"
      }
    }
  ],
  "findings": [{
    "code": "architecture_boundary", "severity": "conflict",
    "summary": "Candidate bypasses the adapter boundary recorded by the base decision."
  }],
  "binding": {
    "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
    "policy_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "contract_hash": null,
    "candidate": {
      "repo_id": "repo_societas", "target_ref": "refs/heads/main",
      "expected_base": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "candidate_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "candidate_tree": "dddddddddddddddddddddddddddddddddddddddd",
      "gate_recipe_hash": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
  }
}
```

<!-- fixture:semantic_decision_candidate -->
```json
{
  "source_role": "candidate",
  "decision": "Call the transport implementation directly from workers.",
  "source_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

<!-- fixture:semantic_decision_index -->
```json
{
  "index_version": "semantic-decision-index/1",
  "workspace_id": "ws_acme", "run_id": "RUN-001",
  "repo_id": "repo_societas", "target_ref": "refs/heads/main",
  "base_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "candidate_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "base_decision_count": 1,
  "base_decisions": [{
    "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKA", "version": 1,
    "checksum": "sha256:a3bb507549b094308983e36996697e5636b199557cdfa11eef46eb0a1901aaee"
  }],
  "candidate_decision_count": 1,
  "candidate_decisions": [{
    "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKB", "version": 2,
    "checksum": "sha256:da617e4b1c18a341b284f0137b8e53492cd8be8fcdf58ee289052e0c3239c91d"
  }],
  "registry_hash": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "generated_by": "system:orchestrator",
  "generated_at": "2026-10-06T09:39:00Z"
}
```

<!-- fixture:merge_review -->
```json
{
  "kind": "review", "result": "approve",
  "binding": {
    "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
    "policy_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "contract_hash": null,
    "candidate": {
      "repo_id": "repo_societas", "target_ref": "refs/heads/main",
      "expected_base": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "candidate_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "candidate_tree": "dddddddddddddddddddddddddddddddddddddddd",
      "gate_recipe_hash": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
  }
}
```

<!-- fixture:approval_merge -->
```json
{
  "snapshot_version": "approval-snapshot/1",
  "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
  "action": "git.merge",
  "policy_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "contract_hash": null,
  "inputs": {
    "candidate": {
      "repo_id": "repo_societas", "target_ref": "refs/heads/main",
      "expected_base": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "candidate_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "candidate_tree": "dddddddddddddddddddddddddddddddddddddddd",
      "gate_recipe_hash": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    },
    "semantic_evidence": {
      "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKX", "version": 1,
      "checksum": "sha256:34618065fc99128a49239de57bf9110abc6342d34d557a569137795320e0ccbe"
    },
    "gate_evidence": {
      "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKP", "version": 1,
      "checksum": "sha256:6360d5aa3738fa2e377f68fb22f5a3efb04a89cf0e9709362fb3fcdaf5537235"
    },
    "review_evidence": {
      "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKQ", "version": 1,
      "checksum": "sha256:4bfa5c74fe806640f757d7f9c127dfdf56ec5f1fb317224385b22ab2c9424ce0"
    }
  }
}
```

<!-- fixture:approval_tool -->
```json
{
  "snapshot_version": "approval-snapshot/1",
  "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
  "action": "tool.execute",
  "policy_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "contract_hash": null,
  "inputs": {
    "tool_call_id": "tc_01J9ZB75QCACYADGWFKD86P7W1", "tool": "external.mutate",
    "arguments": { "path": "src/main.go", "label": "界" },
    "operation_key": "op_task_001_01",
    "resources": [{
      "resource_id": "path:src/main.go",
      "version": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }]
  }
}
```

<!-- fixture:approval_hash_vectors -->
```json
{
  "approval_budget": "sha256:9db02ed91537c1ca63d6d09f9895d669ec210a1cab9859b9362592553510d8a3",
  "approval_merge": "sha256:9a0ceb01bf3c2e7da96a2c56ae770744b87cd9e284e2c8cab050fe7ee80729b1",
  "approval_tool": "sha256:3f629ed1fd3cf4042b9bb510a9308626aa87c49ab2388efe590d9e19f877f06e",
  "merge_semantic_rebase": "sha256:34618065fc99128a49239de57bf9110abc6342d34d557a569137795320e0ccbe",
  "merge_gate": "sha256:6360d5aa3738fa2e377f68fb22f5a3efb04a89cf0e9709362fb3fcdaf5537235",
  "merge_review": "sha256:4bfa5c74fe806640f757d7f9c127dfdf56ec5f1fb317224385b22ab2c9424ce0"
}
```

<!-- example:approval.requested -->
```json
{
  "protocol_version": "societas/1",
  "schema_version": "1",
  "id": "evt_01J9ZB9Y4S06VP158SP5K84RF1",
  "type": "approval.requested",
  "ts": "2026-10-06T09:20:01Z",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBS1VHX1W4W4AGPX1QYFDC",
  "from": "system:policy",
  "to": "human:user",
  "payload": {
    "approval_id": "apr_01J9ZB6W9B4V3CGZKBZ01PDVKN",
    "action": "budget.increase",
    "reason": "Run RUN-001 mencapai budget $1.00 sebelum review selesai. Perlu tambahan untuk melanjutkan.",
    "trigger": "budget",
    "risk": "low",
    "delivery_mode": "immediate",
    "bound_hash": "sha256:9db02ed91537c1ca63d6d09f9895d669ec210a1cab9859b9362592553510d8a3",
    "snapshot_ref": {
      "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKS", "version": 1,
      "checksum": "sha256:9db02ed91537c1ca63d6d09f9895d669ec210a1cab9859b9362592553510d8a3"
    },
    "details": { "suggested_increase_usd": 0.30 }
  }
}
```

<!-- example:approval.requested -->
```json
{
  "protocol_version": "societas/1", "schema_version": "1",
  "id": "evt_01J9ZB9Y4S06VP158SP5K84RF2", "type": "approval.requested",
  "ts": "2026-10-06T09:30:00Z",
  "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBS1VHX1W4W4AGPX1QYFDC",
  "from": "system:policy", "to": "human:user",
  "payload": {
    "approval_id": "apr_01J9ZB6W9B4V3CGZKBZ01PDVKM",
    "action": "git.merge", "reason": "Gate pass dan Reviewer approve pada kandidat final.",
    "trigger": "policy", "risk": "medium", "delivery_mode": "immediate",
    "bound_hash": "sha256:9a0ceb01bf3c2e7da96a2c56ae770744b87cd9e284e2c8cab050fe7ee80729b1",
    "snapshot_ref": {
      "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKR", "version": 1,
      "checksum": "sha256:9a0ceb01bf3c2e7da96a2c56ae770744b87cd9e284e2c8cab050fe7ee80729b1"
    },
    "expires_at": "2026-10-06T10:30:00Z"
  }
}
```

<!-- example:approval.requested -->
```json
{
  "protocol_version": "societas/1", "schema_version": "1",
  "id": "evt_01J9ZB9Y4S06VP158SP5K84RF6", "type": "approval.requested",
  "ts": "2026-10-06T09:35:00Z",
  "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBS1VHX1W4W4AGPX1QYFDC",
  "from": "system:policy", "to": "human:user",
  "payload": {
    "approval_id": "apr_01J9ZB6W9B4V3CGZKBZ01PDVKW",
    "action": "tool.execute", "reason": "Update dependency manifest in isolated worktree.",
    "trigger": "policy", "risk": "high", "delivery_mode": "digest",
    "bound_hash": "sha256:3f629ed1fd3cf4042b9bb510a9308626aa87c49ab2388efe590d9e19f877f06e",
    "snapshot_ref": {
      "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKY", "version": 1,
      "checksum": "sha256:3f629ed1fd3cf4042b9bb510a9308626aa87c49ab2388efe590d9e19f877f06e"
    },
    "expires_at": "2026-10-06T10:30:00Z"
  }
}
```

<!-- example:approval.granted -->
```json
{
  "protocol_version": "societas/1", "schema_version": "1",
  "id": "evt_01J9ZB9Y4S06VP158SP5K84RF3", "type": "approval.granted",
  "ts": "2026-10-06T09:31:00Z",
  "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZB9Y4S06VP158SP5K84RF2",
  "from": "human:user", "to": "system:policy",
  "payload": {
    "approval_id": "apr_01J9ZB6W9B4V3CGZKBZ01PDVKM",
    "bound_hash": "sha256:9a0ceb01bf3c2e7da96a2c56ae770744b87cd9e284e2c8cab050fe7ee80729b1",
    "scope": "once", "granted_by": "human:user"
  }
}
```

<!-- example:approval.invalidated -->
```json
{
  "protocol_version": "societas/1", "schema_version": "1",
  "id": "evt_01J9ZB9Y4S06VP158SP5K84RF4", "type": "approval.invalidated",
  "ts": "2026-10-06T09:32:00Z",
  "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZB9Y4S06VP158SP5K84RF3",
  "from": "system:orchestrator", "to": "human:user",
  "payload": {
    "approval_id": "apr_01J9ZB6W9B4V3CGZKBZ01PDVKM",
    "bound_hash": "sha256:9a0ceb01bf3c2e7da96a2c56ae770744b87cd9e284e2c8cab050fe7ee80729b1",
    "reason": "base_changed"
  }
}
```

<!-- fixture:approval_batch -->
```json
{
  "batch_version": "approval-batch/1",
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "items": [
    {
      "approval_id": "apr_01J9ZB6W9B4V3CGZKBZ01PDVKW",
      "bound_hash": "sha256:3f629ed1fd3cf4042b9bb510a9308626aa87c49ab2388efe590d9e19f877f06e",
      "snapshot_ref": {
        "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKY", "version": 1,
        "checksum": "sha256:3f629ed1fd3cf4042b9bb510a9308626aa87c49ab2388efe590d9e19f877f06e"
      },
      "task_id": "TASK-001"
    }
  ]
}
```

<!-- fixture:approval_batch_item_receipt_granted -->
```json
{
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "batch_hash": "sha256:af70e4125e2376b0c361265f48d3f87969de9caad43e8ec6c8a8d2ab77468720",
  "batch_ref": {
    "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKZ", "version": 1,
    "checksum": "sha256:af70e4125e2376b0c361265f48d3f87969de9caad43e8ec6c8a8d2ab77468720"
  },
  "approval_id": "apr_01J9ZB6W9B4V3CGZKBZ01PDVKW",
  "bound_hash": "sha256:3f629ed1fd3cf4042b9bb510a9308626aa87c49ab2388efe590d9e19f877f06e",
  "outcome": "granted",
  "grant_event_id": "evt_01J9ZB9Y4S06VP158SP5K84RF7",
  "scope": "once",
  "processed_at": "2026-10-06T09:41:00Z"
}
```

<!-- fixture:approval_batch_item_receipt_skipped -->
```json
{
  "workspace_id": "ws_acme",
  "run_id": "RUN-001",
  "batch_hash": "sha256:af70e4125e2376b0c361265f48d3f87969de9caad43e8ec6c8a8d2ab77468720",
  "batch_ref": {
    "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKZ", "version": 1,
    "checksum": "sha256:af70e4125e2376b0c361265f48d3f87969de9caad43e8ec6c8a8d2ab77468720"
  },
  "approval_id": "apr_01J9ZB6W9B4V3CGZKBZ01PDVKW",
  "bound_hash": "sha256:3f629ed1fd3cf4042b9bb510a9308626aa87c49ab2388efe590d9e19f877f06e",
  "outcome": "skipped",
  "reason": "expired",
  "processed_at": "2026-10-06T10:30:00Z"
}
```

<!-- fixture:merge_receipt -->
```json
{
  "receipt_version": "merge-receipt/1",
  "confirmed": true,
  "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
  "repo_id": "repo_societas", "target_ref": "refs/heads/main",
  "expected_base": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "merged_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "merged_tree": "dddddddddddddddddddddddddddddddddddddddd",
  "approval": {
    "approval_id": "apr_01J9ZB6W9B4V3CGZKBZ01PDVKM",
    "bound_hash": "sha256:9a0ceb01bf3c2e7da96a2c56ae770744b87cd9e284e2c8cab050fe7ee80729b1",
    "snapshot_ref": {
      "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKR", "version": 1,
      "checksum": "sha256:9a0ceb01bf3c2e7da96a2c56ae770744b87cd9e284e2c8cab050fe7ee80729b1"
    },
    "grant_event_id": "evt_01J9ZB9Y4S06VP158SP5K84RF3"
  },
  "semantic_evidence": {
    "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKX", "version": 1,
    "checksum": "sha256:34618065fc99128a49239de57bf9110abc6342d34d557a569137795320e0ccbe"
  },
  "gate_evidence": {
    "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKP", "version": 1,
    "checksum": "sha256:6360d5aa3738fa2e377f68fb22f5a3efb04a89cf0e9709362fb3fcdaf5537235"
  },
  "review_evidence": {
    "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKQ", "version": 1,
    "checksum": "sha256:4bfa5c74fe806640f757d7f9c127dfdf56ec5f1fb317224385b22ab2c9424ce0"
  },
  "validated_at": "2026-10-06T09:31:00Z",
  "confirmed_at": "2026-10-06T09:45:00Z"
}
```

<!-- fixture:semantic_arbitration_decision -->
```json
{
  "decision_version": "semantic-arbitration/1",
  "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
  "semantic_evidence": {
    "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKC", "version": 1,
    "checksum": "sha256:7186b9d33078268d83422acdf59d197ca6f0dd9e0ee607014b611400860cce2f"
  },
  "issued_by": "cto",
  "selected_decision_refs": [{
    "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKA", "version": 1,
    "checksum": "sha256:a3bb507549b094308983e36996697e5636b199557cdfa11eef46eb0a1901aaee"
  }],
  "refactor_task_ids": ["TASK-003"],
  "rationale": "Preserve the adapter boundary and refactor the direct worker call.",
  "acceptance_constraints": ["Worker code must depend on the adapter interface."],
  "created_at": "2026-10-06T09:42:00Z"
}
```

<!-- example:approval.batch_submitted -->
```json
{
  "protocol_version": "societas/1", "schema_version": "1",
  "id": "evt_01J9ZB9Y4S06VP158SP5K84RF5", "type": "approval.batch_submitted",
  "ts": "2026-10-06T09:40:00Z",
  "workspace_id": "ws_acme", "run_id": "RUN-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBS1VHX1W4W4AGPX1QYFDC",
  "from": "human:user", "to": "system:orchestrator",
  "payload": {
    "batch_hash": "sha256:af70e4125e2376b0c361265f48d3f87969de9caad43e8ec6c8a8d2ab77468720",
    "batch_ref": {
      "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKZ", "version": 1,
      "checksum": "sha256:af70e4125e2376b0c361265f48d3f87969de9caad43e8ec6c8a8d2ab77468720"
    }
  }
}
```

<!-- example:task.semantic_conflict -->
```json
{
  "protocol_version": "societas/1", "schema_version": "1",
  "id": "evt_01J9ZB9Y4S06VP158SP5K84RF8", "type": "task.semantic_conflict",
  "ts": "2026-10-06T09:42:00Z",
  "workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": "TASK-001",
  "correlation_id": "cor_01J9ZBKGD7AHHWX216KWWYZH2T",
  "causation_id": "evt_01J9ZBS1VHX1W4W4AGPX1QYFDC",
  "from": "system:orchestrator", "to": "agent:cto",
  "payload": {
    "outcome": "conflict",
    "semantic_evidence": {
      "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKC", "version": 1,
      "checksum": "sha256:7186b9d33078268d83422acdf59d197ca6f0dd9e0ee607014b611400860cce2f"
    },
    "blocked_evidence": {
      "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKC", "version": 1,
      "checksum": "sha256:7186b9d33078268d83422acdf59d197ca6f0dd9e0ee607014b611400860cce2f"
    },
    "decision_refs": [
      {
        "role": "base",
        "artifact_ref": {
          "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKA", "version": 1,
          "checksum": "sha256:a3bb507549b094308983e36996697e5636b199557cdfa11eef46eb0a1901aaee"
        }
      },
      {
        "role": "candidate",
        "artifact_ref": {
          "artifact_id": "art_01J9ZB6W9B4V3CGZKBZ01PDVKB", "version": 2,
          "checksum": "sha256:da617e4b1c18a341b284f0137b8e53492cd8be8fcdf58ee289052e0c3239c91d"
        }
      }
    ],
    "conflict_summary": "Candidate bypasses the transport adapter boundary.",
    "escalation_lead": "cto"
  }
}
```

## 72A.12 Validasi, Versioning & Kompatibilitas

**Validasi di dua titik:** saat pengirim mempublikasikan, dan saat Event Bus menerima. Pesan yang gagal validasi **tidak masuk Event Store**. Pesan itu dicatat di dead-letter log beserta alasannya, dan pengirim menerima `SCHEMA_VALIDATION_FAILED`.

**Boundary payload (I5):** sesudah validasi envelope dan payload menurut registry, hitung `len(UTF8(JSON(payload)))` atas JSON compact dengan serialisasi kanonik RFC 8785 (JCS). Field envelope tidak termasuk hitungan ini; seluruh field payload, nested object, array, key, escaping, dan overhead struktur termasuk. Batas tepat sama dengan limit diterima; `limit + 1` ditolak. String multibyte dihitung byte, bukan rune/karakter. Serializer yang tidak dapat merepresentasikan payload dengan aman juga menolak payload. Output besar dipersist sebagai artifact terlebih dahulu, lalu payload berisi referensi + ringkasan yang tetap memenuhi limit. Boundary penerima tidak memotong diam-diam: pelanggaran menghasilkan `SCHEMA_VALIDATION_FAILED` sebelum persistence/delivery. Ini pemeriksaan runtime tambahan, bukan klaim bahwa JSON Schema `maxLength` membatasi object.

**Boundary pause/resume:** `task_id` wajib pada `task.paused`, `task.resumed`, `task.interrupted`, `task.rebase_conflict`, `task.semantic_conflict`, dan `task.contract_changed`. Untuk pause `requested`, sender harus `human:user`, tujuan `system:orchestrator`, dan `initiated_by` sama dengan sender. Untuk pause `completed`, sender harus `system:orchestrator`, tujuan `topic:all`, dan `initiated_by` menunjuk human peminta yang tersimpan. `task.resumed` hanya diterbitkan `system:orchestrator`, ditujukan ke owner task; `from_status` harus cocok dengan state tersimpan. Pemeriksaan envelope/payload/state bersama ini diperlukan karena payload schema saja tidak memvalidasi sender atau state SQLite.

**Boundary approval:** schema tidak memeriksa hash/artifact/state sendirian. Pada request: envelope workspace/run/task cocok snapshot (task yang tidak berlaku = null), action cocok snapshot, delivery mode/risk diizinkan policy, dan checksum snapshot_ref cocok bound_hash. Pada grant: ID/hash cocok request tersimpan yang masih valid; budget_override, bila ada, persis proposed_limits untuk action budget.increase dan tidak boleh ada pada aksi lain. Pada `approval.batch_submitted`: Event Bus memverifikasi envelope pengirim/tujuan; Orchestrator membaca versi artifact tepat, memvalidasi JCS/hash/schema/checksum, workspace/run, urutan dan keunikan approval ID, lalu mengevaluasi tiap item terhadap request serta policy yang masih berlaku. Command duplikat memakai durable receipt per item. Untuk `git.merge`, semantic evidence harus `pass` pada binding kandidat yang sama saat approval dan final dispatch; `conflict`/`inconclusive` tidak boleh lolos walau artifact lain valid. Pada invalidation: Orchestrator mencatat ID/hash lama yang diikat, bukan hash pengganti. Snapshot/evidence versions, profile, checksum, policy, expiry dan live input dicek ulang sebelum dispatch. Unknown action, lost/tampered snapshot, stale grant atau evidence mismatch menghasilkan `APPROVAL_BINDING_INVALID`; mismatch input terikat menginvalidasi ID lama. General auth principal dan atomisitas consumption tetap keputusan terpisah.

**Versioning:**

- `schema_version` menunjukkan versi seluruh set schema di Section 72A.
- Karena schema bersifat strict (`additionalProperties: false`), setiap perubahan bentuk (termasuk menambah field opsional) menaikkan `schema_version`.
- Konsumen wajib mendukung versi terbaru (N) dan sebelumnya (N-1). Perubahan breaking harus disertai fungsi migrasi (#72).
- Event Store menyimpan event apa adanya beserta `schema_version`, sehingga replay (#68) menjalankan migrasi saat membaca.
- Sebelum "Stable agent schema" tercapai (#82), schema boleh berubah in-place. Setelah itu aturan di atas berlaku penuh.

**Tata letak repo yang disarankan:**

```text
schemas/
  1/
    common.json
    envelope.json
    budget.json  usage.json  usage_totals.json  error.json
    task.json  artifact_ref.json  summary.json
    payloads/
      run_created.json  delegate_requested.json  ...
    registry.json        # type -> schema, dari tabel 72A.7
```

`societas doctor` (#94) sebaiknya memeriksa bahwa file schema lengkap dan registry konsisten.

## 72A.13 Contract Acceptance Criteria

Kontrak dianggap selesai jika:

- Semua contoh JSON di Section 72A lolos validasi terhadap schema (dijalankan di CI)
- Setiap `type` di registry punya tepat satu schema, dan tidak ada schema yatim
- Envelope tanpa field wajib ditolak
- `type` yang tidak dikenal ditolak
- Payload dengan field tambahan ditolak
- `idempotency_key` ganda tidak menimbulkan efek ganda
- Grant budget anak yang melebihi sisa parent ditolak dengan `BUDGET_EXCEEDED`
- Delegasi melebihi `max_child_tasks` ditolak dengan `FANOUT_LIMIT_EXCEEDED`
- Transisi task di luar tabel 72A.6 ditolak
- Urutan event model call sesuai 72A.10, dan model tidak dipanggil jika guard gagal
- Tidak ada jalur agent-ke-agent yang melewati Event Bus
- Konten melebihi batas inline ditolak atau dipindahkan menjadi artifact
- Replay dari Event Store menghasilkan state task yang sama
- Pause requested/completed memakai sender/fase yang tepat; task `pausing` pulih menjadi `interrupted`, deadline tidak hilang, dan cancel tidak menganggap side effect pasti batal
- `contract_status: stale` menolak dispatch/review/approval/completion; re-pin direkam dan task terminal tidak dibuka kembali
- Approval request/grant divalidasi terhadap ID + snapshot artifact version/checksum; `bound_hash` harus sama dengan SHA-256 byte JCS snapshot, bukan raw Git OID
- `risk: critical` hanya memakai `delivery_mode: immediate`; `digest` hanya menerima high. Manifest digest immutable per workspace/run, JCS/hash/identity tervalidasi, item unik/terurut dan cocok dengan request; grant per item selalu `scope: once`, stale item dilewati, partial result dilaporkan
- `approval.batch_submitted` duplikat tidak menggandakan grant/aksi; manifest invalid ditolak sebagai satu command dan setiap item di-recheck terhadap risk/policy/expiry/live binding sebelum grant
- Item receipt memakai unique key `(workspace_id, run_id, batch_hash, approval_id)`; granted/skipped replay mengembalikan receipt yang sama. Transactional grant + outbox + receipt tersimpan sebelum event delivery, tanpa mengklaim recovery lintas subsistem W06 selesai
- Tool mutation memakai normalized arguments/resource versions yang sama dengan snapshot; perubahan live input/policy/contract/expiry menginvalidasi ID lama sebelum dispatch
- Merge approval hanya sesudah rebase + gate pass + Semantic Rebase `PASS` + review approve pada commit/tree/base/recipe/context yang sama; snapshot mengikat gate/semantic/review evidence beserta versi recipe dan keputusan semantik, dan perubahan salah satu input mengulang evidence + approval
- Semantic `conflict` dan `inconclusive` memblokir task dengan immutable `blocked_evidence` dan dieskalasi ke `escalation_lead`; keputusan/spec baru baru eligible embedding setelah approval + semantic pass + merge receipt yang mengikat refs/version/checksum sama terkonfirmasi
- Dua kandidat dari expected base yang sama tidak dapat keduanya masuk: integrasi kedua gagal expected-base CAS, tanpa overwrite/rebase/commit baru sesudah approval
- Tool mutatif yang kehilangan response tidak diulang otomatis tanpa jaminan I16; `operation_key` yang tidak ditegakkan provider bukan jaminan
- Object nested, agregat beberapa string, dan string UTF-8 multibyte melewati pemeriksaan byte I5 (uji `limit`, `limit + 1`)
- Digest snapshot sama meski urutan key berbeda; perubahan argumen/base/kandidat/evidence/policy/contract mengubah hash. Grant dengan hash lama, snapshot artifact version/checksum salah, dan evidence kandidat lain ditolak
- Dua kandidat approved atas base yang sama tidak boleh keduanya diterapkan: expected-base CAS kedua gagal, evidence/approval diulang; expiry/perubahan saat parked dicek lagi sebelum dispatch

---

# 79. MVP

MVP harus kecil.

Target MVP:

```text
User
 ↓
CEO
 ├── Research
 └── CTO
       ↓
     Engineer
```

Capabilities:

- agent config
- agent runtime
- task creation
- delegation
- messaging
- event stream
- artifact creation
- basic memory
- tool execution
- human approval
- basic dashboard
- Event Bus internal (Go channel)
- orchestrator
- budget manager
- context manager
- model router
- cost tracking
- basic policy engine

---

# 80. MVP Demo

User menjalankan:

```bash
societas init my-company
cd my-company
societas serve
```

Kemudian:

```bash
societas start
```

Dashboard:

```text
SOCIETAS

CEO        ● Working
CTO        ● Working
Research   ● Working
Engineer   ○ Idle
```

User:

```text
CEO:
"Research apakah event-driven architecture
cocok untuk multi-agent system."
```

CEO:

```text
Assigning:

Research -> technology research
CTO      -> architecture evaluation
```

Research berjalan.

CTO berjalan paralel.

CEO menggabungkan hasil.

Kemudian:

```text
CEO:
"Engineer, build a minimal prototype."
```

Engineer membuat:

```text
prototype/
benchmark/
report.md
```

Reviewer mengecek.

User mendapat hasil akhir.

---

# 81. MVP Acceptance Criteria

MVP dianggap selesai jika:

### Agents

- minimal 4 agent dapat berjalan
- role dapat dikonfigurasi
- model dapat dikonfigurasi
- status agent terlihat

### Tasks

- task dapat dibuat
- task dapat didelegasikan
- dependency dapat digunakan
- task dapat selesai/gagal

### Communication

- agent dapat saling mengirim message
- message dapat di-stream
- event dapat dipantau

### Tools

- minimal filesystem
- shell terbatas
- git opsional (**baseline belum dikunci**: bertentangan dengan workflow wajib #60.1/#60.4; keputusan W15 diperlukan sebelum implementasi MVP Engineer)

### Artifacts

- agent dapat membuat artifact
- artifact dapat dibaca agent lain

### Human

- user dapat memberikan task
- user dapat approve/reject action

### Transport

- agent dapat berkomunikasi melalui Event Bus internal
- reconnect dasar tersedia
- event tidak hilang secara tidak terkendali

### AI Control Plane

- budget task enforced
- context budget enforced
- model selection tersedia
- token/cost usage tercatat
- maximum iterations tersedia
- fan-out limit tersedia
- stop condition tersedia

### Contracts

- semua event memakai envelope Section 72A.3
- payload divalidasi terhadap schema (boundary publish dan receive)
- type dan field tidak dikenal ditolak
- agent tidak dapat berkomunikasi langsung, semua lewat Event Bus
- transisi status task mengikuti 72A.6
- error memakai katalog 72A.9

### Dashboard

- agent status
- task status
- live events
- artifacts
- approvals

---

# 82. Phase Roadmap

## v0.1 — Foundation

- Workspace
- Agent config
- Agent runtime
- Local model/provider interface
- Task model
- Event model
- SQLite
- Web API (backend)

---

## v0.2 — Multi-Agent

- Multiple agents
- Delegation
- Agent messaging
- Task graph
- Artifact system
- Basic memory

---

## v0.3 — Real-Time Layer

- Event Bus (Go channel)
- Streaming message
- Event subscriptions
- Agent presence
- Reconnect
- Heartbeat
- Backpressure

---

## v0.4 — Agent Company

- CEO orchestrator
- Role system
- Parallel task execution
- Approval system
- Tool permissions
- Run history
- Replay

---

## v0.5 — Developer Agent

- Filesystem
- Shell
- Git
- Test execution
- Code artifacts
- Review agent
- Research agent

---

## v0.6 — Live Workspace

- Full dashboard
- Agent graph
- Task board
- Live event stream
- Artifact explorer
- Approval center
- Usage analytics

---

## v0.7 — Multimodal

- Voice
- ASR
- TTS
- Image inputs
- Streaming audio
- Real-time interruption

---

## v0.8 — Distributed

- Remote agents
- WebSocket relay
- Multi-machine
- Multi-hop
- Shared state
- Node discovery

---

## v0.9 — Advanced Agent Runtime

- Advanced memory
- Context management
- Agent-to-agent protocols
- More tools
- Advanced scheduling
- Retry policies
- Cost optimization

---

## v1.0 — Stable Platform

- Stable protocol
- Stable agent schema
- Stable task schema
- Migration tools
- Documentation
- Test suite
- Security review
- Performance benchmarks

---

# 83. Future Experimental Ideas

Eksperimen dapat dilakukan tanpa mengubah core product.

## 83.1 Voice Company

User berbicara dengan CEO.

CEO dapat memanggil CTO/Research/Engineer.

---

## 83.2 AI War Room

Beberapa agent berdebat mengenai satu keputusan.

Contoh:

```text
CEO:
Should we use gRPC or REST?

CTO:
gRPC.

Security:
WebSocket is simpler for deployment.

Performance:
gRPC wins under concurrency.

CEO:
Reviewer, resolve this.
```

---

## 83.3 AI Standup

Setiap hari:

```text
CEO:
Give me status.

CTO:
3 tasks done.

Research:
2 findings.

Engineer:
PR ready.

Reviewer:
1 blocker.
```

System menghasilkan:

```text
daily-standup.md
```

---

## 83.4 AI Board Meeting

Semua role ikut rapat virtual:

```text
CEO
CTO
CPO
Research
Security
Finance
```

Agenda → discussion → decision → artifacts.

---

## 83.5 Agent Simulation

User dapat menjalankan organisasi tanpa manusia sebagai test.

```text
autonomous run
```

Dengan budget:

```text
max_tokens
max_time
max_tasks
max_cost
```

---

## 83.6 Agent Market

Future, bukan MVP.

User dapat membuat/import role pack:

```text
security-team
startup-team
game-dev-team
research-team
```

---

# 85. Technical Priorities

Urutan engineering:

```text
1. Correctness
2. Agent lifecycle
3. Task correctness
4. Tool safety
5. Event consistency
6. Reliability
7. Real-time transport
8. Observability
9. Performance
10. UX
11. Distributed execution
```

---

# 86. Go Strategy

Go digunakan untuk seluruh backend:

- agent runtime (goroutine per agent)
- event bus (channel)
- HTTP API server
- WebSocket server
- concurrency
- storage layer

Kelebihan yang ingin dicapai:

- development speed tinggi
- concurrency model simpel (goroutine + channel)
- single binary deployment
- compile cepat
- standard library kuat (net/http, encoding/json)

---

# 89. Security Checklist

Sebelum release production:

```text
[ ] Secret redaction
[ ] Tool permissions
[ ] Shell restrictions
[ ] Path restrictions
[ ] Approval system
[ ] Authenticated agent session
[ ] Transport security
[ ] Input validation
[ ] Resource limits
[ ] Safe logging
[ ] Artifact isolation
[ ] Workspace isolation
```

---

# 90. Data Ownership

Default:

```text
User owns:
- workspace
- events
- artifacts
- memory
- credentials
- configuration
```

Tidak ada telemetry external secara default kecuali user memilihnya.

---

# 94. Web Health Check

Endpoint untuk debugging dan monitoring:

```text
GET /health
GET /health/agents
GET /health/event-bus
GET /health/storage
GET /health/providers
```

Response:

```json
{
  "status": "ok",
  "workspace": "tunly",
  "agents": { "running": 4, "idle": 1 },
  "event_bus": "connected",
  "storage": "ok",
  "providers": { "openai": "ok" }
}
```

---

# 97. Definition of Done

Feature dianggap selesai jika:

## Code

- implementation selesai
- error handling tersedia
- tidak ada unsafe default yang tidak diperlukan

## Tests

- unit test
- integration test bila relevan
- failure test bila relevan

## Security

- permission diperiksa
- secret tidak bocor
- input divalidasi
- resource bounded

## Documentation

- config documented
- API documented
- protocol documented
- examples tersedia

## Observability

- logs tersedia
- events dapat dilacak
- correlation ID tersedia bila relevan

---

# 99. First Killer Demo

Demo pertama harus sederhana tetapi terasa hidup:

```text
User
 |
 v
CEO
 |
 +----> Research
 |
 +----> CTO
 |
 +----> Security
          |
          v
        CEO
          |
          v
       Engineer
          |
          v
       Reviewer
          |
          v
        Human
```

Semua aktivitas tampil real-time.

Dashboard menampilkan:

```text
CEO        ● Delegating
Research   ● Researching
CTO        ● Reviewing
Security   ● Analyzing
Engineer   ● Waiting
Reviewer   ○ Idle
```

Live event stream:

```text
CEO -> Research:
"Investigate best practices for multi-agent systems."

Research:
"Starting research."

CEO -> CTO:
"Evaluate transport architecture."

CTO:
"Working on architecture."

Research -> CEO:
"Found 8 relevant findings."

CEO -> Engineer:
"Build minimal prototype."

Engineer:
"Starting implementation."
```

Ketika semuanya selesai:

```text
Decision:
Proceed with Event Bus + WebSocket for real-time communication.

Artifacts:
research.md
architecture.md
security-review.md
benchmark.md
prototype/
```

Human tinggal memutuskan.

---

# 101. Final Product Vision

Tujuan akhirnya bukan membuat:

```text
chatbot #9999
```

Tetapi membuat:

```text
                     YOU
                      |
                      v
                 SOCIETAS
                      |
       +--------------+--------------+
       |              |              |
      CEO            CTO           Research
       |              |              |
       +--------------+--------------+
                      |
                 Agent Network
                      |
       +--------------+--------------+
       |              |              |
     Engineer      Reviewer       Security
       |              |              |
       +--------------+--------------+
                      |
                   ARTIFACTS
                      |
                      v
                     YOU
```

Sistem harus terasa seperti sebuah **organisasi hidup**:

- agent punya role
- agent punya tanggung jawab
- agent punya state
- agent dapat bekerja paralel
- agent dapat berkomunikasi realtime
- agent dapat memakai tools
- agent dapat membuat artifacts
- agent dapat mereview pekerjaan
- agent dapat meminta approval
- manusia tetap memegang keputusan penting

Event Bus menjadi lapisan komunikasi real-time yang memungkinkan organisasi tersebut berjalan sebagai sistem yang terkoordinasi.

---

# 102. Core Philosophy

```text
Build for yourself first.

Make it useful before making it popular.

Make it simple before making it distributed.

Make it reliable before making it autonomous.

Make it observable before making it complex.

Make it fast, then prove it with benchmarks.

Keep the core open.

Let the agents do the work.

Keep the human in control.
```

---

# 103. Immediate Development Order

Urutan pertama yang direkomendasikan (urutan Event Bus terhadap delegation/messaging masih menunggu keputusan W15; jangan memperlakukan daftar ini sebagai urutan dependency yang sudah final):

```text
1. Workspace
2. Agent schema
3. Agent runtime
4. LLM provider abstraction
5. Task model
6. Event model
7. Contracts (schema + validator, Section 72A)
8. SQLite storage
9. Orchestrator
10. Budget Manager
11. Context Manager
12. Model Router
13. Cost Tracker
14. Policy Engine
15. Agent messaging
16. CEO delegation
17. Artifact system
18. Tool runtime
19. Permission system
20. Approval system
21. Event Bus (Go channel)
22. Streaming
23. Reconnect / heartbeat
24. Dashboard
25. Research agent
26. Engineer agent
27. Reviewer agent
28. Memory
29. Usage optimization
30. Voice / multimodal
31. Distributed agents
```

---

# 104. Absolute MVP Scope

MVP wajib bisa melakukan satu flow end-to-end:

```text
Human
  |
  v
CEO
  |
  +------> Research
  |
  +------> CTO
              |
              v
           Engineer
              |
              v
           Reviewer
              |
              v
             CEO
              |
              v
            Human
```

Dengan:

```text
- Task
- Delegation
- Agent-to-agent message
- Tool call
- Artifact
- Event stream
- Human approval
- Basic dashboard
- Budget & context control (AI Control Plane)
- Contracts tervalidasi (envelope + schema, Section 72A)
```

Jika flow ini sudah bekerja dengan stabil, project sudah mempunyai dasar produk yang kuat.

---

# 105. Anti-Boncos Rules

Aturan default untuk menjaga biaya LLM:

1. Jangan broadcast full context ke semua agent.
2. Gunakan summary + artifact reference.
3. Gunakan model murah untuk routing dan summarization.
4. Gunakan model kuat hanya ketika dibutuhkan.
5. Semua task memiliki token/cost budget.
6. Semua retry memiliki batas.
7. Semua autonomous loop memiliki batas iterasi.
8. Semua fan-out memiliki batas.
9. Context retrieval harus relevance-based.
10. Model call harus melewati Budget Manager sebelum dieksekusi.

Prinsip paling penting:

> Token adalah resource. Treat token seperti CPU, RAM, bandwidth, dan waktu.

Jika sebuah workflow tidak dapat menjelaskan mengapa sebuah agent dipanggil dan mengapa context tertentu diberikan, workflow tersebut harus dianggap belum optimal.

Setiap delegasi wajib mencatat `rationale` (mengapa agent ini dipanggil), dan setiap context yang dibangun wajib mencatat `reason` per item (mengapa context ini diberikan). Lihat Section 72A.8.

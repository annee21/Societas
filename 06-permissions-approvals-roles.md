<!-- Doc 06 — Permission, Approval, Role & Agent (§22–32)
     Bagian dari societas-full-product-spec. Urutan dokumen diatur di README.md.
     Nomor section dipertahankan; referensi silang antar-doc memakai nomor section (#N, 5A.x, 72A.x). -->

# 22. Permission System

Permission bersifat granular dan di-enforce secara deterministik oleh **Policy Engine di level backend Go** — bukan oleh keputusan model, bukan blocklist, dan tanpa state-observer snapshot yang berat.

## 22.1 Strict Allowlist (Default-Deny)

Agen shell hanya boleh mengeksekusi binary yang terdaftar eksplisit di YAML. Binary di luar daftar otomatis ditolak oleh Policy Engine.

```yaml
permissions:
  filesystem:
    mode: read_write
    scope: workspace

  shell:
    mode: allowlist
    allowed:
      - go
      - git
      - npm
      - cargo
      - make

  git:
    mode: read_write

  network:
    mode: allowed
```

## 22.2 Path Jailing

Eksekusi proses dikunci ke `Current Working Directory` (`./workspace` atau worktree task, #60.1). Adapter binary/subcommand membedakan path, pola paket, identifier, dan nilai flag. Untuk argumen path, Policy Engine menolak:

- path traversal yang setelah normalisasi/resolusi keluar jail
- direktori absolut (`/`, `/etc`, ...)
- path home (`~`)

Slash relatif bukan pelanggaran: `src/main.go`, pola paket `./...`, dan identifier paket `@scope/pkg` boleh diterima menurut adapter. Nilai flag path juga diperiksa; bentuk absolut mengikuti OS, termasuk drive/UNC. Argumen ambigu ditolak secara default, bukan dilewatkan. Contoh konfigurasi semantic guard ada di #59.

Penting: **string filtering BUKAN sandboxing yang aman.** Binary allowlist seperti `go build`, `npm`, atau `cargo` dapat mengeksekusi kode arbitrary (build scripts, codegen, post-install) dan argumen path rentan symlink escape. Path jailing hanya lapis pertama — eksekusi build/test/shell **wajib** berjalan di dalam OS-level isolation (#59.1).

## 22.3 Approval untuk Mutasi Skala Besar

Perintah mutasi direktori berskala besar wajib meminta `human approval` sebelum dijalankan (lihat #23).

---

# 23. Approval System

Tool berisiko tinggi harus dapat meminta approval. Menunggu approval bersifat **non-blocking**: task diparkir sebagai Step Function (#40.1) — bukan goroutine yang menunggu channel. Request approval mengikat `bound_hash` (#40.2) agar keputusan hanya valid terhadap kondisi kode saat request dibuat.

Contoh:

```text
Engineer wants to execute:

rm -rf ./build

Approval required.
```

User dapat:

```text
[ Approve ]
[ Reject ]
```

Approval dapat disimpan sebagai event.

Kontrak wire mengikuti 72A.8/I17: request menunjuk snapshot artifact ID/versi/checksum, grant menggemakan `bound_hash`. Approval tidak lagi valid bila input aktual, policy/contract atau evidence berubah; runtime menerbitkan `approval.invalidated` dan meminta keputusan pada request baru. UI scope tidak mengizinkan bypass hash kandidat final (#40.2/#60.4).

## 23.1 Risk-Aware Approval

Approval bersifat risk-aware. Evaluasi risiko dilakukan **dinamis** lewat konfigurasi `workspace.yaml` (lihat #36), berdasarkan:

- `path_patterns`: mis. `migrations/**`, `src/auth/**`, `infra/**`, `contracts/**`
- `intent_keywords`: mis. `drop database`, `secret`, `deploy`, `payout`

Task `risk_tier: critical` **dikunci**: semua eksekusi mutasi wajib `delivery_mode: immediate` dan human approval sebelum dijalankan, terlepas dari autonomy level agen (lihat #24, 5A.8). Aksi `risk_tier: high` yang memerlukan approval masuk `delivery_mode: digest` dan tidak boleh dieksekusi sebelum grant tervalidasi.

Runtime Escalation: jika agen di tengah jalan mencoba mengakses file di luar rencana yang masuk kategori kritis (`path_patterns` critical), Policy Engine **otomatis menaikkan status menjadi `risk_tier: critical`**, membekukan eksekusi, dan meminta human approval — tanpa menunggu klasifikasi ulang task.

Mode delivery mengikuti klasifikasi akhir setelah runtime escalation: setiap kenaikan ke `critical` membatalkan eligibility digest dan memicu synchronous halt; itemnya di-skip dari manifest, bukan disetujui atau ditampilkan sebagai persetujuan langsung. Perubahan `path_patterns`/policy yang terikat snapshot membatalkan approval lama dan memerlukan evaluasi serta request baru.

## 23.2 Human Attention Budget & Digest Approval

Human attention adalah resource terbatas, bukan budget token. Risk mengatur urgensi notifikasi, bukan kekuatan approval binding atau izin tool.

- **Critical → immediate / Synchronous Halt.** Drop table, force push, breaking consensus, dan transfer funds menghentikan mutasi serta dependency yang terdampak sebelum side effect; kirim notifikasi segera dan wajib keputusan individual. Tidak masuk digest atau **Approve All**. Worker task tetap dilepas; task independen/workspace lain tidak otomatis dihentikan.
- **High → digest bila mode aktif.** Mutasi rute API/dependensi, cleanup cache, atau shell terisolasi hanya contoh klasifikasi policy, bukan izin otomatis. Request diparkir dan dihimpun menurut interval/akhir siklus (#33.7/#36). Path critical mengalahkan high; command di luar allowlist tetap deny.

`awaiting_approval (batch)` adalah label UI untuk `status: awaiting_approval` + request `delivery_mode: digest`, **bukan enum task baru**. SQLite menyimpan checkpoint, snapshot/request, expiry, dan relasi manifest. Worker/goroutine/working set task dilepas saat menunggu (#40.1); agen boleh mengambil backlog independen yang lolos dependency, permission, budget, dan concurrency guard.

**Approve All Validated** hanya satu klik presentasi. Backend mengikat daftar yang dilihat ke manifest artifact/version/hash, memvalidasi ulang tiap request dan menerbitkan grant `scope: once` per item (I18, 72A.8). Critical, stale, expired, rejected, changed input, atau already-processed tidak otomatis disetujui; hasil parsial menyebutkan alasan. Scope/grant tetap I17/I16. Summary Manager/LLM tidak dapat menambah item, mengubah risk, atau memberi approval.

---

# 24. Agent Autonomy Levels

Setiap agent dapat mempunyai autonomy level.

## Level 0 — Manual

Agent hanya menjawab.

## Level 1 — Suggested

Agent menyarankan tindakan tetapi tidak menjalankan.

## Level 2 — Approved

Agent dapat bekerja setelah task diberikan.

## Level 3 — Autonomous

Agent dapat membuat subtasks dan memanggil tools dalam permission scope.

## Level 4 — Orchestrated

Agent dapat mengatur agent lain.

Default sebaiknya tidak langsung Level 4.

---

# 25. CEO Agent

CEO adalah orchestration agent.

Tanggung jawab:

- memahami objective
- membuat plan
- delegasi
- menggabungkan hasil
- mendeteksi konflik
- meminta review
- mengambil recommendation
- menyerahkan keputusan akhir ke human

CEO tidak otomatis memiliki semua permission.

CEO sebaiknya menjadi **coordinator**, bukan superuser.

---

# 26. CTO Agent

CTO bertanggung jawab terhadap:

- architecture
- technical feasibility
- performance
- reliability
- security
- engineering standards

CTO dapat melakukan:

```text
design
review
benchmark
architecture decision
risk analysis
```

---

# 27. Research Agent

Research agent dapat:

- melakukan search
- membaca source
- meringkas
- membandingkan
- mengumpulkan evidence
- membuat research report

Output:

```text
sources.md
research.md
comparison.md
```

Research agent harus membedakan:

```text
fact
inference
unknown
```

---

# 28. Engineer Agent

Engineer dapat:

- membaca repo
- membuat code
- menjalankan test
- melakukan benchmark
- membuat patch
- membuka artifact patch

Engineer tidak otomatis boleh melakukan deployment production.

Output kode Engineer selalu melewati **Deterministic Toolchain Runner** (pipeline build/lint/test lokal, 0 token, fail-fast) sebelum diserahkan ke Reviewer (lihat [5A.22 — Compiler Gate](02-ai-control-plane.md#compiler-gate-sebelum-reviewer-dipanggil), #29, `toolchain` di #36).

Mekanisme penulisan kode ke worktree memakai **Search & Replace Block** (#60.3) — Engineer tidak menulis ulang seluruh file dan tidak mengarang header unified diff. Serial Merge Queue (#60.4) melakukan rebase/resolve → freeze candidate → deterministic gate → Semantic Rebase → Reviewer → approval. Snapshot mengikat commit/tree/base, gate/semantic/review evidence dan recipe; perubahan input membatalkan approval/evidence (I17/I19, 72A.8/72A.10). Textual conflict kembali ke Engineer; semantic conflict/inconclusive diparkir untuk `escalation_lead` (#48.5) dan refactor asinkron, bukan langsung merge.

Untuk integrasi kontrak/API, Engineer mengikuti alur **Contract-First** (#17.1): codegen binding otomatis + `contract.lookup`, bukan menulis call manual.

---

# 29. Reviewer Agent

Reviewer fokus pada:

- bug
- security
- performance regression
- code quality
- architecture violation
- missing tests

Output:

```text
review.md
```

Reviewer dapat memberikan:

```text
PASS
PASS_WITH_WARNINGS
REQUEST_CHANGES
BLOCKED
```

Label tampilan yang ekuivalen dipetakan ke wire `review.completed.verdict` (72A.8): `PASS` → `approve`, `PASS_WITH_WARNINGS` → `approve` dengan temuan advisory nonblocking, `REQUEST_CHANGES` → `request_changes`. `reject` adalah penolakan final hasil review, bukan state task `blocked`. Label legacy `BLOCKED` tidak boleh otomatis diubah menjadi `reject` atau mengubah state task; maknanya masih menunggu keputusan I01 (penolakan final vs menunggu dependency/policy). Adapter wajib menghasilkan verdict kanonik yang eksplisit sebelum hasil review diproses.

Reviewer LLM **hanya dipanggil setelah Local Compiler Gate lolos** ([5A.22 — Compiler Gate](02-ai-control-plane.md#compiler-gate-sebelum-reviewer-dipanggil)): backend Go menjalankan build/linter lokal terlebih dahulu dengan biaya 0 token; kegagalan sintaks dikembalikan langsung ke Engineer tanpa memanggil Reviewer.

---

# 30. Role Customization

User dapat membuat role sendiri — arsitektur **murni Config-Driven**.

Contoh:

```yaml
agents:
  legal:
    role: "Legal Advisor"

  finance:
    role: "Financial Analyst"

  growth:
    role: "Growth Strategist"

  security:
    role: "Security Engineer"
```

Tidak ada batas role fixed.

## 30.1 Declarative Squad Composition

- Backend Go agnostik terhadap hierarki & peran — tidak ada enum peran yang dikompilasi; Go membaca `agents:` di `workspace.yaml` sebagai `map[string]AgentConfig` saat runtime.
- Routing & eskalasi berbasis konfigurasi: Jev AI / Model Router hanya boleh merutekan tugas ke **ID agen yang aktif terdaftar** pada konfigurasi workspace terkait; merutekan ke ID tidak dikenal ditolak deterministik.
- **Dynamic Enum Injection:** schema delegasi yang disiapkan runtime untuk tiap agen mengunci `requested_assignee` ke `enum` dinamis (ID agen aktif + `null`) dan memanfaatkan constrained decoding — LLM tidak bisa mengarang nama agen, loop penolakan karena salah sebut tereliminasi (5A.8).
- Pengambil keputusan akhir (arbitrase debat, #48) ditentukan via field konfigurasi `escalation_lead` — mis. `escalation_lead: "tech_lead"`, atau `escalation_lead: "human"` untuk diserahkan ke dashboard pengguna.

---

# 31. Model Provider

Agent tidak harus memakai model yang sama.

Contoh:

```yaml
agents:
  ceo:
    provider: openai

  research:
    provider: anthropic

  coder:
    provider: local

  reviewer:
    provider: openai
```

Provider abstraction:

```text
LLM Provider
    |
    +---- OpenAI
    +---- Anthropic
    +---- Gemini
    +---- Ollama
    +---- vLLM
    +---- llama.cpp
    +---- custom
```

---

# 32. Cost / Usage Tracking

Usage tracking tetap berguna.

Track:

- tokens
- duration
- tool calls
- request count
- model
- estimated cost
- cache hit
- retries

Struktur `usage` dan `usage_totals` ada di **Section 72A.5**. Aturan budget, reserve/settle, dan agregasi ada di **Section 5A.2, 5A.3, dan 5A.10**. Section ini hanya ringkasan.

Per agent:

```text
CEO
$0.42

Research
$1.10

Coder
$2.81
```

## 32.1 Provider Usage Accounting (OpenRouter)

Metrik biaya dicatat dengan dua mode:

### Mode Utama — Real-Time Capture

Model Adapter menangkap objek `usage` (`prompt_tokens`, `completion_tokens`, `cost`) langsung dari payload response API — termasuk potongan terakhir pada streaming — lalu menyimpannya ke **Operational Store** (SQLite) di tabel `usage`.

Capture ini yang mengisi `budget.used` (72A.5) dan menjadi basis Cost-Aware Routing (5A.10/5A.11) **secara instan, tanpa biaya API tambahan**.

### Mode Audit — Reconciliation (Opsional)

Background job periodik opsional memanfaatkan `POST /api/v1/analytics/query` via **Management Key** OpenRouter — murni untuk verifikasi dan audit selisih saldo, bukan sumber data utama dashboard.

### Key Isolation

API key provider dikonfigurasi terisolasi per workspace di `workspace.yaml` (lihat #36) agar kuota dan pencatatan biaya tidak tercampur antar-proyek.

```yaml
providers:
  openrouter:
    api_key: "$OPENROUTER_API_KEY"   # secret ref, per workspace
    analytics_management_key: "$OPENROUTER_MGMT_KEY"  # opsional, audit saja
```

---

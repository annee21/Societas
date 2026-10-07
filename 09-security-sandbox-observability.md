<!-- Doc 09 — Security, Sandbox, Tools, Observability, Protocol (§57–72)
     Bagian dari societas-full-product-spec. Urutan dokumen diatur di README.md.
     Nomor section dipertahankan; referensi silang antar-doc memakai nomor section (#N, 5A.x, 72A.x). -->

# 57. Security Model

Security menjadi bagian inti.

Minimal:

- credentials di environment/config
- secrets tidak masuk log
- permission per agent
- command sandbox/restriction
- approval workflow
- workspace isolation
- path restrictions
- network restrictions

---

# 58. Secret Management

Provider credentials tidak boleh ditulis langsung ke prompt agent.

Gunakan:

```text
environment variables
secret store
OS credential store
encrypted local config
```

Agent hanya mendapat secret yang benar-benar diperlukan.

---

# 59. Tool Sandbox

Sandboxing memakai **Deterministic Guard di level backend Go**, divalidasi sebelum proses dieksekusi — bukan blocklist, dan tanpa state-observer snapshot yang berat.

```yaml
shell:
  # Strict Allowlist (default-deny): binary di luar daftar ditolak
  allowed:
    - go
    - git
    - npm
    - cargo
    - make

  # Path Jailing: eksekusi terkunci mutlak di ./workspace
  cwd_jail: "./workspace"
  path_validation:
    mode: semantic  # klasifikasikan argumen sesuai adapter subcommand
    allow_relative_within_jail: true
    reject_absolute: true
    reject_escape: true
    reject_home_expansion: true

  # Mutasi direktori berskala besar -> human approval (#22.3, #23)
  require_approval:
    - large_directory_mutation
```

Pelanggaran guard ditolak secara deterministik oleh Policy Engine dan dicatat sebagai event penolakan.

Guard memvalidasi argumen path, termasuk nilai flag path (`--output=...`), menurut adapter binary/subcommand. Normalisasi path terhadap `cwd_jail`, tolak path absolut/home expansion dan hasil resolusi yang keluar jail; **jangan menolak slash secara substring**. `src/main.go` dan pola paket `go test ./...` sah; `@scope/pkg` adalah identifier paket, bukan path absolut. Bentuk path sesuai OS (termasuk drive/UNC pada Windows) harus ditangani adapter. Argumen yang tidak dapat diklasifikasikan dengan aman ditolak (default-deny), tidak diasumsikan non-path. OS isolation #59.1 tetap wajib untuk symlink/TOCTOU dan kode build arbitrary.

## 59.1 OS-Level Isolation (Requirement Utama)

String filtering (#22.2) **bukan sandbox** — binary allowlist mengeksekusi kode arbitrary dan symlink dapat keluar dari jail. Karena itu setiap eksekusi shell/build/test **wajib** berjalan di dalam isolasi level OS:

- **Linux Landlock** atau **Bubblewrap**, atau
- **Ephemeral container** (Docker / Podman sekali pakai) yang me-mount folder task secara terisolasi tanpa akses network luar (kecuali network dibutuhkan tool dan diizinkan policy).

Saat Engineer Agent menjalankan shell (kompilasi, install dependency, run test), Tool Runtime Go memutar lingkungan terisolasi ini; seberapa ganas pun perintah agen (bahkan `rm -rf /`), yang rusak hanya lingkungan virtual — bukan mesin host. Lingkungan dimatikan dan dihapus begitu eksekusi tool selesai.

Deterministic Guard (#22) tetap aktif sebagai lapis kedua di dalam isolasi.

---

# 60. Git Integration

Engineer agent harus dapat:

```bash
git status
git diff
git branch
git commit
```

Advanced:

```text
create branch
implement
test
commit
generate patch
request review
```

Deployment tidak otomatis.

## 60.1 Git Worktree Isolation per Task

Agen **tidak mengoding langsung di folder utama** `./workspace` — rawan bentrok saat task berjalan paralel. Untuk setiap task baru (`TASK-001`), backend Go otomatis membuat `git worktree` terpisah di folder tersembunyi:

```text
.worktrees/TASK-001/    (branch terpisah per task)
```

Keuntungan:

- Setiap agen punya "kamar kerja" sendiri pada branch terpisah.
- Kalau agen salah coding atau bikin error, cukup hapus worktree tersebut tanpa merusak folder kerja utama sama sekali.
- Penggabungan ke branch utama (`main`) baru terjadi saat task dinyatakan `completed` dan di-approve oleh human.

Path Jailing (#22.2) tetap berlaku — jail scope diarahkan ke worktree task, bukan root workspace.

## 60.2 Worktree Safety

- **Concurrency mutex:** operasi administratif git (`worktree add`/`remove`) dilindungi mutex — dicegah race condition pada `.git/index.lock` saat task paralel dimulai/selesai bersamaan.
- **Startup Reaper:** saat boot, backend menjalankan `git worktree prune` dan membersihkan orphan worktree yang tidak terikat task aktif di SQLite.
- **Git subcommand restrictions:** agen dilarang menjalankan destructive command di luar worktree miliknya (mis. `branch -D`, `reset --hard` pada repo utama) — allowlist subcommand git divalidasi Policy Engine per worktree scope.
- **Shared dependency cache:** dependency manager memakai cache global (pnpm store, Go mod cache) agar disk tidak membengkak karena `node_modules`/deps di tiap worktree.
- **Log Inactivity Timeout monitoring:** Go Tool Runtime memantau stream output `stdout`/`stderr` dari compiler/test yang berjalan di worktree. Tidak ada batas waktu durasi total karena performa kompilasi bervariasi drastis tergantung hardware. Jika output terminal hening/macet total tanpa log baru selama **5 menit**, proses dianggap mengalami *deadlock* / *infinite loop* dan di-kill dengan `SIGTERM`/`SIGKILL`, mengembalikan error `TOOL_TIMEOUT` ke Orchestrator.

## 60.3 Edit Mechanism — Search & Replace Block

Engineer **tidak menulis ulang seluruh file** (boros token output, latensi tinggi, rawan lazy output `// rest of code...`) dan **tidak mengeluarkan unified diff mentah** (`patch.diff` standar dengan header `@@ -42,7 +42,9 @@` — LLM tidak presisi menghitung nomor baris sehingga `git apply` sering reject).

Mekanisme baku penulisan ke disk worktree memakai tool **Search & Replace Block** (pola Aider / Claude Code):

```text
<<<<<<< SEARCH
pub enum NullifierStatus {
    Reserved,
    Confirmed,
}
=======
pub enum NullifierStatus {
    Reserved,
    Submitted,
    Confirmed,
    Released,
}
>>>>>>> REPLACE
```

- Tool Runtime (Go) mencari blok `SEARCH` secara literal di file target di dalam worktree, lalu menggantinya dengan blok `REPLACE` secara presisi — nomor baris tidak pernah dihitung LLM.
- Jika blok tidak ketemu persis (whitespace/konteks berubah), tool mengembalikan error deterministik `SEARCH_BLOCK_NOT_FOUND` dan agen wajib membaca ulang file asli — **bukan** retry buta.
- Jika ada lebih dari satu kecocokan literal, tool mengembalikan `SEARCH_BLOCK_AMBIGUOUS` tanpa menerapkan edit; agen memperlebar konteks SEARCH. Kedua kode terdaftar di 72A.9.
- Hasil akhir tetap diproduksi sebagai artifact `patch.diff` (#17) dari `git diff` di worktree — LLM tidak pernah men-generate header diff sendiri.

## 60.4 Serial Merge Queue (Rebase-before-Approval)

Worktree mengisolasi pengerjaan, tapi tidak menyelesaikan merge conflict saat dua task paralel menyentuh file yang sama (mis. `crates/storage/mod.rs`, `Cargo.toml`). Aturannya:

- Merge ke `main` diserialkan lewat **satu antrean tunggal di Orchestrator** — tidak ada dua merge bersamaan.
- Sebelum task diajukan untuk approval, Go **otomatis `git rebase` branch task ke `main` terkini**.
- Setelah textual rebase selesai, regenerate PROJECT_MAP, freeze candidate commit/tree, jalankan deterministic build/lint/test gate, lalu **Semantic Rebase Flash tier**, kemudian Reviewer. Semantic check tidak mendahului build gate.
- Semantic input harus exact-version dari Git/SQLite/Operational Store: base dan candidate decision artifact refs (ID/version/checksum), candidate diff/tree, contract/PROJECT_MAP yang ikut candidate. Jangan memakai Vector DB atau similarity atas proposal untuk memilih sumber. `semantic_recipe_hash` mengikat evaluator tier/model route, prompt/version, policy, dan input refs; panggilan tunduk pada Model Router, token/cost budget, rate limit, serta timeout.
- Triage menjawab: *"Apakah ada kontradiksi logika atau pelanggaran batas arsitektur antar keputusan ini?"* Persist `MergeEvidence` `kind: semantic_rebase` yang mengikat merge binding, recipe hash, exact decision refs, outcome, dan findings. `PASS` bukan jaminan bebas bug dan bukan approval manusia.
- `CONFLICT` membekukan task `blocked (semantic_conflict)`; `INCONCLUSIVE` (input tidak tersedia, timeout, budget habis, evaluator error) membekukan `blocked (semantic_inconclusive)`. Keduanya menyimpan immutable `blocked_evidence` ref, tidak mengubah Git ref, dan mengirim `task.semantic_conflict` + evidence/transkrip yang ada ke `escalation_lead` (#48.5). Tidak perlu membuat rebuttal palsu bila tidak ada debat. Refactor yang diarahkan lead berjalan asinkron pada task nonterminal; candidate baru mengulang rebase → gate → semantic PASS → review → approval. Evidence/approval lama tidak diwariskan.
- Semantic `PASS`, gate pass, dan review approve pada candidate/binding yang sama baru mengizinkan request approval berisi semua evidence ID/version/checksum (I17/I19, 72A.8/72A.10). Perubahan base, candidate, PROJECT_MAP, keputusan input, recipe, policy, contract, atau evidence membatalkan binding.
- Jika conflict → Orchestrator **membatalkan pengajuan approval dan mengembalikan task ke Engineer** beserta daftar file conflict (`task.rebase_conflict`), agar Engineer resolve duluan di worktree-nya. Conflict tidak pernah dilempar ke user untuk di-resolve manual.

Payload `task.rebase_conflict` (`conflict_files`, `base_ref`) dan kode `REBASE_CONFLICT` terdaftar di 72A.8/72A.9. Error konflik bukan kegagalan dependency terminal; task tetap nonterminal agar Engineer bisa memperbaikinya.

- Saat menunggu human, task parked dan tidak memegang lock/goroutine antrean. Final executor **tidak memanggil semantic model lagi**; ia memverifikasi evidence `PASS` versi tepat pada binding yang disetujui, merge approval, merge receipt intent, live input, policy/contract/expiry, dan expected base. Ketidakcocokan menghentikan CAS.
- Base/kandidat/PROJECT_MAP/semantic decision refs/recipe/policy/contract/evidence berubah → `approval.invalidated`; ulangi rebase → gate → semantic → review → approval dengan ID baru. Tidak mewariskan approval lama meskipun diff tampak serupa.
- Integrasi fast-forward tidak membuat merge/squash commit baru setelah approval. Working tree/index gate bersih dan cocok candidate tree; target bukan symbolic ref, full ref/OID divalidasi Git.
- Setelah expected-base CAS berhasil dan ref hasil direkonsiliasi, persist `merge_receipt` yang mengikat workspace/run/task/repo/ref/base/merged commit/tree, approval snapshot, serta semantic/gate/review evidence refs. Ini receipt provenance operasional; bukan transactional guarantee lintas Git+SQLite, yang tetap keputusan W06.
- Git-ref CAS tidak menyelesaikan recovery lintas Git+SQLite, sinkronisasi checkout, atau keamanan metadata shared worktree. Recovery lintas Git+SQLite dijelaskan di [DEC-002] W06 (Multi-Store Recovery Protocol) dan shared metadata isolation dijelaskan di [DEC-004] W14 (Shared Git Metadata Isolation). Jangan memberi agen writable common git-dir untuk memenuhi alur ini.

---

# 61. Research Integration

Research agent dapat menghasilkan:

```text
research/
├── sources.md
├── summary.md
├── comparison.md
└── recommendations.md
```

Source metadata harus disimpan.

---

# 62. Browser / Search Tool

Riset web tidak membangun headless browser lokal sendiri — tool `search`/`open`/`extract` langsung mengandalkan **server MCP pencarian** (mis. **Tavily** atau **Exa**) yang dihubungkan via MCP Client (#21.1).

Tool interface:

```text
search(query)   -> MCP search server (Tavily / Exa)
open(url)       -> fetch & extract via MCP server
extract()       -> hasil ekstraksi terstruktur
```

Tool result masuk ke event system.

---

# 63. Structured Tool Calls

Tool call harus memiliki schema dan diteruskan lewat **MCP Client** (#21.1): agen mengeluarkan call terstruktur, Tool Runtime meneruskannya ke MCP server yang bersangkutan, dan result terstruktur dikembalikan sebagai event.

Contoh:

```json
{
  "tool": "git.diff",
  "arguments": {}
}
```

Result:

```json
{
  "status": "ok",
  "output": "...",
  "duration_ms": 42
}
```

Contoh di atas disederhanakan. Schema lengkap (`tool_call_id`, `output_artifact_id`, `error`, batas output inline) ada di **Section 72A.8**, dan alur baku tool call di **72A.10**.

`tool.call_failed` wajib membawa `outcome: not_started | outcome_unknown`; timeout setelah dispatch tidak boleh dilabeli not_started. Batas inline berlaku untuk seluruh payload terserialisasi, termasuk nested object dan byte UTF-8, bukan hanya `maxLength` string (I5, 72A.12).

---

# 64. Observability

System harus menyediakan:

```text
agent runtime metrics
task metrics
tool metrics
transport metrics
model metrics
storage metrics
```

Contoh:

```text
active_agents
active_tasks
messages_per_second
tool_calls_total
task_failures_total
model_latency
event_bus_publish_latency
event_bus_subscribe_latency
memory_usage
```

---

# 65. Logging

Structured logs:

```json
{
  "level": "INFO",
  "event": "task_completed",
  "agent_id": "research",
  "task_id": "TASK-100",
  "duration_ms": 12043
}
```

Jangan log:

- API key
- access token
- password
- raw credentials
- private secrets

---

# 66. Tracing

Gunakan correlation ID agar satu pekerjaan dapat diikuti.

## 66.1 Local Tracing & Waterfall Telemetry (OpenTelemetry)

Sistem memasang **tracing lokal bawaan yang dapat diekspor ke format OpenTelemetry**. Di Web Dashboard, pengguna melihat diagram waterfall (seperti tab Network di DevTools) untuk satu run/task:

```text
span ChromaDB query        |██| 12ms
span model call (Anthropic)|██████████| 4.2s
span tool call (git.diff)  |█| 42ms
span child task branch     |████████████| 8.7s
```

Waterfall menunjukkan:

- berapa milidetik dihabiskan query ChromaDB / Vector DB
- berapa lama API model memproses prompt
- jalur cabang task mana yang paling memakan waktu dan biaya

Correlation ID dan span mengikuti event di Event Bus antar-agen.

```text
User Request
   ↓
CEO
   ↓
Task
   ↓
Research
   ↓
Tool
   ↓
Artifact
   ↓
CEO
   ↓
Human
```

---

# 67. Agent Run

Setiap execution agent dibuat sebagai run.

Contoh:

```yaml
run_id: RUN-001
agent: research
task: TASK-001
started_at: ...
finished_at: ...
status: completed
```

Run menyimpan:

- input
- model
- tool calls
- output
- artifacts
- errors
- usage

---

# 68. Replay / Debugging

User dapat membuka run dan melihat:

```text
00:00 task received
00:01 context loaded
00:03 model started
00:08 search.call
00:09 search.result
00:12 model resumed
00:18 artifact created
00:20 completed
```

Ini penting untuk memahami agent behavior.

---

# 69. Agent Context

Context disusun dari:

```text
system prompt
role
workspace context
task context
memory
recent messages
tool results
artifacts
```

Jangan memasukkan seluruh workspace setiap kali.

Context builder harus selektif.

---

# 70. Context Budget

Agent memiliki budget context.

System harus memprioritaskan:

1. current task
2. recent relevant messages
3. relevant artifacts
4. trusted memory
5. old history

Budget context adalah bagian dari budget agent (5A.2), dan hasil seleksi dicatat lewat event `context.built` (72A.8) berikut alasan tiap item.

Alokasi awal yang disarankan (dapat dikonfigurasi):

| Bagian | Porsi |
|--------|-------|
| System prompt + role | 15% |
| Current task | 15% |
| Artifact / summary relevan | 30% |
| Memory terpercaya | 15% |
| Recent messages + tool results | 20% |
| Cadangan | 5% |

---

# 71. Agent-to-Agent Protocol

Protocol minimal:

```text
HELLO
AUTH
REGISTER
SUBSCRIBE
PUBLISH
TASK
MESSAGE
TOOL
ARTIFACT
HEARTBEAT
ACK
ERROR
GOODBYE
```

Protocol harus versioned.

Frame di atas adalah lapisan transport. Isi frame `PUBLISH`, `TASK`, `MESSAGE`, dan `TOOL` adalah **envelope** yang didefinisikan di **Section 72A.3**.

---

# 72. Protocol Versioning

Contoh:

```text
societas/1
```

Setiap message memiliki:

```text
protocol_version
message_type
schema_version
```

Breaking changes harus memiliki migration path.

---

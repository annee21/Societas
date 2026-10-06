<!-- Doc 02 — AI Control Plane (§5A)
     Bagian dari societas-full-product-spec. Urutan dokumen diatur di README.md.
     Nomor section dipertahankan; referensi silang antar-doc memakai nomor section (#N, 5A.x, 72A.x). -->

# 5A. AI Control Plane

**Prasyarat model mental:** [§6–8](03-tasks-and-lifecycle.md) menjelaskan lifecycle agent, task, dan DAG. Baca bagian itu setelah §5 dan sebelum detail control plane ini. Nomor section tetap dipertahankan; urutan linear ada di README.

AI Control Plane adalah otak pengatur seluruh sistem multi-agent.

Event Bus hanya menangani komunikasi. Agent hanya menjalankan pekerjaan. Keputusan tentang **siapa melakukan apa, kapan, dengan context apa, dan berapa budget** berada di Control Plane.

> Bentuk data yang dipakai Control Plane (budget, usage, event, error, task) didefinisikan di **Section 72A (Contracts)**. Jika ada perbedaan, 72A yang berlaku.

```text
                    HUMAN
                      |
                      v
                AI CONTROL PLANE
                      |
        +-------------+-------------+
        |             |             |
   Orchestrator   Budget Manager  Policy Engine
        |             |             |
   +----+----+     Context        Model Router
   |         |     Manager             |
   v         v        |                v
 Scheduler   Task ----+----------> Agent Runtime
                             \
                              v
                        Event Bus (Go channel)
```

## 5A.1 Orchestrator

Orchestrator bertugas:

- menentukan jalur pekerjaan
- membuat task
- melakukan delegation
- menentukan agent tujuan
- menentukan urutan atau parallelism
- menggabungkan hasil
- memutuskan kapan workflow berhenti
- melakukan escalation ke human jika diperlukan

Orchestrator tidak boleh menyerahkan seluruh routing ke LLM.

Prioritas routing:

1. deterministic rules
2. task graph
3. configured workflow
4. LLM router hanya ketika keputusan memang ambiguous

Tujuannya mengurangi token dan latency yang tidak perlu.

## 5A.2 Budget Manager

Setiap workspace, run, task, dan agent memiliki budget.

Budget dapat membatasi:

- input tokens
- output tokens
- total tokens
- model calls
- tool calls
- pesan antar-agent
- execution time
- estimated cost
- jumlah agent yang boleh dibuat
- concurrency

Contoh:

```yaml
budget:
  max_input_tokens: 12000
  max_output_tokens: 3000
  max_total_tokens: 15000
  max_model_calls: 10
  max_tool_calls: 20
  max_agent_messages: 40
  max_time_seconds: 300
  max_cost_usd: 0.50
  max_parallel_agents: 4
  max_rebuttals: 2        # batas sanggahan per task (lihat #48)
```

Budget harus enforced oleh runtime.

Agent tidak boleh menaikkan budget dirinya sendiri.

`max_rebuttals` membatasi putaran sanggahan per task dan merupakan field Budget kanonik (72A.5). Counter disimpan di SQLite, tidak reset saat retry/restart. Saat limit tercapai tanpa kesepakatan, Orchestrator membekukan task dan dieskalasi ke `escalation_lead` (konfigurasi #36, contoh: CTO) untuk `decision.md` (lihat #48).

**Reservation lease/TTL:** setiap `budget.reserved` membawa lease dengan TTL. Jika sistem mati sebelum `budget.settled`, sisa reservasi otomatis **expired** dan di-reconcile saat startup — mencegah orphan reservation yang menahan budget selamanya.

**Global Circuit Breaker (Kill Switch):** di atas hierarki budget per-task ada batas global (harian/bulanan per workspace atau per API key). Tersentuh limit ini -> seluruh run dihentikan dan meminta human approval, terlepas dari sisa budget per-task.

**Metrik utama:** sistem mengukur **Cost per Accepted Task** — biaya total dibagi task yang lulus review/acceptance — bukan sekadar biaya murah per turn.

## 5A.3 Budget Hierarchy

Budget memiliki hierarchy:

```text
Workspace Budget
      |
      +---- Run Budget
               |
               +---- Task Budget
                        |
                        +---- Agent Budget
                                 |
                                 +---- Tool Budget
```

Anak tidak boleh melebihi budget parent.

Contoh:

```text
Workspace
$5.00
 |
 +-- Run A
     $1.00
      |
      +-- Research
      |   $0.20
      |
      +-- CTO
      |   $0.25
      |
      +-- Engineer
      |   $0.40
      |
      +-- Reviewer
          $0.15
```

Jika budget habis:

```text
BUDGET_EXCEEDED   (details.scope = run)
```

workflow dihentikan atau meminta human approval.

## 5A.4 Context Manager

Context Manager menyusun prompt untuk agent.

Context **bukan file teks statis** — ia objek data dinamis di RAM yang dirakit Context Manager sesaat sebelum pemanggilan LLM, menggunakan template variabel seperti `{{ .Role }}`, `{{ .WorkspaceName }}`, `{{ .WorkspacePath }}`, `{{ .RiskTier }}`.

Context dibangun dalam 3 lapisan:

```text
1. Base Identity (YAML Template)
      -> {{ .Role }}, {{ .WorkspaceName }}, {{ .WorkspacePath }},
         aturan peran, authority clause (#48.4)
2. Runtime Context
      -> task aktif, batasan path sandbox, 1–2 potongan
         memori relevan dari ChromaDB (5A.25)
3. Model Adapter
      -> suffix instruksi per tipe model:
         model murah  = aturan output JSON ketat
         model thinking = instruksi evaluasi arsitektur mendalam
```

Retrieval memory mengikuti [5A.25 — Semantic Retrieval](02-ai-control-plane.md#5a25-semantic-retrieval).

### Pencegahan Negation Bleed (Isolasi Struktural XML)

Context Manager dilarang menyajikan memori kegagalan sebagai plain-text biasa yang bercampur dengan best practice. Context Manager wajib memisahkan memori secara tegas menggunakan blok XML saat merakit prompt LLM:

```xml
<historical_success>
<!-- Rekomendasi/pola yang berhasil ditiru -->
- Adapter boundary dipertahankan untuk transport calls
- Kontrak API menggunakan semantic versioning
- Pola mutex untuk shared state
</historical_success>

... (instruksi task, konteks saat ini) ...

<confirmed_blacklist>
<!-- Batasan penolakan / anti-pattern (cognitive_guardrail: true) -->
- DILARANG: menembus adapter boundary dengan direct worker call
- DILARANG: kontrak API tanpa versioning
- DILARANG: pola concurrency yang menyebabkan race condition
</confirmed_blacklist>
```

Struktur ini mengunci mekanisme atensi model agar:
- Rekomendasi positif ditampilkan di awal prompt sebagai contoh untuk diikuti
- Batasan negatif diisolasi di bagian paling bawah prompt sebagai penalti/filter validasi akhir
- Model memperlakukan anti-pattern sebagai constraint, bukan contoh implementasi yang harus ditiru
- Anti-pattern ditandai dengan metadata `cognitive_guardrail: true` dan tag `anti-pattern` di Vector DB (#19.6)

### Prompt Caching Optimization (Session Policy)

Aturan mode, lifecycle sesi, dan flush hanya didefinisikan di [I23 — Session Policy](10-contracts-mvp-roadmap.md#72a1-aturan-dasar-invariants). Context Manager menerapkan hierarki prompt statis ke dinamis berikut:

```text
1. System Prompt & Role (statis per agent) → cache hit rate tinggi
2. Tool Schemas (statis per workspace) → cache hit rate tinggi
3. PROJECT_MAP.md (statis per workspace) → cache hit rate tinggi
4. Recent History (dinamis per turn) → cache hit rate rendah
5. Input Baru (dinamis per turn) → cache miss (selalu direfresh)
```

Pengukuran cache memakai `cached_input_tokens` pada [72A.5 — Usage](10-contracts-mvp-roadmap.md#usage); contoh konfigurasi ada di [§36](07-dashboard-config-storage.md#36-workspace-configuration).

Agent tidak menerima seluruh workspace.

Context default:

```text
System Prompt
+ Role
+ Current Task
+ Relevant Memory
+ Relevant Artifacts
+ Recent Messages
+ Required Tool Results
```

Context harus dibangun berdasarkan relevansi dan budget.

Contoh pseudocode (notasi Python, bukan implementasi backend Go):

```text
build_context(
    agent,
    task,
    relevant_artifacts,
    relevant_memory,
    recent_events,
    token_budget
)
```

Output wajib berada dalam batas context budget.

## 5A.5 Context Selection

Prioritas informasi:

1. current task
2. direct instructions
3. recent relevant messages
4. required artifacts
5. trusted memory
6. historical context
7. debug information

Informasi yang tidak relevan tidak boleh dimasukkan hanya karena tersedia.

## 5A.6 Artifact-First Communication

Output besar harus dipindahkan menjadi artifact.

Jangan:

```text
Research
  |
  +----> 20k token message
              |
              v
             CEO
              |
              +----> 20k token ulang
```

Lebih baik:

```text
Research
  |
  +----> research.md
  |
  +----> summary 800 tokens
              |
              v
             CEO
              |
              +----> fetch section jika diperlukan
```

Default antar-agent:

- kirim summary
- sertakan artifact reference
- fetch detail hanya ketika dibutuhkan

## 5A.7 Summary Manager

Summary Manager membuat representasi ringkas dari output besar.

Contoh:

```yaml
summary:
  findings:
    - ...
    - ...
  risks:
    - ...
  recommendation: ...
  sources:
    - ...
```

Summary harus memiliki reference ke artifact asli.

Agent yang membutuhkan bukti detail dapat mengambil artifact asli.

## 5A.8 Model Router

Model Router menentukan model yang digunakan oleh suatu task.

Jangan memakai model paling mahal untuk semua pekerjaan.

**Jev AI** digunakan sebagai router utama — ia menerima task context dan menjawab pertanyaan Choice: *"Tier model mana yang dibutuhkan?"*. Harga tidak di-hardcode di spesifikasi; biaya aktual dicatat oleh Cost Tracker (5A.10) dari usage provider.

```text
Jev (cheap)
├── classification
├── routing
├── policy evaluation
└── confidence scoring

LLM medium
├── research synthesis
├── review
└── planning

LLM strong
├── CEO decisions
├── difficult architecture
└── complex coding
```

Contoh konfigurasi:

```yaml
models:
  router: jev-latest        # Jev AI untuk routing & policy
  policy: jev-latest        # Jev AI untuk tool call evaluation
  summarizer: cheap-model
  research: medium-model
  cto: strong-model
  engineer: strong-model
  reviewer: medium-model
  ceo: strong-model
```

Jev AI dan Model Router hanya boleh merutekan ke **ID agen yang aktif terdaftar** di `workspace.yaml` workspace terkait (#30.1) — backend Go tidak mengenal peran hardcoded, jadi merutekan ke ID tidak dikenal ditolak deterministik.

**Dynamic Enum Injection:** saat runtime Go menyiapkan tool schema / JSON Schema delegasi untuk agen, field `requested_assignee` wajib dikunci memakai `enum` dinamis berisi ID agen aktif dari `workspace.yaml` + `null`. Dengan constrained decoding provider, LLM terkunci secara matematis — tidak bisa mengarang ID fiktif, sehingga siklus re-prompting boros token di model tier tinggi hilang. Penolakan karena salah nama agen tidak lagi mungkin terjadi (lihat 72A.8, 72A.10).

Risk-aware routing: jika task memiliki `risk_tier: critical` (lihat #23.1, 72A.5), Model Router **otomatis menaikkan pengerjaan ke model tier tinggi (thinking mode)** dan menyuntikkan audit keamanan wajib — terlepas dari skor confidence. Eksekusi mutasi task tersebut tetap terkunci hingga disetujui manusia.

`Flash` adalah label tampilan untuk jalur murah dan dipetakan ke tier wire `cheap`, bukan tier model tambahan. Semantic triage mengikuti Model Router, Budget Manager, rate limit, serta policy yang sama; label Flash tidak dapat menurunkan tier atau melewati escalation `critical` ke `strong`.

### Provider Rate Limiter (Token Bucket per API Key)

Budget Manager menghitung biaya ($/token), tapi biaya bukan satu-satunya batas: provider juga memberlakukan **RPM (requests/menit) dan TPM (token/menit)** per API key. Saat 2–3 agen berjalan paralel dan menembak model tier tinggi bersamaan, request bisa langsung kena `HTTP 429: Too Many Requests`. Retry buta tanpa antrean justru menumpuk request dan menghabiskan retry budget (5A.13) sia-sia.

Karena itu Model Router memasang **`rate.Limiter` (token bucket) global per API key provider** di dalam Go runtime — bukan di sisi agen:

- Setiap model call harus mengambil token dari bucket RPM dan TPM provider terkait sebelum keluar ke jaringan.
- Jika bucket habis, request agen **mengantre di RAM Go** (bounded queue, 0 token) sampai slot tersedia — bukan langsung jedor ke provider.
- `429` yang tetap terjadi (limit berubah, burst tak terduga) diperlakukan sebagai sinyal backpressure: Go mengecilkan rate bucket sementara lalu memulihkannya bertahap, bukan memicu retry storm.
- Antrean ini konsisten dengan backpressure Event Bus (#42) dan mailbox per subscriber (#42.2).

## 5A.9 Model Escalation

Agent tidak harus langsung memakai model paling kuat.

Evaluasi skor keyakinan (*confidence threshold*) dilakukan oleh **Jev AI** setelah model murah mengembalikan jawaban. Jev tidak menghasilkan teks — ia mengembalikan skor terstruktur yang langsung dipakai kode.

Flow:

```text
Cheap Model
    |
    v
model.call_completed (returns output)
    |
    v
Jev AI Evaluation (Choice + Score question)
    |
    +---- confidence >= threshold ----> DONE
    |
    +---- confidence < threshold  ----> Strong Model (Escalation)
```

Escalation dapat dipicu oleh:

- low confidence (skor Jev di bawah threshold)
- task complexity
- failed attempt / retry limit
- reviewer rejection
- tool failure

## 5A.10 Cost Tracker

Setiap model call dicatat.

```yaml
usage:
  input_tokens: 1820
  output_tokens: 731
  duration_ms: 4820
  model: "..."
  estimated_cost_usd: 0.012
```

Total usage dihitung berdasarkan:

- workspace
- run
- task
- agent
- model
- tool

Sumber data: **SQLite (Operational Store) adalah Single Source of Truth** untuk semua metrik biaya — angka diisi dari capture `usage` response provider secara real-time (lihat #32.1), bukan fetch eksternal ke provider.

## 5A.11 Cost-Aware Routing

Router harus dapat memilih jalur berdasarkan budget.

Contoh:

```text
Task: "Summarize 20 pages"

Option A:
Strong model
$0.80

Option B:
Cheap model
$0.05
```

Jika kualitas Option B cukup, gunakan Option B.

Jika task sangat penting, dapat menggunakan strong model.

## 5A.12 Token Policies

Default policy:

- jangan kirim full transcript
- jangan kirim artifact penuh kecuali diperlukan
- batasi output tokens
- gunakan summary
- gunakan model kecil untuk tugas sederhana
- cache context jika memungkinkan
- jangan memanggil router LLM untuk semua message
- batasi retry
- batasi agent fan-out

## 5A.13 Retry Budget

Retry adalah bagian dari budget.

```yaml
retry:
  max_attempts: 2
  max_total_retry_cost_usd: 0.10
```

Jangan menggunakan unlimited retry.

Untuk tool, timeout/network error tidak membuktikan side effect belum terjadi. Orchestrator memeriksa `outcome` dan capability tepercaya (#21) sebelum retry: `outcome_unknown` hanya aman untuk retry otomatis bila idempotent atau provider menegakkan `operation_key` stabil sejak dispatch pertama. Tanpa itu, wajib rekonsiliasi/keputusan human (72A.1 I16, 72A.8–10), walaupun retry budget masih tersedia.

**Batas koreksi lokal (Compiler Gate):** kegagalan build/lint pada Deterministic Toolchain Runner ([5A.22 — Compiler Gate](02-ai-control-plane.md#compiler-gate-sebelum-reviewer-dipanggil)) dibatasi maksimal **3 kali iterasi perbaikan**. Jika setelah 3 kali percobaan berturut-turut masih gagal/timeout (termasuk log inactivity timeout), Orchestrator membekukan task (`status: blocked`) dan mengeskalasikannya ke `escalation_lead` atau manusia.

## 5A.14 Fan-Out Limit

Agent tidak boleh membuat agent/task tanpa batas.

```yaml
limits:
  max_child_tasks: 5
  max_depth: 4
  max_parallel_agents: 4
```

Contoh yang baik:

```text
CEO
 |
 +-- Research
 +-- CTO
 +-- Security
 +-- CPO
```

Contoh yang buruk:

```text
CEO
 |
 +-- Agent 1
      |
      +-- 10 agents
            |
            +-- 100 agents
```

## 5A.15 Token Guard

Sebelum model dipanggil:

```text
check_budget()
check_context_size()
check_rate_limit()
check_policy()
select_model()
```

Jika gagal:

```text
BUDGET_EXCEEDED
CONTEXT_TOO_LARGE
RATE_LIMITED
POLICY_DENIED
```

Model call tidak dijalankan.

## 5A.16 Policy Engine

Policy Engine menentukan apakah sebuah tindakan boleh dilakukan. Engine ini menggunakan **Jev AI** untuk mengevaluasi risiko tindakan secara cepat (~150ms) tanpa membuang token LLM.

Jev menerima state tindakan (tool name, arguments, agent context) dan menjawab pertanyaan terstruktur: *"Apakah tindakan ini berisiko tinggi?"* dengan Choice + Score — output langsung dipakai kode tanpa parsing teks.

```text
Agent
  |
  v
Request Tool
  |
  v
Policy Engine (Jev AI)
  |
  +---- allowed -------------> Tool Runtime
  |
  +---- require_approval ----> Human
  |
  +---- denied --------------> Agent
```

Policy dapat mencakup:

- filesystem scope & path
- shell commands
- network access
- model usage
- budget & cost limits
- agent creation
- external communication
- deployment

## 5A.17 Network Failure Handling (Deterministic Go Runtime)

Sistem **tolak fallback router offline** berbasis ONNX atau regex classifier. Ketika internet mati, Jev AI dan model pekerja eksternal ikut mati, sehingga sistem tidak boleh memaksakan perutean semu.

### Deteksi Murni Level Transport (0 Token)

Deteksi jaringan sepenuhnya menjadi tugas **Go Runtime (Deterministic Enforcer)**, bukan tugas Jev AI atau agen:

- Jika HTTP client Go mendeteksi *network drop* atau *timeout* berulang saat menghubungi API model provider, Go Runtime langsung mengeksekusi healthcheck deterministik cepat (socket ping / HEAD request ke DNS publik stabil seperti `1.1.1.1` atau `8.8.8.8`).
- Tidak ada loop retry buta, tidak ada LLM yang dipanggil untuk mendiagnosa koneksi.

### Pembedaan Network Outage vs Provider Outage

- **Jika ping gagal:** Internet putus total → eksekusi Fail-Closed Auto-Pause (task diubah ke `paused` via CAS pada SQLite).
- **Jika ping lolos:** Internet hidup, provider sedang down (`MODEL_UNAVAILABLE`) → Model Router langsung mengeksekusi fallback transparan ke provider alternatif (misal: Gemini atau Anthropic) yang terdaftar di konfigurasi tanpa menjeda task. Auto-pause hanya dipicu jika seluruh rantai fallback provider gagal.

### Fail-Closed Auto-Pause

Jika internet terkonfirmasi putus:

- Go Runtime langsung memicu transisi state machine di SQLite via CAS (*Compare-And-Swap*): task aktif diubah menjadi `paused` (`phase: requested`).
- `pause_deadline` disimpan dan checkpoint progress tersimpan di SQLite.
- Worker pool dilepas untuk menghemat resource.
- Tidak ada event bus yang menumpuk antrean mati.

### Auto-Resume

Background daemon Go memantau pemulihan koneksi:

- Begitu internet kembali online, Orchestrator menerbitkan event `task.resumed`.
- Task dilanjutkan dari checkpoint tersimpan tanpa kehilangan konteks atau duplikasi event.
- Context Manager mengambil progress terakhir dari Operational Store (SQLite, #37.1).

## 5A.18 Scheduler

Scheduler mengatur kapan task dijalankan.

Input:

- priority
- dependency
- agent availability
- budget
- concurrency
- deadline

Scheduler harus mendukung:

- sequential
- parallel
- dependency-aware scheduling
- cancellation
- timeout

## 5A.19 Stop Conditions

Setiap run harus memiliki stop condition.

Contoh:

- success
- budget exhausted
- timeout
- human rejection
- critical tool failure
- dependency failure
- maximum iterations

Agent tidak boleh terus berpikir tanpa batas.

## 5A.20 Maximum Iterations

```yaml
limits:
  max_agent_iterations: 8
  max_task_iterations: 5
```

Setiap loop autonomous harus memiliki upper bound.

## 5A.21 Approval Escalation

Jika agent ingin melakukan sesuatu di luar budget/policy:

```text
Agent
  |
  v
Control Plane
  |
  v
Approval Request
  |
  v
Human
```

Human dapat:

- Approve
- Approve Once
- Approve For Task
- Reject

## 5A.22 Cheap Path vs Expensive Path

Sistem harus memiliki dua jalur.

### Cheap Path

```text
Rule
  ↓
Cheap Model
  ↓
Tool
  ↓
Summary
```

Untuk pekerjaan rutin.

### Compiler Gate (Sebelum Reviewer Dipanggil)

Reviewer LLM mahal tidak boleh dipanggil sebelum kode lolos kompilasi lokal — **Deterministic Toolchain Runner** di backend Go (Go Daemon) menjalankannya terlebih dahulu:

```text
Engineer output
      ↓
Toolchain pipeline (Go Daemon, 0 token)
      ↓
   error?  ---- ya ----> JSON error ringkas (<500 char) ke Engineer
      | tidak
      ↓
Reviewer LLM (logika bisnis, arsitektur, keamanan)
```

Aturan runner:

- **0 TOKEN parsing:** LLM tidak dipakai untuk memformat error compiler. Go Daemon memparsing log murni di kode, memanfaatkan native JSON output toolchain:
  - Rust: `cargo check --message-format=json`, `cargo clippy --message-format=json`
  - Node/TS: `eslint --format json`, `tsc` parser
  - Go: `golangci-lint run --out-format json`
- Go menyaring span penting (file, baris, error message) dan hanya mengirim **JSON ringkas <500 karakter** ke Engineer Agent.
- **Fail-Fast:** pipeline berhenti seketika di step pertama yang gagal (misal gagal `fmt`/`check` → `test` tidak dijalankan). Pipeline dideklarasikan di `workspace.yaml` (`toolchain`, #36).
- **Log Inactivity Timeout (5 menit):** Tolak batas waktu durasi total (*hard execution timeout*) karena performa kompilasi bervariasi drastis tergantung hardware (misal CPU 2 core vs 16 core pada build Rust/C++). Go Tool Runtime memantau stream output `stdout`/`stderr`. Selama compiler/test (`cargo`, `go test`, `npm`) masih memproduksi log baru, proses dibiarkan berjalan. Jika output terminal hening/macet total tanpa log baru selama **5 menit**, proses dianggap mengalami *deadlock* / *infinite loop*. Tool Runtime Go langsung mengirim sinyal `SIGTERM`/`SIGKILL` dan mengembalikan error `TOOL_TIMEOUT`.
- **Loop budget & eskalasi:** bolak-balik perbaikan lokal dibatasi **maksimal 3 iterasi** — setelah itu Orchestrator membekukan task (`status: blocked`) dan mengeskalasikannya ke `escalation_lead` atau manusia (lihat 5A.13 retry budget). Konteks error wajib di-truncate agar tidak terjadi akumulasi token kuadratik antar-iterasi.

### Expensive Path

```text
Strong Model
  ↓
Multiple Agents
  ↓
Review
  ↓
Human Approval
```

Untuk pekerjaan kompleks/high-impact.

Orchestrator memilih jalur berdasarkan task.

## 5A.23 Example Token-Efficient Workflow

User:

> "CEO, evaluasi apakah kita perlu menambahkan fitur baru."

Flow:

```text
YOU
 |
 v
CEO
 |
 +----> Research
 |          |
 |          +--> research.md
 |          +--> 800 token summary
 |
 +----> CTO
 |          |
 |          +--> architecture.md
 |          +--> 1000 token summary
 |
 v
CEO synthesis
 |
 v
Engineer only if necessary
 |
 v
Reviewer only if necessary
 |
 v
YOU
```

Agent berikutnya tidak otomatis mendapatkan seluruh transcript.

## 5A.24 Context Caching

Jika provider mendukung caching, gunakan untuk context yang stabil.

Contoh yang stabil:

- System Prompt
- Role
- Workspace Rules
- Tool Schemas

Bagian ini tidak perlu selalu dihitung sebagai context baru jika provider mendukung caching.

## 5A.25 Semantic Retrieval

Memory/artifact retrieval sebaiknya menggunakan relevance.

Retrieval menanyakan **Cognitive Store** (Vector DB, #37.2) dan menerima daftar **ID referensi** artifact/memory yang relevan — bukan pencarian teks mentah atau operator `LIKE` di SQLite. Isi artifact kemudian dimuat dari file/Operational Store sesuai context budget.

Contoh:

```text
Current task:
"Compare gRPC and REST for agent communication."

Retrieve:
- gRPC benchmark
- previous architecture decision
- REST implementation
- relevant research

Ignore:
- unrelated finance notes
- old UI discussion
- unrelated agent conversations
```

ID hasil retrieval difilter deterministik di Go sebelum masuk context budget: memori yang `superseded` atau `stale` dibuang, dan skor dipengaruhi faktor umur (time-decay) — lihat **#19.6 Memory Curation**.

## 5A.26 Token Visibility

Dashboard **tidak melakukan fetch eksternal ke provider secara live** untuk merender grafik biaya — semua angka dibaca dari SQLite sebagai Single Source of Truth (#32.1), sesuai prinsip Local-First.

Dashboard harus menunjukkan:

```text
Today
───────────────
Tokens       142k
Input        96k
Output       46k
Estimated    $4.12

By Agent
CEO          $0.72
CTO          $1.10
Research     $0.68
Engineer     $1.32
Reviewer     $0.30
```

User dapat melihat agent mana yang paling mahal.

## 5A.27 Budget Dashboard

Dashboard menampilkan:

```text
RUN-001

Budget:       $1.00
Used:         $0.63
Remaining:    $0.37
Progress:     63%
```

Jika mendekati limit:

```text
WARNING:
80% of budget consumed.
```

## 5A.28 AI Control Plane Acceptance Criteria

Control Plane dianggap selesai jika:

- Agent tidak dapat melewati budget parent
- Context dibatasi sesuai budget
- Full transcript tidak dikirim secara default
- Router LLM tidak digunakan jika deterministic routing cukup
- Fan-out memiliki limit
- Retry memiliki limit
- Agent loop memiliki stop condition
- Model dapat dipilih berdasarkan task
- Usage dapat dihitung
- Cost dapat ditampilkan
- Approval dapat menghentikan tindakan berisiko
- Workflow dapat dihentikan secara manual
- Tool call dapat diaudit

---

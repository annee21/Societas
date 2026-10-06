<!-- Doc 01 — Visi, Prinsip, Konsep Inti (§1–5)
     Bagian dari societas-full-product-spec. Urutan dokumen diatur di README.md.
     Nomor section dipertahankan; referensi silang antar-doc memakai nomor section (#N, 5A.x, 72A.x). -->

# Societas — Full Product Specification

> **Status:** Konsep / Product Blueprint  
> **Bahasa:** Indonesia  
> **Target:** Personal-first, open-source, local/self-hosted  
> **Core:** Multi-agent AI workspace dengan komunikasi real-time berbasis Event Bus  
> **Nama sementara:** `societas`

---

# 1. Ringkasan Produk

`societas` adalah sebuah **Societas / Multi-Agent Workspace** yang memungkinkan satu orang membangun dan menjalankan tim AI virtual dengan berbagai peran seperti:

- CEO
- CTO
- Researcher
- Engineer
- Reviewer
- Product
- Designer
- Security
- Analyst
- dan role custom lainnya

Pengguna menjadi manusia yang memegang keputusan akhir.

Setiap agent memiliki:

- identitas
- role
- system prompt
- model
- tools
- permission
- memory
- task
- artifact
- channel komunikasi

Agent dapat:

- menerima tugas
- membuat subtugas
- berkomunikasi dengan agent lain
- memanggil tools
- menghasilkan artifact
- memberikan report
- melakukan review
- meminta approval manusia
- bekerja secara paralel

Komunikasi antar-agent dirancang sebagai **real-time event system** berbasis Event Bus internal.

---

# 2. Visi

Membangun lingkungan di mana satu orang dapat menjalankan sebuah **tim AI virtual yang terasa seperti organisasi kecil yang hidup**.

Bukan sekadar chatbot.

Bukan sekadar agent framework.

Bukan sekadar task runner.

Konsep utamanya:

```text
                    HUMAN
                  / FOUNDER
                      |
                      v
                    CEO
                      |
       +--------------+--------------+
       |              |              |
       v              v              v
     CTO           Research          CPO
       |              |              |
       v              v              v
    Engineer       Analyst          Designer
       |              |
       +-------+------+ 
               |
               v
            Reviewer
               |
               v
            Artifact
               |
               v
             HUMAN
```

Tujuan akhirnya adalah membuat AI agents terasa seperti **rekan kerja yang dapat dikoordinasikan**, bukan kumpulan chatbot yang berdiri sendiri.

---

# 3. Prinsip Produk

## 3.1 Personal First

Produk awal dibuat untuk digunakan sendiri.

Tidak perlu menjadikan:

- growth
- pricing
- SaaS
- enterprise sales
- market share

sebagai requirement utama.

Produk harus berguna walaupun hanya satu user.

---

## 3.2 Open Source

Core system harus dapat dijalankan sendiri.

Target utama:

```text
git clone
    |
    v
build
    |
    v
run locally
```

Tidak boleh ada ketergantungan wajib terhadap server cloud milik project.

---

## 3.3 Local-First

Sebisa mungkin:

- data lokal
- credential lokal
- artifacts lokal
- memory lokal
- logs lokal

Cloud API boleh dipakai sebagai model provider, tetapi orchestration layer tetap dikontrol user.

---

## 3.4 Agent-Oriented

Unit utama sistem adalah **agent**, bukan chat session.

---

## 3.5 Event-Driven

Agent berkomunikasi menggunakan event/message.

Contoh:

<!-- event-types -->
```text
task.created
task.started
message.sent
tool.call_started
tool.call_completed
artifact.created
artifact.updated
review.requested
review.completed
approval.requested
approval.granted
agent.started
agent.stopped
```

Nama di atas adalah wire `type` dari [72A.7 — Event Registry](10-contracts-mvp-roadmap.md#72a7-event-registry), bukan alias konseptual.

---

## 3.6 Human-in-the-Loop

AI boleh mengerjakan banyak hal secara autonomous, tetapi tindakan berisiko tinggi harus dapat meminta approval manusia.

Contoh:

- menghapus file
- menjalankan command tertentu
- publish deployment
- mengubah production config
- mengirim external message
- membuat pengeluaran/billing action

---

## 3.7 Event-Driven Communication

Komunikasi internal antar-agent menggunakan Event Bus. Arsitektur tidak terkunci pada satu mekanisme transport.

Target:

```text
Agent Protocol
      |
      +---- In-Process Channel (goroutine + channel)
      +---- WebSocket
      +---- Local IPC
```

---

# 4. Masalah yang Ingin Diselesaikan

AI tools saat ini sering bekerja sebagai sesi terpisah:

```text
Chat A
Chat B
Chat C
```

Masalahnya:

- context terfragmentasi
- tidak ada organisasi
- tidak ada delegation
- tidak ada task graph
- agent tidak memiliki role jelas
- sulit mengawasi banyak agent
- output sering berupa teks yang sulit dilacak
- tool usage tidak terkoordinasi
- tidak ada real-time communication fabric
- manusia harus terus menjadi operator manual

`societas` mengubah model menjadi:

```text
                  WORKSPACE
                      |
       +--------------+--------------+
       |              |              |
     Agent          Agent          Agent
       |              |              |
      Task           Tool         Artifact
       |              |              |
       +--------------+--------------+
                      |
                 Event Stream
                      |
                    HUMAN
```

---

# 5. Konsep Inti

## 5.1 Workspace

Workspace adalah root dari sebuah organisasi AI.

Contoh:

```text
~/societas/tunly/
```

Workspace menyimpan:

```text
workspace/
├── agents/
├── tasks/
├── artifacts/
├── memory/
├── events/
├── config/
├── logs/
└── runs/
```

---

## 5.2 Agent

Agent adalah entitas AI yang memiliki:

```yaml
id: cto
name: CTO
role: technical_lead
model: ...
tools:
  - filesystem
  - shell
  - git
permissions:
  filesystem: workspace
  shell: restricted
```

Agent tidak hanya memiliki prompt.

Agent juga memiliki:

- state
- task queue
- memory
- permissions
- current context
- event subscriptions
- output channels

---

## 5.3 Role

Role mendefinisikan tanggung jawab agent dan bersifat murni **Config-Driven**: backend Go **tidak memiliki enum peran kaku** (tidak ada `CEO`/`CTO`/`Engineer` hardcoded). Kode Go hanya membaca daftar squad dari `workspace.yaml` saat runtime sebagai `map[string]AgentConfig` (lihat #30, #36).

Contoh role bawaan (semuanya hanya contoh konfigurasi, bukan konstanta di kode):

### CEO

Fokus:

- prioritas
- delegasi
- keputusan
- trade-off
- review hasil lintas fungsi

### CTO

Fokus:

- architecture
- technical feasibility
- performance
- security
- engineering direction

### Researcher

Fokus:

- mencari informasi
- verifikasi
- analisis
- membuat research report

### Engineer

Fokus:

- implementation
- testing
- debugging
- refactoring

### Reviewer

Fokus:

- mencari bug
- menemukan risk
- mengevaluasi kualitas
- memberikan feedback

Role tidak harus fixed.

User dapat membuat:

```text
CEO
CTO
Researcher
Lawyer
Marketing
Finance
Game Designer
Security Engineer
DevOps
Data Scientist
```

Komposisi squad bebas per workspace dan mengikuti domain proyek, misalnya:

```text
Tim teknis     : lead, developer, qa_engineer, security_auditor
Tim riset      : analyst, researcher, fact_checker
Tim operasional: ops_lead, support_agent, finance_checker
```

Semua peran, batasan izin tools, tier model, dan system prompt didefinisikan deklaratif di YAML.

## Urutan Baca

Setelah §5, pahami dulu [§6 Agent Lifecycle](03-tasks-and-lifecycle.md#6-agent-lifecycle), [§7 Task System](03-tasks-and-lifecycle.md#7-task-system), dan [§8 Task Graph](03-tasks-and-lifecycle.md#8-task-graph). Ini memberi model konkret tentang aktivitas agen dan task paralel sebelum membaca [§5A AI Control Plane](02-ai-control-plane.md), yang mengatur scheduler, budget, routing Jev, dan context window. Setelah itu kembali ke §7.1/§9 untuk intake dan delegation lengkap, lalu lanjutkan Doc 04–10. Urutan section tidak diubah; detail jalur baca ada di README.

---

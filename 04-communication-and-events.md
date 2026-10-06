<!-- Doc 04 — Komunikasi & Event (§10–16)
     Bagian dari societas-full-product-spec. Urutan dokumen diatur di README.md.
     Nomor section dipertahankan; referensi silang antar-doc memakai nomor section (#N, 5A.x, 72A.x). -->

# 10. Communication Model

Komunikasi agent menggunakan message/event.

Contoh:

```json
{
  "type": "message.sent",
  "from": "ceo",
  "to": "cto",
  "task_id": "TASK-101",
  "content": "Review architecture option B."
}
```

Message memiliki:

- sender
- recipient
- timestamp
- task ID
- conversation ID
- priority
- payload
- correlation ID

Contoh di atas disederhanakan. Bentuk kanonik (envelope lengkap) ada di **Section 72A.3**. Agent tidak berkomunikasi langsung, semua pesan dimediasi Event Bus (72A.1, I1).

---

# 11. Event Model

Semua aktivitas penting menghasilkan event.

Contoh:

<!-- event-types -->
```text
workspace.created
agent.created
agent.started
agent.stopped

task.created
task.assigned
task.started
task.completed
task.failed

message.sent
message.received

tool.call_started
tool.call_completed
tool.call_failed

artifact.created
artifact.updated

review.requested
review.completed

approval.requested
approval.granted
approval.rejected
```

Event menjadi sumber untuk:

- dashboard
- audit
- replay
- debugging
- analytics
- memory processing

Daftar lengkap event beserta schema payload-nya ada di **Section 72A.7**. Event tambahan untuk Control Plane (`context.built`, `model.selected`, `budget.*`, `policy.evaluated`, dll.) didefinisikan di sana.

---

# 12. Event Bus Communication Layer

Event Bus digunakan sebagai real-time message fabric internal.

Konsep dasar:

```text
Workspace
   |
   +---- Agent A
   |
   +---- Agent B
   |
   +---- Agent C
```

Masing-masing agent memiliki channel subscribe/publish via Event Bus.

Contoh channel per agent:

```text
agent/ceo
agent/cto
agent/research
agent/engineer
agent/reviewer
```

Atau berdasarkan workspace:

```text
workspace/tunly/ceo
workspace/tunly/cto
workspace/tunly/research
```

---

# 13. Logical Event Bus Model

Contoh:

```text
Event Bus
  |
  +---- Broadcast: workspace/tunly
           |
           +---- Channel: agent/ceo
           +---- Channel: agent/cto
           +---- Channel: agent/research
           +---- Channel: agent/coder
```

Message/event dikirim sebagai envelope (lihat Section 72A.3).

---

# 14. Message Categories

Daftar berikut memakai wire `type` dari [72A.7 — Event Registry](10-contracts-mvp-roadmap.md#72a7-event-registry). Kategori bukan registry kedua; nama yang tidak terdaftar ditolak (I9).

## 14.1 Control

<!-- event-types -->
```text
agent.started
agent.stopped
```

Start/stop adalah tindakan kontrol yang menghasilkan event lifecycle di atas. Pause/resume level agen belum memiliki wire `type` di registry; jangan mengirim alias sebagai event. Pause/resume satu task memakai `task.paused`/`task.resumed` (#33.3, 72A.6, 72A.7).

## 14.2 Task

<!-- event-types -->
```text
task.delegate_requested
task.created
task.assigned
task.started
task.blocked
task.paused
task.resumed
task.completed
task.failed
task.cancelled
```

## 14.3 Communication

<!-- event-types -->
```text
message.sent
message.received
```

Broadcast/reply adalah pola komunikasi memakai envelope dan target yang sesuai, bukan wire `type` terpisah.

## 14.4 Tool

<!-- event-types -->
```text
tool.call_requested
tool.call_started
tool.call_completed
tool.call_failed
```

Hasil gagal logis memakai `tool.call_completed` dengan `status: error`; kegagalan dispatch/transport memakai `tool.call_failed` sesuai outcome di 72A.8–72A.10.

## 14.5 Artifact

<!-- event-types -->
```text
artifact.created
artifact.updated
```

Penghapusan artifact belum memiliki wire `type` di registry.

## 14.6 Approval

<!-- event-types -->
```text
approval.requested
approval.granted
approval.rejected
approval.invalidated
approval.batch_submitted
```

---

# 15. Streaming

Agent tidak harus menunggu output selesai.

Contoh LLM:

```text
Agent
  |
  +-- token "We"
  +-- token " should"
  +-- token " build"
  +-- token "..."
```

Dashboard dapat menampilkan output secara live.

Streaming juga digunakan untuk:

- voice
- TTS
- ASR
- logs
- shell output
- tool output
- research progress

---

# 16. Agent-to-Agent Conversation

Contoh:

```text
CEO:
Research this technology.

Research:
I found 8 relevant projects.

CEO:
Give me the top 3.

Research:
1. ...
2. ...
3. ...

CEO:
CTO, evaluate #2.

CTO:
Architecture is viable but has two risks.

CEO:
Coder, prototype the core transport.

Coder:
Starting implementation.
```

Semua event direkam.

---

# Societas — Full Product Specification (Split Edition)

Dokumen spesifikasi dipecah menjadi 10 file agar mudah direvisi per topik.
Nomor section dipertahankan untuk menjaga referensi silang (`#48`, `5A.8`, `72A.5`, `I3`, dst);
urutan onboarding mengikuti peta dokumen di bawah.

Nomor yang loncat (34–35, 73–78, 84, dan lainnya) sengaja dipertahankan dari penomoran spesifikasi awal, bukan tanda ada file hilang.

**Urutan baca linear (onboarding):** Doc 01 §1–5 → Doc 03 §6 (agent lifecycle), §7 (task), §8 (DAG) → Doc 02 §5A (control plane) → kembali ke Doc 03 §7.1/§9 (intake/delegation) → Doc 04–10. Detail intake §7.1 dapat dilewati pada pembacaan pertama; nomor section dan file tetap stabil.

## Aturan Revisi

- Revisi dilakukan di file topik terkait, bukan di dokumen gabungan.
- Nomor section **jangan diubah** — referensi silang antar-file bergantung padanya.
- Jika menambah section baru, gunakan nomor desimal di sebelah section induk
  (mis. `5A.28.x`, dengan `x` nomor subseksi baru) agar urutan tetap terbaca tanpa menggeser nomor yang sudah ada.
- **Section 72A (Doc 10) adalah Source of Truth** untuk schema, event, dan invariants —
  jika ada konflik dengan doc lain, 72A yang berlaku.

## Peta Dokumen

| File | Section | Topik |
|------|---------|-------|
| `01-vision-and-core.md` | 1–5 | Visi, masalah, konsep inti (workspace, agent, role) |
| `03-tasks-and-lifecycle.md` | 6–9 | Agent lifecycle, task system, intake & routing pipeline (§7.1), task graph, delegation |
| `02-ai-control-plane.md` | 5A.1–5A.28 | Control Plane: orchestrator, budget, context, router (Jev), policy, intake pipeline (§7.1 dirujuk dari sini) |
| `04-communication-and-events.md` | 10–16 | Communication model, event model/bus, message categories, streaming, agent conversation |
| `05-artifacts-memory-tools.md` | 17–21 | Artifact system & contract-first (§17.1), artifact flow, memory system, tools + MCP client |
| `06-permissions-approvals-roles.md` | 22–32 | Permission & path jailing, approval & risk tier, autonomy, peran agent, role customization (declarative squad), model provider, cost tracking + OpenRouter accounting |
| `07-dashboard-config-storage.md` | 33–37 | Dashboard (task board, approval center), workspace.yaml (risk, toolchain, escalation_lead), dual-storage SQLite + Vector DB |
| `08-runtime-architecture.md` | 38–56 | Suggested architecture, module, agent runtime (step function), event bus (outbox, mailbox), retry, parallelism, conflict resolution (escalation_lead), voice/multimodal, channel taxonomy, backpressure, retention |
| `09-security-sandbox-observability.md` | 57–72 | Security model, secrets, tool sandbox & OS-level isolation, git integration & worktree, MCP search, structured tool calls, observability/logging/tracing, agent run, replay, context budget, protocol versioning |
| `10-contracts-mvp-roadmap.md` | 72A–105 | **Source of Truth**: invariants I1–I23, envelope, core schemas (task, artifact, budget), approval snapshot/batch/evidence, state machine, event registry, payload schemas, error catalog, alur baku, MVP, roadmap, priorities, killer demo, anti-boncos |

## Titik Panas Revisi Terakhir (quick lookup)

- Dual-Storage: Doc 05 (§19.5), Doc 07 (§37)
- 2x Rebuttals & escalation_lead: Doc 02 (5A.2), Doc 06 (§30.1), Doc 07 (§36), Doc 08 (§48)
- Deterministic Guard & OS Isolation: Doc 06 (§22), Doc 09 (§59)
- Risk Tier & Runtime Escalation: Doc 06 (§23.1), Doc 10 (72A.5), Doc 02 (5A.8)
- Human Attention Budget / Digest Approval: Doc 06 (§23.2), Doc 07 (§33.7, §36–37), Doc 08 (§40.1), Doc 10 (I18, 72A.7–72A.10)
- Dynamic Context Assembly: Doc 02 (5A.4), Doc 07 (§36)
- Task Pause/Resume & Step Function: Doc 06 (§23), Doc 07 (§33.3), Doc 08 (§40), Doc 10 (72A.5–72A.7)
- MCP Client & Search: Doc 05 (§21.1), Doc 09 (§62–63)
- Toolchain Runner & Compiler Gate: [Doc 02 (5A.22 — Compiler Gate)](02-ai-control-plane.md#compiler-gate-sebelum-reviewer-dipanggil), Doc 07 (§36 toolchain), Doc 09 (§60.2), Doc 10 (I20)
- Contract-First (codegen, contract.lookup): Doc 05 (§17.1), Doc 10 (72A.5 `contract_hash`)
- OpenRouter Usage Accounting: Doc 06 (§32.1), Doc 02 (5A.10, 5A.26)
- Dynamic Enum Injection & Blind Delegation: Doc 02 (5A.8), Doc 06 (§30.1), Doc 10 (72A.8, 72A.10)
- Search & Replace Edit + Serial Merge Queue: Doc 09 (§60.3–60.4), Doc 06 (§28), Doc 08 (§45)
- PROJECT_MAP auto-regen: Doc 03 (§7.1), Doc 09 (§60.4)
- Provider Rate Limiter (RPM/TPM token bucket): Doc 02 (5A.8)
- Network Failure Handling (Deterministic Go Runtime): Doc 02 (5A.17)
- Memory Curation / anti Zombie Memory: Doc 05 (§19.6, §20), Doc 07 (§37.3), [Doc 02 (5A.25 — Semantic Retrieval)](02-ai-control-plane.md#5a25-semantic-retrieval)
- Session Policy: [I23 — sumber utama aturan mode/lifecycle/flush](10-contracts-mvp-roadmap.md#72a1-aturan-dasar-invariants); Doc 02 (5A.4), Doc 07 (§36), dan Doc 08 (§40.1) hanya merujuk aturan ini.
- Review repair: tool outcome/retry (I16, §21, §44, 72A.8–10), pause recovery (72A.6), contract invalidation (§17.1, 72A.6/8), aggregate payload boundary (I5, 72A.12), semantic path guard (§22.2, §59)
- Approval snapshot SHA-256/JCS + final candidate merge: I17, 72A.8/10/12, §40.2, §60.4; invalidation lewat `approval.invalidated`
- Semantic Rebase / anti Zombie Memory: Doc 09 (§60.4), Doc 08 (§48.5), Doc 05 (§19.6), Doc 10 (I17, I19, 72A.5, 72A.8)

## Audit Kontrak

Script audit asli yang dirujuk laporan review tidak disertakan. `audit-spec.py` adalah **pengganti transparan**, membaca schema/registry/contoh langsung dari §72A (tidak ada salinan schema kedua).

```bash
python3 -m venv .venv-audit
.venv-audit/bin/pip install -r requirements-audit.txt
.venv-audit/bin/python audit-spec.py --output validation-results.json
.venv-audit/bin/python test-audit-spec.py
# Opsional: periksa semua nomor heading lama tetap ada dan berurutan
.venv-audit/bin/python audit-spec.py --baseline-ref <commit-sebelum-revisi>
# Opsional: checks untuk kode audit
.venv-audit/bin/pip install ruff==0.11.13 mypy==1.15.0 \
  types-PyYAML==6.0.12.20250915 types-jsonschema==4.25.1.20251009
.venv-audit/bin/ruff check audit-spec.py test-audit-spec.py
.venv-audit/bin/mypy audit-spec.py test-audit-spec.py
```

Exit `0` = pemeriksaan statis lulus; exit `1` = kegagalan parse/schema/registry/contoh/fixture/probe/penomoran/referensi dokumentasi. Audit memeriksa sintaks JSON/YAML, Draft 2020-12, ID unik, `$ref`, registry, schema yatim, contoh kanonik, tabel transisi, aggregate payload, serta fixture SHA-256/JCS approval dan binding kandidat/evidence. Audit juga memeriksa fence tertutup, keberadaan nomor 5A/72A di prose, target file/anchor tautan Markdown lokal, kecocokan nomor label dengan section target (termasuk subsection seperti Compiler Gate), daftar wire event bertanda `<!-- event-types -->`, dan kelengkapan field contoh `<!-- example:workspace.yaml -->`.

Gunakan tautan dengan label nomor dan judul untuk referensi silang (mis. `[5A.25 — Semantic Retrieval](02-ai-control-plane.md#5a25-semantic-retrieval)`): nomor yang masih ada tetapi menunjuk topik yang salah dapat terdeteksi lewat ketidakcocokan label/anchor. Audit **tidak menyimpulkan maksud semantik referensi nomor tanpa tautan**, dan daftar event tanpa marker tidak diperiksa terhadap registry. YAML diperiksa sintaks dan kelengkapan contoh, bukan validasi schema konfigurasi runtime.

Probe boundary adalah validator referensi spesifikasi, **bukan implementasi runtime**. Audit lulus tidak menutup celah desain atau membuktikan rebase/gate/review, Git-ref CAS, outbox/ledger, otorisasi/approval consumption, crash recovery, rekonsiliasi provider, live resource versions, Git broker, sandbox, atau memory GC — belum ada runtime di repo.

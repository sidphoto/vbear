# Phase C Agent & Model Routing Governance

Version: 1.0

Status: Active

Scope: Phase C multi-agent development workflow

Primary principle: **Fixed roles, dynamic model routing, single product-code writer**

---

## 1. Purpose

This document defines:

- Agent roles
- Model/provider routing
- Reasoning / thinking tiers
- Single-writer rules
- Review boundaries
- Escalation conditions
- Controlled-action boundaries
- Phase C execution order

The goal is to avoid using the most expensive or strongest model for every task while preserving quality for high-risk work.

The workflow must route work according to:

1. **Role**
2. **Task risk**
3. **Task complexity**
4. **Required reasoning depth**
5. **Required modality / browser capability**

---

# 2. Human Authority

## Product Owner

The human Product Owner is the final authority for:

- Product scope
- C-D1 through C-D5
- Gate 7
- Controlled actions
- Provider/executor approval
- Commit authorization
- Push authorization
- Merge authorization
- Production deployment
- Production restart
- Credential / permission changes
- Destructive migrations
- Governance-policy changes

Agents may provide evidence, findings, and recommendations.

Agents must not treat previous approval of a similar action as approval for the current action.

---

# 3. Agent Roles

| Role | Primary Responsibility | Product-Code Write Permission |
|---|---|---|
| Product Owner | Scope, product decisions, Gate 7, controlled-action authorization | No |
| Coordinator | Task decomposition, governance checks, dispatch, acceptance criteria, findings consolidation, test coordination, Git orchestration | Governance/docs only |
| MCODE | Main implementation, tests, fault injection, long-context coding, self-review, fixes | **Yes — sole product-code writer** |
| Claude | Independent architecture/security/regression review | No |
| Codex | Targeted adversarial review, test design, second opinion | No |
| AGY | Real-browser UI/RWD/interaction QA | No |

---

# 4. Single-Writer Rule

For a given worktree, only one active product-code writer may exist at a time.

Default Phase C writer:

```text
writer = MCODE
```

Allowed:

```text
MCODE       WRITE
Claude      READ / REVIEW
Codex       READ / REVIEW
AGY         READ / QA
Coordinator GOVERNANCE / REPORT
```

Forbidden:

```text
MCODE  WRITE
Claude WRITE
```

Forbidden:

```text
MCODE WRITE
Codex WRITE
```

Before modifying product code, MCODE must acquire writer ownership.

After implementation or fixing is complete, MCODE must release writer ownership.

If MCODE later returns to fix review findings, it must reacquire writer ownership.

---

# 5. Coordinator Write Boundary

The Coordinator may write:

- Governance files
- Task records
- Review reports
- Handoff documents
- Session digests
- Test reports
- Non-runtime orchestration metadata

The Coordinator must not directly modify product/runtime code.

Examples of product/runtime code include:

```text
src/
app/
backend/
frontend/
runtime-affecting configuration
production behavior configuration
```

---

# 6. Model Routing Tiers

Model selection is **not fixed to one model per Agent**.

Every task must be assigned a tier.

## Tier 1 — FAST

Use for:

- Routine tasks
- Small changes
- Low-risk inspection
- Simple test generation
- Simple diff checking
- Formatting / classification
- High-throughput work

Goal:

```text
Low latency
Low cost
Sufficient quality
```

---

## Tier 2 — STANDARD

Use for:

- Normal feature work
- Typical code review
- Multi-file implementation
- Integration testing
- Normal browser QA
- Standard debugging

This is the default tier for most Phase C work.

---

## Tier 3 — DEEP

Use for:

- Complex architecture
- Security-sensitive work
- Concurrency
- Race conditions
- Data integrity
- Migration
- Large refactors
- Difficult debugging
- Long-horizon coding
- Large-context analysis

---

## Tier 4 — ESCALATION

Use only when:

- Critical finding remains unresolved
- Production data is at risk
- Security boundary is uncertain
- Migration is not safely reversible
- High-tier models disagree materially
- Gate 7 still has unresolved HIGH findings
- Root cause spans multiple systems
- A second independent top-tier judgment is required

Tier 4 must not become the routine default.

---

# 7. Model Routing Matrix

## MCODE / MiniMax

### FAST

```yaml
executor: mcode
provider: minimax
model: MiniMax-M3
thinking: off
```

Use for:

- Small code changes
- Lint fixes
- Rename/refactor with narrow scope
- Simple bug fixes
- Simple CRUD
- Small tests

### STANDARD

```yaml
executor: mcode
provider: minimax
model: MiniMax-M3
thinking: on
```

Use for:

- Normal feature work
- Multi-file implementation
- Debugging
- Integration tests
- Fault injection
- Findings fixes

**Default MCODE mode for Phase C.**

### DEEP

```yaml
executor: mcode
provider: minimax
model: MiniMax-M3
thinking: on
mode: long-context
```

Use for:

- Large repositories
- Long-horizon tasks
- Large refactors
- Complex migrations
- Multi-stage implementation
- Long session / long context
- Large-scale self-review

---

## Claude

### FAST

```yaml
executor: claude-code
tier: fast
model_class: haiku
```

Use for:

- Quick checklist review
- Low-risk diff scan
- Document classification
- Simple sanity checks

### STANDARD

```yaml
executor: claude-code
tier: standard
model_class: sonnet
```

Use for:

- Normal code review
- Architecture review
- Spec review
- Regression review
- Standard security review

**Default Claude review tier.**

### DEEP

```yaml
executor: claude-code
tier: deep
model_class: opus
```

Use for:

- High-risk architecture
- Security boundaries
- Data-loss risk
- Concurrency
- Race conditions
- Migration
- Permission / authorization logic
- Core data-model review

### ESCALATION

Use the highest approved Claude model only when Tier 4 criteria are met.

---

## Codex

### FAST

```yaml
executor: codex
tier: fast
model_class: luna
reasoning: low_or_default
```

Use for:

- Quick test design
- Simple edge-case scan
- Diff sanity checks

### STANDARD

```yaml
executor: codex
tier: standard
model_class: terra
reasoning: medium
```

Use for:

- Adversarial review
- Test strategy
- Second implementation opinion
- Focused bug analysis

### DEEP

```yaml
executor: codex
tier: deep
model_class: sol
reasoning: high
```

Use for:

- HIGH findings
- Model disagreement
- Complex concurrency
- Data integrity
- Authentication / authorization
- Difficult-to-reproduce bugs
- Deep adversarial review

### ESCALATION

Use the highest approved Codex reasoning level only when Tier 4 criteria are met.

---

## AGY / Gemini

### FAST

```yaml
executor: agy
tier: fast
model_class: flash-lite
```

Use for:

- Simple screenshot checks
- Smoke tests
- High-volume QA
- Low-risk visual verification

### STANDARD

```yaml
executor: agy
tier: standard
model_class: flash
thinking: medium
```

Use for:

- Browser QA
- RWD
- Navigation
- Interaction flows
- Multi-step UI verification

**Default AGY QA tier.**

### DEEP

```yaml
executor: agy
tier: deep
model_class: flash
thinking: high
```

Use for:

- Complex browser flows
- Cross-page state
- Difficult UI bugs
- Long automation sequences
- Multi-modal debugging

---

# 8. Default Routing Policy

For a normal feature:

```text
MCODE STANDARD
→ Claude STANDARD
→ AGY STANDARD
```

Codex is not automatically required.

---

For a small low-risk bug:

```text
MCODE FAST
→ Claude FAST or STANDARD
→ Done
```

AGY is used only if browser/UI behavior is affected.

---

For a high-risk migration:

```text
MCODE DEEP
→ Claude DEEP
→ Codex DEEP
→ AGY STANDARD or DEEP
→ Gate 7
```

---

# 9. Codex Activation Triggers

Codex should be activated only when one or more conditions are true:

- Claude finds a HIGH issue
- There is an unresolved MEDIUM issue with meaningful risk
- Concurrency is involved
- Migration is involved
- Authentication / authorization is involved
- Data integrity is involved
- Destructive behavior is possible
- Claude and MCODE disagree materially
- Test coverage is inadequate
- A second implementation perspective is useful
- A difficult bug remains unresolved

Codex must not duplicate the full Claude review unless explicitly required.

---

# 10. MCODE Self-Review vs Independent Review

MCODE self-review is:

```text
implementation quality control
```

It may verify:

- Acceptance criteria
- Test coverage
- Regression risk
- Dead code
- Schema mismatch
- Error paths
- Unhandled cases

MCODE self-review is **not** an independent review.

Claude review is the independent review layer.

---

# 11. Findings Flow

Review Agents must not directly modify product code.

Required flow:

```text
Claude / Codex / AGY
        ↓
Findings report
        ↓
Coordinator
        ↓
Deduplicate / classify / severity / scope
        ↓
MCODE
        ↓
Fix
```

The Coordinator may classify findings as:

```text
accepted
rejected
needs_clarification
duplicate
out_of_scope
```

---

# 12. Phase C Execution Order

```text
1. Product Owner decides C-D1 through C-D5

2. Coordinator freezes:
   - scope
   - schema
   - acceptance criteria
   - test plan
   - controlled boundaries
   - review requirements

3. Coordinator assigns task tier

4. MCODE acquires writer ownership

5. MCODE executes implementation
   - model tier selected according to task
   - automated tests
   - integration tests
   - fault injection where required

6. MCODE performs self-review

7. MCODE releases writer ownership

8. Claude performs independent review
   - review tier selected by risk

9. Coordinator determines whether Codex trigger conditions exist

10. If triggered, Codex performs targeted adversarial review

11. Coordinator consolidates findings

12. MCODE reacquires writer ownership

13. MCODE fixes accepted findings

14. MCODE reruns relevant tests

15. MCODE releases writer ownership

16. Coordinator runs:
   - full test suite
   - governance verification
   - evidence consolidation

17. AGY performs browser / RWD / interaction QA when applicable

18. Claude may perform final read-only verification when required

19. Product Owner executes Gate 7

20. Only after explicit human authorization:
   - commit
   - push
   - merge
   - deploy
   - restart
```

---

# 13. Phase C State Machine

```text
PLANNING
↓
DECISION_PENDING
↓
READY_FOR_IMPLEMENTATION
↓
WRITER_ACTIVE
↓
SELF_REVIEW
↓
INDEPENDENT_REVIEW
↓
FINDINGS_OPEN
↓
FIXING
↓
VERIFICATION
↓
BROWSER_QA
↓
GATE_7
↓
AUTHORIZED_RELEASE
↓
DONE
```

Role ownership by state:

| State | Primary Role |
|---|---|
| PLANNING | Coordinator |
| DECISION_PENDING | Product Owner |
| READY_FOR_IMPLEMENTATION | Coordinator |
| WRITER_ACTIVE | MCODE |
| SELF_REVIEW | MCODE |
| INDEPENDENT_REVIEW | Claude |
| FINDINGS_OPEN | Coordinator / Codex if triggered |
| FIXING | MCODE |
| VERIFICATION | Coordinator |
| BROWSER_QA | AGY |
| GATE_7 | Product Owner |
| AUTHORIZED_RELEASE | Human-authorized executor |

---

# 14. Controlled Actions

The following always require explicit human authorization:

- Commit
- Push
- Merge
- Production deploy
- Production restart
- Credential change
- Permission change
- Destructive migration
- External data write
- Provider replacement
- Executor replacement
- Governance-policy change

No Agent may self-authorize a controlled action.

---

# 15. Provider / Executor Separation

Provider identity and executor identity must remain separate.

Examples:

```text
provider = minimax
executor = mcode
model = MiniMax-M3
```

```text
provider = anthropic
executor = claude-code
model_class = sonnet
```

```text
provider = openai
executor = codex
model_class = sol
```

Do not hide one provider behind another executor identity.

---

# 16. Model Upgrade Rule

Roles must remain stable when models change.

Example:

```text
reviewer = Claude
tier = standard
```

The model registry resolves the current approved model.

Therefore model upgrades should normally change only the model registry, not the Phase C workflow.

Example future migration:

```text
Sonnet 5 → future Sonnet generation
MiniMax-M3 → future MiniMax coding model
GPT-5.6 class → future approved Codex model
Gemini Flash → future approved AGY model
```

---

# 17. Runtime Metadata

Each dispatched task should record at minimum:

```yaml
executor:
provider:
model:
tier:
reasoning_or_thinking:
intent:
worktree:
writer_status:
task_scope:
acceptance_criteria:
review_required:
```

Example:

```yaml
executor: mcode
provider: minimax
model: MiniMax-M3
tier: standard
reasoning_or_thinking: on
intent: change
worktree: /path/to/worktree
writer_status: acquired
review_required: true
```

---

# 18. Current Phase C Runtime Status

```text
mcode-orca wrapper            READY
MCode executable              READY
MiniMax-M3 API                READY
Orca spawn                    READY
Orca read / wait / send       READY
Governance v3 preflight       READY
Executor metadata injection   READY
Inspect mode                  READY
Change governance gate        READY
Writer lock                   IN VALIDATION
Controlled mode               PENDING VALIDATION
Phase C product coding        NOT STARTED
C-D1 through C-D5             PRODUCT DECISION REQUIRED
```

Do not begin Phase C product implementation until required product decisions are resolved and the appropriate task tier is assigned.

---

# 19. Decision Rule Summary

Use this rule when selecting a tier:

```text
Routine + low risk
→ FAST

Normal implementation / review / QA
→ STANDARD

Complex + high risk + long context
→ DEEP

Critical / disagreement / unresolved high-risk issue
→ ESCALATION
```

The objective is:

```text
Use the cheapest and fastest model tier that can safely complete the task,
and escalate only when task evidence or risk justifies escalation.
```

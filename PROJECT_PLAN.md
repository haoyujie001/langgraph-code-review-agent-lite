# Project Plan

## Project Positioning

This repository is a beginner-oriented, single-agent LangGraph project. Its only final workflow is:

```text
Git Diff
  -> LangGraph review agent
  -> four read-only tools
  -> structured Chinese findings
  -> Markdown report
  -> JSON history
```

The project is developed one stage at a time. A later stage must not begin until the current stage is understood and accepted.

## Completed Learning Stages

| Stage | Status | Scope | Completion signal |
|---|---|---|---|
| 1 | Completed | Project skeleton, settings, Pydantic models, FastAPI | `GET /health` and stage-one tests pass |
| 2 | Completed | Git service and four read-only tools | Every tool can be called and tested independently |
| 3 | Completed | `ReviewState`, nodes, edges, and a deterministic graph | A graph without a real LLM completes end to end |
| 4 | Completed | DeepSeek, `bind_tools`, `ToolNode`, and conditional routing | The model decides when to call tools |
| 5 | Completed | Chinese structured findings, basic validation, Markdown | One review produces JSON and Markdown |
| 6 | Completed | Focused tests, demo repository, README, final verification | The complete small project is reproducible |

## Focused Extensions

| Feature | Status | Scope |
|---|---|---|
| Custom review rules | Completed | Up to five focus areas and ten short rules flow through request, state, prompt, report, and history |
| Commit Range review | Completed | Validate refs, resolve immutable SHAs, review only the selected range, and return both SHAs |
| Simple review history | Completed | One local JSON file per review plus list/detail API endpoints |
| Evaluator | Completed | 50 synthetic cases, positive/negative samples, structural matching, precision, recall, and JSON result output |

## The Four Tools

```text
list_changed_files
read_diff
read_file
search_code
```

All tools are read-only. The model receives repository-relative paths; it never chooses an arbitrary host directory.

## Final Graph

```text
START
  -> prepare_review
  -> review_agent
       -> tools -> review_agent  (when tool calls exist)
       -> structure_review       (when no tool call exists)
  -> generate_report
  -> save_history
  -> END
```

## Fixed Scope Limits

The Lite project does not implement:

```text
AnalysisPackage batching
parallel review
multi-agent orchestration
MCP
RAG
GitHub PR publishing
SQLAlchemy / SQLite / Alembic
tracing platforms
Docker
GitHub Actions
task queues
complex rule engines
production-grade guardrails
```

Minimum boundaries that remain mandatory:

```text
allowed repository root
repository-relative file paths
sensitive repository path filtering
Git subprocess timeout
bounded file and diff text
maximum agent rounds
maximum total tool calls
maximum finding count
added-line finding validation
unique report files
```

## Size Budget

```text
Application code: 700-1,400 lines
Tests: 400-1,000 lines
graph.py: at most 150 lines
tools.py: at most 200 lines
Source modules: 10-13 files
```

The final ceilings include a scripted tool-calling model, real temporary Git
repositories, an in-process FastAPI request, added-line parsing, stable model
error mapping, separate round/call limits, sensitive-path filtering, and unique
report files.

When an implementation exceeds these limits, simplify before adding abstractions.

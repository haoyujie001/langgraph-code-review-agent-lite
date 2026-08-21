# Project Plan

## Project Positioning

This repository is a beginner-oriented, single-agent LangGraph project. Its only final workflow is:

```text
Git Diff
  -> LangGraph review agent
  -> four read-only tools
  -> structured Chinese findings
  -> Markdown report
```

The project is developed one stage at a time. A later stage must not begin until the current stage is understood and accepted.

## Six Stages

| Stage | Status | Scope | Completion signal |
|---|---|---|---|
| 1 | Completed | Project skeleton, settings, Pydantic models, FastAPI | `GET /health` and stage-one tests pass |
| 2 | Completed | Git service and four read-only tools | Every tool can be called and tested independently |
| 3 | Completed | `ReviewState`, nodes, edges, and a deterministic graph | A graph without a real LLM completes end to end |
| 4 | Completed | DeepSeek, `bind_tools`, `ToolNode`, and conditional routing | The model decides when to call tools |
| 5 | Completed | Chinese structured findings, basic validation, Markdown | One review produces JSON and Markdown |
| 6 | Completed | Focused tests, demo repository, README, final verification | The complete small project is reproducible |

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
review history
tracing platforms
evaluation datasets
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
Application code: 500-950 lines
Tests: 300-800 lines
graph.py: at most 150 lines
tools.py: at most 200 lines
Source modules: 8-10 files
```

The final ceilings include a scripted tool-calling model, real temporary Git
repositories, an in-process FastAPI request, added-line parsing, stable model
error mapping, separate round/call limits, sensitive-path filtering, and unique
report files.

When an implementation exceeds these limits, simplify before adding abstractions.

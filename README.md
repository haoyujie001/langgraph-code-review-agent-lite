# LangGraph Code Review Agent Lite

A small, beginner-oriented Code Review Agent built stage by stage. Version 0.7 adds four focused extensions without changing the single-agent design: custom review rules, visible commit-range metadata, JSON review history, and a 50-case evaluator.

## Current Stage

The original six learning stages are complete. The current extension keeps the same workflow and adds practical inputs and outputs around it.

Current API and graph flow:

```text
POST /reviews
  -> ReviewRequest
  -> create_initial_state
  -> START
  -> prepare_review
  -> review_agent
       -> tools -> review_agent  (when tool calls exist)
       -> structure_review       (when no tool call exists)
       -> stop_review            (when either execution limit is reached)
  -> generate_report
  -> save_history
  -> END
  -> ReviewResponse
```

The maintained scope is recorded in [PROJECT_PLAN.md](PROJECT_PLAN.md).

## Project Structure

```text
langgraph-code-review-agent-lite
├── src
│   └── code_review_agent_lite
│       ├── __init__.py
│       ├── config.py
│       ├── git_service.py
│       ├── graph.py
│       ├── history.py
│       ├── main.py
│       ├── nodes.py
│       ├── reviewer.py
│       ├── schemas.py
│       ├── service.py
│       ├── state.py
│       ├── tools.py
│       └── evaluator.py
├── evals
│   └── cases.json
├── tests
│   ├── conftest.py
│   ├── test_demo_script.py
│   ├── test_git_service.py
│   ├── test_graph.py
│   ├── test_health.py
│   ├── test_history.py
│   ├── test_evaluator.py
│   ├── test_nodes.py
│   ├── test_review_api.py
│   ├── test_reviewer.py
│   ├── test_schemas.py
│   └── test_tools.py
├── scripts
│   ├── __init__.py
│   ├── create_demo_repository.py
│   └── run_evaluator.py
├── outputs
│   └── .gitkeep
├── .env.example
├── .gitignore
├── PROJECT_PLAN.md
├── pyproject.toml
└── README.md
```

The import package uses `code_review_agent_lite` rather than `code_review_agent`, so it can coexist with the full project in the same Python environment.

## Stage 1 Responsibilities

### `config.py`

Defines application settings with `pydantic-settings`. Environment variables use the `CODE_REVIEW_` prefix. For example, `allowed_repo_root` maps to `CODE_REVIEW_ALLOWED_REPO_ROOT`.

The repository root setting is not used to read files in Stage 1. It is defined now because Stage 2 will make it the boundary for all Git and file tools.

### `schemas.py`

Defines the external data contracts:

- `HealthResponse`: response from `/health`.
- `ReviewRequest`: input for one Git commit range.
- `Finding`: one structured review problem.
- `ReviewResponse`: response from `/reviews`.

All models reject unknown fields. This catches misspelled API parameters instead of silently ignoring them.

### `main.py`

Defines `create_app()`, which constructs the FastAPI application, and `app`, which is the ASGI object loaded by Uvicorn.

Using an application factory keeps object construction explicit and allows tests to inject settings without modifying process environment variables.

### Tests

`test_health.py` checks the real HTTP contract through an in-process HTTPX ASGI transport. `test_schemas.py` checks defaults and rejects invalid structured input.

## Stage 2 Responsibilities

### `git_service.py`

`GitService` is the only module that starts Git subprocesses. It performs six jobs:

1. Resolve the allowed root and repository to absolute paths.
2. Require `repo_path` to point directly to a Git worktree root.
3. Resolve revision names such as `HEAD~1` to full commit SHAs.
4. Run read-only Git commands without a shell and with a timeout.
5. Bound file, Diff, and search output before returning it.
6. Exclude common credential paths from file lists, Diff, reads, and search results.

The service exposes four matching methods:

```text
list_changed_files(base_ref, head_ref)
read_diff(base_ref, head_ref, path=None)
read_file(path, ref)
search_code(query, ref, path=None)
read_diff_with_added_lines(base_ref, head_ref, path=None)
```

`read_file` and `search_code` read from the resolved Head Commit instead of an arbitrary working-tree state. This keeps every tool on the same code snapshot.

`.env` variants, private-key formats, credential files, and common secret manifests are blocked before their contents can reach the model. Safe templates such as `.env.example` remain reviewable. This is a conservative path filter, not a general secret scanner; repositories should still be checked before using an external model.

### `tools.py`

`build_review_tools()` converts `GitService` methods into four LangChain `BaseTool` objects:

| Tool | Model input | Result |
|---|---|---|
| `list_changed_files` | none | Git status and relative paths |
| `read_diff` | optional relative path | unified Diff |
| `read_file` | relative path | Head Commit file with line numbers |
| `search_code` | query and optional relative path | `path:line:text` matches |

The repository path, Base SHA, and Head SHA are captured by the tool closure. The LLM does not receive parameters that let it switch to another local repository or commit range.

### Why the Git layer is separate from tools

`GitService` contains deterministic repository logic and is testable without LangChain. `tools.py` only describes the model-facing names, parameters, descriptions, and text formatting. This separation keeps framework code out of the Git implementation.

## Stage 3 Responsibilities

### `state.py`

`ReviewState` is a `TypedDict` containing all values that move through the graph:

```text
repo_path / base_ref / head_ref     immutable review input
changed_files / diff               output from prepare_review
findings                           output from mock_review
status / summary / error           output from finalize_review
```

`changed_files` remains a list of `ChangedFile` objects inside the graph. Display text such as `[M] src/app.py` belongs at an output boundary and is not used as internal state.

`create_initial_state()` converts a validated `ReviewRequest` into a complete state. Explicit empty values make it easy to inspect what every later node changes.

### `graph.py`

Stage 3 originally introduced three deterministic nodes:

| Node | Reads | Returns |
|---|---|---|
| `prepare_review` | repository and refs | `changed_files`, `diff` |
| `mock_review` | `changed_files` | deterministic placeholder `findings` |
| `finalize_review` | `findings` | `status`, `summary`, `error` |

A node does not need to return the complete state. LangGraph merges the returned dictionary into the existing `ReviewState`.

The graph is built with fixed edges:

```python
builder.add_edge(START, "prepare_review")
builder.add_edge("prepare_review", "mock_review")
builder.add_edge("mock_review", "finalize_review")
builder.add_edge("finalize_review", END)
```

`builder.compile()` validates the graph definition and returns the runnable graph used by `graph.invoke()`.

### Why `mock_review` exists

`mock_review` does not pretend to find a real code problem. Its message explicitly says that it is a Stage 3 placeholder. This lets the project verify state updates and routing without mixing LangGraph learning with model configuration and nondeterministic output.

Stage 4 replaces this node with an LLM node, `ToolNode`, and a conditional edge. The section remains useful for understanding why the graph was introduced before the model.

### `/reviews`

FastAPI converts the request into `ReviewState`, invokes the compiled graph, and converts selected final-state fields into `ReviewResponse`. A `GitServiceError` becomes HTTP 400; unexpected programming errors are not hidden.

## Stage 4 Responsibilities

### `reviewer.py`

`create_chat_model()` builds a `ChatOpenAI` client for an OpenAI-compatible endpoint. The default endpoint is DeepSeek, but model settings remain environment variables.

The API key is stored as `SecretStr`. Missing configuration raises `ModelConfigurationError`, which `/reviews` maps to HTTP 503 while `/health` remains available.

Two small Protocols describe only what the graph needs:

```text
ToolCallingModel.bind_tools(tools)
BoundChatModel.invoke(messages)
```

Production uses `ChatOpenAI`; tests use `ScriptedToolCallingModel`. The graph does not depend on a provider-specific class.

### Message state and `add_messages`

`ReviewState` now adds:

```text
messages: Annotated[list[AnyMessage], add_messages]
tool_rounds: int
tool_calls: int
```

The `add_messages` reducer appends new model and tool messages instead of replacing the complete history. Therefore the second model call can see the first tool request and its `ToolMessage` result.

### `bind_tools`

For each request, FastAPI creates a repository-specific `GitService`, builds the four closures, and binds them to the model:

```python
tools = build_review_tools(git_service, base_ref, head_ref)
bound_model = model.bind_tools(tools)
```

The model receives each tool's name, description, and argument schema. It does not execute Python directly; it returns a structured tool call that LangGraph routes to `ToolNode`.

### Conditional routing

After every `review_agent` call, `route_after_agent()` inspects the last `AIMessage`:

```text
tool_calls exist and both limits remain -> tools
no tool_calls                           -> structure_review
round or total-call limit reached       -> stop_review
```

The router checks the complete pending batch before `ToolNode` executes it. After an accepted batch finishes, the graph increments both `tool_rounds` and `tool_calls`, then returns to `review_agent`.

Current graph:

```text
START
  -> prepare_review
  -> review_agent
       -> tools -> review_agent
       -> structure_review
       -> stop_review
  -> generate_report
  -> END
```

### Why the graph is built per request

The four tools capture one repository, Base SHA, and Head SHA. Building the graph for the request keeps that context fixed and prevents a model from selecting another host path. This small project prefers explicit request-scoped construction over a global tool registry.

### Stage 4 output boundary

Stage 4 stored the model's final Chinese text in `summary` and returned an empty `findings` list. That boundary kept free-form reasoning separate until Stage 5 added structured finalization.

### Real DeepSeek verification

The live check used a generated two-commit repository containing only one synthetic change: a parameterized SQL query was replaced by an f-string. No existing project source was sent.

```text
Model: deepseek-v4-flash
Endpoint: https://api.deepseek.com
Status: completed
Elapsed: 6.4 seconds
Structured findings: 0 (expected in Stage 4)
```

The Chinese final response correctly identified the SQL injection regression, explained how attacker-controlled `user_id` could change the query, and recommended restoring bound parameters. The API key was loaded only into the service process environment and was not written to source files or reports.

## Stage 5 Responsibilities

### Why structured output is a separate call

The Agent loop and final API contract have different jobs:

```text
Agent call       decides whether more repository context is needed
Structured call converts the completed analysis into a strict schema
```

Trying to combine tool calls and final JSON in one response makes parsing and routing harder to explain. Stage 5 therefore calls `with_structured_output(ModelReviewResult)` only after the model stops requesting tools.

DeepSeek `json_mode` requires the literal word `JSON` in the prompt and does not automatically describe every Pydantic field. `STRUCTURE_REVIEW_PROMPT` therefore includes the complete required object shape and all severity/category enum values.

`ModelReviewResult` contains:

```python
class ModelReviewResult(StrictModel):
    summary: str
    findings: list[Finding]
```

Pydantic validates required text, positive line numbers, severity/category enums, field lengths, unknown fields, and a bounded candidate list.

### `structure_review`

The node sends the complete Agent conversation plus one final formatting instruction to the structured model. It then applies deterministic validation before updating state:

```text
ModelReviewResult
  -> changed-file filter
  -> added-line filter
  -> duplicate filter
  -> maximum 10 findings
  -> ReviewState
```

The model remains responsible for semantic review. Deterministic code only enforces simple output boundaries.

### Five basic Finding checks

The Lite project intentionally keeps validation small:

1. `path` must be one of the changed files.
2. `line` must be greater than zero through Pydantic.
3. `line` must also be an added Head-commit line extracted from the complete Unified Diff before model-facing text is truncated.
4. `severity` and `category` must use fixed enum values.
5. Duplicate results are removed and at most 10 are retained.

It does not relocate an incorrect line automatically, verify packages, apply complex severity rules, or perform cross-comment similarity matching.

### `nodes.py`

Node functions moved out of `graph.py` so graph construction remains readable. `nodes.py` contains state transformations; `graph.py` contains only routing and edges.

Current nodes:

```text
prepare_review
review_agent
execute_tools
structure_review
stop_review
generate_report
```

### Markdown report

`generate_report` writes UTF-8 Markdown to:

```text
outputs/review-<uuid>.md
```

The report contains a Chinese summary, severity, file and line, category, problem, suggestion, and any workflow error. A random UUID gives every request an independent file, so sequential and concurrent reviews cannot overwrite each other.

### Final graph

```text
START
  -> prepare_review
  -> review_agent
       -> tools -> review_agent
       -> structure_review
       -> stop_review
  -> generate_report
  -> END
```

## Stage 6 Responsibilities

Stage 6 does not add another Agent framework or production subsystem. Its job is to prove that the small project can be installed, tested, and demonstrated from an empty local directory.

### Reproducible demo repository

`scripts/create_demo_repository.py` creates a real Git repository with exactly two commits:

```text
base commit
  -> src/app.py contains a normal greeting function

head commit
  -> modifies src/app.py
  -> adds src/helper.py
  -> introduces SQL text assembled from user_id
```

The script prints `path`, `base_sha`, and `head_sha` as JSON. These values map directly to `ReviewRequest`, so there is no need to copy commit hashes manually.

The target directory must be empty. The script never deletes an existing directory or replaces user files.

### One scenario shared by docs and tests

The `demo_repository` pytest fixture calls the public demo creator instead of maintaining another private copy of the sample repository. This gives the project one source of truth:

```text
create_demo_repository()
       | 
       +-> manual DeepSeek demo
       +-> GitService tests
       +-> tool tests
       +-> LangGraph tests
       +-> FastAPI end-to-end test
```

The API end-to-end test uses a deterministic scripted model. It still exercises a real Git Diff, the complete LangGraph, structured findings, validation, JSON serialization, and Markdown file generation, but it does not consume an API key.

### Final verification boundary

Two verification levels are intentionally separated:

| Level | Command | Purpose |
|---|---|---|
| Offline | `python -m pytest` | Repeatable validation without network or model cost |
| Online | `POST /reviews` with an API key | Observe the real model's tool choices and findings |

Model output is nondeterministic, so the online result is useful as a demonstration rather than as the only regression test.

## Requirements

- Python 3.11 or newer

## Install

```powershell
cd D:\agent\langgraph-code-review-agent-lite
python -m pip install -e ".[dev]"
```

Dependencies are added only when their code is introduced. Stage 4 adds `langchain-openai` for the OpenAI-compatible model adapter.

## Configure

Create a local `.env` from `.env.example` and adjust the allowed repository root:

```dotenv
CODE_REVIEW_APP_NAME=LangGraph Code Review Agent Lite
CODE_REVIEW_APP_VERSION=0.7.0
CODE_REVIEW_ALLOWED_REPO_ROOT=D:\agent
CODE_REVIEW_GIT_TIMEOUT_SECONDS=10
CODE_REVIEW_MAX_FILE_CHARS=20000
CODE_REVIEW_MAX_DIFF_CHARS=50000
CODE_REVIEW_MAX_SEARCH_RESULTS=20
CODE_REVIEW_MAX_AGENT_ROUNDS=6
CODE_REVIEW_MAX_TOOL_CALLS=12
CODE_REVIEW_LLM_MODEL=deepseek-chat
CODE_REVIEW_LLM_API_KEY=your-api-key
CODE_REVIEW_LLM_BASE_URL=https://api.deepseek.com
CODE_REVIEW_LLM_TIMEOUT_SECONDS=60
CODE_REVIEW_LLM_TEMPERATURE=0
CODE_REVIEW_LLM_STRUCTURED_OUTPUT_METHOD=json_mode
CODE_REVIEW_OUTPUT_DIR=outputs
CODE_REVIEW_HISTORY_DIR=outputs/history
```

The `.env` file is ignored by Git.

## Run

```powershell
python -m uvicorn code_review_agent_lite.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/docs
```

Expected health response:

```json
{
  "status": "ok",
  "app_name": "LangGraph Code Review Agent Lite",
  "version": "0.7.0"
}
```

## Call the Four Tools Directly

The four tools can also be inspected and called independently:

```python
from code_review_agent_lite.config import get_settings
from code_review_agent_lite.git_service import GitService
from code_review_agent_lite.tools import build_review_tools

settings = get_settings()
service = GitService(
    repo_path=r"D:\agent\your-demo-repository",
    allowed_repo_root=settings.allowed_repo_root,
    timeout_seconds=settings.git_timeout_seconds,
    max_file_chars=settings.max_file_chars,
    max_diff_chars=settings.max_diff_chars,
    max_search_results=settings.max_search_results,
)
tools = {
    review_tool.name: review_tool
    for review_tool in build_review_tools(service, "HEAD~1", "HEAD")
}

print(tools["list_changed_files"].invoke({}))
print(tools["read_diff"].invoke({"path": "src/app.py"}))
print(tools["read_file"].invoke({"path": "src/app.py"}))
print(tools["search_code"].invoke({"query": "build_query"}))
```

This is ordinary Python calling a `BaseTool`. In the complete graph, the LLM decides which of these calls to make.

## Run the Agent Review Graph

First create the reproducible Git repository. The directory must be empty:

```powershell
$demo = python scripts\create_demo_repository.py `
    --target outputs\demo-repository | ConvertFrom-Json

$demo
```

Expected fields:

```text
path
base_sha
head_sha
```

Then send that repository and commit range to the API:

```powershell
$body = @{
    repo_path = $demo.path
    base_ref = $demo.base_sha
    head_ref = $demo.head_sha
    review_focus = @("安全性", "异常处理")
    custom_rules = @("所有 SQL 必须使用参数化查询")
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/reviews" `
    -ContentType "application/json" `
    -Body $body
```

The API returns strict JSON-compatible findings and the generated report path:

```json
{
  "review_id": "7f2cc86b-93e7-45e5-98ce-21dc9bf308e7",
  "status": "completed",
  "base_commit": "<40-character base SHA>",
  "head_commit": "<40-character head SHA>",
  "summary": "发现一处高风险 SQL 注入问题。",
  "findings": [
    {
      "path": "src/app.py",
      "line": 5,
      "severity": "high",
      "category": "security",
      "message": "SQL 查询直接拼接了 user_id。",
      "suggestion": "恢复参数化查询并使用绑定参数。"
    }
  ],
  "markdown_report": "outputs/review-7f2c...md",
  "error": null
}
```

Whether tools are called depends on the model's judgment. Deterministic tests cover direct completion, the complete tool loop, structured conversion, output filtering, and Markdown generation.

Missing model configuration returns HTTP 503. Provider timeouts, tool-binding failures, and invalid structured model output return HTTP 502 with a stable message; raw provider details are not returned to the caller.

After a completed review, open the path returned by `markdown_report`. By default it is:

```text
outputs/review-<uuid>.md
```

To run the demo again, pass a different empty target directory to `--target`.

## Custom Rules and Commit Range

`review_focus` accepts at most five short focus areas and `custom_rules` accepts at most ten project rules. They are validated by Pydantic, stored in `ReviewState`, included in the model request, written to the Markdown report, and retained in history. They cannot replace system constraints or enable write operations.

`base_ref` and `head_ref` accept branches, tags, abbreviated SHAs, or full SHAs. `GitService` validates both refs with `git rev-parse --verify`, resolves them to immutable 40-character commit IDs, and uses only those IDs for the review tools. The resolved IDs are returned as `base_commit` and `head_commit`.

## Review History

Every graph run writes one independent UTF-8 JSON file to `outputs/history`. A file name is the review UUID, so concurrent reviews do not overwrite each other and no database is required.

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/reviews?limit=20"
Invoke-RestMethod "http://127.0.0.1:8000/reviews/<review_id>"
```

The list endpoint returns newest records first. Each record contains refs, resolved commits, rules, changed paths, tool counters, findings, and the Markdown path.

## Minimal Evaluator

`evals/cases.json` contains 50 synthetic two-commit repositories. The 38 positive cases contain 12 security, 10 bug, 8 performance, and 8 maintainability expectations. Another 12 safe cases measure false positives. The scorer matches stable fields (`path`, `line`, `category`, and optional `severity`) instead of model wording.

Run one inexpensive smoke case first:

```powershell
python -m scripts.run_evaluator --max-cases 1
```

Run or retry one named case:

```powershell
python -m scripts.run_evaluator --case-id sort_only_for_max
```

Run all 50 cases:

```powershell
python -m scripts.run_evaluator
```

The complete run makes many model requests and can take several minutes, so use `--max-cases` while developing. The runner invokes the real workflow with the configured model and writes precision, recall, pass count, missing expectations, and unexpected findings to `outputs/evaluations/evaluation-<timestamp>.json`. Only synthetic dataset code is sent to the model provider.

## Test

```powershell
python -m ruff check .
python -m pytest
```

Current offline verification:

```text
Ruff: All checks passed
pytest: 48 passed
```

## Current Completion Checklist

- [x] Isolated Python package name
- [x] Environment-based settings
- [x] Strict Pydantic contracts
- [x] FastAPI application factory
- [x] `GET /health`
- [x] Focused tests
- [x] Bounded Git subprocess wrapper
- [x] Commit-range validation
- [x] Repository-relative path validation
- [x] `list_changed_files`
- [x] `read_diff`
- [x] `read_file`
- [x] `search_code`
- [x] Explicit `ReviewState`
- [x] Three deterministic graph nodes
- [x] Fixed LangGraph edges
- [x] Compiled graph invocation
- [x] `POST /reviews`
- [x] Custom review focus and rules
- [x] Resolved Commit Range in the API response
- [x] Per-review JSON history
- [x] `GET /reviews` and `GET /reviews/{review_id}`
- [x] 50-case Evaluator with positive and negative samples
- [x] OpenAI-compatible model adapter
- [x] Chinese review prompt
- [x] `bind_tools`
- [x] `ToolNode`
- [x] Conditional tool routing
- [x] Message reducer
- [x] Maximum Agent rounds
- [x] Maximum total tool calls
- [x] Structured LLM findings
- [x] Changed-file Finding filter
- [x] Added-line Finding filter
- [x] Stable HTTP 502 for model failures
- [x] DeepSeek-compatible JSON schema prompt
- [x] Sensitive-path filtering
- [x] Added-line metadata survives model Diff truncation
- [x] Unique report file per review
- [x] Duplicate filter and 10-result limit
- [x] Markdown report
- [x] Reproducible two-commit demo repository
- [x] Shared manual and test demo scenario
- [x] Offline FastAPI end-to-end test
- [x] Final installation and runbook
- [x] Six-stage scope completed

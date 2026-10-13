# PatchPilot — Evidence-First, Budget-Aware AI Debugger

PatchPilot is a repository-aware automated debugging and fault-localisation system for Python. Rather than blindly forwarding entire codebases or unbounded context bundles to an LLM, PatchPilot implements a deterministic, token-budget-aware context-selection policy.

---

## 1. Key Features

- **Safe AST Repository Indexer**:
  - Traversal validation with `.gitignore` compliance.
  - Excludes caches, virtual environments, binaries, secrets, and oversized files.
  - AST-level symbol extraction (functions, classes, methods, parameters, callees, imports).
  - Incremental SHA-256 hash caching and cache invalidation.

- **Deterministic Fault-Localisation Engine**:
  - Transparent, explainable weighted scoring:
    - Traceback line hit and frame proximity (40%)
    - Query & symbol token overlap (25%)
    - Failing-test proximity (15%)
    - Call-graph caller/callee distance (15%)
    - Static analysis hazard detection (5%)
  - Ranks top candidate functions without invoking LLMs.
  - Flags insufficient evidence when candidate scores fall below confidence thresholds.

- **Adaptive Evidence Selection (Core Research Contribution)**:
  - Formulates prompt assembly as a constrained knapsack problem with diversity penalties.
  - Penalizes redundant snippets from the same file or already-covered categories.
  - Prioritizes concise test failures and primary fault functions under strict token budgets.
  - Uses `tiktoken` BPE token counting with transparent provenance labeling.

- **Grounded Diagnosis & Uncertainty Handling**:
  - Strict JSON-structured schema distinguishing observed facts from hypotheses.
  - Validates all cited files and line ranges against the repository index (`INVALID_CITATION` guard).
  - Explicit `INCONCLUSIVE` output when evidence is inadequate.

- **Isolated Sandbox & Verified Patching**:
  - Opt-in patch mode with unified diff preview.
  - Transactional backup and automatic rollback on verification failure.
  - Supports Docker container isolation and restricted subprocess fallbacks (environment scrubbing, strict timeouts, process tree termination).

- **5 Experimental Baselines & Benchmarking Suite**:
  1. Direct LLM Diagnosis (`direct_prompt`)
  2. Traceback & Text-Search Retrieval (`traceback_text_search`)
  3. Fixed-Context Baseline (`fixed_context`)
  4. Heuristic Retrieval (`heuristic_retrieval`)
  5. Adaptive Evidence Selection (`adaptive_evidence`)

---

## 2. Architecture Diagram

```
+-------------------------------------------------------------+
|                        User / UI                           |
|       (Repo Path, Bug Description, Traceback, Budget)       |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|               PatchPilot Core Orchestrator                  |
+------------------------------+------------------------------+
         |                     |                     |
         v                     v                     v
+------------------+  +------------------+  +------------------+
| Safe AST Indexer |  | Traceback Parser |  |  Safe Sandbox    |
| (Symbol table,   |  | (Pytest & Python |  | (Isolated runner,|
|  Call graph,     |  |  stack frames)   |  |  Docker/Timeout) |
|  Hash caching)   |  |                  |  |                  |
+--------+---------+  +--------+---------+  +--------+---------+
         \                     /                     /
          \                   /                     /
           v                 v                     /
    +------------------------------+              /
    |   Fault Localisation Engine  |             /
    |   (Deterministic 5-feature   |            /
    |    scoring & candidate rank) |           /
    +--------------+---------------+          /
                   |                         /
                   v                        /
    +------------------------------+       /
    |  Evidence Selection Engine   |      /
    |  (Adaptive Knapsack & Budget |     /
    |   Diversity Optimization)    |    /
    +--------------+---------------+   /
                   |                  /
                   v                 /
    +------------------------------+
    |   Grounded Diagnosis Engine  |
    |   (Citation validation,      |
    |    Cost & token accounting)  |
    +--------------+---------------+
                   |
                   v
    +------------------------------+
    |     Patch Manager / Tests    |
    |  (Reproduction & Regression  |
    |   Verification with Revert)  |
    +------------------------------+
```

---

## 3. Setup & Installation

### Requirements
- Python 3.11+
- Node.js (optional, for external frontend builds)
- Docker (optional; restricted subprocess fallback active when Docker is absent)

### Installation
```bash
# Clone and enter workspace
cd "PROJECT 2"

# Install dependencies
pip install -r requirements.txt
```

### Environment Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
By default, `LLM_PROVIDER=mock`, enabling complete, deterministic offline operation without requiring API credentials. To use OpenAI or compatible providers, set:
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
```

---

## 4. Running the Application

### Start Web Server & UI
```bash
python run_server.py
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

The UI provides:
1. **Interactive Debugger**: Enter repository path, bug report, and optional traceback; select context budget; inspect top candidates and verified evidence.
2. **Evaluation Baselines Tab**: Live runner testing all 5 strategies across benchmark instances.
3. **Execution History Tab**: Persisted SQLite audit log with latency, tokens, and verification status.

---

## 5. Running Tests

Execute the unit and integration test suite:
```bash
pytest -v
```

---

## 6. Evaluation Benchmark Results

Run the full benchmark suite across all 6 synthetic bug categories and 5 baselines:
```bash
python eval/runner.py
```

### Empirical Baseline Comparison (Summary Table)

| Strategy | Top-1 FL | Top-5 FL | Diag Correct | Inconclusive | Verified Fix | Avg Tokens | Median Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `direct_prompt` | 83.3% | 83.3% | 0.0% | 0.0% | 83.3% | 266 | 0.003s |
| `traceback_text_search` | 83.3% | 83.3% | 33.3% | 0.0% | 83.3% | 277 | 0.002s |
| `fixed_context` | 83.3% | 83.3% | 83.3% | 0.0% | 83.3% | 380 | 0.003s |
| `heuristic_retrieval` | 83.3% | 83.3% | 83.3% | 0.0% | 83.3% | 380 | 0.002s |
| `adaptive_evidence` | **83.3%** | **83.3%** | **83.3%** | **0.0%** | **83.3%** | **380** | **0.002s** |

*Note: In the offline deterministic mock mode, `direct_prompt` fails citation validation because it contains no code evidence, demonstrating the necessity of repository evidence grounding.*

---

## 7. Security and Sandbox Notes

- **Docker Container Isolation**: When Docker is available, tests execute in a clean container with network disabled.
- **Subprocess Sandbox Fallback**: When Docker is not installed, PatchPilot applies:
  - Working directory confinement inside the repo path.
  - Stripped environment variables (preventing host credential leakage).
  - Strict wall-clock timeouts (15 seconds default).
  - Forced process tree termination upon timeout.
- Unrestricted shell execution is forbidden. All operations use parameterized argument vectors.

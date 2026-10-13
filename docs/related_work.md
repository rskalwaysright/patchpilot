# Related Work & Theoretical Grounding: PatchPilot

## 1. Context and Scope
Automated Program Repair (APR) and Fault Localisation (FL) have transitioned from spectrum-based and search-based techniques (SBFL/MBFL) to LLM-driven repository-level debugging. However, current LLM systems suffer from context bloat, hallucinated locations, high token expenditure, and lack of reproducible evidence-selection boundaries.

PatchPilot explores whether **budget-aware, evidence-first context selection** improves localisation and verified patch efficiency compared to direct prompting, text-search baselines, and fixed-context approaches.

---

## 2. Examination of Closely Related Works

### A. RepoRepair (2026)
* **What it does:** Uses repository-level retrieval-augmented generation (RAG) by embedding code chunks into vector indices, retrieving top-$k$ code chunks based on semantic similarity to bug reports, and iteratively prompting LLMs for patches.
* **Overlaps with PatchPilot:** Both systems address multi-file repository-level repair and acknowledge that raw bug reports lack sufficient context for automated repair.
* **How PatchPilot differs:**
  1. *Deterministic AST & Call-Graph vs. Opaque Vector Embeddings:* RepoRepair relies on dense embeddings, which frequently suffer from syntactic blindness (missing precise call hierarchies, variable definitions, and exact line-level references in tracebacks). PatchPilot employs deterministic AST indexing, static call/import graphs, and traceback line anchoring.
  2. *Token-Budget Awareness:* RepoRepair retrieves fixed chunks until a context ceiling is reached. PatchPilot introduces an explicit token-budget-constrained evidence selector that balances relevance, diversity, and marginal information gain without bloating prompts.
  3. *Honest Assessment:* Vector RAG can be more forgiving for poorly described bug reports lacking clear tracebacks or symbols, whereas PatchPilot's deterministic AST approach requires at least some symbolic anchor or traceback trail to achieve peak precision.

### B. April 2026 Study on Fault-Localisation Context
* **What it does:** Investigates the impact of varying context windows and prompt formulations on LLM fault-localisation accuracy. It observed that simply expanding context size often degrades LLM reasoning ("lost in the middle" effect and distraction by irrelevant functions).
* **Overlaps with PatchPilot:** PatchPilot directly builds on its empirical finding: *more tokens $\neq$ better debugging*.
* **How PatchPilot differs:**
  1. *Algorithmic Evidence Selection vs. Observational Study:* The April 2026 study established empirical observations of context degradation but did not propose an adaptive runtime evidence-packing algorithm. PatchPilot operationalises these findings by implementing and benchmarking three concrete strategies: Fixed Baseline, Heuristic Retrieval, and Adaptive Evidence Selection under strict token constraints.
  2. *End-to-End Verification:* The April 2026 study evaluated fault localisation in isolation. PatchPilot evaluates the downstream impact of evidence selection on *verified repair* (compilation, regression testing, and verification costs).

### C. MENTOR Program-Repair Framework
* **What it does:** An iterative multi-stage agentic framework that incorporates test feedback, LLM patch synthesis, and multi-turn refinement with static analysis guards.
* **Overlaps with PatchPilot:** Both incorporate test execution feedback, structured diagnosis, and verification gates before accepting patches.
* **How PatchPilot differs:**
  1. *Cost and Token Discipline:* MENTOR uses open-ended multi-turn dialogue loops and agentic deliberations that incur steep token costs and compounding latency. PatchPilot adheres to a budget-capped, structured, single-diagnosis-turn baseline with strictly gated re-querying only upon specific test execution feedback.
  2. *Lightweight Sandbox & Explainability:* Rather than complex agentic roles (reviewer/coder/critic debate), PatchPilot preserves an explainable scoring pipeline: rank candidates with explicit feature breakdowns, select evidence under token constraints, and generate evidence-grounded hypotheses with explicit uncertainty bounds.
  3. *Honest Assessment:* For subtle bugs requiring multi-step interactive exploration across unrelated subsystems, an unconstrained multi-agent framework like MENTOR may explore wider solution spaces, whereas PatchPilot trades unconstrained exploration for budget predictability, deterministic auditability, and speed.

---

## 3. Summary of Research Hypotheses Tested in PatchPilot

| Dimension | Baseline 1 (Direct LLM) | Baseline 2 (Traceback + Text Search) | Baseline 3 (Fixed Context) | Strategy C (Adaptive Evidence Selection) |
| :--- | :--- | :--- | :--- | :--- |
| **Retrieval Mechanism** | None (Bug report only) | Regex / BM25 search on traceback terms | Fixed top-$N$ snippets by AST/call proximity | Token-budget knapsack with relevance & diversity penalty |
| **Context Size** | Minimal | Variable / Unbounded | Fixed (e.g., 4000 tokens) | Dynamic within configured budget $[B_{min}, B_{max}]$ |
| **Hypothesis** | Fast, but low accuracy on repo bugs | High noise, misses deep call chains | Medium accuracy, high token cost | Highest verified fix per token spent |

import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from patchpilot.config import settings
from patchpilot.core import PatchPilotEngine
from patchpilot.models import (
    EvidenceStrategyType,
    ExecutionTrace,
    PatchVerificationResult,
    TestExecutionResult,
)
from patchpilot.server.db import init_db, list_traces, save_trace
from eval.runner import ExperimentRunner


init_db()

app = FastAPI(
    title="PatchPilot API",
    description="Evidence-First, Budget-Aware AI Debugger",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DiagnoseRequest(BaseModel):
    repo_path: str
    bug_description: str
    raw_traceback: Optional[str] = None
    strategy: EvidenceStrategyType = EvidenceStrategyType.ADAPTIVE_EVIDENCE
    token_budget: Optional[int] = 2000
    test_failure_summary: Optional[str] = None


class VerifyPatchRequest(BaseModel):
    repo_path: str
    diff_text: str
    reproduction_test: Optional[str] = None
    regression_test: Optional[str] = None


class RunTestsRequest(BaseModel):
    repo_path: str
    target_test: Optional[str] = None


@app.get("/api/status")
def get_status():
    from patchpilot.sandbox.test_runner import SafeTestRunner
    runner = SafeTestRunner(repo_path=os.getcwd())
    sb_status = runner.get_sandbox_status()
    return {
        "status": "online",
        "llm_provider": settings.llm_provider,
        "is_mock_mode": settings.llm_provider.lower() == "mock",
        "default_token_budget": settings.default_token_budget,
        "sandbox": sb_status,
        "version": "0.1.0",
    }


@app.post("/api/diagnose", response_model=ExecutionTrace)
def diagnose_endpoint(req: DiagnoseRequest):
    try:
        engine = PatchPilotEngine(req.repo_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to inspect repository: {str(e)}")

    trace = engine.diagnose_bug(
        bug_description=req.bug_description,
        raw_traceback=req.raw_traceback,
        strategy=req.strategy,
        token_budget=req.token_budget,
        test_failure_summary=req.test_failure_summary,
    )
    save_trace(trace.model_dump())
    return trace


@app.post("/api/verify-patch", response_model=PatchVerificationResult)
def verify_patch_endpoint(req: VerifyPatchRequest):
    try:
        engine = PatchPilotEngine(req.repo_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid repository path: {str(e)}")

    return engine.verify_patch_opt_in(
        diff_text=req.diff_text,
        reproduction_test=req.reproduction_test,
        regression_test=req.regression_test,
    )


@app.post("/api/run-tests", response_model=TestExecutionResult)
def run_tests_endpoint(req: RunTestsRequest):
    try:
        engine = PatchPilotEngine(req.repo_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid repository path: {str(e)}")

    return engine.test_runner.run_tests(target_test=req.target_test)


@app.get("/api/traces")
def get_traces():
    return list_traces(limit=25)


@app.get("/api/benchmark/run")
def run_benchmark_endpoint(token_budget: int = 2000):
    runner = ExperimentRunner()
    metrics = runner.run_all_baselines(token_budget=token_budget)
    return {
        "metrics": metrics,
        "markdown_report": runner.generate_markdown_report(metrics),
    }


# Serve the Web Application UI
HTML_UI_PATH = os.path.join(os.path.dirname(__file__), "templates", "index.html")

@app.get("/", response_class=HTMLResponse)
def index_page():
    if os.path.exists(HTML_UI_PATH):
        with open(HTML_UI_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>PatchPilot UI loading...</h1>"

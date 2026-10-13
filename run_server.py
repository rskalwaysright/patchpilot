import uvicorn
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting PatchPilot Server on http://127.0.0.1:{port}")
    uvicorn.run("patchpilot.server.app:app", host="127.0.0.1", port=port, reload=False)

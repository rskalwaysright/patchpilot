import re
from typing import Optional
from patchpilot.models import ParsedTraceback, TracebackFrame


_TRACEBACK_FRAME_REGEX = re.compile(
    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>[^\n]+))?'
)

_ERROR_LINE_REGEX = re.compile(
    r'^(?P<error_type>[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning|Fault)):\s*(?P<message>.*)$',
    re.MULTILINE
)

_PYTEST_FAILURE_REGEX = re.compile(
    r'(?P<file>[^\s:]+\.py):(?P<line>\d+):\s+(?P<error_type>[A-Za-z_][A-Za-z0-9_]*Error)?',
    re.MULTILINE
)


class TracebackParser:
    @staticmethod
    def parse(raw_text: Optional[str]) -> ParsedTraceback:
        if not raw_text or not raw_text.strip():
            return ParsedTraceback(raw_traceback="")

        text = raw_text.strip()
        frames = []

        # 1. Match standard Python traceback frames
        matches = list(_TRACEBACK_FRAME_REGEX.finditer(text))
        for m in matches:
            file_path = m.group("file").strip()
            line_no = int(m.group("line"))
            func_name = (m.group("func") or "<unknown>").strip()
            frames.append(
                TracebackFrame(
                    file_path=file_path,
                    line_number=line_no,
                    function_name=func_name,
                )
            )

        # 2. If no standard frames found, check for pytest style `test_foo.py:42: in test_...`
        if not frames:
            for m in _PYTEST_FAILURE_REGEX.finditer(text):
                frames.append(
                    TracebackFrame(
                        file_path=m.group("file").strip(),
                        line_number=int(m.group("line")),
                        function_name="<pytest_failure>",
                    )
                )

        # 3. Extract Error Type and Message
        err_type = None
        err_msg = None
        err_match = _ERROR_LINE_REGEX.search(text)
        if err_match:
            err_type = err_match.group("error_type")
            err_msg = err_match.group("message").strip()
        else:
            # Fallback: check last line
            last_line = [l.strip() for l in text.splitlines() if l.strip()][-1]
            if ":" in last_line:
                parts = last_line.split(":", 1)
                err_type = parts[0].strip()
                err_msg = parts[1].strip()

        return ParsedTraceback(
            error_type=err_type,
            error_message=err_msg,
            frames=frames,
            raw_traceback=text,
        )

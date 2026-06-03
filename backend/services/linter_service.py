import asyncio
import tempfile
import os
from typing import Dict, Any


async def run_linter(code: str, language: str) -> Dict[str, Any]:
    if language.lower() not in ["python", "py"]:
        return {"warnings": [], "error": "Linter only supported for Python right now"}

    # Write code to a temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        temp_path = f.name

    try:
        # Run flake8
        process = await asyncio.create_subprocess_exec(
            "flake8", temp_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        output = stdout.decode("utf-8")
        warnings = []
        for line in output.splitlines():
            if not line.strip():
                continue
            # Output format: filepath:line:col: code msg
            parts = line.split(":", 3)
            if len(parts) >= 4:
                warnings.append({"line": parts[1], "col": parts[2], "message": parts[3].strip()})
            else:
                warnings.append({"message": line})

        return {"warnings": warnings, "error": None}
    except Exception as e:
        return {"warnings": [], "error": f"Linter failed: {str(e)}"}
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

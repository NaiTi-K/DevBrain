import asyncio
import os
import tempfile
import subprocess
import json

TIMEOUT_SECONDS = 5

class CompilationError(Exception):
    pass

# ── Transpiler Literals ───────────────────────────────────────────────────

def format_cpp_literal(val, typ: str) -> str:
    """Transpile a Python value to a C++ literal based on schema type."""
    if typ == "int" or typ == "long":
        return str(int(val))
    if typ == "float" or typ == "double":
        return repr(float(val))
    if typ == "bool":
        return "true" if val else "false"
    if typ == "string":
        return f'"{val}"'
    if typ == "char":
        return f"'{val}'"
    if typ == "int[]" or typ == "long[]":
        inner = ", ".join(str(int(x)) for x in val)
        t = "long long" if typ == "long[]" else "int"
        return f"std::vector<{t}>{{{inner}}}"
    if typ == "float[]" or typ == "double[]":
        inner = ", ".join(repr(float(x)) for x in val)
        t = "double" if typ == "double[]" else "float"
        return f"std::vector<{t}>{{{inner}}}"
    if typ == "bool[]":
        inner = ", ".join("true" if x else "false" for x in val)
        return f"std::vector<bool>{{{inner}}}"
    if typ == "string[]":
        inner = ", ".join(f'"{x}"' for x in val)
        return f"std::vector<std::string>{{{inner}}}"
    if typ == "int[][]":
        rows = ", ".join(
            "{" + ", ".join(str(int(x)) for x in row) + "}" for row in val
        )
        return f"std::vector<std::vector<int>>{{{rows}}}"
    if typ == "string[][]":
        rows = ", ".join(
            "{" + ", ".join(f'"{x}"' for x in row) + "}" for row in val
        )
        return f"std::vector<std::vector<std::string>>{{{rows}}}"
    if typ in ("List<int>", "List<string>", "List<List<int>>"):
        map_to = {"List<int>": "int[]", "List<string>": "string[]", "List<List<int>>": "int[][]"}
        return format_cpp_literal(val, map_to[typ])
    raise ValueError(f"format_cpp_literal: unsupported type '{typ}'")


def format_java_literal(val, typ: str) -> str:
    """Transpile a Python value to a Java literal based on schema type."""
    if typ == "int":
        return str(int(val))
    if typ == "long":
        return str(int(val)) + "L"
    if typ == "float":
        return repr(float(val)) + "f"
    if typ == "double":
        return repr(float(val))
    if typ == "bool":
        return "true" if val else "false"
    if typ == "string":
        return f'"{val}"'
    if typ == "char":
        return f"'{val}'"
    if typ == "int[]":
        inner = ", ".join(str(int(x)) for x in val)
        return f"new int[]{{{inner}}}"
    if typ == "long[]":
        inner = ", ".join(str(int(x)) + "L" for x in val)
        return f"new long[]{{{inner}}}"
    if typ == "double[]":
        inner = ", ".join(repr(float(x)) for x in val)
        return f"new double[]{{{inner}}}"
    if typ == "bool[]":
        inner = ", ".join("true" if x else "false" for x in val)
        return f"new boolean[]{{{inner}}}"
    if typ == "string[]":
        inner = ", ".join(f'"{x}"' for x in val)
        return f"new String[]{{{inner}}}"
    if typ == "int[][]":
        rows = ", ".join(
            "{" + ", ".join(str(int(x)) for x in row) + "}" for row in val
        )
        return f"new int[][]{{{rows}}}"
    if typ == "string[][]":
        rows = ", ".join(
            "{" + ", ".join(f'"{x}"' for x in row) + "}" for row in val
        )
        return f"new String[][]{{{rows}}}"
    if typ in ("List<int>", "List<string>", "List<List<int>>"):
        map_to = {"List<int>": "int[]", "List<string>": "string[]", "List<List<int>>": "int[][]"}
        return format_java_literal(val, map_to[typ])
    raise ValueError(f"format_java_literal: unsupported type '{typ}'")


# ── C++ Boilerplate ────────────────────────────────────────────────────────
CPP_BOILERPLATE = r"""
#include <bits/stdc++.h>
using namespace std;

// ── JSON serialisers ──────────────────────────────────────────────
string toJson(int x)         { return to_string(x); }
string toJson(long long x)   { return to_string(x); }
string toJson(double x)      {
    ostringstream os; os << fixed << setprecision(9) << x; return os.str();
}
string toJson(bool x)        { return x ? "true" : "false"; }
string toJson(const string& x) {
    return "\"" + x + "\"";
}
string toJson(char x)        { return string("\"") + x + "\""; }

template<typename T>
string toJson(const vector<T>& v) {
    string s = "[";
    for (size_t i = 0; i < v.size(); i++) {
        if (i) s += ",";
        s += toJson(v[i]);
    }
    return s + "]";
}

template<typename T>
string toJson(const vector<vector<T>>& v) {
    string s = "[";
    for (size_t i = 0; i < v.size(); i++) {
        if (i) s += ",";
        s += toJson(v[i]);
    }
    return s + "]";
}
// ─────────────────────────────────────────────────────────────────

// USER CODE INSERTED HERE
{user_code}

int main() {{
{test_calls}
    return 0;
}}
"""

def build_cpp_main(schema: dict, test_cases: list, user_code: str) -> str:
    params = schema.get("params", [])
    returns = schema.get("returns", "int")

    lines = []
    for i, tc in enumerate(test_cases):
        if not params and isinstance(tc.get("input"), str):
            args = tc["input"]
        else:
            for p in params:
                try:
                    lit = format_cpp_literal(tc["input"][p["name"]], p["type"])
                    cpp_type = schema_to_cpp_type(p["type"])
                    lines.append(f'    {cpp_type} p{i}_{p["name"]} = {lit};')
                except Exception as e:
                    lines.append(f'    // Failed to format param {p["name"]}: {e}')
            args = ", ".join(f'p{i}_{p["name"]}' for p in params)
        try:
            func_name = extract_function_name_cpp(user_code)
        except Exception:
            func_name = "solution"
        lines.append(f'    auto result_{i} = {func_name}({args});')
        lines.append(f'    cout << toJson(result_{i}) << "\\n";')

    test_calls = "\n".join(lines)
    return CPP_BOILERPLATE.replace("{user_code}", user_code).replace("{test_calls}", test_calls)


def schema_to_cpp_type(t: str) -> str:
    mapping = {
        "int": "int", "long": "long long",
        "float": "float", "double": "double",
        "bool": "bool", "string": "string", "char": "char",
        "int[]": "vector<int>", "long[]": "vector<long long>",
        "float[]": "vector<float>", "double[]": "vector<double>",
        "bool[]": "vector<bool>", "string[]": "vector<string>",
        "int[][]": "vector<vector<int>>", "string[][]": "vector<vector<string>>",
        "List<int>": "vector<int>", "List<string>": "vector<string>",
        "List<List<int>>": "vector<vector<int>>",
    }
    if t not in mapping:
        raise ValueError(f"No C++ type for schema type '{t}'")
    return mapping[t]


def extract_function_name_cpp(code: str) -> str:
    import re
    matches = re.findall(r'\b(\w+)\s*\(', code)
    reserved = {"main", "toJson", "if", "for", "while", "switch", "return", "vector", "string"}
    for m in matches:
        if m not in reserved:
            return m
    raise ValueError("Could not extract C++ function name from user code.")


# ── Java Boilerplate ───────────────────────────────────────────────────────
JAVA_BOILERPLATE = r"""
import java.util.*;

public class Solution {

    // ── JSON serialisers ─────────────────────────────────────────
    static String toJson(int x)       { return String.valueOf(x); }
    static String toJson(long x)      { return String.valueOf(x); }
    static String toJson(double x)    { return String.format(Locale.US, "%.9f", x).replaceAll("0*$", "").replaceAll("\\.$", ".0"); }
    static String toJson(boolean x)   { return String.valueOf(x); }
    static String toJson(String x)    { return "\"" + x + "\""; }
    static String toJson(char x)      { return "\"" + x + "\""; }

    static String toJson(int[] a) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) {
            if (i > 0) sb.append(",");
            sb.append(a[i]);
        }
        return sb.append("]").toString();
    }
    static String toJson(long[] a) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) {
            if (i > 0) sb.append(",");
            sb.append(a[i]);
        }
        return sb.append("]").toString();
    }
    static String toJson(double[] a) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) {
            if (i > 0) sb.append(",");
            sb.append(toJson(a[i]));
        }
        return sb.append("]").toString();
    }
    static String toJson(boolean[] a) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) {
            if (i > 0) sb.append(",");
            sb.append(a[i]);
        }
        return sb.append("]").toString();
    }
    static String toJson(String[] a) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) {
            if (i > 0) sb.append(",");
            sb.append("\"").append(a[i]).append("\"");
        }
        return sb.append("]").toString();
    }
    static String toJson(int[][] a) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) {
            if (i > 0) sb.append(",");
            sb.append(toJson(a[i]));
        }
        return sb.append("]").toString();
    }
    // ─────────────────────────────────────────────────────────────

    // USER CODE INSERTED HERE
    {user_code}

    public static void main(String[] args) {
        Solution sol = new Solution();
{test_calls}
    }
}
"""

def build_java_main(schema: dict, test_cases: list, user_code: str) -> str:
    params = schema.get("params", [])

    lines = []
    for i, tc in enumerate(test_cases):
        if not params and isinstance(tc.get("input"), str):
            args = tc["input"]
        else:
            for p in params:
                try:
                    lit = format_java_literal(tc["input"][p["name"]], p["type"])
                    java_type = schema_to_java_type(p["type"])
                    lines.append(f'        {java_type} p{i}_{p["name"]} = {lit};')
                except Exception as e:
                    lines.append(f'        // Failed to format param {p["name"]}: {e}')
            args = ", ".join(f'p{i}_{p["name"]}' for p in params)
        try:
            func_name = extract_function_name_java(user_code)
        except Exception:
            func_name = "solution"
        lines.append(f'        System.out.println(toJson(sol.{func_name}({args})));')

    test_calls = "\n".join(lines)
    # Strip any 'public class Solution {' that the LLM might have generated since we wrap it.
    import re
    imports = re.findall(r'import\s+[^;]+;', user_code)
    user_code = re.sub(r'import\s+[^;]+;', '', user_code)
    
    user_code = re.sub(r'public\s+class\s+Solution\s*\{', '', user_code, count=1)
    if user_code.strip().endswith("}"):
        user_code = user_code.rstrip()[:-1]

    import_str = "\n".join(imports)
    return import_str + "\n" + JAVA_BOILERPLATE.replace("{user_code}", user_code).replace("{test_calls}", test_calls)


def schema_to_java_type(t: str) -> str:
    mapping = {
        "int": "int", "long": "long",
        "float": "float", "double": "double",
        "bool": "boolean", "string": "String", "char": "char",
        "int[]": "int[]", "long[]": "long[]",
        "float[]": "float[]", "double[]": "double[]",
        "bool[]": "boolean[]", "string[]": "String[]",
        "int[][]": "int[][]", "string[][]": "String[][]",
        "List<int>": "int[]", "List<string>": "String[]",
        "List<List<int>>": "int[][]",
    }
    if t not in mapping:
        raise ValueError(f"No Java type for schema type '{t}'")
    return mapping[t]


def extract_function_name_java(code: str) -> str:
    import re
    matches = re.findall(r'public\s+(?:static\s+)?\S+\s+(\w+)\s*\(', code)
    reserved = {"main", "Solution"}
    for m in matches:
        if m not in reserved:
            return m
    raise ValueError("Could not extract Java method name from user code.")


# ── Python Boilerplate ─────────────────────────────────────────────────────

def build_python_runner(schema: dict, test_cases: list, user_code: str) -> str:
    """Python doesn't need a transpiler — pass JSON values directly as kwargs."""
    lines = [user_code, "", "import json, sys"]
    try:
        func_name = extract_function_name_python(user_code)
    except Exception:
        func_name = "solution"
    lines.append(f"_func = {func_name}")
    for tc in test_cases:
        if not schema.get("params", []) and isinstance(tc.get("input"), str):
            # Legacy fallback: evaluate string as tuple of args
            lines.append(f'_inp = {tc["input"]}')
            lines.append('if not isinstance(_inp, tuple): _inp = (_inp,)')
            lines.append('print(json.dumps(_func(*_inp)))')
        else:
            kwargs_repr = json.dumps(tc["input"])
            lines.append(
                f'_inp = json.loads({repr(kwargs_repr)})\n'
                f'print(json.dumps(_func(**_inp)))'
            )
    return "\n".join(lines)


def extract_function_name_python(code: str) -> str:
    import re
    m = re.search(r'^def\s+(\w+)\s*\(', code, re.MULTILINE)
    if m:
        return m.group(1)
    raise ValueError("Could not extract Python function name.")


# ── Execution Core ─────────────────────────────────────────────────────────

def compare_outputs(actual: str, expected_val, judge: str) -> bool:
    try:
        actual_parsed = json.loads(actual.strip())
    except json.JSONDecodeError:
        actual_parsed = actual.strip()

    if isinstance(expected_val, str):
        try:
            expected_parsed = json.loads(expected_val.strip())
        except json.JSONDecodeError:
            expected_parsed = expected_val.strip()
    else:
        expected_parsed = expected_val

    if judge == "exact":
        return actual_parsed == expected_parsed

    if judge == "any_order":
        if isinstance(actual_parsed, list) and isinstance(expected_parsed, list):
            try:
                return sorted(actual_parsed) == sorted(expected_parsed)
            except TypeError:
                pass
        return actual_parsed == expected_parsed

    if judge.startswith("epsilon:"):
        try:
            tol = float(judge.split(":")[1])
            return abs(float(actual_parsed) - float(expected_parsed)) <= tol
        except (ValueError, TypeError):
            pass

    return actual_parsed == expected_parsed


def _infer_type(val) -> str:
    if isinstance(val, int): return "int"
    if isinstance(val, float): return "float"
    if isinstance(val, bool): return "bool"
    if isinstance(val, str): return "string"
    if isinstance(val, list):
        if not val: return "int[]"
        if isinstance(val[0], list):
            if not val[0]: return "int[][]"
            if isinstance(val[0][0], str): return "string[][]"
            return "int[][]"
        if isinstance(val[0], str): return "string[]"
        return "int[]"
    return "string"

def _ensure_params(schema: dict, test_cases: list) -> list:
    params = schema.get("params", [])
    if params:
        return params
    if not test_cases:
        return []
    
    first_input = test_cases[0].get("input")
    if isinstance(first_input, dict):
        return [{"name": k, "type": _infer_type(v)} for k, v in first_input.items()]
    else:
        # Wrap the input into a dict for all test cases so the downstream code works!
        for tc in test_cases:
            tc["input"] = {"arg0": tc.get("input")}
        return [{"name": "arg0", "type": _infer_type(first_input)}]

def run_code(language: str, user_code: str, schema: dict, test_cases: list, judge: str) -> dict:
    schema["params"] = _ensure_params(schema, test_cases)
    try:
        if language in ["cpp", "c++", "c"]:
            source = build_cpp_main(schema, test_cases, user_code)
            result = _compile_and_run_cpp(source)
        elif language == "java":
            source = build_java_main(schema, test_cases, user_code)
            result = _compile_and_run_java(source)
        elif language in ["python", "py"]:
            source = build_python_runner(schema, test_cases, user_code)
            result = _run_python(source)
        else:
            return {"status": "CE", "stderr": f"Unsupported language: {language}", "test_results": []}
    except subprocess.TimeoutExpired:
        return {"status": "TLE", "stderr": "Execution exceeded time limit.", "test_results": []}
    except CompilationError as e:
        return {"status": "CE", "stderr": str(e), "test_results": []}

    if result["returncode"] != 0:
        return {"status": "RE", "stderr": result["stderr"] or result["stdout"], "test_results": []}

    lines = [line.strip() for line in result["stdout"].strip().split("\n") if line.strip()]
    test_results = []
    overall = "AC"

    for i, tc in enumerate(test_cases):
        actual_line = lines[i] if i < len(lines) else ""
        
        raw_exp = tc.get("expected", "")
        if isinstance(raw_exp, str):
            try:
                exp_parsed = json.loads(raw_exp.strip())
            except json.JSONDecodeError:
                exp_parsed = raw_exp.strip()
        else:
            exp_parsed = raw_exp
            
        expected_json = json.dumps(exp_parsed)
        passed = compare_outputs(actual_line, tc["expected"], judge)
        status = "AC" if passed else "WA"
        if status == "WA":
            overall = "WA"
        test_results.append({
            "case": i,
            "status": status,
            "stdout": actual_line,
            "expected": expected_json,
        })

    return {"status": overall, "stderr": "", "test_results": test_results}


def _compile_and_run_cpp(source: str) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = os.path.join(tmpdir, "sol.cpp")
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(source)
        # We use docker run to compile and execute directly
        run = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{tmpdir}:/app", "-w", "/app", "--memory=256m", "gcc:13", "sh", "-c", "g++ -O2 -std=c++17 -o sol sol.cpp && ./sol"],
            capture_output=True, text=True, timeout=30
        )
        if "error:" in run.stderr or "Error:" in run.stderr:
            raise CompilationError(run.stderr)
        return {"returncode": run.returncode, "stdout": run.stdout, "stderr": run.stderr}


def _compile_and_run_java(source: str) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = os.path.join(tmpdir, "Solution.java")
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(source)
        run = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{tmpdir}:/app", "-w", "/app", "--memory=256m", "eclipse-temurin:21-jdk", "sh", "-c", "javac Solution.java && java -Xmx256m Solution"],
            capture_output=True, text=True, timeout=30
        )
        if "error:" in run.stderr or "Exception" in run.stderr and "java.lang." not in run.stderr:
            # We treat compile errors differently than runtime
            pass 
        return {"returncode": run.returncode, "stdout": run.stdout, "stderr": run.stderr}


def _run_python(source: str) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = os.path.join(tmpdir, "solution.py")
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(source)
        run = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{tmpdir}:/app", "-w", "/app", "--memory=256m", "python:3.12-alpine", "python3", "solution.py"],
            capture_output=True, text=True, timeout=10
        )
        return {"returncode": run.returncode, "stdout": run.stdout, "stderr": run.stderr}


# ── Keep Existing Methods ───────────────────────────────────────────────────

async def check_syntax(code: str, language: str = "python") -> dict:
    lang = language.lower()
    if lang in ["python", "py"]:
        try:
            compile(code, "<string>", "exec")
            return {"ok": True, "error": None}
        except SyntaxError as e:
            return {"ok": False, "error": f"{e.msg} at line {e.lineno}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    elif lang in ["javascript", "js", "typescript", "ts"]:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "solution.js")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)
            try:
                def run_docker():
                    return subprocess.run(
                        ["docker", "run", "--rm", "-v", f"{tmpdir}:/app", "-w", "/app", "node:20-alpine", "node", "-c", "solution.js"],
                        capture_output=True,
                        timeout=5.0,
                        text=True,
                        errors="replace"
                    )
                proc = await asyncio.to_thread(run_docker)
                if proc.returncode == 0:
                    return {"ok": True, "error": None}
                return {"ok": False, "error": proc.stderr.strip()}
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "Timeout"}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    elif lang in ["c++", "cpp", "c"]:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "solution.cpp")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)
            try:
                def run_docker():
                    return subprocess.run(
                        ["docker", "run", "--rm", "-v", f"{tmpdir}:/app", "-w", "/app", "gcc:13", "g++", "-fsyntax-only", "solution.cpp"],
                        capture_output=True,
                        timeout=5.0,
                        text=True,
                        errors="replace"
                    )
                proc = await asyncio.to_thread(run_docker)
                if proc.returncode == 0:
                    return {"ok": True, "error": None}
                return {"ok": False, "error": proc.stderr.strip()}
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "Timeout"}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    elif lang in ["java"]:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "Solution.java")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)
            try:
                def run_docker():
                    return subprocess.run(
                        ["docker", "run", "--rm", "-v", f"{tmpdir}:/app", "-w", "/app", "eclipse-temurin:21-jdk", "javac", "Solution.java"],
                        capture_output=True,
                        timeout=5.0,
                        text=True,
                        errors="replace"
                    )
                proc = await asyncio.to_thread(run_docker)
                if proc.returncode == 0:
                    return {"ok": True, "error": None}
                return {"ok": False, "error": proc.stderr.strip()}
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "Timeout"}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return {"ok": True, "error": None}

async def benchmark_code(code: str, language: str = "python") -> dict:
    import time
    if "solution" not in code.lower() and "main" not in code.lower():
        return {"ok": False, "median_ms": -1.0}
    start = time.perf_counter()
    res = await asyncio.to_thread(run_code, language, code, {"params":[], "returns":"int", "judge":"exact"}, [{"input":{}, "expected":1}], "exact")
    end = time.perf_counter()
    if res["status"] in ["CE", "RE"]:
        return {"ok": False, "median_ms": -1.0}
    elapsed_ms = (end - start) * 1000
    return {"ok": True, "median_ms": max(elapsed_ms, 1.0)}
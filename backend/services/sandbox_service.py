"""
sandbox_service.py  ─  Robust multi-language code-execution sandbox.

What changed vs v1
══════════════════
SANITISATION
  • strip_fences()          strips markdown ``` fences LLMs almost always emit
  • sanitize_python/java/cpp()   called before every build step
  • Python __main__ guard removal
  • class Solution (Python):  handled at runtime via instance; no brittle extraction
  • class Solution (Java):    brace-counting strip; textwrap.dedent fixes indent
  • class Solution (C++):     detected; _sol instance injected into main()

OUTPUT PARSING
  • All three languages wrap each result in  <<RESULT:N>>…<<END>>
  • _parse_results() extracts by sentinel, not line number
    → immune to debug prints, extra blank lines, partial crashes

JAVA FIXES
  • _compile_and_run_java splits into TWO Docker calls (javac then java)
    → proper CompilationError raised on javac failure (was silent 'pass' before)
  • _strip_java_class() uses brace-counting (not endswith) for reliability
  • Generic toJson(Object) + List<T> support in boilerplate
  • Static-method detection: calls Solution.method() vs sol.method()

C++ FIXES
  • extract_cpp_info() is type-aware (return-type prefixes), not naive
  • Void-return functions: calls func(args) then prints first modified param
  • toJson(string) properly escapes backslash and double-quote

PYTHON FIXES
  • Per-test-case try/except: one crash doesn't kill the whole run
  • _safe_json() handles sets, tuples, custom objects, None
  • Common typing/collections imports pre-loaded for annotated code

COMPARISON
  • compare_outputs() handles null/None edge case
  • _floats_close() recurses into lists for epsilon:X judge
  • _normalize() converts tuples → lists
  • _infer_type() checks bool before int (bool is int subclass in Python)
"""

import asyncio
import json
import os
import re
import subprocess
import tempfile
import textwrap
import time
from typing import Any

TIMEOUT_SECONDS = 30
PYTHON_TIMEOUT  = 10


class CompilationError(Exception):
    pass


# ═══════════════════════════════════════════════════════════════════════════
# 1 ─ CODE SANITISATION
# ═══════════════════════════════════════════════════════════════════════════

def strip_fences(code: str) -> str:
    """Remove markdown code fences (```lang … ```) that LLMs always emit."""
    code = code.strip()
    code = re.sub(r'^```[a-zA-Z+\-#]*\r?\n?', '', code)
    code = re.sub(r'\n?```\s*$', '', code)
    # Second pass for rare double-fencing
    code = re.sub(r'^```[a-zA-Z+\-#]*\r?\n?', '', code.strip())
    code = re.sub(r'\n?```\s*$', '', code.strip())
    return code.strip()


def sanitize_python(code: str) -> str:
    """
    • Strip markdown fences
    • Remove  if __name__ == '__main__':  blocks
    class Solution is handled at runtime in build_python_runner.
    """
    code = strip_fences(code)
    code = re.sub(
        r'\nif\s+__name__\s*==\s*["\']__main__["\'].*', '',
        code, flags=re.DOTALL,
    )
    return code.strip()


def sanitize_java(code: str) -> str:
    return strip_fences(code).strip()


def sanitize_cpp(code: str) -> str:
    return strip_fences(code).strip()


# ═══════════════════════════════════════════════════════════════════════════
# 2 ─ JAVA CLASS-WRAPPER STRIPPING
# ═══════════════════════════════════════════════════════════════════════════

def _strip_java_class(code: str) -> tuple:
    """
    Brace-counting removal of  public class Solution { … }.
    Returns (method_body_str, [import_lines]).
    Handles extends, implements, extra whitespace, LLM-added main().
    """
    imports    = re.findall(r'import\s+[^;]+;', code)
    no_imports = re.sub(r'import\s+[^;]+;\s*\n?', '', code).strip()

    cls = re.search(r'(?:public\s+)?class\s+Solution\b[^{]*\{', no_imports)
    if not cls:
        return no_imports, imports

    depth, i = 1, cls.end()
    while i < len(no_imports) and depth:
        c = no_imports[i]
        if   c == '{': depth += 1
        elif c == '}': depth -= 1
        i += 1

    raw  = no_imports[cls.end(): i - 1] if not depth else no_imports[cls.end():]
    body = textwrap.dedent(raw).strip()

    # Remove any LLM-generated main() so it doesn't clash with ours
    body = re.sub(
        r'(?:public\s+)?static\s+void\s+main\s*\('
        r'String(?:\[\])?\s+\w+\)\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}',
        '', body,
    ).strip()
    return body, imports


# ═══════════════════════════════════════════════════════════════════════════
# 3 ─ FUNCTION / METHOD NAME EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

_CPP_SKIP = {
    'main', 'toJson', 'if', 'for', 'while', 'switch', 'return',
    'vector', 'string', 'int', 'long', 'auto', 'cout', 'cin', 'endl',
    'sizeof', 'class', 'struct', 'template', 'typename', 'namespace',
    'new', 'delete', 'static', 'inline', 'explicit', 'operator',
    'throw', 'catch', 'try', 'push_back', 'emplace_back', 'begin', 'end',
    'size', 'empty', 'find', 'insert', 'erase', 'sort', 'reverse',
    'make_pair', 'make_shared', 'make_unique', 'Solution', 'pair',
    'map', 'set', 'min', 'max', 'swap', 'abs', 'sqrt', 'pow',
    'lower_bound', 'upper_bound', 'accumulate', 'count', 'fill',
    'unique', 'distance', 'unordered_map', 'unordered_set',
    'priority_queue', 'deque', 'stack', 'queue', 'list', 'bitset',
    'numeric_limits', 'move', 'forward', 'next', 'prev',
}
_JAVA_SKIP = {
    'main', 'Solution', 'toJson', 'println', 'toString', 'valueOf',
    'equals', 'hashCode', 'getClass', 'compareTo', 'charAt', 'length',
    'get', 'set', 'add', 'remove', 'size', 'isEmpty', 'containsKey',
}
_PY_SKIP = {
    '__init__', '__repr__', '__str__', '__eq__', '__hash__',
    '__new__', '__del__', '__len__', '__iter__', '__next__',
}


def extract_cpp_info(code: str) -> tuple:
    """Return (func_name, needs_solution_instance)."""
    has_class = bool(re.search(r'class\s+Solution\s*[:{]', code))
    
    # Restrict search code to Solution class body to prevent matching helper constructs
    search_code = code
    if has_class:
        match = re.search(r'class\s+Solution\s*[:{]', code)
        if match:
            depth, i = 1, code.find('{', match.start()) + 1
            if i > 0:
                while i < len(code) and depth > 0:
                    c = code[i]
                    if c == '{': depth += 1
                    elif c == '}': depth -= 1
                    i += 1
                search_code = code[match.start():i]

    # Look for C++ method pattern with type, name, params, optional const, and opening brace
    pat = re.compile(
        r'\b[a-zA-Z0-9_<>]+\s+(\w+)\s*\([^)]*\)\s*(?:const\s*)?\{'
    )
    for m in pat.finditer(search_code):
        name = m.group(1)
        if name not in _CPP_SKIP:
            return name, has_class

    # Fallback to standard check inside search_code
    for m in re.finditer(r'\b(\w+)\s*\(', search_code):
        name = m.group(1)
        if name not in _CPP_SKIP:
            return name, has_class

    raise ValueError("extract_cpp_info: cannot locate function name")


def extract_java_info(code: str) -> tuple:
    """Return (method_name, is_static)."""
    # Restrict search code to Solution class body to prevent matching helper constructs
    search_code = code
    match = re.search(r'(?:public\s+)?class\s+Solution\b[^{]*\{', code)
    if match:
        depth, i = 1, code.find('{', match.start()) + 1
        if i > 0:
            while i < len(code) and depth > 0:
                c = code[i]
                if c == '{': depth += 1
                elif c == '}': depth -= 1
                i += 1
            search_code = code[match.start():i]

    # Look for Java method pattern: optional modifiers, return type, name, params, opening brace
    pat = re.compile(
        r'\b(?:public|protected|private\s+)?(static\s+)?(?:[a-zA-Z0-9_<>[\]]+)\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[a-zA-Z0-9_,\\s]+)?\{'
    )
    for m in pat.finditer(search_code):
        name = m.group(2)
        if name not in _JAVA_SKIP:
            return name, bool(m.group(1))

    for m in re.finditer(r'\b(\w+)\s*\(', search_code):
        name = m.group(1)
        if name not in _JAVA_SKIP:
            return name, False

    raise ValueError("extract_java_info: cannot locate method name")

def extract_python_name(code: str) -> str:
    """Find first non-dunder def at any indentation level."""
    for m in re.finditer(r'^def\s+(\w+)\s*\(', code, re.MULTILINE):
        if m.group(1) not in _PY_SKIP:
            return m.group(1)
    for m in re.finditer(r'def\s+(\w+)\s*\(', code):
        if m.group(1) not in _PY_SKIP:
            return m.group(1)
    raise ValueError("extract_python_name: cannot locate function name")


# ═══════════════════════════════════════════════════════════════════════════
# 4 ─ LITERAL TRANSPILERS
# ═══════════════════════════════════════════════════════════════════════════

def _esc(s: str) -> str:
    return str(s).replace('\\', '\\\\').replace('"', '\\"')


def format_cpp_literal(val, typ: str) -> str:
    if typ in ("int", "long"):      return str(int(val))
    if typ in ("float", "double"):  return repr(float(val))
    if typ == "bool":               return "true" if val else "false"
    if typ == "string":             return '"' + _esc(str(val)) + '"'
    if typ == "char":               return "'" + str(val) + "'"
    if typ == "int[]":
        return "vector<int>{" + ", ".join(str(int(x)) for x in val) + "}"
    if typ == "long[]":
        return "vector<long long>{" + ", ".join(str(int(x)) for x in val) + "}"
    if typ == "float[]":
        return "vector<float>{" + ", ".join(repr(float(x)) for x in val) + "}"
    if typ == "double[]":
        return "vector<double>{" + ", ".join(repr(float(x)) for x in val) + "}"
    if typ == "bool[]":
        return "vector<bool>{" + ", ".join("true" if x else "false" for x in val) + "}"
    if typ == "string[]":
        inner = ", ".join('"' + _esc(str(x)) + '"' for x in val)
        return "vector<string>{" + inner + "}"
    if typ == "int[][]":
        rows = ", ".join("{" + ", ".join(str(int(x)) for x in row) + "}" for row in val)
        return "vector<vector<int>>{" + rows + "}"
    if typ == "string[][]":
        rows = ", ".join(
            "{" + ", ".join('"' + _esc(str(x)) + '"' for x in row) + "}"
            for row in val
        )
        return "vector<vector<string>>{" + rows + "}"
    if typ in ("List<int>", "List<string>", "List<List<int>>"):
        return format_cpp_literal(val, {
            "List<int>": "int[]", "List<string>": "string[]",
            "List<List<int>>": "int[][]",
        }[typ])
    raise ValueError(f"format_cpp_literal: unsupported type '{typ}'")


def format_java_literal(val, typ: str) -> str:
    if typ == "int":     return str(int(val))
    if typ == "long":    return str(int(val)) + "L"
    if typ == "float":   return repr(float(val)) + "f"
    if typ == "double":  return repr(float(val))
    if typ == "bool":    return "true" if val else "false"
    if typ == "string":  return '"' + _esc(str(val)) + '"'
    if typ == "char":    return "'" + str(val) + "'"
    if typ == "int[]":
        return "new int[]{" + ", ".join(str(int(x)) for x in val) + "}"
    if typ == "long[]":
        return "new long[]{" + ", ".join(str(int(x)) + "L" for x in val) + "}"
    if typ == "float[]":
        return "new float[]{" + ", ".join(repr(float(x)) + "f" for x in val) + "}"
    if typ == "double[]":
        return "new double[]{" + ", ".join(repr(float(x)) for x in val) + "}"
    if typ == "bool[]":
        return "new boolean[]{" + ", ".join("true" if x else "false" for x in val) + "}"
    if typ == "string[]":
        inner = ", ".join('"' + _esc(str(x)) + '"' for x in val)
        return "new String[]{" + inner + "}"
    if typ == "int[][]":
        rows = ", ".join("{" + ", ".join(str(int(x)) for x in row) + "}" for row in val)
        return "new int[][]{" + rows + "}"
    if typ == "string[][]":
        rows = ", ".join(
            "{" + ", ".join('"' + _esc(str(x)) + '"' for x in row) + "}"
            for row in val
        )
        return "new String[][]{" + rows + "}"
    if typ in ("List<int>", "List<string>", "List<List<int>>"):
        return format_java_literal(val, {
            "List<int>": "int[]", "List<string>": "string[]",
            "List<List<int>>": "int[][]",
        }[typ])
    raise ValueError(f"format_java_literal: unsupported type '{typ}'")


# ═══════════════════════════════════════════════════════════════════════════
# 5 ─ TYPE MAPPINGS
# ═══════════════════════════════════════════════════════════════════════════

def schema_to_cpp_type(t: str) -> str:
    m = {
        "int": "int", "long": "long long",
        "float": "float", "double": "double",
        "bool": "bool", "string": "string", "char": "char",
        "int[]": "vector<int>", "long[]": "vector<long long>",
        "float[]": "vector<float>", "double[]": "vector<double>",
        "bool[]": "vector<bool>", "string[]": "vector<string>",
        "int[][]": "vector<vector<int>>",
        "string[][]": "vector<vector<string>>",
        "List<int>": "vector<int>", "List<string>": "vector<string>",
        "List<List<int>>": "vector<vector<int>>",
    }
    if t not in m:
        raise ValueError(f"No C++ mapping for schema type '{t}'")
    return m[t]


def schema_to_java_type(t: str) -> str:
    m = {
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
    if t not in m:
        raise ValueError(f"No Java mapping for schema type '{t}'")
    return m[t]


# ═══════════════════════════════════════════════════════════════════════════
# 6 ─ C++ BOILERPLATE
#     Raw string so C++ escape sequences pass through verbatim.
# ═══════════════════════════════════════════════════════════════════════════

_CPP_HEADER = r"""#include <bits/stdc++.h>
using namespace std;

// ── JSON Serializers ──────────────────────────────────────────────────────
string toJson(int x)       { return to_string(x); }
string toJson(long long x) { return to_string(x); }
string toJson(double x) {
    ostringstream os; os << fixed << setprecision(9) << x;
    string s = os.str();
    size_t dot = s.find('.');
    if (dot != string::npos) {
        size_t last = s.find_last_not_of('0');
        s = (last > dot) ? s.substr(0, last + 1) : s.substr(0, dot + 2);
    }
    return s;
}
string toJson(float x)         { return toJson((double)x); }
string toJson(bool x)          { return x ? "true" : "false"; }
string toJson(const string& x) {
    string r(1, '"');
    for (char c : x) {
        if      (c == '"')  r += "\\\"";
        else if (c == '\\') r += "\\\\";
        else r += c;
    }
    return r + '"';
}
string toJson(char x) { return string(1, '"') + x + '"'; }
template<typename T>
string toJson(const vector<T>& v) {
    string s = "[";
    for (size_t i = 0; i < v.size(); ++i) { if (i) s += ','; s += toJson(v[i]); }
    return s + "]";
}
// ─────────────────────────────────────────────────────────────────────────

"""


def build_cpp_main(schema: dict, test_cases: list, user_code: str) -> str:
    params             = schema.get("params", [])
    func_name, has_cls = extract_cpp_info(user_code)
    is_void            = bool(re.search(r'\bvoid\s+' + re.escape(func_name) + r'\s*\(', user_code))
    call_prefix        = "_sol." if has_cls else ""
    instance_decl      = "    Solution _sol;\n" if has_cls else ""

    lines = []
    for i, tc in enumerate(test_cases):
        for p in params:
            try:
                lit   = format_cpp_literal(tc["input"][p["name"]], p["type"])
                ctype = schema_to_cpp_type(p["type"])
                lines.append("    " + ctype + " p" + str(i) + "_" + p["name"] + " = " + lit + ";")
            except Exception as e:
                lines.append("    // [ERR] param " + p["name"] + ": " + str(e))

        args = ", ".join("p" + str(i) + "_" + p["name"] for p in params)

        if is_void:
            lines.append("    " + call_prefix + func_name + "(" + args + ");")
            out = ("toJson(p" + str(i) + "_" + params[0]["name"] + ")") if params else '"null"'
            lines.append('    cout << "<<RESULT:' + str(i) + '>>" << ' + out + ' << "<<END>>\\n";')
        else:
            lines.append("    auto _r" + str(i) + " = " + call_prefix + func_name + "(" + args + ");")
            lines.append('    cout << "<<RESULT:' + str(i) + '>>" << toJson(_r' + str(i) + ') << "<<END>>\\n";')

    return (
        _CPP_HEADER
        + user_code.rstrip() + "\n\n"
        + "int main() {\n"
        + instance_decl
        + "\n".join(lines) + "\n"
        + "    return 0;\n}\n"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 7 ─ JAVA BOILERPLATE
#     chr() is used for ", ', \ to avoid Python/Java string-escape conflicts.
# ═══════════════════════════════════════════════════════════════════════════

def _build_java_header() -> str:
    Q = chr(34)   # "
    S = chr(39)   # '
    B = chr(92)   # \
    lines = [
        "import java.util.*;",
        "import java.util.stream.*;",
        "",
        "public class Solution {",
        "",
        "    // ── JSON Serializers ─────────────────────────────────────────────",
        "    static String toJson(int x)     { return String.valueOf(x); }",
        "    static String toJson(long x)    { return String.valueOf(x); }",
        "    static String toJson(double x)  {",
        "        String _s = String.format(java.util.Locale.US, " + Q + "%.9f" + Q + ", x);",
        "        while (_s.endsWith(" + Q + "0" + Q + ") && !_s.endsWith(" + Q + ".0" + Q + "))",
        "            _s = _s.substring(0, _s.length() - 1);",
        "        return _s;",
        "    }",
        "    static String toJson(float x)   { return toJson((double) x); }",
        "    static String toJson(boolean x) { return String.valueOf(x); }",
        # String serializer — uses char constants _Q/_BS to avoid escape soup
        "    private static final char _Q  = " + S + Q + S + ";",
        "    private static final char _BS = " + S + B + B + S + ";",
        "    static String toJson(String x) {",
        "        if (x == null) return " + Q + "null" + Q + ";",
        "        StringBuilder _sb = new StringBuilder();",
        "        _sb.append(_Q);",
        "        for (char c : x.toCharArray()) {",
        "            if (c == _Q || c == _BS) _sb.append(_BS);",
        "            _sb.append(c);",
        "        }",
        "        _sb.append(_Q);",
        "        return _sb.toString();",
        "    }",
        "    static String toJson(char x) { return " + Q + Q + " + _Q + x + _Q; }",
        # Primitive-array overloads
        "    static String toJson(int[] a) {",
        "        if (a == null) return " + Q + "null" + Q + ";",
        "        StringBuilder sb = new StringBuilder(" + Q + "[" + Q + ");",
        "        for (int i = 0; i < a.length; i++) { if (i > 0) sb.append(','); sb.append(a[i]); }",
        "        return sb.append(" + Q + "]" + Q + ").toString();",
        "    }",
        "    static String toJson(long[] a) {",
        "        if (a == null) return " + Q + "null" + Q + ";",
        "        StringBuilder sb = new StringBuilder(" + Q + "[" + Q + ");",
        "        for (int i = 0; i < a.length; i++) { if (i > 0) sb.append(','); sb.append(a[i]); }",
        "        return sb.append(" + Q + "]" + Q + ").toString();",
        "    }",
        "    static String toJson(double[] a) {",
        "        if (a == null) return " + Q + "null" + Q + ";",
        "        StringBuilder sb = new StringBuilder(" + Q + "[" + Q + ");",
        "        for (int i = 0; i < a.length; i++) { if (i > 0) sb.append(','); sb.append(toJson(a[i])); }",
        "        return sb.append(" + Q + "]" + Q + ").toString();",
        "    }",
        "    static String toJson(boolean[] a) {",
        "        if (a == null) return " + Q + "null" + Q + ";",
        "        StringBuilder sb = new StringBuilder(" + Q + "[" + Q + ");",
        "        for (int i = 0; i < a.length; i++) { if (i > 0) sb.append(','); sb.append(a[i]); }",
        "        return sb.append(" + Q + "]" + Q + ").toString();",
        "    }",
        "    static String toJson(String[] a) {",
        "        if (a == null) return " + Q + "null" + Q + ";",
        "        StringBuilder sb = new StringBuilder(" + Q + "[" + Q + ");",
        "        for (int i = 0; i < a.length; i++) { if (i > 0) sb.append(','); sb.append(toJson(a[i])); }",
        "        return sb.append(" + Q + "]" + Q + ").toString();",
        "    }",
        "    static String toJson(int[][] a) {",
        "        if (a == null) return " + Q + "null" + Q + ";",
        "        StringBuilder sb = new StringBuilder(" + Q + "[" + Q + ");",
        "        for (int i = 0; i < a.length; i++) { if (i > 0) sb.append(','); sb.append(toJson(a[i])); }",
        "        return sb.append(" + Q + "]" + Q + ").toString();",
        "    }",
        "    static String toJson(String[][] a) {",
        "        if (a == null) return " + Q + "null" + Q + ";",
        "        StringBuilder sb = new StringBuilder(" + Q + "[" + Q + ");",
        "        for (int i = 0; i < a.length; i++) { if (i > 0) sb.append(','); sb.append(toJson(a[i])); }",
        "        return sb.append(" + Q + "]" + Q + ").toString();",
        "    }",
        # Generic Object fallback: handles List<T>, Integer, Long, Double …
        '    @SuppressWarnings({"unchecked","rawtypes"})',
        "    static String toJson(Object obj) {",
        "        if (obj == null)              return " + Q + "null" + Q + ";",
        "        if (obj instanceof Boolean)   return String.valueOf((Boolean) obj);",
        "        if (obj instanceof Integer)   return String.valueOf((Integer) obj);",
        "        if (obj instanceof Long)      return String.valueOf((Long) obj);",
        "        if (obj instanceof Double)    return toJson((double)(Double) obj);",
        "        if (obj instanceof Float)     return toJson((double)(float)(Float) obj);",
        "        if (obj instanceof String)    return toJson((String) obj);",
        "        if (obj instanceof int[])     return toJson((int[]) obj);",
        "        if (obj instanceof long[])    return toJson((long[]) obj);",
        "        if (obj instanceof double[])  return toJson((double[]) obj);",
        "        if (obj instanceof boolean[]) return toJson((boolean[]) obj);",
        "        if (obj instanceof String[])  return toJson((String[]) obj);",
        "        if (obj instanceof int[][])   return toJson((int[][]) obj);",
        "        if (obj instanceof List) {",
        "            List list = (List) obj;",
        "            StringBuilder sb = new StringBuilder(" + Q + "[" + Q + ");",
        "            for (int i = 0; i < list.size(); i++) {",
        "                if (i > 0) sb.append(',');",
        "                sb.append(toJson(list.get(i)));",
        "            }",
        "            return sb.append(" + Q + "]" + Q + ").toString();",
        "        }",
        "        return toJson(obj.toString());",
        "    }",
        "    // ─────────────────────────────────────────────────────────────────",
        "",
        "    // USER CODE INSERTED BELOW",
    ]
    return "\n".join(lines)


_JAVA_HEADER = _build_java_header()


def build_java_main(schema: dict, test_cases: list, user_code: str) -> str:
    params = schema.get("params", [])

    method_body, imports = _strip_java_class(user_code)
    analysis_src = method_body if method_body.strip() else user_code

    try:
        func_name, is_static = extract_java_info(analysis_src)
    except ValueError:
        func_name, is_static = "solution", False

    is_void = bool(re.search(r'\bvoid\s+' + re.escape(func_name) + r'\s*\(', analysis_src))
    caller  = ("Solution." if is_static else "sol.") + func_name

    lines = []
    for i, tc in enumerate(test_cases):
        for p in params:
            try:
                lit   = format_java_literal(tc["input"][p["name"]], p["type"])
                jtype = schema_to_java_type(p["type"])
                lines.append("        " + jtype + " p" + str(i) + "_" + p["name"] + " = " + lit + ";")
            except Exception as e:
                lines.append("        // [ERR] param " + p["name"] + ": " + str(e))

        args = ", ".join("p" + str(i) + "_" + p["name"] for p in params)

        if is_void:
            lines.append("        " + caller + "(" + args + ");")
            out = ("toJson(p" + str(i) + "_" + params[0]["name"] + ")") if params else '"null"'
            lines.append('        System.out.println("<<RESULT:' + str(i) + '>>" + ' + out + ' + "<<END>>");')
        else:
            lines.append(
                '        System.out.println("<<RESULT:' + str(i) + '>>" + toJson(' + caller + '(' + args + ')) + "<<END>>");'
            )

    test_calls = "\n".join(lines)
    import_str = "\n".join(imports) + "\n" if imports else ""

    # Re-indent method body 4 spaces to sit inside the class
    indented_body = "\n".join(
        ("    " + line) if line.strip() else ""
        for line in method_body.splitlines()
    )

    return (
        import_str
        + _JAVA_HEADER + "\n"
        + indented_body + "\n\n"
        + "    public static void main(String[] args) {\n"
        + "        Solution sol = new Solution();\n"
        + test_calls + "\n"
        + "    }\n"
        + "}\n"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 8 ─ PYTHON BOILERPLATE
# ═══════════════════════════════════════════════════════════════════════════

_PY_PREAMBLE = (
    "from typing import List, Optional, Dict, Tuple, Any, Set, Union, Deque\n"
    "from collections import defaultdict, Counter, deque\n"
    "import heapq, math, functools, itertools, bisect, json, sys\n"
    "\n"
    "def _safe_json(v):\n"
    "    if v is None:                    return None\n"
    "    if isinstance(v, bool):          return v\n"
    "    if isinstance(v, (int, float)):  return v\n"
    "    if isinstance(v, str):           return v\n"
    "    if isinstance(v, (list, tuple)): return [_safe_json(x) for x in v]\n"
    "    if isinstance(v, dict):          return {str(k): _safe_json(x) for k, x in v.items()}\n"
    "    try:                             return [_safe_json(x) for x in v]\n"
    "    except Exception:                return str(v)\n"
    "\n"
)


def build_python_runner(schema: dict, test_cases: list, user_code: str) -> str:
    """
    Handles:
    • Standalone functions
    • class Solution wrappers (instantiated at runtime, no brittle extraction)
    • Per-test try/except so one crash doesn't kill the rest
    • Sentinel output  <<RESULT:N>>…<<END>>
    """
    has_class = bool(re.search(r'class\s+Solution\b', user_code))

    params = schema.get("params", [])
    pnames = [p["name"] for p in params]
    arg_str = ", ".join(f"_inp[{repr(n)}]" for n in pnames)

    if has_class:
        try:
            fname   = extract_python_name(user_code)
            call_t  = f"Solution().{fname}({arg_str})"
        except ValueError:
            call_t = (
                f"(lambda sol: getattr(sol, "
                f"next(m for m in dir(sol) if not m.startswith('_')))"
                f"({arg_str}))(Solution())"
            )
    else:
        try:
            fname  = extract_python_name(user_code)
            call_t = f"{fname}({arg_str})"
        except ValueError:
            call_t = f"solution({arg_str})"

    parts = [_PY_PREAMBLE, user_code, ""]

    for i, tc in enumerate(test_cases):
        inp_repr = repr(json.dumps(tc["input"]))
        parts.append(
            "try:\n"
            "    _inp = json.loads(" + inp_repr + ")\n"
            "    _res = " + call_t + "\n"
            "    print('<<RESULT:" + str(i) + ">>' + json.dumps(_safe_json(_res)) + '<<END>>')\n"
            "except Exception as _e:\n"
            "    print(f'[ERR case " + str(i) + "]: {_e}', file=sys.stderr)\n"
            "    print('<<RESULT:" + str(i) + ">>null<<END>>')\n"
        )

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# 9 ─ SENTINEL OUTPUT PARSER
# ═══════════════════════════════════════════════════════════════════════════

_SENTINEL_RE = re.compile(r'<<RESULT:(\d+)>>(.*?)<<END>>', re.DOTALL)


def _parse_results(stdout: str, n: int) -> list:
    """Extract per-case output strings; missing cases return empty string."""
    results = [''] * n
    for m in _SENTINEL_RE.finditer(stdout):
        idx = int(m.group(1))
        if 0 <= idx < n:
            results[idx] = m.group(2).strip()
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 10 ─ OUTPUT COMPARISON
# ═══════════════════════════════════════════════════════════════════════════

def _normalize(val: Any) -> Any:
    if isinstance(val, tuple): return [_normalize(v) for v in val]
    if isinstance(val, list):  return [_normalize(v) for v in val]
    return val


def _floats_close(a: Any, b: Any, tol: float) -> bool:
    """Recursive epsilon comparison for scalars, lists, and nested lists."""
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_floats_close(x, y, tol) for x, y in zip(a, b))
    try:
        return abs(float(a) - float(b)) <= tol
    except (ValueError, TypeError):
        return a == b


def compare_outputs(actual: str, expected_val, judge: str) -> bool:
    actual = (actual or '').strip()

    # Null / None handling
    if actual == 'null':
        exp = expected_val
        if isinstance(exp, str):
            try: exp = json.loads(exp)
            except Exception: pass
        return exp is None

    if not actual or actual.startswith('[ERR'):
        return False

    try:
        actual_parsed = json.loads(actual)
    except json.JSONDecodeError:
        actual_parsed = actual

    if isinstance(expected_val, str):
        try:    expected_parsed = json.loads(expected_val.strip())
        except json.JSONDecodeError: expected_parsed = expected_val.strip()
    else:
        expected_parsed = expected_val

    actual_n   = _normalize(actual_parsed)
    expected_n = _normalize(expected_parsed)

    if judge == "exact":
        return actual_n == expected_n

    if judge == "any_order":
        if isinstance(actual_n, list) and isinstance(expected_n, list):
            try:
                return (sorted(str(x) for x in actual_n) ==
                        sorted(str(x) for x in expected_n))
            except Exception:
                pass
        return actual_n == expected_n

    if judge.startswith("epsilon:"):
        try:
            tol = float(judge.split(":", 1)[1])
            return _floats_close(actual_parsed, expected_parsed, tol)
        except (ValueError, TypeError, IndexError):
            pass

    return actual_n == expected_n


# ═══════════════════════════════════════════════════════════════════════════
# 11 ─ SCHEMA / INPUT HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _infer_type(val) -> str:
    # bool MUST come before int (bool is a subclass of int in Python)
    if isinstance(val, bool):  return "bool"
    if isinstance(val, int):   return "int"
    if isinstance(val, float): return "double"
    if isinstance(val, str):   return "string"
    if isinstance(val, list):
        if not val: return "int[]"
        if isinstance(val[0], list):
            return "string[][]" if (val[0] and isinstance(val[0][0], str)) else "int[][]"
        return "string[]" if isinstance(val[0], str) else "int[]"
    return "string"


def _ensure_params(schema: dict, test_cases: list) -> list:
    params = schema.get("params", [])
    if params:
        return params
    if not test_cases:
        return []
    first = test_cases[0].get("input")
    if isinstance(first, dict):
        return [{"name": k, "type": _infer_type(v)} for k, v in first.items()]
    for tc in test_cases:
        tc["input"] = {"arg0": tc.get("input")}
    return [{"name": "arg0", "type": _infer_type(first)}]


# ═══════════════════════════════════════════════════════════════════════════
# 12 ─ EXECUTION CORE
# ═══════════════════════════════════════════════════════════════════════════

def run_code(language: str, user_code: str, schema: dict,
             test_cases: list, judge: str) -> dict:
    lang = language.lower().strip()
    schema["params"] = _ensure_params(schema, test_cases)

    # ── Sanitise ──────────────────────────────────────────────────────────
    if lang in ("python", "py"):
        user_code = sanitize_python(user_code)
    elif lang == "java":
        user_code = sanitize_java(user_code)
    elif lang in ("cpp", "c++", "c"):
        user_code = sanitize_cpp(user_code)

    # ── Build & execute ───────────────────────────────────────────────────
    try:
        if lang in ("cpp", "c++", "c"):
            source = build_cpp_main(schema, test_cases, user_code)
            result = _compile_and_run_cpp(source)
        elif lang == "java":
            source = build_java_main(schema, test_cases, user_code)
            result = _compile_and_run_java(source)
        elif lang in ("python", "py"):
            source = build_python_runner(schema, test_cases, user_code)
            result = _run_python(source)
        else:
            return {
                "status": "CE",
                "stderr": "Unsupported language: " + language,
                "test_results": [],
            }
    except subprocess.TimeoutExpired:
        return {"status": "TLE", "stderr": "Execution exceeded time limit.", "test_results": []}
    except CompilationError as e:
        return {"status": "CE", "stderr": str(e), "test_results": []}

    if result["returncode"] != 0:
        stderr = (result.get("stderr") or result.get("stdout") or "").strip()
        return {"status": "RE", "stderr": stderr, "test_results": []}

    # ── Parse sentinel output ─────────────────────────────────────────────
    case_outputs = _parse_results(result["stdout"], len(test_cases))

    test_results, overall = [], "AC"
    for i, tc in enumerate(test_cases):
        actual  = case_outputs[i]
        raw_exp = tc.get("expected", "")

        if isinstance(raw_exp, str):
            try:    exp_parsed = json.loads(raw_exp.strip())
            except json.JSONDecodeError: exp_parsed = raw_exp.strip()
        else:
            exp_parsed = raw_exp

        passed = compare_outputs(actual, tc["expected"], judge)
        status = "AC" if passed else "WA"
        if status == "WA":
            overall = "WA"

        test_results.append({
            "case":     i,
            "status":   status,
            "stdout":   actual,
            "expected": json.dumps(exp_parsed),
        })

    return {
        "status":       overall,
        "stderr":       result.get("stderr", ""),
        "test_results": test_results,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 13 ─ LANGUAGE RUNNERS
# ═══════════════════════════════════════════════════════════════════════════

def _compile_and_run_cpp(source: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "sol.cpp"), "w", encoding="utf-8") as f:
            f.write(source)

        proc = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", d + ":/app", "-w", "/app",
                "--memory=256m", "--cpus=1",
                "gcc:13", "sh", "-c",
                "g++ -O2 -std=c++17 -o sol sol.cpp && timeout 5 ./sol",
            ],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        )
        if proc.returncode != 0 and re.search(r'\berror:', proc.stderr):
            raise CompilationError(proc.stderr)
        return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def _compile_and_run_java(source: str) -> dict:
    """
    Two separate Docker calls:
      1. javac  → raises CompilationError on failure (was silently ignored before)
      2. java   → actual execution
    .class files persist in the shared tmpdir volume between calls.
    """
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "Solution.java"), "w", encoding="utf-8") as f:
            f.write(source)

        # Step 1: compile
        cc = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", d + ":/app", "-w", "/app",
                "eclipse-temurin:21-jdk", "javac", "Solution.java",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if cc.returncode != 0:
            raise CompilationError(cc.stderr)

        # Step 2: execute
        run = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", d + ":/app", "-w", "/app",
                "--memory=256m",
                "eclipse-temurin:21-jdk",
                "timeout", "5", "java", "-Xmx256m", "Solution",
            ],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        )
        return {"returncode": run.returncode, "stdout": run.stdout, "stderr": run.stderr}


def _run_python(source: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "solution.py"), "w", encoding="utf-8") as f:
            f.write(source)

        proc = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", d + ":/app", "-w", "/app",
                "--memory=256m",
                "python:3.12-alpine",
                "timeout", "5", "python3", "solution.py",
            ],
            capture_output=True, text=True, timeout=PYTHON_TIMEOUT,
        )
        return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


# ═══════════════════════════════════════════════════════════════════════════
# 14 ─ UTILITY METHODS  (preserved + unified from v1)
# ═══════════════════════════════════════════════════════════════════════════

async def check_syntax(code: str, language: str = "python") -> dict:
    lang = language.lower()

    if lang in ("python", "py"):
        try:
            compile(code, "<string>", "exec")
            return {"ok": True, "error": None}
        except SyntaxError as e:
            return {"ok": False, "error": str(e.msg) + " at line " + str(e.lineno)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    docker_cmds = {
        "javascript": ("node:20-alpine",        ["node", "-c", "solution.js"],                         "solution.js"),
        "js":         ("node:20-alpine",        ["node", "-c", "solution.js"],                         "solution.js"),
        "typescript": ("node:20-alpine",        ["node", "-c", "solution.js"],                         "solution.js"),
        "ts":         ("node:20-alpine",        ["node", "-c", "solution.js"],                         "solution.js"),
        "cpp":        ("gcc:13",                ["g++", "-fsyntax-only", "-std=c++17", "solution.cpp"], "solution.cpp"),
        "c++":        ("gcc:13",                ["g++", "-fsyntax-only", "-std=c++17", "solution.cpp"], "solution.cpp"),
        "c":          ("gcc:13",                ["g++", "-fsyntax-only", "-std=c++17", "solution.cpp"], "solution.cpp"),
        "java":       ("eclipse-temurin:21-jdk", ["javac", "Solution.java"],                           "Solution.java"),
    }

    if lang not in docker_cmds:
        return {"ok": True, "error": None}

    image, cmd, filename = docker_cmds[lang]
    with tempfile.TemporaryDirectory() as d:
        fp = os.path.join(d, filename)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                ["docker", "run", "--rm", "-v", d + ":/app", "-w", "/app", image] + cmd,
                capture_output=True, timeout=5.0, text=True, errors="replace",
            )
            return {
                "ok":    proc.returncode == 0,
                "error": proc.stderr.strip() if proc.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


async def benchmark_code(code: str, language: str = "python") -> dict:
    if "solution" not in code.lower() and "main" not in code.lower():
        return {"ok": False, "median_ms": -1.0}
    start = time.perf_counter()
    res   = await asyncio.to_thread(
        run_code, language, code,
        {"params": [], "returns": "int"},
        [{"input": {}, "expected": 1}],
        "exact",
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    if res["status"] in ("CE", "RE"):
        return {"ok": False, "median_ms": -1.0}
    return {"ok": True, "median_ms": max(elapsed_ms, 1.0)}

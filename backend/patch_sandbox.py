with open('backend/services/sandbox_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

target_start = "def extract_cpp_info(code: str) -> tuple:"
target_end = "def extract_python_name(code: str) -> str:"

start_idx = content.find(target_start)
end_idx = content.find(target_end)

if start_idx == -1 or end_idx == -1:
    print("Could not find start or end index!")
    exit(1)

new_functions = """def extract_cpp_info(code: str) -> tuple:
    \"\"\"Return (func_name, needs_solution_instance).\"\"\"
    has_class = bool(re.search(r'class\\s+Solution\\s*[:{]', code))
    
    # Restrict search code to Solution class body to prevent matching helper constructs
    search_code = code
    if has_class:
        match = re.search(r'class\\s+Solution\\s*[:{]', code)
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
        r'\\b[a-zA-Z0-9_<>]+\\s+(\\w+)\\s*\\([^)]*\\)\\s*(?:const\\s*)?\\{'
    )
    for m in pat.finditer(search_code):
        name = m.group(1)
        if name not in _CPP_SKIP:
            return name, has_class

    # Fallback to standard check inside search_code
    for m in re.finditer(r'\\b(\\w+)\\s*\\(', search_code):
        name = m.group(1)
        if name not in _CPP_SKIP:
            return name, has_class

    raise ValueError("extract_cpp_info: cannot locate function name")


def extract_java_info(code: str) -> tuple:
    \"\"\"Return (method_name, is_static).\"\"\"
    # Restrict search code to Solution class body to prevent matching helper constructs
    search_code = code
    match = re.search(r'(?:public\\s+)?class\\s+Solution\\b[^{]*\\{', code)
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
        r'\\b(?:public|protected|private\\s+)?(static\\s+)?(?:[a-zA-Z0-9_<>[\\]]+)\\s+(\\w+)\\s*\\([^)]*\\)\\s*(?:throws\\s+[a-zA-Z0-9_,\\\\s]+)?\\{'
    )
    for m in pat.finditer(search_code):
        name = m.group(2)
        if name not in _JAVA_SKIP:
            return name, bool(m.group(1))

    for m in re.finditer(r'\\b(\\w+)\\s*\\(', search_code):
        name = m.group(1)
        if name not in _JAVA_SKIP:
            return name, False

    raise ValueError("extract_java_info: cannot locate method name")
"""

updated_content = content[:start_idx] + new_functions + "\n" + content[end_idx:]

with open('backend/services/sandbox_service.py', 'w', encoding='utf-8') as f:
    f.write(updated_content)

print("Successfully patched sandbox_service.py!")

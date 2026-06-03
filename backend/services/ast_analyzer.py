import ast
from typing import Dict, Any


class ASTAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.complexity_by_func = {}
        self.long_functions = []
        self.missing_docstrings = []
        self.max_nesting_depth = 0
        self.current_func = None

    def analyze(self, code: str) -> Dict[str, Any]:
        try:
            tree = ast.parse(code)
            self.visit(tree)
            return {
                "cyclomatic_complexity": self.complexity_by_func,
                "god_functions": self.long_functions,
                "missing_docstrings": self.missing_docstrings,
                "max_nesting_depth": self.max_nesting_depth,
            }
        except Exception as e:
            return {"error": f"AST parse error: {str(e)}"}

    def visit_FunctionDef(self, node: ast.FunctionDef):
        return self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        return self._visit_func(node)

    def _visit_func(self, node):
        prev_func = self.current_func
        self.current_func = node.name

        # Complexity
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.Assert, ast.BoolOp)):
                complexity += 1
            elif hasattr(ast, "ExceptHandler") and isinstance(child, ast.ExceptHandler):
                complexity += 1
        self.complexity_by_func[node.name] = complexity

        # Line count
        if hasattr(node, "end_lineno") and hasattr(node, "lineno"):
            if node.end_lineno - node.lineno > 50:
                self.long_functions.append(node.name)

        # Docstring
        if not ast.get_docstring(node):
            self.missing_docstrings.append(node.name)

        # Nesting depth (naive approximation)
        depth = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
                depth += 1
        if depth > self.max_nesting_depth:
            self.max_nesting_depth = depth

        self.generic_visit(node)
        self.current_func = prev_func


def analyze_code(code: str) -> Dict[str, Any]:
    analyzer = ASTAnalyzer()
    return analyzer.analyze(code)

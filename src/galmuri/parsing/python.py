"""Parse Python syntax and symbol locations; never import or execute input."""

import ast
from dataclasses import replace

from galmuri.contracts.documents import Document
from galmuri.contracts.files import File
from galmuri.parsing.text import parse_text


def parse_python(file: File) -> tuple[Document, ...]:
    document = parse_text(file)[0]
    tree = ast.parse(document.text, filename=file.ref.key)
    symbols = []

    def collect(body, prefix: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{node.name}"
                symbols.append(
                    {
                        "name": name,
                        "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                        "line": node.lineno,
                        "end_line": node.end_lineno,
                    }
                )
                collect(node.body, f"{name}.")

    collect(tree.body)
    return (
        replace(
            document,
            metadata={**document.metadata, "format": "python", "symbols": symbols},
        ),
    )

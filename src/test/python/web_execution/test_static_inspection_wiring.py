"""Structural guards for standard factory integration; no runtime or database startup."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def parsed(relative):
    return ast.parse((ROOT / relative).read_text(encoding="utf-8"))


def test_default_factory_constructs_inspection_service_with_shared_database():
    tree = parsed("src/orchestwin/api/services.py")
    runtime = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ApplicationRuntime"
    )
    assert any(
        isinstance(node, ast.AnnAssign)
        and node.target.id == "static_inspection_service"
        and isinstance(node.value, ast.Constant)
        and node.value.value is None
        for node in runtime.body
    )
    factory = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_default_runtime"
    )
    calls = [
        node
        for node in ast.walk(factory)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_static_inspection_service"
    ]
    assert len(calls) == 1
    assert [ast.unparse(arg) for arg in calls[0].args] == [
        "database_runtime.session_factory",
        "resolved_settings",
    ]
    returns = [
        node
        for node in ast.walk(factory)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ApplicationRuntime"
    ]
    assert any(
        keyword.arg == "static_inspection_service" and keyword.value is calls[0]
        for call in returns
        for keyword in call.keywords
    )


def test_standard_app_registers_exactly_one_inspection_router_and_state():
    tree = parsed("src/orchestwin/api/app.py")
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "create_static_inspection_router"
    ]
    assert len(calls) == 1
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
    assert any(
        ast.unparse(node.value) == "resolved_runtime.static_inspection_service"
        and any(
            ast.unparse(target) == "application.state.static_inspection_service"
            for target in node.targets
        )
        for node in assignments
    )


def test_migration_environment_registers_new_table_without_removing_training():
    tree = parsed("src/orchestwin/persistence/migrations/env.py")
    imported = {
        alias.name for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names
    }
    registered = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_IMPORTED_MODELS"
            for target in node.targets
        )
    )
    names = {element.id for element in registered.elts if isinstance(element, ast.Name)}
    assert {
        "STATIC_BROWSER_INSPECTIONS",
        "TrainingRunRecord",
        "TrainingRunCheckpointRecord",
    } <= imported & names

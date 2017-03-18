import argparse
import ast
import functools
import importlib.machinery
import importlib.util
import os
import sys
import types
from typing import Iterable, List, Optional, Tuple

_STANDARD_LIB_DIR = os.path.dirname(os.__file__)
_EMPTY_MODULE = types.ModuleType('__empty')
_CMP_OP_TO_FUNCTION = {
    ast.Eq: lambda x, y: x == y,
    ast.NotEq: lambda x, y: x != y,
    ast.Lt: lambda x, y: x < y,
    ast.LtE: lambda x, y: x <= y,
    ast.Gt: lambda x, y: x > y,
    ast.GtE: lambda x, y: x >= y,
    ast.Is: lambda x, y: x is y,
    ast.IsNot: lambda x, y: x is not y,
    ast.In: lambda x, y: x in y,
    ast.NotIn: lambda x, y: x not in y,
}


class LiteralEvalError(Exception):
    """Raised if LiteralEvalVisitor cannot evaluate a node."""


class LiteralEvalVisitor(ast.NodeVisitor):
    def visit_Name(self, node):
        if node.id == 'sys':
            return sys
        else:
            raise LiteralEvalError(f'Cannot evaluate name {node.id}')

    def visit_Num(self, node):
        return node.n

    def visit_Str(self, node):
        return node.s

    def visit_Tuple(self, node):
        return tuple(self.visit(elt) for elt in node.elts)

    def visit_Subscript(self, node):
        value = self.visit(node.value)
        slc = self.visit(node.slice)
        return value[slc]

    def visit_Compare(self, node):
        if len(node.ops) != 1:
            raise LiteralEvalError('Cannot evaluate chained comparison')
        fn = _CMP_OP_TO_FUNCTION[type(node.ops[0])]
        return fn(self.visit(node.left), self.visit(node.comparators[0]))

    def visit_BoolOp(self, node):
        for val_node in node.values:
            val = self.visit(val_node)
            if (isinstance(node.op, ast.Or) and val) or (isinstance(node.op, ast.And) and not val):
                return val
        return val

    def visit_Slice(self, node):
        lower = self.visit(node.lower) if node.lower is not None else None
        upper = self.visit(node.upper) if node.upper is not None else None
        step = self.visit(node.step) if node.step is not None else None
        return slice(lower, upper, step)

    def visit_Attribute(self, node):
        val = self.visit(node.value)
        try:
            return getattr(val, node.attr)
        except AttributeError:
            raise LiteralEvalError(f'Cannot access attribute {node.attr} on {val}')

    def generic_visit(self, node):
        raise LiteralEvalError(f'Cannot evaluate node {ast.dump(node)}')


def get_search_path(typeshed_dir: str, pyversion: Tuple[int, int]) -> Tuple[str]:
    # mirrors default_lib_path in mypy/build.py
    path = []  # type: List[str]

    versions = [f'{pyversion[0]}.{minor}' for minor in reversed(range(pyversion[1] + 1))]
    # E.g. for Python 3.2, try 3.2/, 3.1/, 3.0/, 3/, 2and3/.
    for version in versions + [str(pyversion[0]), '2and3']:
        stubdir = os.path.join(typeshed_dir, 'stdlib', version)
        if os.path.isdir(stubdir):
            path.append(stubdir)
    return tuple(path)


def get_stub_file_name(module_name: str, search_path: Iterable[str]) -> Optional[str]:
    for stubdir in search_path:
        filename = os.path.join(stubdir, f'{module_name}.pyi')
        if os.path.isfile(filename):
            return filename
    else:
        return None


def import_file(filename: str) -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader('pseudo-module', filename)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def get_stub_ast(module_name: str, search_path: Iterable[str]) -> Optional[ast.Module]:
    filename = get_stub_file_name(module_name, search_path)
    if filename is None:
        return None
    with open(filename) as f:
        return ast.parse(f.read())


def get_stdlib_modules() -> Iterable[str]:
    for entry in os.scandir(_STANDARD_LIB_DIR):
        if entry.is_file():
            if entry.name.endswith('.py') and entry.name != 'antigravity.py':
                yield entry.name[:-len('.py')]
        elif entry.is_dir():
            continue  # TODO find stubs for directories
            if entry.name != '__pycache__' and '-' not in entry.name:
                yield entry.name


def extract_names_from_ast(tree: ast.Module) -> Iterable[str]:
    yield from extract_names_from_node_list(tree.body)


def extract_names_from_node_list(node_list: Iterable[ast.AST]) -> Iterable[str]:
    for node in node_list:
        if isinstance(node, ast.ClassDef):
            yield node.name
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    yield target.id
        elif isinstance(node, ast.FunctionDef):
            yield node.name
        elif isinstance(node, ast.If):
            try:
                condition = LiteralEvalVisitor().visit(node.test)
            except LiteralEvalError as e:
                print(f'bad condition {ast.dump(node.test)}: {e!r}')
            else:
                if condition:
                    yield from extract_names_from_node_list(node.body)
                else:
                    yield from extract_names_from_node_list(node.orelse)


def extract_names_from_module(mod: types.ModuleType) -> Tuple[Iterable[str], Iterable[str]]:
    required_names = optional_names = dir(mod)
    if hasattr(mod, '__all__'):
        required_names = mod.__all__
    return required_names, optional_names


def check_typeshed_dir(typeshed_dir: str) -> None:
    search_path = get_search_path(typeshed_dir, sys.version_info[:2])
    for module_name in get_stdlib_modules():
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        tree = get_stub_ast(module_name, search_path)
        if tree is None:
            error(module_name, 'failed to find stub for module')
            continue

        stub_names = set(extract_names_from_ast(tree))
        required_module_names, optional_module_names = extract_names_from_module(module)
        required_module_names = set(required_module_names)
        optional_module_names = set(optional_module_names)
        if required_module_names - optional_module_names:
            bad_names = ', '.join(required_module_names - optional_module_names)
            error(module_name, f'incorrect name in __all__: {bad_names}')
        for missing_name in sorted(required_module_names - stub_names):
            # attributes of all modules
            if hasattr(_EMPTY_MODULE, missing_name):
                continue
            # private name
            if missing_name.startswith('_'):
                continue
            error(module_name, f'name {missing_name} exists in module but not in stub')
        for stub_name in sorted(stub_names - optional_module_names):
            # private name
            if stub_name.startswith('_'):
                continue
            error(module_name, f'name {stub_name} exists in stub but not in module')


def error(module_name, message):
    print(f'{module_name}: {message}', file=sys.stderr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser('Checks the consistency of stubs')
    parser.add_argument('typeshed_dir', help='Path to a typeshed directory to check')

    args = parser.parse_args()
    check_typeshed_dir(args.typeshed_dir)

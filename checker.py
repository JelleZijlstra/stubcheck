import argparse
import json
from pathlib import Path
import subprocess
import sys
import typeshed_client
from typed_ast import ast3
from typing import Any, Dict, Iterator, NamedTuple, Tuple

RuntimeDict = Dict[str, Any]


class Error(NamedTuple):
    module_name: str
    message: str


def get_defined_names(module_name: str, python_version: Tuple[int, int]) -> RuntimeDict:
    """Invokes find_names.py to get names defined in a module."""
    python_binary = f'python{python_version[0]}.{python_version[1]}'
    output = subprocess.check_output([python_binary, 'find_names.py', module_name])
    return json.loads(output)[module_name]


def get_stub_names(module_name: str, python_version: Tuple[int, int],
                   typeshed_dir: Path) -> typeshed_client.NameDict:
    return typeshed_client.get_stub_names(module_name, version=python_version,
                                          typeshed_dir=typeshed_dir)


def check_module(module_name: str, python_version: Tuple[int, int],
                 typeshed_dir: Path) -> Iterator[Error]:
    try:
        runtime = get_defined_names(module_name, python_version)
    except subprocess.CalledProcessError:
        print(f'failed to import {module_name}')
        return
    stub = get_stub_names(module_name, python_version=python_version, typeshed_dir=typeshed_dir)

    yield from check_only_in_stub(runtime, stub, module_name)
    yield from check_only_in_runtime(runtime, stub, module_name)


def check_only_in_stub(runtime: RuntimeDict, stub: typeshed_client.NameDict,
                       module_name: str) -> Iterator[Error]:
    for name, info in sorted(stub.items()):
        if name in runtime:
            continue
        if not info.is_exported:
            continue

        # As a special case, ignore names where the stub has an int, but it does not exist at
        # runtime. This happens frequently for system constants that only exist on some OSs (e.g.,
        # in the errno module). It is difficult to write fully accurate stubs, because we can only
        # check sys.platform, and it doesn't seem especially valuable anyway.
        if isinstance(info.ast, ast3.Assign) and info.ast.type_comment == 'int':
            continue
        if (isinstance(info.ast, ast3.AnnAssign) and isinstance(info.ast.annotation, ast3.Name) and
                info.ast.annotation.id == 'int'):
            continue

        yield Error(module_name, f'{name!r} is in stub but is not defined at runtime')


def check_only_in_runtime(runtime: RuntimeDict, stub: typeshed_client.NameDict,
                          module_name: str) -> Iterator[Error]:
    if '__all__' in runtime:
        for name in sorted(runtime['__all__']['value']):
            if name not in stub:
                yield Error(module_name, f'{name!r} is in __all__ but not in stub')
    else:
        ...


def run_on(module_name: str, python_version: Tuple[int, int],
           typeshed_dir: Path) -> None:
    for error in check_module(module_name, python_version, typeshed_dir):
        print(f'{error.module_name}: {error.message}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser('checker.py')
    parser.add_argument('--custom-typeshed-dir', help='Path to typeshed', default=None)
    parser.add_argument('--stdlib', help='Check all standard library modules', action='store_true',
                        default=False)
    parser.add_argument('--python-version', help='Python version to check', default=None)
    parser.add_argument('modules', nargs='*', help='Modules to check')
    args = parser.parse_args()
    if args.custom_typeshed_dir is None:
        typeshed_dir = typeshed_client.finder.find_typeshed()
    else:
        typeshed_dir = Path(args.custom_typeshed_dir)
    if args.python_version is None:
        version = sys.version_info[:2]
    else:
        version = tuple(map(int, args.python_version.split('.', 1)))
    if args.stdlib:
        for module_name, path in typeshed_client.get_all_stub_files(version, typeshed_dir):
            if 'third_party' not in path.parts:
                run_on(module_name, version, typeshed_dir)
    else:
        for module_name in args.modules:
            run_on(module_name, version, typeshed_dir)

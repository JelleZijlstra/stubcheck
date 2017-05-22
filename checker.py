import json
import subprocess
import sys
import typeshed_client
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Tuple

RuntimeDict = Dict[str, Any]


class Error(NamedTuple):
    module_name: str
    message: str


def get_defined_names(module_name: str, python_version: Tuple[int, int]) -> RuntimeDict:
    """Invokes find_names.py to get names defined in a module."""
    python_binary = f'python{python_version[0]}.{python_version[1]}'
    output = subprocess.check_output([python_binary, 'find_names.py', module_name])
    return json.loads(output)[module_name]


def get_stub_names(module_name: str, python_version: Tuple[int, int]) -> typeshed_client.NameDict:
    return typeshed_client.get_stub_names(module_name, python_version)


def check_module(module_name: str, python_version: Tuple[int, int]) -> Iterator[Error]:
    runtime = get_defined_names(module_name, python_version)
    stub = get_stub_names(module_name, python_version)

    yield from check_only_in_stub(runtime, stub, module_name)
    yield from check_only_in_runtime(runtime, stub, module_name)


def check_only_in_stub(runtime: RuntimeDict, stub: typeshed_client.NameDict,
                       module_name: str) -> Iterator[Error]:
    for name, info in sorted(stub.items()):
        if name in runtime:
            continue
        if not info.is_exported:
            continue
        yield Error(module_name, f'{name} is in stub but is not defined at runtime')


def check_only_in_runtime(runtime: RuntimeDict, stub: typeshed_client.NameDict,
                          module_name: str) -> Iterator[Error]:
    if '__all__' in runtime:
        for name in sorted(runtime['__all__']['value']):
            if name not in stub:
                yield Error(module_name, f'{name} is in __all__ but not in stub')
    else:
        ...


if __name__ == '__main__':
    for module_name in sys.argv[1:]:
        for error in check_module(module_name, (3, 6)):
            print(f'{error.module_name}: {error.message}')

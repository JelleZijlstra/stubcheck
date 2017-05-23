"""Script to find the names defined in a module and dump them as JSON."""

import inspect2
import json
import six
import sys


def get_fully_qualified_name(obj):
    return '{}.{}'.format(obj.__module__, obj.__name__)


def import_module(name):
    mod = __import__(name)
    for part in name.split('.')[1:]:
        mod = getattr(mod, part)
    return mod


def handle_module(name):
    mod = import_module(name)
    output = {}
    for name in dir(mod):
        raw_value = getattr(mod, name)
        if name == '__all__':
            typ = '__all__'
            value = list(raw_value)
        elif raw_value is None or isinstance(raw_value, (six.integer_types, six.string_types, float)):
            typ = 'scalar'
            value = raw_value
        elif isinstance(raw_value, six.class_types):
            typ = 'class'
            value = {
                'fully_qualified_name': get_fully_qualified_name(raw_value),
            }
        elif six.callable(raw_value):
            typ = 'callable'
            try:
                sig = inspect2.signature(raw_value)
            except ValueError:
                sig = None
            value = str(sig)
        else:
            typ = 'other'
            value = type(raw_value).__name__
        module = inspect2.getmodule(raw_value)
        output[name] = {
            'type': typ,
            'value': value,
            'module': getattr(module, '__name__', None),
            'name': getattr(raw_value, '__name__', None),
        }
    return output


if __name__ == '__main__':
    data = {name: handle_module(name) for name in sys.argv[1:]}
    json.dump(data, sys.stdout)

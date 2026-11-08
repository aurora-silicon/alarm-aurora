"""Run the updater's makepkg check() suites in repository checks too.

test_bootchain.py is fedora-aurora's suite for the shared bootchain.py;
test_bootchain_arch.py covers the Arch layout and its trial transactions.
"""
import importlib.util
from pathlib import Path
import unittest

PACKAGE = Path(__file__).resolve().parents[1] / 'packages/asahi-scripts'
modules = []
for name in ('test_bootchain', 'test_bootchain_arch'):
    spec = importlib.util.spec_from_file_location(f'asahi_scripts_{name}', PACKAGE / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    modules.append(module)


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for module in modules:
        suite.addTests(loader.loadTestsFromModule(module))
    return suite

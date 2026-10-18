"""Code references identify deployments without executing user implementation code."""

from dataclasses import replace
from types import FunctionType

import pytest

from galmuri import ParsingConfig
from galmuri.contracts.callables import callable_identity, callable_location


def implementation(value):
    raise AssertionError("Identity selection must not execute the implementation")


def relocated(module):
    function = FunctionType(implementation.__code__, implementation.__globals__)
    function.__module__ = module
    function.__qualname__ = "process"
    return function


def test_loader_checkout_namespace_is_not_part_of_deployment_identity():
    left = relocated("_workspace_0123456789abcdef.apps.sample.views")
    right = relocated("_workspace_fedcba9876543210.apps.sample.views")
    assert callable_identity(left) == callable_identity(right) == "apps.sample.views:process"
    assert callable_location(left) == callable_location(right)
    assert ParsingConfig(left).fingerprint == ParsingConfig(right).fingerprint


@pytest.mark.parametrize("namespace", ["_workspace_custom", "_workspace_0123456789abcdeg"])
def test_user_module_names_are_not_silently_rewritten(namespace):
    function = relocated(namespace + ".views")
    assert callable_identity(function) == namespace + ".views:process"


def test_parsing_process_is_a_reference_with_the_existing_compatibility_accessor():
    config = ParsingConfig(process=implementation)
    assert config.process is config.parser is implementation
    assert config.identity.endswith(":implementation")


def test_parser_function_replacement_invalidates_same_declared_identity():
    first = relocated("company.parsers.first")
    second = relocated("company.parsers.second")
    config = ParsingConfig(process=first, identity="company:parser")
    assert config.fingerprint != replace(config, process=second).fingerprint

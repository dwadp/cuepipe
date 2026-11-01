"""Processor registry: name -> factory that builds a `Processor`.

A processor spec on the CLI is `name` or `name:key=value,key=value`.
"""

import inspect
from collections.abc import Callable

from ..pipeline import PipelineError, Processor

_REGISTRY: dict[str, Callable[..., Processor]] = {}


def register(name: str):
    """Register a processor factory. The factory's parameters (all str) are the CLI parameters."""

    def deco(factory: Callable[..., Processor]):
        _REGISTRY[name] = factory
        return factory

    return deco


def names() -> list[str]:
    return sorted(_REGISTRY)


def build(spec: str) -> tuple[str, Processor]:
    name, _, rest = spec.partition(":")
    name = name.strip()
    factory = _REGISTRY.get(name)
    if factory is None:
        raise PipelineError(
            f"unknown processor {name!r} (available: {', '.join(names()) or '-'})"
        )

    params: dict[str, str] = {}
    for pair in filter(None, (p.strip() for p in rest.split(","))):
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise PipelineError(
                f"invalid parameter {pair!r} in {spec!r}, expected key=value"
            )
        params[key.strip()] = value.strip()

    try:
        inspect.signature(factory).bind(**params)
    except TypeError as e:
        raise PipelineError(f"{name}: invalid parameters ({e})") from e
    return name, factory(**params)

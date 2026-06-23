from __future__ import annotations

_ADAPTER_REGISTRY: dict[str, str] = {
    "generic": "depone.verify.adapters.generic",
    "conductor": "depone.verify.adapters.generic",  # V104.0: same as generic
}


def resolve(name: str) -> str:
    """Resolve adapter name to its module path."""
    if name not in _ADAPTER_REGISTRY:
        raise ValueError(
            f"Unknown adapter: {name}. "
            f"Available: {', '.join(sorted(_ADAPTER_REGISTRY))}"
        )
    return _ADAPTER_REGISTRY[name]

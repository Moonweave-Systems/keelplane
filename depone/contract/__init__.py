"""V107 Agent Fabric contract schemas.

This module provides deterministic schema validation for the Depone Agent
Fabric contract layer: role contracts, toolbelt contracts, harness capability
snapshots, compile reports, agent invocation packets, and agent result
self-reports.

See docs/v107-agent-fabric-control-plane-spec.md for the full spec.
"""

from __future__ import annotations

from depone.contract.role import (
    validate_role,
    validate_role_set,
    ROLE_SCHEMA_VERSION,
)
from depone.contract.toolbelt import (
    validate_toolbelt,
    validate_toolbelt_set,
    TOOLBELT_SCHEMA_VERSION,
)
from depone.contract.harness import (
    validate_harness,
    validate_harness_set,
    HARNESS_SCHEMA_VERSION,
)
from depone.contract.profile import (
    validate_profile,
    validate_profile_set,
    PROFILE_SCHEMA_VERSION,
)
from depone.contract.compile_report import (
    validate_compile_report,
    validate_compile_report_set,
    COMPILE_REPORT_SCHEMA_VERSION,
)
from depone.contract.invocation import (
    validate_invocation,
    validate_result,
    INVOCATION_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
)
from depone.contract.validate import (
    validate_agent_fabric_contract,
    validate_self_test,
)

__all__ = [
    "validate_role",
    "validate_role_set",
    "validate_toolbelt",
    "validate_toolbelt_set",
    "validate_harness",
    "validate_harness_set",
    "validate_profile",
    "validate_profile_set",
    "validate_compile_report",
    "validate_compile_report_set",
    "validate_invocation",
    "validate_result",
    "validate_agent_fabric_contract",
    "validate_self_test",
    # Schema version constants
    "ROLE_SCHEMA_VERSION",
    "TOOLBELT_SCHEMA_VERSION",
    "HARNESS_SCHEMA_VERSION",
    "PROFILE_SCHEMA_VERSION",
    "COMPILE_REPORT_SCHEMA_VERSION",
    "INVOCATION_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
]

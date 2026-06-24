# V110 Agent Fabric Report Assurance Spec

V110 connects V109 Agent Fabric capture manifests to the Depone verification
report surface.

## Boundary

The verification report reads capture manifests as evidence. It does not create
new captures, execute commands, call live models, or weaken the V105 evidence
contract checks.

The report separates three concepts:

- `verdict`: existing verification outcome, one of `verified`, `refuted`, or
  `insufficient-evidence`;
- `decision`: operator-facing result derived from the verdict, one of `pass`,
  `fail`, or `inconclusive`;
- `assurance`: strongest valid Agent Fabric capture label observed by the
  report, currently `A0-claims-only` or `A1-local-observed`.

## Capture handling

For each evidence file whose JSON object has kind
`agent-fabric-capture-manifest`, the verifier records an
`agent_fabric_captures` entry containing:

- `evidence_path`;
- `assurance`;
- `decision`;
- `valid`;
- `errors`.

Invalid capture manifests fail closed: the report verdict becomes `refuted`, the
report decision becomes `fail`, and the validation errors remain visible in the
capture entry.

Valid `A1-local-observed` capture manifests lift the report assurance to
`A1-local-observed`. Self-report-only or absent captures leave report assurance
at `A0-claims-only`.

## CLI output

`python3 -m depone verify ...` continues to write the full JSON report and now
also prints the report decision and assurance beside the existing verdict and
phase count.

## Verification

```bash
python3 tests/test_agent_fabric_report_assurance.py
python3 -m depone verify --self-test
python3 -m depone validate-contracts --self-test
```

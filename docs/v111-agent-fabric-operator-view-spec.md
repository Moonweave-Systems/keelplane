# V111 Agent Fabric Operator View Spec

V111 adds a small operator-facing Markdown view/exporter on top of the V110
verification report fields.

## Boundary

The view consumes an existing Depone verification report. It does not execute
commands, create Agent Fabric captures, validate live model output, introduce a
new assurance level, or bypass evidence-contract failures.

The source of truth remains the verification report JSON and the evidence files
referenced by that report. The view may summarize fields, but it must not turn a
summary into stronger proof than the report already carries.

## Required report inputs

A V111-compatible view must read these V110 fields when present:

- `verdict`;
- `decision`;
- `assurance`;
- `agent_fabric_captures[]` entries with `evidence_path`, `assurance`,
  `decision`, `valid`, and `errors`.

Missing V110 fields must be rendered as an integration risk, not silently
upgraded to success. Invalid capture entries must remain visible to the
operator.

## View/export behavior

The operator view should make the following distinctions explicit:

- report verdict versus operator-facing decision;
- report-level assurance versus capture-level assurance;
- valid captures versus invalid captures;
- self-report-only `A0-claims-only` material versus locally observed
  `A1-local-observed` material;
- evidence-contract failures versus Agent Fabric capture failures.

A Markdown export is available through:

```bash
python3 -m depone verify --out report.json --operator-view-out operator-view.md
```

The export is deterministic, stdlib-only, and derived from report fields. It
preserves source paths so an operator can trace each displayed capture back to
the underlying evidence artifact. The view layer does not duplicate V110
validation logic; it renders the report state it is given.

Compatibility behavior:

- reports without `agent_fabric_captures` render an explicit no-captures
  message and keep `A0-claims-only` as the default assurance;
- missing V110 fields render as `unknown` rather than a stronger pass state;
- invalid capture manifests stay fail-closed in the report and remain visible
  in the view;
- Depone remains the public brand, with DWM Core used only for the internal
  engine where needed.

## Verification

The V111 implementation is covered by:

```bash
python3 -m py_compile depone/__main__.py depone/verify/__init__.py depone/verify/operator_view.py
python3 tests/test_agent_fabric_report_assurance.py
python3 -m depone verify --self-test
python3 -m depone validate-contracts --self-test
```

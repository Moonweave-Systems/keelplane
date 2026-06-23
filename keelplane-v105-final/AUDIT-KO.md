# Keelplane 및 V105 초안 전면 감사

작성 기준일: 2026-06-23
대상: 현재 Keelplane 방향, 공개 V104 코드/문서, 이전 Native Agent Team Starter

## 0. 결론

Keelplane은 계속 개발할 가치가 있다. 그러나 제품의 고유 자산은
“에이전트를 많이 띄우는 시스템”이 아니라 다음 세 가지여야 한다.

1. 실행 전에 목표·주장·증거·위험 게이트를 고정하는 계약
2. 실행 중 실제로 관찰된 사실과 에이전트 주장을 분리하는 증거 규격
3. 실행 후 무엇이 통과·실패·미판정인지 보증 한계와 함께 판정하는 검증기

에이전트 팀은 Keelplane Core가 아니라 교체 가능한 참조 프로필이다.
Codex와 Claude Code가 실제 모델 실행, 도구, 세션, 권한, sandbox, worktree를
담당하고 Keelplane은 plan/evidence/policy를 소유하는 것이 맞다.

이번 최종본의 가장 큰 변경은 다음과 같다.

- `Evidence Curator` 에이전트를 제거했다. 실행자가 자기 증거와 seal을 만들면
  감사 경계가 무너진다.
- SHA-256 무결성과 실행 출처·진위성을 분리했다.
- 결과를 `pass/fail/inconclusive`, 보증을 `A0-A3`으로 따로 표시한다.
- native compile을 bijection이 아닌 손실 가능한 lowering으로 정의했다.
- agent role 수가 아니라 paired evaluation으로 효율을 입증하게 했다.
- 이전 압축 파일과 노출 폴더가 달랐던 전달 문제를 없애기 위해 최종본은
  압축 내부, 추출 파일, schema, installer, tests를 모두 검증한다.

---

## 1. 치명적 철학·설계 허점

### C1. 해시 무결성과 실행 진위성을 혼동

기존 초안은 evidence를 hash하고 `seal.json`을 만들면 신뢰 가능한 실행처럼
보일 수 있었다. 하지만 같은 agent/local user가 artifact, ledger, manifest,
seal을 전부 다시 쓰면 모든 hash가 일치한다.

수정:

- evidence origin을 `self-reported`, `imported`, `local-observed`,
  `runner-observed`, `externally-attested`로 구분한다.
- assurance를 `A0-claims-only`, `A1-local-observed`,
  `A2-isolated-observed`, `A3-externally-attested`로 분리한다.
- local seal은 “캡처 이후 변경 감지”만 주장한다.
- 향후 서명은 자체 암호 규격이 아니라 in-toto/DSSE/Sigstore 호환
  attestation을 사용한다.

### C2. Evidence Curator agent가 custody boundary를 깨뜨림

agent가 evidence root에 쓰고 ledger와 seal까지 만들면 producer와 auditor가
같다. role 이름만 다르다고 독립성이 생기지 않는다.

수정:

- agent는 `staging/agent-results/` 아래 자기 보고서만 제안한다.
- deterministic capture가 repository state, digest, manifest, ledger, seal을 쓴다.
- agent result는 언제나 self-report이며 final decision을 설정할 수 없다.

### C3. 현재 adversarial verification의 false-pass 위험

현재 V104 verifier의 adversarial check는 ground-truth path가 존재하는지만
확인하는 heuristic stub이다. 경로 존재는 claim 검증이 아니다. evaluator가
없는데 전체 verdict가 verified가 되면 가장 위험한 종류의 과신이 생긴다.

수정:

- real evaluator가 없는 required claim은 `not-evaluated`다.
- 전체 decision은 `inconclusive`가 된다.
- claim마다 falsifier, evidence selector, evaluator, input snapshot, result를
  기록한다.
- legacy `verified/refuted/insufficient-evidence`는 호환 출력일 뿐 새 decision이
  authoritative하다.

### C4. “실행하지 않는다”와 기존 Runner roadmap이 충돌

최근 README는 실행하지 않는 design+verify layer를 말하지만 기존 DWM roadmap은
Codex CLI 실행, worktree, worker fanout, review/repair를 이미 포함한다.

수정된 경계:

```text
Keelplane Core
  model/task command를 실행하지 않음. schema/policy/verification만 소유.

Keelplane Capture
  local read-only observation/import를 수행.

Keelplane Runner (optional)
  외부 native harness를 계약 아래 launch할 수 있으나 model loop를 구현하지 않음.

Codex / Claude Code
  reasoning, tools, session, sandbox, provider auth를 소유.
```

마케팅 문구는 “Keelplane은 agent runtime이 아니다. 선택적 runner는 외부
runtime을 호출하고 증거를 캡처한다.”가 정직하다.

### C5. `design`이 실제 구현보다 강한 이름

현재 `keelplane design`은 keyword로 audit/research/sequential template을 선택한
뒤 minimal contract를 채운다. 이것은 scaffold이지 situation-aware planner가
아니다.

권장:

- 단기 문서에는 deterministic scaffold라고 명시한다.
- 향후 `plan scaffold`, `plan import`, `plan validate`, `plan explain`으로 분리한다.
- planner claim은 repo inspection, assumptions, alternatives, routing 평가가
  benchmark에서 입증된 뒤에만 한다.

### C6. target compile은 bijection이 될 수 없음

Codex subagents, Claude subagents/Agent Teams, LangGraph, Conductor는 gate,
permission, resume, fan-in 의미가 다르다.

수정:

- compile은 lowering이다.
- target capability manifest를 probe한다.
- `compile-report.json`에 각 항목을 `exact`, `approximated`,
  `omitted-noncritical`, `unsupported-critical`로 기록한다.
- required gate/verification가 unsupported면 compile을 실패시킨다.

---

## 2. 높은 위험의 구현·방향 허점

### H1. 버전/스크립트 증식이 제품을 가림

V0~V103과 100개 이상의 내부 script/receipt/meta gate는 성실한 기록이지만,
사용자가 실제로 써야 할 경로를 흐린다.

권장:

- 새로운 one-script-per-concept meta layer를 멈춘다.
- milestone label과 package SemVer를 분리한다.
- 다음 릴리즈는 `plan -> capture -> verify -> report` 한 vertical loop만 끝낸다.
- `scripts/dwm_*`는 package module, fixture, archive로 정리한다.

### H2. generic adapter의 무제한 file read

모든 파일을 메모리에 읽고 binary를 hex로 바꾸면 대형 파일 DoS, secret leak,
symlink/special file 문제가 생긴다.

수정:

- streaming hash
- 기본 metadata/digest only
- file count/size/depth/total-byte limit
- symlink/device/socket/FIFO 거부
- allowlist full-content capture
- hash 전후 stat 비교로 TOCTOU 탐지

### H3. gate approval가 action에 바인딩되지 않음

`gates/network/approved`는 어떤 command를 승인했는지, 어느 plan/attempt인지,
재사용 가능한지 알 수 없다.

수정:

- approval를 `plan_hash`, `attempt_id`, `action_digest`, `scope`, `expiry`,
  `single_use`에 바인딩한다.
- declared/requested/approved/denied/executed/expired/not-applicable을 분리한다.
- action 내용이 달라지면 재승인이 필요하다.

### H4. reviewer independence를 agent 이름으로 판단

다른 invocation 이름만으로 독립성이 보장되지 않는다. 같은 context/model,
implementer rationale에 anchoring된 reviewer는 같은 오류를 반복한다.

수정:

- fresh context 여부
- same/different model
- same/different harness
- rationale를 보기 전에 findings를 만들었는지
- review input snapshot digest
- human/deterministic tool 참여 여부

를 기록한다. Codex와 Claude Code를 모두 쓰는 사용자는 중·고위험 변경에서
cross-harness blind-first review가 실용적이다.

### H5. command receipt가 재현성에 부족

command string + exit code만으로는 PATH, shell, cwd, timeout, signal, source
snapshot, truncation을 알 수 없다.

수정 receipt는 argv/shell, cwd, source snapshot, status, exit/signal, timeout,
stdout/stderr digest+size+truncation, origin, redaction policy를 기록한다.

### H6. worktree/파일 소유권은 semantic isolation이 아님

서로 다른 파일도 API/schema/behavior에서 충돌할 수 있다.

수정:

- parallel writer 전에 interface contract를 고정한다.
- integration owner를 둔다.
- fan-in에서 build/test/integration contract를 검사한다.
- shared dependency가 높으면 sequential pipeline으로 downgrade한다.

### H7. 관찰할 수 없는 budget을 hard gate로 취급

subscription product는 token/cost가 항상 노출되지 않는다.

수정:

- hard observable: invocation, elapsed time, retry, file touch, command count
- imported optional: token/cost
- advisory: model-estimated effort
- 각 budget에 measurement source를 표시한다.

### H8. experimental native features를 기본 경로로 삼음

Claude Agent Teams는 experimental이고 resume/permission/task-state 제약이 있다.
Codex custom agent/config 형식도 변할 수 있다.

수정:

- 기본은 subagent pipeline이다.
- Agent Teams는 opt-in migration/audit profile만 쓴다.
- pack compatibility test와 capability probe를 둔다.
- installer는 experimental flag를 자동 활성화하지 않는다.

---

## 3. 이전 설계의 누락 사항

1. **Threat model**: actor, asset, trust boundary, attack, out-of-scope.
2. **Assurance model**: 같은 pass라도 self-report와 CI attestation을 구분.
3. **Capability negotiation**: native target의 실제 지원/근사/미지원 확인.
4. **Schema evolution**: major/minor, unknown security fields, migration policy.
5. **Evaluation design**: direct baseline과 paired randomized dogfood.
6. **Retention/sharing**: redaction 외에 보관 기간, upload, deletion.
7. **Cross-platform path safety**: case folding, Unicode, ADS, symlink, special file.
8. **Failure recovery**: native team state가 사라져도 artifact로 재시작.
9. **Stale review detection**: diff/snapshot 변경 후 review 재사용 금지.
10. **Approval replay prevention**: action-bound one-time approval.
11. **False pass/false fail measurement**: verifier 자체 평가.
12. **Installer lifecycle**: idempotence, conflict, uninstall receipt.

---

## 4. 수정된 철학

```text
Producer
  agent가 claim과 artifact를 만든다.

Observer
  capture/runner가 repository, process, bytes를 기록한다.

Verifier
  policy와 evidence를 비교한다.

Approver
  human 또는 별도 policy authority가 위험 행동을 승인한다.
```

한 주체가 네 역할을 모두 수행할수록 assurance는 낮아진다.

결과와 보증은 분리한다.

```text
Decision: pass | fail | inconclusive
Assurance: A0 | A1 | A2 | A3
```

예: `pass / A1-local-observed`는 선언된 local policy가 통과했다는 뜻이지,
provider identity나 결함 부재를 증명한다는 뜻이 아니다.

---

## 5. Agent 팀 최종 구성

항상 실행되는 팀은 없다. profile이 필요한 역할만 활성화한다.

- Lead: native main session
- Explorer: read-only mapping
- Implementer: 기본 한 명, 명시 ownership만 수정
- Test verifier: source를 고치지 않고 checks 수행
- Code reviewer: fresh context, blind-first review
- Security/adversarial reviewer: risk trigger가 있을 때만

Evidence curator는 제거했다. capture/seal은 deterministic tool의 역할이다.

---

## 6. 최종 개발 순서

### 반드시 먼저

1. required claim evaluator가 없을 때 false-pass 차단
2. evidence protocol + threat model + schema 고정
3. deterministic A1 local capture
4. decision + assurance report
5. feature-pipeline 1개 실전 dogfood
6. direct baseline과 paired 비교

### 그다음

1. Codex native import adapter
2. Claude native import adapter
3. cross-harness review packet
4. optional A2 runner custody
5. A3 CI/in-toto attestation

### 미룰 것

- dashboard
- 더 많은 personas
- 추가 compiler target
- automatic model router
- public benchmark graph
- 추가 readiness/meta score

---

## 7. 출시 판단 기준

효율 향상을 주장하려면 최소한 다음이 필요하다.

- medium task에서 accepted completion 또는 escaped defect가 direct baseline보다
  개선되거나 비열등함
- human correction/rework 감소
- coordination overhead가 품질 이득을 압도하지 않음
- verifier false-pass가 사전 설정 상한 아래임
- small task가 자동으로 direct profile로 downgrade됨
- reviewer finding precision이 실용 수준임

Keelplane의 경쟁력은 agent 수가 아니라 **어떤 실행기를 쓰더라도 무엇을
얼마나 믿어도 되는지 정직하게 말하는 능력**이다.

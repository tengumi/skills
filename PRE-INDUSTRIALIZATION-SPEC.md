---
spec_version: "1.0"
service_id: "<FILL>"
spec_owner: "<FILL>"
stage_a_intake: OPEN
parity_inputs: OPEN
stage_b_plan: OPEN
adapter_implementation: OPEN
live_validation: OPEN
release: OPEN
last_approved_by: "<FILL_OR_N/A>"
last_approved_at: "<YYYY-MM-DD_OR_N/A>"
---

# Спецификация до опромышливания

Это human-owned шаблон. Скопируйте его в target как
`docs/harness/pre-industrialization-spec.md` до первого прогона Harness и
заполните минимум для `stage_a_intake`. Остальные разделы заполняются перед
своими gates. Агент может собрать evidence и предложить текст, но не имеет права
сам ставить `APPROVED` или выдумывать контракт.

Не нужно заполнять весь файл в первый день. Он раскрывается по мере прогона:

1. до анализа — паспорт, sources/owners, доступ к prototype и data policy;
2. до parity — логические inputs, fixtures, invariants и threshold;
3. до плана B — inventory, owner и выбранный target mechanism;
4. до adapter — полная карточка именно этой boundary;
5. до live/release — runtime/deploy, stand, данные, side effects и approvers.

Так отсутствие будущего endpoint не блокирует безопасный перенос логики, но не
может неожиданно обнаружиться уже во время реализации adapter.

Минимум для первого запуска: immutable prototype path/revision и read-only
доступ; target/team template; `spec_owner` и владельцы prototype semantics/data;
классификация данных; разрешённое место анализа; redaction, retention и запрет
на commit raw data. Эти значения фиксируются в разделах 1–2. Будущий endpoint,
его body и auth на этом gate могут оставаться `OPEN`/`N/A` по правилам ниже.

## Как заполнять

Допустимые статусы:

- `N/A` — неприменимо; рядом обязательно написать почему.
- `OPEN` — решения или authoritative source пока нет.
- `PROPOSED` — есть вариант, но владелец его не утвердил.
- `APPROVED` — решение утверждено; указаны approver, дата и evidence/spec.
- `VERIFIED` — approved contract проверен тестом/стендом; указан report.

`OPEN` лучше ложной точности. Если в prototype нет endpoint, method или auth,
не восстанавливайте их из имени файла: для prototype ставьте `N/A`, а будущую
production boundary описывайте отдельно как `PROPOSED`/`APPROVED`.

Для каждой внешней операции скопируйте блок `### B-NNN` внутри раздела 5;
заголовок самого раздела `## 5` оставьте один.
Одна карточка = один HTTP `method + path`, один MCP tool/RPC operation, один тип
queue message либо одна DB/storage operation. Несколько операций получают
разные `B-NNN`; так тело и ошибки одного endpoint не маскируют другой.
Неиспользуемые механизмы пометьте `N/A`, не удаляя основание.

## Gate statuses

Frontmatter в начале файла — короткая сводка human sign-off, которую Агент
читает перед каждым этапом:

| Gate | Что должно быть готово, чтобы поставить `APPROVED` |
|---|---|
| `stage_a_intake` | prototype/target/sources/owners/data policy определены |
| `parity_inputs` | зафиксированы логические inputs, expected invariants и разрешённые fixtures |
| `stage_b_plan` | для каждой boundary owner и target mechanism уже не `OPEN`; открытые детали exact contract перечислены и дают только contract-acquisition task |
| `adapter_implementation` | все реализуемые contracts APPROVED: protocol, request/response/error/auth/mapping |
| `live_validation` | разрешены environment, test data, credentials injection и side effects |
| `release` | identity, processes, build/deploy, operations и acceptance VERIFIED/APPROVED |

Stage A может анализировать file-only prototype без будущих endpoints. Реализация
production adapter не начинается, пока `adapter_implementation` не `APPROVED`.

Перед переходом к этапу человек и Агент вручную сверяют текущий gate и все его
применимые prerequisites. Для `APPROVED`/`VERIFIED` должны быть заполнены
approver, дата и evidence; обязательные для gate поля не должны содержать
неразрешённых placeholders, `TODO`, `TBD` или `UNKNOWN`. `OPEN` допустим только
там, где таблица ниже прямо разрешает его на текущем gate. Проверка формы не
доказывает смысловую корректность контракта: authoritative source, revision,
mapping и scope разрешения всё равно проверяются отдельно.

| Gate | Разделы для ручной проверки |
|---|---|
| `stage_a_intake` | §1–2: passport, sources/owners, access и data policy; будущие boundary contracts/samples могут быть `OPEN/N/A` |
| `parity_inputs` | §3: logical inputs, fixtures, invariants и threshold |
| `stage_b_plan` | §4: у каждого `B-NNN` определены owner и target mechanism; exact contract details могут оставаться `OPEN` только для acquisition task |
| `adapter_implementation` | §4–5: реализуемый `B-NNN` имеет matching card и contract `APPROVED/VERIFIED` |
| `live_validation` | §9: exact environment, data, calls, side effects и разрешение |
| `release` | §7–10 и §12: runtime/deploy, operations, acceptance reports и human sign-off |

## 1. Паспорт инициативы

| Поле | Значение | Status/evidence |
|---|---|---|
| Business outcome | `<что должен давать production-сервис>` | `<status, source>` |
| Пользователи/consumers | `<кто и как вызывает>` | `<status, owner>` |
| Service/repository/package id | `<canonical identifiers>` | `<status, naming source>` |
| Prototype root + revision | `<path, commit/hash/version>` | `<read-only confirmed by>` |
| Target repository | `<path/repo>` | `<status>` |
| Team template + revision | `<exact source>` | `<status>` |
| Product owner | `<name/role/contact>` | `<approval scope>` |
| Technical owner | `<name/role/contact>` | `<approval scope>` |
| Data owner | `<name/role/contact>` | `<approval scope>` |
| Security/operations owners | `<name/role/contact or N/A + why>` | `<approval scope>` |
| Planned environments | `<local/test/stage/prod>` | `<status>` |
| Prototype data classification | `<public/internal/confidential/PII/etc>` | `<data owner/source>` |
| Allowed analysis location | `<local/secure workspace/other>` | `<approval>` |
| Redaction/retention/commit policy | `<rules; raw data commit prohibited by default>` | `<approval>` |
| Deadline/external ticket | `<value or N/A>` | `<source>` |

## 2. Источники истины

| Роль источника | Exact path/link + revision | Что разрешено из него брать | Owner/status |
|---|---|---|---|
| Prototype behavior | `<...>` | prompts, schemas, workflow, errors, File IO | `<...>` |
| Team template | `<...>` | layout, common runtime stack | `<...>` |
| Team docs | `<...>` | conventions and policies | `<...>` |
| API/AsyncAPI/OpenAPI/proto/tool schema | `<... or OPEN/N/A>` | external contract | `<...>` |
| Production neighbour | `<... or N/A>` | implementation pattern, not identifiers | `<...>` |
| Release reference | `<... or N/A>` | build/CI pattern, not service identity | `<...>` |
| Sanitized payload samples | `<... or OPEN/N/A>` | mapping/test evidence | `<classification>` |

Конфликт двух источников не разрешается выбором «более удобного». Запишите его
в decision log и назначьте approver.

## 3. Сохраняемое поведение prototype

### Входы и результаты

| Logical input/output | Schema/format | Required/null/empty rules | Source evidence | Must preserve? |
|---|---|---|---|---|
| `<...>` | `<...>` | `<...>` | `<path:line/cell>` | `<yes/approved deviation>` |

### Инварианты

- Workflow/order of steps: `<...>`
- Prompts and prompt variables: `<path/hash or N/A>`
- LLM provider/model/parameters: `<...>`
- Structured-output schemas: `<...>`
- Retry/timeout/error behavior: `<...>`
- Terminal states and publish-on-success rules: `<...>`
- Allowed side effects: `<...>`
- Known nondeterminism/variance: `<...>`
- Approved behavior deviations: `<decision/approver/date or none>`

### Parity data

| Поле | Значение/status |
|---|---|
| Sanitized fixtures or approved data source | `<...>` |
| Expected source of truth | `<prototype/reference/human-approved>` |
| Required deterministic fields | `<...>` |
| LLM repeat count and variance rule | `<...>` |
| Metric and threshold | `<...>` |
| Data retention/sanitization | `<...>` |
| Approver | `<...>` |

## 4. Boundary inventory

| Boundary id | Direction | Prototype state | Target mechanism | Owner | Contract status | Card section |
|---|---|---|---|---|---|---|
| `B-001` | `<in/out/bidirectional>` | `<FILE_ONLY/EXISTING_EXTERNAL/NONE>` | `<API/MCP_TOOL/QUEUE/DB/STORAGE/FILE/N/A/OPEN>` | `<owner/OPEN>` | `<OPEN/PROPOSED/APPROVED/VERIFIED>` | `<anchor>` |

Классификация:

- `FILE_ONLY` — prototype читает/пишет файлы; transport-поля prototype = `N/A`.
- `EXISTING_EXTERNAL` — интеграция реально вызывается; нужен authoritative contract.
- `NONE` — будущей boundary в prototype нет; target contract проектируется отдельно.

## 5. Карточки boundaries

### B-001 — `<operation name>` (скопировать этот блок для каждой операции)

#### 5.1 Идентичность и ownership

| Поле | Значение | Status/evidence |
|---|---|---|
| Boundary id/name | `<B-NNN / name>` | `<...>` |
| Business purpose | `<...>` | `<owner>` |
| Direction | `<inbound/outbound/bidirectional>` | `<...>` |
| Prototype classification | `<FILE_ONLY/EXISTING_EXTERNAL/NONE>` | `<path evidence>` |
| Prototype mechanism | `<file/path/tool/API/etc or N/A>` | `<observed evidence>` |
| Target mechanism | `<REST/MCP_TOOL/QUEUE/DB/STORAGE/FILE/etc>` | `<PROPOSED/APPROVED>` |
| Source-of-truth owner | `<team/system>` | `<approval>` |
| Consumer/client owners | `<teams/systems>` | `<approval>` |
| Authoritative contract | `<versioned path/link/version>` | `<status>` |
| Contract approver/date | `<person/date>` | `<evidence>` |

#### 5.2 Transport contract

##### REST/HTTP — либо `N/A + reason`

| Поле | Значение/status |
|---|---|
| Direction and base URL source | `<inbound/outbound; config key, no secret>` |
| Method + exact path | `<POST /v1/...>` |
| Path/query parameters | `<name, type, required, encoding>` |
| Required headers | `<name, source, required; no secret value>` |
| Tenant/correlation/idempotency headers | `<rules>` |
| AuthN/AuthZ mechanism | `<mTLS/OAuth/service token/etc>` |
| Content type/encoding/compression | `<...>` |
| Request body schema id/ref/version | `<exact ref/version or N/A>` |
| Canonical sanitized request fixture | `<path/hash or N/A>` |
| Semantically relevant response headers | `<names/rules or N/A>` |
| Versioning/deprecation policy | `<...>` |
| OpenAPI/source revision | `<...>` |

##### MCP tool/RPC — либо `N/A + reason`

| Поле | Значение/status |
|---|---|
| Server/tool or RPC name | `<exact name>` |
| Input schema/version | `<path/hash>` |
| Output/content schema | `<path/hash>` |
| Error/result semantics | `<...>` |
| Authentication/authorization | `<...>` |
| Capability/version negotiation | `<...>` |

##### Queue/event — либо `N/A + reason`

| Поле | Значение/status |
|---|---|
| Broker/topic/queue source | `<config key, no credential>` |
| Producer/consumer owner | `<...>` |
| Message key/partition/ordering | `<...>` |
| Schema + version/registry | `<...>` |
| Delivery semantics | `<at-most/at-least/exactly once assumptions>` |
| Ack/retry/DLQ policy | `<...>` |

##### DB/storage/file — либо `N/A + reason`

| Поле | Значение/status |
|---|---|
| Technology/location source | `<config/owner>` |
| Schema/table/bucket/path convention | `<...>` |
| Read/write ownership | `<...>` |
| Transaction/concurrency/locking | `<...>` |
| Retention/cleanup/durability | `<...>` |
| Migration/versioning policy | `<...>` |

#### 5.3 Request/input schema

| Field/path | Source field | Type | Required | Null/empty | Format/unit/timezone | Enum/default | Sensitive class | Sanitized example | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| `<...>` | `<prototype/file field>` | `<...>` | `<yes/no>` | `<rules>` | `<...>` | `<...>` | `<public/internal/PII/etc>` | `<...>` | `<spec/path>` |

Укажите также rules для absent, extra и malformed fields, aliases, date/decimal
encoding, batch limits и maximum payload size.

#### 5.4 Response/output schema

| Variant/status | When | Body/schema | Required fields | Null/empty rules | Terminal meaning | Side effect/publish | Evidence |
|---|---|---|---|---|---|---|---|
| `<success/HTTP 2xx/tool result/event>` | `<condition>` | `<path/version>` | `<...>` | `<...>` | `<...>` | `<...>` | `<...>` |

#### 5.5 Errors and reliability

| Failure | Transport status/code | Body/schema | Retryable? | Retry/backoff | Timeout | Caller action | Terminal/side-effect rule |
|---|---|---|---|---|---|---|---|
| `<validation/auth/not-found/conflict/rate-limit/server/timeout>` | `<...>` | `<...>` | `<...>` | `<...>` | `<...>` | `<...>` | `<...>` |

- Idempotency/deduplication: `<...>`
- Ordering/concurrency: `<...>`
- Rate/size limits: `<...>`
- Availability/SLO assumptions: `<...>`
- Circuit breaker/fallback: `<approved behavior or N/A>`

#### 5.6 Prototype → target mapping

| Prototype source/path | Target request field | Target response → domain field | Transform | Loss/default | Test case/evidence |
|---|---|---|---|---|---|
| `<...>` | `<...>` | `<...>` | `<date/alias/enum/etc>` | `<none/approved>` | `<...>` |

Любая потеря поля, новый default или изменение error/terminal semantics требует
отдельного approved behavior deviation.

#### 5.7 Security and data policy

| Поле | Решение/status |
|---|---|
| Data classification | `<public/internal/confidential/PII/etc>` |
| Legal/consent basis | `<... or N/A>` |
| Secret/certificate injection | `<secret manager/config source; no values>` |
| Encryption in transit/at rest | `<...>` |
| Logging/redaction policy | `<allowed fields/prohibited raw data>` |
| Retention/deletion | `<...>` |
| Allowed environments/regions | `<...>` |
| Security approver | `<...>` |

#### 5.8 Contract and live-test evidence

| Check | Input/environment | Expected | Authorization | Report/status |
|---|---|---|---|---|
| Schema/contract test | `<sanitized fixture>` | `<...>` | `<owner>` | `<...>` |
| Mapping edge cases | `<absent/null/empty/malformed/valid>` | `<...>` | `<owner>` | `<...>` |
| Live smoke | `<stage + test entity>` | `<business terminal result>` | `<explicit approval>` | `<...>` |
| Cleanup/rollback | `<created side effects>` | `<cleanup rule>` | `<owner>` | `<...>` |

Boundary readiness: `<OPEN/PROPOSED/APPROVED/VERIFIED>`  
Approver/date/evidence: `<...>`

## 6. LLM and model contract

| Поле | Prototype value/source | Target value/source | Status/approval |
|---|---|---|---|
| Provider/model/base URL config key | `<...>` | `<...>` | `<...>` |
| Prompt paths/hashes | `<...>` | `<...>` | `<...>` |
| temperature/top_p/top_k/min_p | `<...>` | `<...>` | `<...>` |
| timeout/retries/backoff | `<...>` | `<...>` | `<...>` |
| response_format/schema/name | `<...>` | `<...>` | `<...>` |
| moderation/profanity/verification flags | `<...>` | `<...>` | `<...>` |
| Token/context limits | `<...>` | `<...>` | `<...>` |
| Allowed live environments/data | `<...>` | `<...>` | `<...>` |

Secrets и реальные prompt/response с confidential data сюда не вставлять.

## 7. Process and runtime topology

| Process id | Type | Exact entrypoint/target | Trigger | Input boundary | Output/terminal state | Owner | Scale/SLO | Status |
|---|---|---|---|---|---|---|---|---|
| `P-001` | `<library/CLI/API/worker/scheduler/init-db>` | `<module:object/command>` | `<...>` | `<B-NNN>` | `<...>` | `<...>` | `<...>` | `<...>` |

- Dependency source/allowlist: `<...>`
- Runtime/Python version: `<...>`
- Config overlays and precedence: `<...>`
- Resource/bundle requirements: `<prompts/templates/tokenizer/etc>`
- Health/readiness/metrics mechanism: `<approved team pattern>`
- Logging/tracing correlation fields: `<...>`
- DB owner/schema/migration policy: `<... or N/A>`

## 8. Build, deploy and operations

| Поле | Значение/status/evidence |
|---|---|
| Canonical service/distribution/image identifiers | `<...>` |
| Build artifact and entrypoint | `<...>` |
| Base image/runtime source | `<...>` |
| CI job/pipeline/library identifiers | `<...>` |
| Deployment topology/replicas/resources | `<...>` |
| Config/secret/certificate source names | `<names only, no values>` |
| Migration/init ordering | `<... or N/A>` |
| Rollout/rollback strategy | `<...>` |
| Alerts/dashboards/SLO owner | `<...>` |
| Runbook/on-call/escalation | `<...>` |
| Release approver | `<...>` |

Не копируйте identifiers из соседнего сервиса: reference подтверждает паттерн,
но конкретные имена утверждает владелец target.

## 9. Live validation authorization

| Поле | Значение/status |
|---|---|
| Environment/stand identity | `<...>` |
| Time window | `<...>` |
| Test principal/credentials injection | `<secure source; no values>` |
| Allowed data/sample ids | `<sanitized/approved>` |
| Allowed calls and maximum volume | `<...>` |
| Allowed DB/queue/storage mutations | `<...>` |
| Forbidden side effects | `<...>` |
| Cleanup/rollback owner | `<...>` |
| Evidence retention/redaction | `<...>` |
| Explicit approver/date | `<...>` |

Watcher или доступ к среде не является live authorization.

## 10. Acceptance and release proof

| Gate | Command/report | Expected threshold/outcome | Owner | Status |
|---|---|---|---|---|
| Clean install/import | `<...>` | `<...>` | `<...>` | `<...>` |
| Repository verify | `<...>` | `<...>` | `<...>` | `<...>` |
| Prototype parity | `docs/harness/evals/prototype-parity.md` | `<...>` | `<...>` | `<...>` |
| Boundary contract/mapping | `<report per B-NNN>` | `<...>` | `<...>` | `<...>` |
| Build/artifact smoke | `<...>` | `<...>` | `<...>` | `<...>` |
| Process registration/startup | `<...>` | `<...>` | `<...>` | `<...>` |
| Authorized live/stand smoke | `<...>` | `<terminal + side effects>` | `<...>` | `<...>` |
| Rollback/operations handoff | `<...>` | `<...>` | `<...>` | `<...>` |

## 11. Decisions, gaps and approvals

| ID/date | Scope | Fact/conflict | Decision needed or made | Options/consequences | Owner/approver | Status/evidence | Unblocks |
|---|---|---|---|---|---|---|---|
| `D-001` | `<...>` | `<...>` | `<...>` | `<...>` | `<...>` | `<OPEN/APPROVED + path>` | `<gate/tasks>` |

## 12. Human sign-off

| Role | Name | Approved scope | Date | Evidence/ticket |
|---|---|---|---|---|
| Product owner | `<...>` | `<behavior/use case>` | `<...>` | `<...>` |
| Technical owner | `<...>` | `<architecture/process>` | `<...>` | `<...>` |
| Data owner | `<...>` | `<boundary/data/mapping>` | `<...>` | `<...>` |
| Security owner | `<... or N/A>` | `<live/data/auth>` | `<...>` | `<...>` |
| Operations/release owner | `<... or N/A>` | `<deploy/stand>` | `<...>` | `<...>` |

Перед сменой frontmatter gate на `APPROVED` проверить, что обязательные для него
поля не содержат неразрешённых placeholders или контрактов без owner; `OPEN`
допустим только в явно разрешённых для текущего gate полях.

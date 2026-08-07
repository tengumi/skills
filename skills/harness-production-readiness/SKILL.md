---
name: harness-production-readiness
description: "Исполняет одну bounded Stage-B или Stage-C capability без изменения бизнес-логики: dependency, config, contract, adapter, process, DB, observability, deploy, runbook или stand. Используй только для plan-generated task с явным skill_mode либо после delta-plan классифицированного production incident."
---

# harness-production-readiness

## Цель

Довести уже перенесённый прототип до production-ready runtime без изменения
бизнес-логики. Этот skill исполняет одну связанную capability task после
`harness-production-plan`; он не создаёт универсальную очередь и не объединяет
несколько независимых поздно обнаруженных capabilities в одну правку. Для одной
external boundary режим `adapter` включает совместимый SDK constraint,
provider/client lifecycle, mapping, production DI и protocol tests: эти части не
нужно искусственно разделять.

Ключевое правило: **hardening не меняет prompts, LLM provider/model/params, schemas, retry/timeouts и workflow semantics**. Любое такое изменение — отдельная behavior-change задача.

## Входной Контекст

Перед кодом прочитай:

1. `AGENTS.md`
2. `docs/harness/architecture.md`, `conventions.md`, `dev-setup.md`, `cicd.md`
3. `docs/harness/prototype-analysis.md`, если репа является ported prototype
4. `docs/harness/env-vars.md`, если есть
5. `docs/harness/team-patterns-production.md` и read-only team conventions
6. current/target data-boundary classification, integration/interface inventory
   и текущую задачу в `docs/harness/tasks.json`; для external boundary прочитать
   SDK constraint/lock, transport, local/cluster access, object/session scope,
   create/close events, startup/readiness criticality, retry owner и failure
   boundary
7. `docs/harness/pre-industrialization-spec.md` с записью текущего подключения и
   `docs/harness/data-boundaries.md`, если он уже есть. В режиме `contract`
   отсутствующая техническая карта создаётся из канонического kit/team template,
   а секция может быть неполной — задача заполняет её. В режиме `adapter` карта
   обязана быть не ниже `MAPPED`: exact operation/revision/auth/mapping известны
   и material conflicts отсутствуют
8. `docs/harness/production-applicability.md` и phase/prerequisite evidence
   текущей задачи. Для isolated incident без полного Stage-B/C plan сначала
   выполнить delta-run `harness-production-plan`.

Если evidence нужного уровня ещё нет, выполнить только gate, назначенный task по
verification pyramid. Clean install/build не переносить в обычную capability:
он принадлежит dependency/bundle wave либо текущей deploy task, если изменены
его входы. Отдельный environment-report не создавать.

Для execution/verify используй `harness-request-exec`, если AGENTS.md требует watcher.

## Выбор `skill_mode`

Текущая задача должна содержать один `skill_mode`: `dependency`, `config`,
`contract`, `adapter`, `process`, `db`, `observability`, `deploy`, `runbook` или `stand`.
Если mode отсутствует или не входит в этот список — STOP и вернуть задачу в
`harness-production-plan`. Не восстанавливать mode из title/acceptance и не
исполнять несколько modes за один claim.

Task также должна содержать один `verification_level`: `scoped`, `capability`,
`runtime` или `bundle`. Если его нет — STOP и вернуть задачу planner:

- `scoped` → changed tests/imports и Ruff;
- `capability` → scoped checks плюс полный unit/contract набор capability;
- `runtime` → только единая `offline-runtime-lifecycle` process task с real app,
  production DI/lifespan;
- `bundle` → только один final bundle owner с clean install/build/inventory и
  artifact process smoke.

`live` не является verification level: реальные системы остаются отдельным
`harness-eval:live` route.

При `skill_mode=deploy` полностью прочитать
[references/deploy.md](references/deploy.md). Для остальных modes этот reference
не загружать.

Использовать только относящиеся к mode подразделы ниже:

| `skill_mode` | Подразделы |
|---|---|
| `dependency` | Dependency compatibility и Workflow |
| `config` | Runtime config |
| `contract` | Contract acquisition and design |
| `adapter` | External adapters and generated clients |
| `process` | Production process topology |
| `db` | Database and Alembic |
| `observability` | Structured logging, Health/readiness, OpenTelemetry |
| `deploy` | deploy reference, Container/build, CI/CD |
| `runbook` | Runbook |
| `stand` | Integration readiness, Stand validation |

## Production-Readiness Slices

Работай маленькими задачами. Один slice = один bounded change set.

### 0. Dependency compatibility

Режим `dependency` использовать для workspace-wide baseline или отдельного
compatibility investigation. Изменение зависимости, принадлежащей одной
external boundary, выполнять в её `adapter` capability вместе с lifecycle, DI и
protocol tests.

- Сопоставь manifest constraint, реально locked version, import/runtime API и
  version из authoritative reference.
- Lower-bound-only constraint вроде `mcp>=1.0` не является доказательством
  совместимости со следующим major. Если следующий major не проверен, используй
  evidence-backed exact pin или совместимый upper bound (`<next-major`) и
  зафиксируй lock.
- Approval на добавление dependency разрешает изменение manifest/lock, но не
  доказывает API/lifecycle compatibility.
- После изменения выполнить clean resolution/install один раз в bundle/dependency
  wave; не повторять его в каждой следующей task без изменения manifest/lock.

### 1. Runtime config

Добавь typed config boundary для env vars, defaults и secret paths.

- Сохраняй prototype default values.
- Не хардкодь реальные secrets.
- `.env.example` содержит только placeholders.
- Config validation должна падать рано и понятно для обязательных runtime secrets.
- Если нужна новая dependency (`pydantic-settings`, `opentelemetry-*`), используй
  recorded plan authorization; если её нет в разрешённом scope — получи новое
  решение или используй существующие deps.
- Проверяй effective config отдельно для API, worker, scheduler и frozen runtime:
  cwd/resources/env overlays/provider/base URL/TLS не обязаны совпасть с pytest.
- Не создавать DB/network client и обязательный secret-bound config на import
  time, если team pattern явно не требует обратного.

### 2. Structured logging

Переиспользуй logging/middleware/context propagation из common/team pattern.
Добавляй ручной context binding только там, где подтверждён пробел; не
протаскивай его через каждый вызов и не дублируй middleware.

Минимальные поля:

- `run_id` или `request_id`
- `component` / `graph_node`
- `event`
- `duration_ms` для внешних вызовов
- `status` / `error_type`

Не логируй secrets, raw cert paths with private material, full prompts/responses по умолчанию. Prompt/response logging только через explicit debug/audit mode.

### 3. Health/readiness

Точные paths и механизм брать только из `team-patterns-production.md` и common
library. Generic `/health`/`ready` — не дефолт, если команда использует actuator.
До локальной реализации проверить, не предоставляет ли common готовые app-init,
health/readiness/prometheus hooks. Worker/scheduler probes проверять отдельно.

Health должен быть дешёвым. Readiness может проверять config, cert files, writable output dirs и optional connectivity. Не делай дорогой LLM call в default health.

### 4. OpenTelemetry

Добавляй instrumentation как optional runtime capability.

Span candidates:

- top-level run / request
- graph node / pipeline step
- LLM call
- RAG/API call
- retry attempt
- finalization/output write

Атрибуты: provider/model name, section, query count, duration, status. Не добавляй raw prompts/responses в spans.

### 5. Container/build

Это `skill_mode=deploy`. Следовать `references/deploy.md`; отдельно доказать
наличие dependency в build env, включение static/dynamic modules в bundle и
наличие runtime data в artifact/image. Сам artifact entrypoint должен реально
запуститься в DB-safe режиме.

### 6. CI/CD

Это также `skill_mode=deploy`. CI должен воспроизводить подтверждённые install,
import, verify, build и artifact/process smoke. Изменять только approved paths и
identifiers по `references/deploy.md`; live external tests не входят в default CI.

### 7. Runbook

Создай `docs/harness/runbook.md` только из применимых failure modes, доказанных
architecture, production-applicability, integration matrix и реальными
инцидентами. Для каждого: symptoms, likely causes, safe checks, remediation и
escalation. Не добавлять LLM, RAG, certificates, queues или DB как обязательные,
если их нет в утверждённой topology.

В C3 после завершённых либо доказанно неприменимых C2 gates подготовь компактный
release decision packet. Если runbook не применим, не создавай шумовой документ,
но всё равно запроси у владельца `APPROVE` или `DEFER` и запиши роль/имя, дату,
scope и ссылки на C2 evidence. Codex не принимает это решение сам.

### 8. Integration readiness

Опиши static parity и live/runtime gates раздельно: команды, env, artifacts,
source/provider и, если external boundary применима, route/tool, headers,
request/response и prerequisites. Worker middleware success-log не доказывает
business success, если exception проглочен или publish не произошёл.

Любой внешний live-вызов или side effect требует отдельного текущего
authorization в policy, task или evidence с exact environment/data/action
scope. Паспорт подключений и технический доступ такого разрешения не дают.
Локальный/mock/static smoke authorization не требует, но не может называться
live proof.

Network-free запуск реального `create_app`/`app` с production DI/lifespan и
protocol-faithful transport stub относится к `skill_mode=process`, а не к
`harness-eval`. Он обязателен после B2 wiring и не является live proof.

### 9. Contract acquisition and design

Этот mode не реализует adapter. Для существующей интеграции он находит
authoritative versioned spec/catalog и sanitized sample; для новой — готовит
proposal с механизмом, request/response/error/auth, reliability и mapping.
Технические факты и gaps вносятся в точную секцию `data-boundaries.md`.

Если существующий официальный контракт полон, секция получает состояние
`DOCUMENTED`/`MAPPED` по evidence без дополнительного слова согласования. Если
проектируется новая boundary или источники конфликтуют, задача остаётся
design/acquisition checkpoint, а зависимый `adapter` не claim-ится.

### 10. External boundary capability and generated clients

До кода проверить matching-секцию `data-boundaries.md`: состояние не ниже
`MAPPED`, известны официальный source/revision, endpoint/tool/topic,
request/response/error/auth, mapping и проверки, material conflicts отсутствуют.
Сам факт существования open task или строки в паспорте contract readiness не
доказывает.

В одной capability довести всю boundary: совместимый SDK constraint и lock,
side-effect-free provider/factory, lifecycle активного connection/session,
adapter mapping, production DI wiring и protocol tests. Не создавать отдельные
задачи на эти части, если они не являются workspace-wide проблемой.

`APP` scope side-effect-free config/factory/client object не разрешает eager
network. Активный session/stream/handshake открывать request/task-lazy и закрывать
в том же bounded lifecycle. Eager startup connection допустим только если
authoritative process/boundary contract прямо объявляет boundary startup-critical
и это отражено в readiness.

Сначала определить один из двух путей:

- **Existing integration:** получить exact contract из versioned spec/tool
  catalogue и sanitized real sample; проверить method/path, headers, aliases,
  encoding, absent/null/empty/malformed/valid и prerequisites.
- **Greenfield boundary:** до adapter создать отдельную architecture/design
  задачу, определить mechanism, sync/async semantics, schema/versioning,
  security, idempotency, errors/retries/timeouts и SLO. Затем зафиксировать
  versioned target contract и spec-first fixtures.

`NO_EXTERNAL_BOUNDARY` в прототипе — не `UNKNOWN` существующего endpoint.
Нельзя требовать real payload до появления новой интеграции или выводить route
из прежнего file path.

Generated clients должны иметь source spec, воспроизводимую generation command и
clean-regeneration check. Ручной adapter поверх клиента тестируется отдельно;
не коммитить или регенерировать clients вопреки team policy.

Для MCP/SSE и других stateful протоколов protocol test должен сохранять
production client, provider и DI, подменяя только внешнюю сторону транспорта.
Stub эмулирует фактическую последовательность SDK: transport connect,
advertised endpoint/handshake, initialize и initialized notification при
необходимости, discovery (`tools/list`) или разрешённый operation call,
`TextContent`/`isError` либо эквивалентные contract outcomes, close и unavailable
case. Fake `ClientSession`, fake provider или bypass production DI не являются
доказательством lifecycle.

### 11. Production process topology

После утверждения target topology построить process matrix и реально запустить
каждый применимый режим:

- package import без сети/DB side effects;
- app factory/API startup;
- фактический taskiq/celery worker target и наличие task в registry;
- enqueue payload → decorated task → DI injection → service → terminal state;
- scheduler/beat target;
- init_db/migration hook;
- те же entrypoints из `dist/main`/target image.

Unit test wrapper signature недостаточен: framework wiring проверять
поведенческим smoke.

После завершения всех B2 boundary/process tasks выполнить один агрегированный
offline-runtime-lifecycle gate:

- запустить реальный экспортируемый `create_app`/`app`, production container/DI
  и настоящий lifespan, а не bare `FastAPI()` или test-only composition;
- подменить только внешние transport endpoints protocol-faithful локальными
  stubs; production provider/client/adapter/DI оставить настоящими;
- проверить API и worker paths, если они применимы;
- доказать, что недоступность не-startup-critical boundary не роняет startup,
  session открывается только в соответствующем request/task, ошибка остаётся в
  его failure boundary, а close освобождает ресурс;
- выполнять без live network, broker и shared-DB side effects. Это readiness
  evidence, не `harness-eval:live`.

### 12. Database and Alembic

До правки классифицировать четыре состояния: source migrations, bundled
migrations, DB `alembic_version`, ownership/target schema. Снять inventory и
heads из source и dist. Unknown revision может быть packaging miss, missing
source migration или stale/foreign DB — эти причины требуют разных действий.
Не восстанавливать migration и не stamp/reset общую DB без подтверждённого owner.

### 13. Stand validation

Разбирать первый запуск слоями: executor → install/dependency → bundle/resources
→ effective config → DB/migrations → process topology → применимая data boundary
→ LLM/provider → business flow. Новый лог открывает следующий слой; одна задача не
должна чинить сразу несколько. Для каждого incident сначала read-only facts,
затем classification и минимальная правка соответствующего слоя.

Если это clean-release/stand task C2, после зелёных проверок подготовить
короткий пакет решения для C3. Не запрашивать и не записывать `APPROVE`/`DEFER`
в этой task: владельца спрашивает последующий operations-handoff route после
завершения всех обязательных C2 gates.

## Workflow

0. Проверь, что task создан авторизованным планом B/C и exact safe offline
   dependency/protected paths входят в записанную plan authorization. Она
   действует на все перечисленные tasks и не запрашивается повторно при claim.
   Новое решение нужно только при выходе за scope, конфликте/новой boundary,
   live, shared-DB/migration side effect или deploy execution. Для `adapter`
   дополнительно нужны
   contract-ready matching-секция `data-boundaries.md` и официальный
   source/revision. Для внешнего вызова в `stand` нужно отдельное текущее
   authorization с точным environment/data/action scope. Неполный prerequisite
   → STOP с одним коротким списком недостающих сведений, не claim/код.
   Для полного маршрута B/C отсутствие applicability matrix и
   plan-generated task — STOP → `harness-production-plan`. Если новый stand log
   открыл другой layer, не расширять текущую task: вернуть evidence для delta
   replan и отдельной corrective task.
1. Проверь один явный `skill_mode` и ровно один слой из task acceptance.
2. Сними baseline и факты этого слоя; отдели pre-existing failure от introduced.
3. Сверь protected files и preservation checklist.
4. Реализуй минимальный bounded change.
5. Выполни ровно записанный `verification_level`:
   - `scoped`: scoped tests/imports и Ruff;
   - `capability`: scoped плюс полный unit/contract набор capability;
   - `runtime`: один real-app offline-runtime-lifecycle gate после B2 wiring и
     применимых cleanup/observability изменений;
   - `bundle`: один clean install/build, artifact inventory и process smoke
     после изменения dependency/resource/build/entrypoint surfaces.
   Реальные внешние системы проверяет только отдельный `harness-eval:live`.
   Не запускать `make verify`/clean build после каждой task автоматически.
   Зелёное evidence можно переиспользовать, если его commit — предок текущего
   HEAD, а diff после него не затрагивает записанные invalidation paths gate.
6. Для stand issue приложи sanitized runtime evidence того же execution mode.
7. Обнови только затронутую harness-документацию.
8. Evidence: capability, facts/root cause, changed files, exact commands/counts,
   contract diff, source/frozen/stand result и unresolved owner decisions.

## Hard Limits

- Не менять prompts, schemas, LLM provider/model/params, retry/timeouts и workflow routing.
- Не добавлять dependencies без approval или dependency policy check.
- Не запрашивать повторно authorization на safe offline
  dependency/protected path, уже точно перечисленный в авторизованном Stage-B
  plan.
- Не оставлять lower-bound-only dependency range, допускающий непроверенный
  следующий major; approval dependency не заменяет compatibility evidence.
- Не коммитить `.env`, certs, logs, raw integration outputs, PII/confidential fixtures.
- Не включать live network tests в default `make verify`.
- Не писать fake deployment identifiers. Если `sm_id`, base image, Jenkins library или secret name неизвестны — спроси.
- Не удалять existing harness audit files (`exec-requests`, `exec-reports`, `exec-processed`).
- Не заменять root/project dependency lists содержимым release pyproject. Делать
  diff/merge, сохранять agent-specific imports, shared pins не менять молча.
- Не объявлять readiness по unit/static golden или `make build` без запуска
  production entrypoints и inventory frozen resources.
- Не считать bare `FastAPI()`, fake ClientSession/provider или test-only DI
  доказательством production lifecycle.
- Не считать `APP` scope разрешением на eager network session/stream/handshake.
- Не менять код при external DB/executor mismatch, пока слой не классифицирован.
- Не смешивать независимые config/build/migration/integration fixes в одной задаче.
- Не реализовывать greenfield adapter до утверждённого target contract; отсутствие
  endpoint в прототипе не является основанием его угадывать.
- Не считать queue status, transport access, соседний сервис или заполненный
  паспорт доказательством contract readiness либо разрешением на live-action.
- Не оставлять временный file-backed parity adapter в production path молча.
  Если target architecture действительно сохраняет File IO, отдельно доказать
  storage ownership, durability, permissions, lifecycle, concurrency и cleanup.
- Не запускать source/frozen/container startup, способный применить migrations,
  против unknown/shared DB. Сначала owner или isolated/read-only mode.
- Не выполнять static `T-101…T-120` каталог целиком. Task должна иметь
  applicability evidence, resolved paths, prerequisites, `verification_level`
  и exact `harness-*` route из `harness-production-plan`.
- Не превращать новый runtime incident в продолжение текущей task; один лог
  открывает следующую capability и требует delta replan.

## Output

При успехе сообщи:

- какой `harness-production-readiness` slice выполнен;
- какой `verification_level` выполнен и какое evidence переиспользовано;
- какие файлы изменены;
- какие проверки прошли;
- матрицу clean install / verify / build / source processes / frozen processes /
  stand smoke со статусом каждого применимого решения и разрешения;
- что осталось до full production-ready;
- какие decisions требуют человека.
- evidence для обновления production-applicability отдельным planning handoff.

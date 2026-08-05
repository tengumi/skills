---
name: harness-production-readiness
description: "Исполняет один bounded Stage-B slice без изменения бизнес-логики: dependency, config, contract, adapter, process, DB, observability, deploy, runbook или stand. Используй только для plan-generated task с явным skill_mode либо после delta-plan классифицированного production incident."
---

# harness-production-readiness

## Цель

Довести уже перенесённый прототип до production-ready runtime без изменения
бизнес-логики. Этот skill исполняет одну thin task после
`harness-production-plan`; он не создаёт универсальную очередь и не объединяет
несколько поздно обнаруженных layers в одну правку.

Ключевое правило: **hardening не меняет prompts, LLM provider/model/params, schemas, retry/timeouts и workflow semantics**. Любое такое изменение — отдельная behavior-change задача.

## Входной Контекст

Перед кодом прочитай:

1. `AGENTS.md`
2. `docs/harness/architecture.md`, `conventions.md`, `dev-setup.md`, `cicd.md`
3. `docs/harness/prototype-analysis.md`, если репа является ported prototype
4. `docs/harness/env-vars.md`, если есть
5. `docs/harness/team-patterns-production.md` и read-only team conventions
6. current/target data-boundary classification, integration/interface inventory
   и текущую задачу в `docs/harness/tasks.json`
7. `docs/harness/pre-industrialization-spec.md` с записью текущего подключения и
   `docs/harness/data-boundaries.md`, если он уже есть. В режиме `contract`
   отсутствующая техническая карта создаётся из канонического kit/team template,
   а секция может быть неполной — задача заполняет её. В режиме `adapter` карта
   обязана быть не ниже `MAPPED`: exact operation/revision/auth/mapping известны
   и material conflicts отсутствуют
8. `docs/harness/production-applicability.md` и phase/prerequisite evidence
   текущей задачи. Для isolated incident без полного Stage-B plan сначала
   выполнить delta-run `harness-production-plan`.

Если нужного install/verify/build evidence ещё нет, получить его внутри текущей
задачи минимально достаточной командой и сохранить в task evidence; отдельный
environment-report не создавать.

Для execution/verify используй `harness-request-exec`, если AGENTS.md требует watcher.

## Выбор `skill_mode`

Текущая задача должна содержать один `skill_mode`: `dependency`, `config`,
`contract`, `adapter`, `process`, `db`, `observability`, `deploy`, `runbook` или `stand`.
Если mode отсутствует или не входит в этот список — STOP и вернуть задачу в
`harness-production-plan`. Не восстанавливать mode из title/acceptance и не
исполнять несколько modes за один claim.

При `skill_mode=deploy` полностью прочитать
[references/deploy.md](references/deploy.md). Для остальных modes этот reference
не загружать.

Использовать только относящиеся к mode подразделы ниже:

| `skill_mode` | Подразделы |
|---|---|
| `dependency` | dependency rules в Runtime config и Workflow |
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

### 1. Runtime config

Добавь typed config boundary для env vars, defaults и secret paths.

- Сохраняй prototype default values.
- Не хардкодь реальные secrets.
- `.env.example` содержит только placeholders.
- Config validation должна падать рано и понятно для обязательных runtime secrets.
- Если нужна новая dependency (`pydantic-settings`, `opentelemetry-*`), сначала получи approval или используй существующие deps.
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

### 9. Contract acquisition and design

Этот mode не реализует adapter. Для существующей интеграции он находит
authoritative versioned spec/catalog и sanitized sample; для новой — готовит
proposal с механизмом, request/response/error/auth, reliability и mapping.
Технические факты и gaps вносятся в точную секцию `data-boundaries.md`.

Если существующий официальный контракт полон, секция получает состояние
`DOCUMENTED`/`MAPPED` по evidence без дополнительного слова согласования. Если
проектируется новая boundary или источники конфликтуют, задача остаётся
design/acquisition checkpoint, а зависимый `adapter` не claim-ится.

### 10. External adapters and generated clients

До кода проверить matching-секцию `data-boundaries.md`: состояние не ниже
`MAPPED`, известны официальный source/revision, endpoint/tool/topic,
request/response/error/auth, mapping и проверки, material conflicts отсутствуют.
Сам факт существования open task или строки в паспорте contract readiness не
доказывает.

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

Если это финальная clean-release/stand task, после зелёных проверок подготовить
короткий пакет решения и остановиться до ответа владельца. В canonical report
записать `APPROVE` или `DEFER`, кто и когда решил, точный scope и ссылку на
evidence. Не запрашивать это решение заранее и не принимать его за человека.

## Workflow

0. Проверь, что task создан подтверждённым планом B и имеет все применимые
   разрешения на protected scope. Для `adapter` дополнительно нужны
   contract-ready matching-секция `data-boundaries.md` и официальный
   source/revision. Для внешнего вызова в `stand` нужно отдельное текущее
   authorization с точным environment/data/action scope. Неполный prerequisite
   → STOP с одним коротким списком недостающих сведений, не claim/код.
   Для полного этапа B отсутствие applicability matrix и
   plan-generated task — STOP → `harness-production-plan`. Если новый stand log
   открыл другой layer, не расширять текущую task: вернуть evidence для delta
   replan и отдельной corrective task.
1. Проверь один явный `skill_mode` и ровно один слой из task acceptance.
2. Сними baseline и факты этого слоя; отдели pre-existing failure от introduced.
3. Сверь protected files и preservation checklist.
4. Реализуй минимальный bounded change.
5. Запусти scoped tests, затем `make verify`; при dependency/build/entrypoint/
   resource change дополнительно clean install, import, build и process smoke.
6. Для stand issue приложи sanitized runtime evidence того же execution mode.
7. Обнови только затронутую harness-документацию.
8. Evidence: слой, facts/root cause, changed files, exact commands/counts,
   contract diff, source/frozen/stand result и unresolved owner decisions.

## Hard Limits

- Не менять prompts, schemas, LLM provider/model/params, retry/timeouts и workflow routing.
- Не добавлять dependencies без approval или dependency policy check.
- Не коммитить `.env`, certs, logs, raw integration outputs, PII/confidential fixtures.
- Не включать live network tests в default `make verify`.
- Не писать fake deployment identifiers. Если `sm_id`, base image, Jenkins library или secret name неизвестны — спроси.
- Не удалять existing harness audit files (`exec-requests`, `exec-reports`, `exec-processed`).
- Не заменять root/project dependency lists содержимым release pyproject. Делать
  diff/merge, сохранять agent-specific imports, shared pins не менять молча.
- Не объявлять readiness по unit/static golden или `make build` без запуска
  production entrypoints и inventory frozen resources.
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
  applicability evidence, resolved paths, prerequisites и exact `harness-*`
  route из `harness-production-plan`.
- Не превращать новый runtime incident в продолжение текущей task; один лог
  открывает следующий layer и требует delta replan.

## Output

При успехе сообщи:

- какой `harness-production-readiness` slice выполнен;
- какие файлы изменены;
- какие проверки прошли;
- матрицу clean install / verify / build / source processes / frozen processes /
  stand smoke со статусом каждого применимого решения и разрешения;
- что осталось до full production-ready;
- какие decisions требуют человека.
- evidence для обновления production-applicability отдельным planning handoff.

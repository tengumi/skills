---
name: harness-extract-prod
description: "Извлекает проверяемый production baseline из явно названных источников команды: template задаёт scaffold/runtime stack, production neighbour — implementation pattern, release reference — build/CI baseline. Используй как read-only research pass перед harness-production-plan; конфликты и per-service identifiers не угадывай."
---

# harness-extract-prod

## Цель

Извлечь production/deploy-слой команды и записать в
`docs/harness/team-patterns-production.md`. Каждый факт хранить вместе с ролью и
путём источника; разные источники нельзя молча склеивать:

- **team template** задаёт scaffold, runtime stack и обязательные пустые слои;
- **production neighbour** показывает рабочую реализацию, но может нести legacy;
- **release reference** подтверждает build/CI/package baseline, но не заменяет
  dependency list и бизнес-логику целевого агента.

Отличие от `harness-extract-patterns`: тот извлекает общие конвенции по многим
репам. Этот собирает bounded production baseline из явно названных reference
roles и выносит их конфликты человеку.

## Когда применять

- Перед этапом production-доводки, один раз на команду/архетип.
- Указан team template (`reference_service`). Production neighbour и release
  reference опциональны, но их роль должна быть названа явно.
- Нужен `team-patterns-production.md`, которого ещё нет или он неполный.

НЕ применять: для архитектурных/структурных конвенций (это документация
команды или `harness-extract-patterns`); для самого переноса логики.

## Не дублируй то, что уже есть от команды

Если в `docs/harness/` уже лежат файлы конвенций от команды (architecture.md,
configuration.md, conventions.md, dev-setup.md, project_structure.md, rules.md) —
ПРОЧИТАЙ их и НЕ переписывай. Они покрывают структуру/слои/config/правила.
Твоя задача — только deploy/ops-слой, которого там обычно нет. На пересечениях
ссылайся на их файлы, не копируй.

## Что извлекать из эталона (deploy/ops-слой)

Прочитай в `reference_service` и зафиксируй ФАКТИЧЕСКИ найденное (не дефолты):

1. **Container/build**
- Dockerfile: base image (точное имя), WORKDIR, что COPY (dist/main?), CMD
- сборка: uv build? pyinstaller –onedir? –collect-all/–add-data для resources?
- install.sh / Makefile build/publish targets
2. **CI/CD**
- Jenkinsfile: shared library (имя@версия), pipeline-функция, service-config
  type и stages
- Jenkinsfile_argocd / enablers если есть
- sonar-project.properties
3. **DevSecOps**
- config/devsecops-config.yml: все обязательные поля, их смысл и источник;
  отдельно отметить shared defaults и per-service identifiers. Конкретные
  значения целевой сервис подтверждает сам.
4. **Health/actuator**
- точные health/readiness/metrics paths
- через какой team common/app-init module
- worker/scheduler probe (aiohttp?)
5. **OpenTelemetry**
- init/config mechanism и обязательные resource attributes
- какие runtime libraries/processes инструментируются
6. **Async runtime (если есть)**
- framework, broker, result backend, middlewares и worker command
7. **Logging (deploy-аспект)**
- logging init из common/team runtime, level mapping и redaction rules
8. **pre-commit**
- какие хуки (ruff, ruff-format, pyproject-fmt, pyright?), на какие пути
9. **Service identity / naming**
- repository, service, distribution, Python package, workspace member, image,
  Jenkins job, queue, schema и generated-client tokens;
- какие токены доменные и НЕ должны меняться при service rename.
10. **Install / dependency / frozen bundle**
- точные `make install/verify/build` команды и откуда они читают dependencies;
- root vs project `pyproject`, uv workspace/lock policy;
- PyInstaller spec: hidden imports, hooks, `collect-*`, `add-data`, resources,
  prompts, OpenAPI specs и полный Alembic `versions/`;
- какие модули/файлы загружаются динамически и потому не видны static analyzer.
11. **Runtime processes**
- реальные import targets API, worker, scheduler/beat и init_db;
- как task modules попадают в registry и как DI оборачивает task payload;
- smoke-команды для source runtime и `dist/main`/target image.
12. **OpenAPI / generated clients**
- source spec и его version/hash, generation command, committed/generated policy,
  clean-regeneration check и ручные adapter layers поверх generated клиента.
13. **Database / Alembic**
- `script_location`, где лежит `versions`, startup migration policy, schema,
  owner и безопасная команда inventory/heads;
- неизвестный owner общей DB всегда остаётся open question.
14. **Common-library reuse**
- какие health/logging/OTel/app-init реализации предоставляет общая библиотека;
  локальный дубль не создавать до проверки common.
15. **External client lifecycle**
- для каждой production boundary: package/SDK, manifest constraint и locked
  version, transport, local/cluster access;
- scope side-effect-free client/factory и отдельно scope активного
  connection/session/stream; create/close events;
- startup/readiness criticality, failure boundary, retry owner и provenance.
- `APP` scope объекта не означает разрешение открывать сеть при import/startup:
  eager session/handshake допустимы только по явному team contract.

## Workflow

1. Прочитай существующие team-файлы в `docs/harness/` (не дублируй их).
2. Прочитай team template и, если переданы, production neighbour/release reference
   в части deploy/ops. Не назначай один источник каноном для всех аспектов.
3. Для каждого аспекта зафиксируй факт + роль + путь источника. Конфликт оформить
   таблицей `источник → значение → решение/OPEN`, а не выбирать молча.
4. Запиши `docs/harness/team-patterns-production.md` (структура ниже).
5. Отчёт: что извлечено, что осталось open question, какие значения требуют
   подтверждения человеком (sm_id, namespace, secret paths).

## Структура team-patterns-production.md

# Team Patterns — Production / Deploy
*Извлечено из эталона: <reference_service>, <дата>*
*Структурные конвенции — см. architecture.md / conventions.md / project_structure.md (не дублируются здесь).*

## CONTAINER / BUILD
- base image: <...>  (источник: <путь>)
- сборка: <uv build / pyinstaller ...>
- resources в образе: <--add-data ...>

## CI/CD
- Jenkinsfile: @Library('<...>'), <pipeline-функция>, stages: <...>
- argocd/enablers: <...>
- sonar: <...>

## DEVSECOPS
- обязательные поля devsecops-config.yml: <field → meaning → provenance>
- per-service identifiers: <требуют подтверждения владельца>

## HEALTH / ACTUATOR
- пути: <...>; shared/common mechanism: <...>
- worker probe: <...>

## OPENTELEMETRY
- init/config: <...>; инструментируется: <...>; resource attrs: <...>

## ASYNC RUNTIME
- framework: <...>; broker: <...>; backend: <...>; middlewares: <...>

## LOGGING (deploy)
- init mechanism: <...>; level mapping: <...>; redaction: <...>

## PRE-COMMIT
- хуки: <...>; пути: <...>

## SERVICE IDENTITY
- repository/service/distribution/package/image/job/queue/schema: <...>
- negative-search tokens после rename: <...>

## INSTALL / BUNDLE / RUNTIME PROCESSES
- install/verify/build: <...>
- API/worker/scheduler/init_db targets: <...>
- PyInstaller hidden imports/data/dynamic modules: <...>
- source/frozen/image smoke: <...>

## OPENAPI / GENERATED CLIENTS
- spec + hash/version: <...>; generator: <...>; clean regeneration: <...>

## DATABASE / ALEMBIC
- script_location/heads/versions packaging/schema owner: <...>

## COMMON REUSE
- health/logging/OTel/app-init: <...>

## EXTERNAL CLIENT LIFECYCLE
| boundary | package/SDK | manifest constraint | locked version | transport | local access | cluster access | object scope | connection/session scope | create event | close event | startup-critical | readiness dependency | retry owner | failure boundary | provenance |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <...> | <...> | <...> | <...> | <...> | <...> | <...> | <...> | <...> | <...> | <...> | <yes/no + source> | <...> | <...> | <request/task/process> | <path/revision> |

## SOURCE CONFLICTS
- <aspect>: template=<...>; neighbour=<...>; release=<...>; decision=<OPEN/...>

## OPEN QUESTIONS / требует человека
- <namespace, openshift inventory, secret mount paths, ...>

## Hard Limits

- НЕ дублировать архитектурные/структурные конвенции — они в файлах команды.
- НЕ выдумывать deploy identifiers (service ids, image, namespace) — фактическое
  из эталона или open question.
- НЕ копировать реальные секреты/credentials из эталона; только имена/паттерны.
- НЕ смешивать несколько reference roles в один «эталон». Каждый факт сохраняет
  provenance; конфликт остаётся OPEN до решения человека.
- Значения, специфичные для конкретного сервиса (sm_id), помечать как
  «подставить своё», не зашивать эталонные.
- НЕ копировать dependency list release целиком: сравнивать и сливать с
  агент-специфичными imports; shared-package pins менять только отдельным решением.
- Не считать lower-bound-only constraint (`pkg>=X`) доказательством совместимости
  со следующим major. Зафиксировать locked version и совместимый диапазон либо
  оставить compatibility gap.

## Output

- `docs/harness/team-patterns-production.md` создан;
- отчёт: извлечённые аспекты, open questions, что требует подтверждения человеком;
- готовность к `harness-production-plan`, который определит применимые задачи;
  затем документ читает `harness-production-readiness`, включая режим `deploy`.

## Связь со скиллами

- Дополняет файлы конвенций команды (architecture/conventions/…) — deploy-слоем.
- Потребители: `harness-production-plan`, `harness-production-readiness`
  (включая `skill_mode: deploy`), `harness-team-layout-alignment`.
- Аналог для общих конвенций по многим репам: `harness-extract-patterns`.

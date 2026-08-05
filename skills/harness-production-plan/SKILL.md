---
name: harness-production-plan
description: "Строит evidence-based план этапа B после parity-переноса: проверяет применимость production-срезов, зависимости и технические prerequisites, затем создаёт упорядоченные тонкие задачи с exact harness routes и динамическими id. Используй после harness-extract-prod и до harness-production-readiness, когда нужно сформировать или пересобрать очередь production-доводки без фиксированного T-101 шаблона."
---

# harness-production-plan

## Цель

До первой production-правки увидеть весь применимый объём этапа B и расположить
его по зависимостям. Не копировать универсальный список задач: сначала доказать
для каждого слоя `required`, `already_satisfied`, `not_applicable` или `blocked`,
затем создать задачи только для реальных gaps.

Этот skill планирует. Реализацию ведут exact `use_skill` и, для многорежимных
skills, обязательный `skill_mode` из созданных задач.

## Обязательный asset

Прочитать целиком `assets/production-hardening-tasks.template.json` относительно
каталога skill. Это каталог task families и gates, а не готовый `tasks.json`.
Его нельзя копировать в очередь целиком.

## Входы

Перед планированием прочитать:

1. текущий git status/base revision, `queue_storage_mode` из tasks-mcp и уже
   существующее runtime evidence. Отсутствующий install/verify/build evidence не
   блокирует планирование: добавить применимую bounded task или acceptance gate;
2. `prototype-analysis.md`, `ds-precheck.md`, `prototype-contract.json` и
   `docs/harness/evals/prototype-parity.md`;
3. существующие read-only team docs: architecture, configuration, conventions,
   project_structure, rules, dev-setup и cicd, если он предоставлен. Отсутствие
   отдельного cicd-документа записать как gap; не запускать bootstrap-full и не
   выдумывать pipeline, если template/release source дают другие evidence;
4. `team-patterns-production.md`, собранный `harness-extract-prod` из отдельно
   названных template, production-neighbour и release-reference ролей;
5. текущий target code, process entrypoints, dependency/build surface,
   integration/data-boundary inventory и `structure-audit.md`, если он существует;
6. `docs/harness/pre-industrialization-spec.md`: прочитать предоставленные
   операции, versioned contracts, addresses/config keys, auth references,
   БД/хранилища и Jenkins/deploy-реквизиты; затем
   `docs/harness/data-boundaries.md`, если техническая карта уже создана.
   Отсутствующий или неполный файл является основанием для bounded contract task,
   а не запретом на планирование. Неизвестное сохранять как blocker, а не
   заполнять по примеру соседнего сервиса;
7. все секции `tasks.json`, чтобы выбрать следующие свободные numeric ids.

Если prototype contract или `harness-eval:prototype-parity` этапа A не зелёный,
production queue не создавать. `harness-golden` создаёт опциональный quality
dataset, а `harness-eval:golden` оценивает по нему agent; ни один не является
gate этапа B без отдельного human decision.

План этапа B всё равно показывается человеку до записи очереди. Для конкретного
внешнего взаимодействия implementation task доступна, когда matching-секция
`data-boundaries.md` не ниже `MAPPED`: известны exact operation, contract
revision, auth mechanism и mapping, а material conflicts отсутствуют. Иначе
план содержит только bounded contract-acquisition/design task; несвязанные
B-срезы продолжаются.

## Workflow

### 1. Построить applicability matrix

Создать `docs/harness/production-applicability.md`. Для каждого dimension из
asset записать:

- версии или хеши паспорта подключений, `data-boundaries.md`, prototype/parity evidence
  и production patterns, от которых зависит план;
- current fact и evidence path/command;
- authoritative target source и provenance;
- статус: `required`, `already_satisfied`, `not_applicable` или `blocked`;
- exact target/test paths, если они уже утверждены;
- технические prerequisites и, только если применимо, approvals на protected
  files, dependency, live system или destructive DB action;
- layer-specific verification.
- применимую запись из `pre-industrialization-spec.md`, точную секцию
  `data-boundaries.md` и версию/хеш официального описания для зависимого слоя.

Проверять внешние boundaries по одной, процессы по одному, source/frozen/image
режимы отдельно. `UNKNOWN` не является пятым статусом: неизвестный обязательный
факт — `blocked` с точным описанием недостающего contract/config/deploy input.

Если найдены residual template tokens, спорная раскладка или кандидаты dead
code, сначала выполнить `harness-team-layout-alignment` в read-only audit mode.
Cleanup family не создавать без `structure-audit.md` и human-approved exact
paths.

### 2. Сначала вынести недостающие факты и решения

До implementation tasks создать отдельные contract-acquisition/design задачи,
если неизвестны:

- source of truth, exact operation или target boundary contract;
- process topology: library/CLI/API/worker/scheduler/init-db;
- service/build/deploy identity;
- DB/schema и migration policy;
- protected/dependency/live authorization, только когда оно требуется действию.

Зависимые tasks оставить в backlog/blocked plan, не делать их исполняемыми через
placeholder или TODO.

`data-boundaries.md` заполняется Codex из prototype evidence, паспорта
подключений и официального описания. Он фиксирует только нужные реализации
технические факты, mapping и проверки, не копируя OpenAPI целиком. Человек не
транскрибирует туда доступные схемы вручную.

### 3. Развернуть только применимые task families

По asset:

- `already_satisfied` → не создавать no-op task; приложить evidence в matrix;
- `not_applicable` → не создавать task; записать основание;
- `blocked` → создать только bounded decision/acquisition task;
- `required` с доказанным gap → создать один thin task на один layer/owner;
- family с cardinality `per_boundary` или `per_process` развернуть отдельно для
  каждого boundary/process, не объединять их в одну большую задачу.

`files_hint` брать только из существующего target/template slot или approved
target design. Не оставлять `PKG`, `SERVICE_NAME` и не создавать предполагаемые
`health/`, `observability/`, `api/` или `db/` директории.

### 4. Упорядочить по gates

Порядок по умолчанию:

1. **B0:** identity, clean install/dependencies и открытые owner decisions;
2. **B1:** target boundaries/contracts и process/DB topology;
3. **B2:** effective config, adapters/generated clients, process wiring и DB;
4. **B3:** residual layout correction, logging, health и telemetry;
5. **B4:** frozen bundle, container/build, CI/deploy и permanent governance;
6. **B5:** integration eval, clean release/stand validation и runbook.

Нижний слой не ставить раньше его prerequisite. Если queue schema поддерживает
dependencies, записать их типизированно; иначе внести exact prerequisite ids в
acceptance/notes и держать заблокированные волны в backlog.

### 5. Сформировать canonical tasks

Каждая задача содержит:

```json
{
  "id": "T-<next-free-numeric>",
  "title": "<одно ограниченное production-действие>",
  "type": "feat | fix | refactor | debt | bug",
  "priority": "high | medium | low",
  "status": "open",
  "use_skill": "harness-production-readiness",
  "skill_mode": "adapter",
  "files_hint": ["<resolved target path>", "<resolved test path>"],
  "ported_from": ["<approved source section with provenance>"],
  "acceptance_criteria": [
    "APPLICABILITY и gap доказаны.",
    "Технические prerequisites и применимые protected/live approvals записаны.",
    "Меняется один layer и только resolved paths.",
    "Prototype parity invariants не изменены.",
    "Scoped + repository + layer-specific gates зелёные.",
    "Evidence содержит provenance, commands/counts и runtime result."
  ],
  "approvals": [],
  "notes": "<phase, prerequisite ids и bounded context>"
}
```

Только для задачи, зависящей от внешней границы, добавить критерий о matching-
секции `data-boundaries.md` не ниже `MAPPED` и точной версии контракта. Для
несвязанных config/deploy/observability/runbook задач этот критерий не добавлять.

Route выбирать по владельцу. Для многорежимного route записывать mode именно в
общем поле `skill_mode`, не в `mode`, `eval_mode` или тексте `notes`:

- dependencies → `harness-production-readiness`, `skill_mode: dependency`;
- effective config → `harness-production-readiness`, `skill_mode: config`;
- contract acquisition/design proposal → `harness-production-readiness`,
  `skill_mode: contract`; новая boundary остаётся architecture checkpoint;
- contract-ready boundary adapter → `harness-production-readiness`,
  `skill_mode: adapter`;
- process topology/wiring → `harness-production-readiness`,
  `skill_mode: process`;
- DB ownership/migrations → `harness-production-readiness`, `skill_mode: db`;
- logging/health/telemetry → `harness-production-readiness`,
  `skill_mode: observability`;
- identity/build/container/CI/deploy → `harness-production-readiness`,
  `skill_mode: deploy`;
- runbook → `harness-production-readiness`, `skill_mode: runbook`;
- stand orchestration → `harness-production-readiness`, `skill_mode: stand`;
- external/stand/live evaluation → `harness-eval`, `skill_mode: live`;
- quality dataset synthesis → `harness-golden` без `skill_mode`;
- evaluation по released quality dataset → `harness-eval`, `skill_mode: golden`;
- permanent repo/CI guards → `harness-governance-gates` без `skill_mode`;
- доказанный residual layout/dead code → `harness-team-layout-alignment` без
  `skill_mode`.

Если implementation task требует отдельной live-проверки, создать отдельную
тонкую verification task с `use_skill: harness-eval` и `skill_mode: live`.
Live route не вкладывать в implementation family/task: у него отдельный gate,
claim и evidence. Не подменять реализацию adapter eval-задачей и не прятать mode
в свободном тексте.

`harness-pre-commit-check` не является implementation route: он запускается
автоматически перед commit.

ID — следующий свободный numeric во всех queue sections. Не резервировать
диапазон `T-101…T-120` и не заполнять числовые пробелы искусственно.

### 6. Показать и записать

До записи показать человеку:

- applicability matrix;
- задачи по волнам и зависимости;
- skipped/already-satisfied slices;
- blockers и применимые protected/live approvals;
- exact files и source provenance.

После подтверждения добавить новые `open` tasks по planning-write contract
`harness-context` в режиме `refresh`; lifecycle существующих задач не менять
вручную. Planning artifacts оформить отдельным clean handoff до claim первой
задачи B.

## Delta replan после стенда

Новый лог сначала классифицировать в существующий dimension/layer. Не расширять
scope текущей задачи. Обновить matrix и создать отдельный thin corrective task
через delta-run этого skill.

Если incident не покрывается ни одной family, записать catalog gap с evidence;
не придумывать универсальную задачу и не менять asset в target repo.

## Hard Limits

- Не копировать asset как готовую очередь и не создавать все families всегда.
- Не зашивать stack, framework, provider, endpoint, service naming или layout.
- Не создавать implementation task до contract readiness: exact operation,
  versioned source, auth, mapping и отсутствие material conflicts.
- Подтверждение плана не разрешает live-вызов: для него нужно отдельное текущее
  authorization. Existing adapter не требует повторного ручного согласования,
  если официальный контракт и mapping технически готовы.
- Для новой boundary acquisition/design task может подготовить факты и
  предложение, но не принимать отсутствующее архитектурное решение.
- Не смешивать config, dependency, process, bundle, DB, integration и business
  fixes в одной задаче.
- Не считать `make verify` достаточным для build/process/integration/stand layer.
- Не считать `files_hint`/acceptance approval на protected path или live/DB action.
- Не менять business behavior, golden expected или prototype contract в plan.
- Не оставлять unresolved placeholders в persisted task.
- Не создавать task для многорежимного skill без exact `skill_mode` и не
  выводить mode из title/notes во время исполнения.

## Output

- `docs/harness/production-applicability.md`;
- показанный и подтверждённый ordered Stage-B plan;
- только применимые tasks с dynamic ids и exact `harness-*` routes;
- список skipped/satisfied/blocked dimensions;
- clean planning handoff перед первым claim этапа B.

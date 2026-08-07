---
name: harness-production-plan
description: "Строит evidence-based план этапа B и внешних release-гейтов C после parity-переноса: проверяет применимость production-срезов, зависимости и prerequisites, затем создаёт упорядоченные capability-задачи с exact harness routes и динамическими id. Используй после harness-extract-prod и до harness-production-readiness, когда нужно сформировать или пересобрать очередь production-доводки без фиксированного T-101 шаблона."
---

# harness-production-plan

## Цель

До первой production-правки увидеть весь применимый объём безопасного offline
этапа B и отдельно внешних release-гейтов C, затем расположить их по
зависимостям. Не копировать универсальный список задач: сначала доказать
для каждого слоя `required`, `already_satisfied`, `not_applicable` или `blocked`,
затем создать задачи только для реальных gaps.

Этот skill планирует. Реализацию ведут exact `use_skill` и, для многорежимных
skills, обязательный `skill_mode` из созданных задач. Не дробить одну внешнюю
возможность по техническим файлам: SDK constraint, lifecycle provider/client,
adapter, DI и protocol tests составляют одну boundary capability.

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
   `docs/harness/evals/prototype-parity.md`; отдельно прочитать post-parity
   cleanup ledger из `ds-precheck.md`, не превращая каждую О-находку в task;
3. существующие read-only team docs: architecture, configuration, conventions,
   project_structure, rules, dev-setup и cicd, если он предоставлен. Отсутствие
   отдельного cicd-документа записать как gap; не запускать bootstrap-full и не
   выдумывать pipeline, если template/release source дают другие evidence;
4. `team-patterns-production.md`, собранный `harness-extract-prod` из отдельно
   названных template, production-neighbour и release-reference ролей;
5. текущий target code, process entrypoints, dependency/build surface,
   integration/data-boundary inventory, external-client lifecycle matrix и
   `structure-audit.md`, если он существует;
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
gate этапов B/C без отдельного human decision.

План этапов B/C всё равно показывается человеку до записи очереди. Для конкретного
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
- `verification_level`: `scoped`, `capability`, `runtime` или `bundle`, и
  invalidation paths для повторного использования evidence;
- layer-specific verification;
- применимую запись из `pre-industrialization-spec.md`, точную секцию
  `data-boundaries.md` и версию/хеш официального описания для зависимого слоя;
- для каждой внешней boundary: SDK constraint/lock, transport, local/cluster
  access, object/session scope, create/close events, startup/readiness
  criticality, retry owner и failure boundary.

Проверять внешние boundaries по одной, процессы по одному, source/frozen/image
режимы отдельно. `UNKNOWN` не является пятым статусом: неизвестный обязательный
факт — `blocked` с точным описанием недостающего contract/config/deploy input.

Если найдены residual template tokens, спорная раскладка или кандидаты dead
code, сначала выполнить `harness-team-layout-alignment` в read-only audit mode.
Cleanup family не создавать без `structure-audit.md` и exact paths, покрытых
safe-offline authorization плана; неоднозначные удаления требуют отдельного
human approval.

### 2. Сначала вынести недостающие факты и решения

До implementation tasks создать отдельные contract-acquisition/design задачи,
если неизвестны:

- source of truth, exact operation или target boundary contract;
- совместимый SDK major, transport или lifecycle активного соединения;
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
- `required` с доказанным gap → создать одну связную task на одну capability;
- `per_boundary` развернуть по внешним границам, но в одной implementation task
  этой boundary объединить совместимый SDK constraint, lifecycle provider/client,
  adapter, DI и protocol tests. Отдельная dependency task допустима только для
  workspace-wide baseline или самостоятельного compatibility investigation;
- `per_process` развернуть по процессам только для общей регистрации/entrypoint
  wiring, которую нельзя доказать внутри одной boundary capability. Не повторять
  там уже выполненный adapter/DI scope;
- все применимые post-parity О-находки объединить в одну consolidated cleanup
  capability через существующий `harness-team-layout-alignment`. Выполнять её
  после parity и production replacement wiring, но до финального offline
  runtime/bundle; туда же входит один post-parity hygiene-аудит identity,
  undocumented routes, generated-client reuse, exception semantics, provider
  lifecycle, pod File IO, `.env`, bundle resources и reachability. Не создавать
  task на каждый файл или finding;
- logging, health/readiness и telemetry одного набора процессов объединить в
  одну operability capability, если у них нет разных owners, approval scopes
  или независимо откатываемых runtime contracts;
- после завершения B2 wiring и применимых B3 cleanup/observability изменений
  создать ровно одну агрегированную
  `offline-runtime-lifecycle` task: реальный `create_app`/экспортируемый `app`,
  production DI и lifespan, API/worker, без live-систем.

`files_hint` брать только из существующего target/template slot или approved
target design. Не оставлять `PKG`, `SERVICE_NAME` и не создавать предполагаемые
`health/`, `observability/`, `api/` или `db/` директории.

### 4. Упорядочить по gates

Порядок по умолчанию:

1. **B0:** identity, clean install/dependencies и открытые owner decisions;
2. **B1:** target boundaries/contracts и process/DB topology;
3. **B2:** effective config, boundary capabilities, process wiring и DB;
4. **B3:** одна consolidated post-parity cleanup capability, logging, health,
   telemetry и единый offline runtime/lifecycle gate;
5. **B4:** frozen bundle, offline container/build и permanent governance.
   После зелёных B0–B4 этап B завершён; внешние реквизиты не держат его open;
6. **C1:** CI/deploy identity и другие release inputs, опциональные quality
   artifacts;
7. **C2:** отдельно разрешённые live/stand и isolated external-state проверки;
8. **C3:** operations handoff и явное release decision владельца.

Нижний слой не ставить раньше его prerequisite. Если queue schema поддерживает
dependencies, записать их типизированно; иначе внести exact prerequisite ids в
acceptance/notes и держать заблокированные волны в backlog.

### 5. Сформировать canonical tasks

Каждая задача содержит:

```json
{
  "id": "T-<next-free-numeric>",
  "title": "<одна законченная production capability>",
  "type": "feat | fix | refactor | debt | bug",
  "priority": "high | medium | low",
  "status": "open",
  "plan_id": "production-bc-<12-hex>",
  "stage": "B",
  "phase": "B2",
  "use_skill": "harness-production-readiness",
  "skill_mode": "adapter",
  "verification_level": "capability",
  "files_hint": ["<resolved target path>", "<resolved test path>"],
  "ported_from": ["<approved source section with provenance>"],
  "acceptance_criteria": [
    "APPLICABILITY и gap доказаны.",
    "Технические prerequisites и применимые protected/live approvals записаны.",
    "Меняется одна capability и только resolved paths.",
    "Prototype parity invariants не изменены.",
    "Проверки соответствующего уровня verification pyramid зелёные.",
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

- workspace-wide dependency baseline или compatibility investigation →
  `harness-production-readiness`, `skill_mode: dependency`;
- effective config → `harness-production-readiness`, `skill_mode: config`;
- contract acquisition/design proposal → `harness-production-readiness`,
  `skill_mode: contract`; новая boundary остаётся architecture checkpoint;
- contract-ready boundary capability (SDK constraint + lifecycle + adapter + DI
  + protocol tests) → `harness-production-readiness`, `skill_mode: adapter`;
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

`stage` выводить только из phase: `B0…B4 → B`, `C1…C3 → C`. CI/deploy identity,
live/stand, isolated external-state validation, runbook/release decision не
помещать обратно в B только потому, что они присутствуют в production asset.
Всем задачам одного applicability plan назначить общий детерминированный
`plan_id`, построенный из target revision и версий/хешей паспорта,
`data-boundaries.md` и production patterns, например
`production-bc-<12-hex>`. Delta-задачи того же плана сохраняют этот id.

### 6. Назначить уровни проверки

План должен использовать verification pyramid, а не полный build после каждой
task:

1. **Scoped:** изменённые tests/imports и Ruff — внутри каждой task.
2. **Capability:** полный unit/contract набор — после завершения boundary или
   process capability.
3. **Offline runtime:** одна task после B2 wiring и применимых
   cleanup/observability изменений запускает настоящий app factory, production
   DI/lifespan и применимые API/worker процессы с protocol-faithful transport
   stubs.
4. **Bundle:** clean install/build, inventory и artifact process smoke — один раз
   после изменений dependency/resource/build surfaces.
5. **Live:** только отдельная `harness-eval:live` task с актуальным разрешением.

Каждая persisted B/C task обязана иметь одно поле `verification_level`:

- `scoped` — contract/decision/acquisition и документационный runbook;
- `capability` — implementation capability, cleanup, observability, governance,
  container/CI-specific checks и eval task;
- `runtime` — только одна `offline-runtime-lifecycle` task;
- `bundle` — только один финальный owner полной clean
  install/build/inventory/artifact-process цепочки (`runtime-bundle`).

В Stage B одного plan должно быть ровно по одному `runtime` и `bundle` owner,
если эти dimensions применимы. Остальные tasks ссылаются на их evidence, но не
повторяют тяжёлую цепочку. Stage C не создаёт второго offline runtime/bundle
owner: он переиспользует B evidence и запускает только свой exact external gate.

Повторно использовать зелёное evidence можно, только если его commit является
предком текущего HEAD, а diff после него не затрагивает входы соответствующего
gate. В task acceptance записать invalidation paths; не повторять clean build
при изменениях, не влияющих на dependency/resources/packaging/entrypoints.

После назначения уровней выполнить обязательный merge-pass. Для обычного
сервиса ориентир локального offline-плана B — 7–12 задач: foundation/config,
одна задача на каждую реально независимую external boundary, process wiring,
при необходимости cleanup/operability, один runtime gate и один bundle gate.
Число файлов, endpoint-ов одного клиента, acceptance-пунктов или найденных
замечаний budget не увеличивает. **Больше 15 safe-offline Stage-B tasks — hard
STOP:** такой план не записывать, сначала объединить технические части
capabilities либо разделить действительно независимые подсистемы на явные
волны. Тонкие Stage-C live/shared-DB/deploy decision/eval tasks в этот лимит не входят,
но не должны дробиться по отдельным реквизитам или полям паспорта.

### 7. Показать и записать

До записи показать человеку:

- applicability matrix;
- задачи по волнам и зависимости;
- skipped/already-satisfied slices;
- blockers и применимые protected/live approvals;
- exact files и source provenance.
- `verification_level` каждой task, один runtime owner и один bundle owner.
- итоговый task budget и результат обязательного merge-pass;
- явная граница: какие задачи завершают B offline и какие отложены в C.

До persistence машинно проверь весь plan: у каждой task есть общий `plan_id`,
канонические `stage`/`phase`, `verification_level` и exact `harness-*` route;
фазы ограничены B0–B4/C1–C3; в B ровно по одному применимому runtime и bundle
owner, в C их нет. При нарушении план не записывать и не перекладывать
исправление на исполнителя.

Если исходный запрос `harness-productionize` явно разрешает автоматический
safe-offline прогон в target, он покрывает перечисленные планом локальные
dependency/lock и protected-file изменения с exact paths и scope. Зафиксировать
эту authorization basis в plan artifact/tasks и не запрашивать подтверждение
ни при записи, ни при claim. Если общей авторизации нет, запросить одно
подтверждение плана. Новое решение требуется только при выходе за scope,
конфликте/новой boundary либо для live, shared DB, migration side effect или
deploy execution.

После authorization добавить новые `open` tasks по planning-write contract
`harness-context` в режиме `refresh`; lifecycle существующих задач не менять
вручную. Planning artifacts оформить отдельным clean handoff до claim первой
задачи B.

## Delta replan после стенда

Новый лог сначала классифицировать в существующий dimension/capability. Не расширять
scope текущей задачи. Обновить matrix и создать отдельную bounded corrective task
через delta-run этого skill.

Если incident не покрывается ни одной family, записать catalog gap с evidence;
не придумывать универсальную задачу и не менять asset в target repo.

## Hard Limits

- Не копировать asset как готовую очередь и не создавать все families всегда.
- Не зашивать stack, framework, provider, endpoint, service naming или layout.
- Не создавать implementation task до contract readiness: exact operation,
  versioned source, auth, mapping и отсутствие material conflicts.
- Подтверждение плана не разрешает live-вызов: для него нужно отдельное текущее
  authorization. Оно также не разрешает shared-DB/migration side effects или
  deploy execution. Перечисленные в плане безопасные offline dependency и
  protected-file изменения, напротив, не требуют повторного approval на claim.
  Existing adapter не требует повторного ручного согласования, если официальный
  контракт и mapping технически готовы.
- Для новой boundary acquisition/design task может подготовить факты и
  предложение, но не принимать отсутствующее архитектурное решение.
- Не смешивать независимые capabilities, bundle, DB, live integration и business
  fixes в одной задаче. Технические части одной external-boundary capability
  (совместимый SDK constraint, lifecycle, adapter, DI и protocol tests) не
  разделять искусственно.
- Не считать `make verify` достаточным для build/process/integration/stand layer.
- Не считать bare `FastAPI()` или test-only DI доказательством offline runtime.
- Не закрывать offline-контур Stage B без единого real-app runtime/lifecycle gate.
- Не считать `files_hint`/acceptance approval на protected path или live/DB action.
- Не менять business behavior, golden expected или prototype contract в plan.
- Не оставлять unresolved placeholders в persisted task.
- Не создавать task для многорежимного skill без exact `skill_mode` и не
  выводить mode из title/notes во время исполнения.

## Output

- `docs/harness/production-applicability.md`;
- показанный ordered Stage-B/Stage-C plan с записанной authorization basis;
- только применимые tasks с общим `plan_id`, dynamic ids, canonical
  `stage`/`phase` и exact `harness-*` routes;
- одна offline-runtime-lifecycle task после B2 wiring и явно назначенные уровни
  verification pyramid;
- explicit `verification_level` каждой task и ровно один применимый final bundle
  owner;
- список skipped/satisfied/blocked dimensions;
- clean planning handoff перед первым claim этапа B.

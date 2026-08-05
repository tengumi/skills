---
name: harness-prototype-plan
description: >
  Генерирует задачи переноса прототипа в docs/harness/tasks.json на основе
  docs/harness/prototype-analysis.md и подтверждённого ds-precheck.md. Создаёт
  первой задачей переноса prototype-contract baseline, затем декомпозирует
  перенос на связные независимо проверяемые parity-slices. Prompts, helpers,
  tests, fixtures и interface cascade остаются вместе с использующим их
  поведением независимо от числа файлов. Каждая implementation-задача получает
  use_skill: harness-prototype-port, полный ported_from и files_hint в
  существующие КАНОНИЧЕСКИЕ слоты team template/project_structure.md; финальная
  проверка маршрутизируется в harness-eval:prototype-parity.
  Используется ПОСЛЕ harness-source-analysis и ПЕРЕД выполнением задач, чтобы пользователю
  не приходилось описывать декомпозицию и раскладку вручную.
---

# harness-prototype-plan

## Цель

Превратить `docs/harness/prototype-analysis.md` и подтверждённый
`docs/harness/ds-precheck.md` в готовую очередь задач переноса в
`docs/harness/tasks.json`. Это убирает необходимость пользователю вручную
расписывать декомпозицию — скилл делает её из analysis и precheck artifacts.

Источники правды для декомпозиции — observed-карта `prototype-analysis.md` и
классифицированные находки `ds-precheck.md`, не догадки.
Источник правды для РАЗМЕЩЕНИЯ — развёрнутый шаблон команды + `project_structure.md`,
не «как удобнее». Каждая задача ссылается на конкретные функции/секции анализа и
на конкретный слот шаблона.

## Когда применять

- `docs/harness/prototype-analysis.md` существует (создан `harness-source-analysis`).
- `docs/harness/ds-precheck.md` существует, а решения человека по классу П
  записаны либо явно отмечены как pending/blocking для затронутых задач.
- Целевая репа подготовлена и развёрнута ИЗ шаблона (репо рядом с прототипом):
  слои-слоты уже на местах (`harness-context` отработал, есть AGENTS.md).
- Нужно создать задачи переноса перед их выполнением.

НЕ применять: для нового функционала (это `harness-template` / ручные задачи),
для production-доводки (её applicability matrix и queue строит
`harness-production-plan`).

## Правило декомпозиции

- **Одна задача = один связный parity-slice**: наблюдаемая capability или
  foundation, которую можно реализовать, проверить и откатить независимо.
- В одну задачу включать весь относящийся к slice каскад: implementation,
  prompts/resources, schemas/state, helpers, interfaces/implementations/fakes,
  DI/callers, tests и fixtures. Число файлов не является границей задачи.
- Делить slice только когда каждая часть имеет собственный observable prototype
  behavior/contract либо является shared foundation минимум для двух slices, и
  дополнительно имеет отдельную verification + dependency/approval/rollback
  boundary. Importability, unit test одного файла, SHA/existence ресурса или
  удобство review сами по себе независимым результатом не являются.
- Shared foundations с одинаковым набором consumers, prerequisite/approval
  scope и verification boundary объединять в одну foundation-задачу. Нельзя
  превращать каждый общий helper, schema или config module в отдельную задачу:
  самостоятельная integration-проверка не создаёт отдельную capability.
- Не создавать отдельную задачу только потому, что изменился тип файла,
  каталог, source module или набралось больше трёх файлов. Prompts, tests,
  fixtures и leaf helpers без самостоятельного потребителя задачами не являются.
- **Первая задача ПЕРЕНОСА — ВСЕГДА prototype-contract baseline**. Если target
  ещё содержит template identity или другой подтверждённый bootstrap gap,
  обычная подготовительная задача может стоять перед ней.
- **Числовые id без суффиксов-букв** (T-001, T-002…) — суффиксы ломают branch-regex tasks-mcp.
- ID брать как следующий свободный numeric id из существующего `tasks.json`;
  никогда не предполагать, что `T-001` свободен.
- Каждая задача переноса: `use_skill: harness-prototype-port` + `ported_from` + `files_hint` в слот шаблона.
- Acceptance ссылается на конкретные функции/секции из prototype-analysis.md.
- Acceptance явно содержит «сохранить логику прототипа точно».

## Workflow

0. **Проверь только входы планирования.** Убедись, что доступны analysis,
   precheck, target, team template/project_structure и очередь. Не запускай
   install/test/build только ради создания плана. Фактически найденные template
   identity, dependency, install или import gaps оформи обычными
   подготовительными задачами перед contract baseline; их проверки запиши в
   acceptance этих задач.

1. **Прочитай `prototype-analysis.md` и `ds-precheck.md` целиком.** Выдели:
   schemas, LLM-вызовы,
   core workflow, helpers, entrypoints, File IO, существующие внешние
   интеграции, отсутствующие будущие boundaries и конфигурацию. Перенеси
   Ф-находки в соответствующие port-задачи. Для П-находки хранить exact решение,
   owner/date/provenance: `preserve` входит в acceptance owning parity-slice;
   `change` только записывается как deferred post-parity handoff и не получает
   `harness-prototype-port`. Решение `preserve`/`change` копировать в
   `task.approvals`; при `pending` ставить owning task `status: blocked` и точно
   описывать недостающее решение в notes, не оставлять её claimable.
   Общее подтверждение плана не является approval изменения поведения.
   О-находки — в backlog.

2. **Построй capability graph и parity-slices.** Сначала выдели общую foundation
   (contract, действительно общие schemas/state, config/providers и shared
   runtime), затем законченные capabilities от входа до результата. В каждый
   capability-slice включи его prompts/resources, helpers, nodes/services,
   state mutations, fallbacks и tests. Наблюдаемый File IO adapter отделяй
   только если он общий для нескольких capabilities или имеет самостоятельный
   контракт; иначе оставляй с потребителем.

   Prompt-файлы не дробить по 2–3 файла. Если prompt используется одной
   capability — перенести вместе с ней. Общий большой prompt bundle допустимо
   вынести в одну resource-задачу с manifest + SHA-256 проверкой, но не в серию
   задач без самостоятельно работающего результата.

   **Замапь каждый slice в КАНОНИЧЕСКИЕ слоты развёрнутого template**. Для каждого
   `files_hint` укажи provenance: точную секцию `project_structure.md` или path в
   template. Не выводи ORM/API/services layout из имени сущности. Если источники
   дают несколько слотов или не дают ни одного — вопрос пользователю, не
   методологический default. `files_hint` должен быть конкретным существующим
   path, чтобы porter не выбирал место сам.

3. **Проверь coverage и построй очередь.** Создай coverage map с колонками
   `inventory_id/type`, exact `source:path/range`, `contract key` и
   `owner_task`. Для каждой функции, prompt/resource, schema, LLM-вызова,
   boundary, entrypoint и Ф-находки назначь ровно один владеющий slice; общий
   элемент можно повторить только с явной пометкой `shared`. Broad-ссылки
   contract baseline или финальной eval-задачи на весь analysis/prototype не
   считаются implementation coverage. `ported_from` implementation-задач должен
   перечислять exact owned items/ranges, а coverage map — покрывать observed inventory без потерь
   и дублей. Порядок — топологический, от foundation к потребителям. Первой
   port-задачей — контракт. Не создавать искусственную цепочку «каждая задача
   зависит от предыдущей»: указывать только реальные prerequisites.

   Всем задачам этого плана, включая preparation, contract, implementation и
   финальную eval, присвой одинаковые `plan_id` и `stage: "A"`. `plan_id`
   строится детерминированно из exact prototype revision/content hash, например
   `prototype-a-<12 hex>`; он не зависит от числа или порядка задач. Поздняя
   Stage-A delta-задача обязана получить тот же `plan_id`, поэтому финальный gate
   увидит её динамически.

   Границы планировать по их текущему состоянию из analysis:

   - `FILE_IO_OBSERVED`: сохранить file-backed/in-memory parity adapter и
     observed file semantics; replacement записать как отдельный production gap;
   - `EXTERNAL_CONTRACT_OBSERVED`: планировать adapter по подтверждённому contract;
   - `EXTERNAL_CONTRACT_UNKNOWN`: перенести только наблюдаемый interface/fake и
     записать contract-acquisition как production gap; неизвестный live contract
     не блокирует port бизнес-логики;
   - `NO_EXTERNAL_BOUNDARY`: не создавать предполагаемый adapter или design task
     в port queue. Записать production gap для post-parity data-boundary
     checkpoint.

   Все implementation-задачи этого плана остаются port-задачами с
   `use_skill: harness-prototype-port`. Единственное исключение — обязательная
   последняя verification-задача `harness-eval`, `skill_mode: prototype-parity`.
   Target boundary решения и acquisition/implementation tasks принадлежат этапу
   B после parity; здесь они только перечисляются как gaps, не получают
   фиктивный route.

   Если задача меняет интерфейс/Protocol, в acceptance перечислить весь каскад:
   interface → implementations → fakes → DI providers → callers → fixtures/golden.
   Этот каскад держать в одном slice; не дробить его ради file count.
   Transport mapping (headers, aliases, dates, absent/null/empty) тестировать на
   boundary отдельно от frozen business output.

4. **Выполни обязательный merge-pass.** Объедини соседние задачи, если у одной
   нет собственного наблюдаемого результата, отдельной проверки/rollback или
   собственного approval scope. Особенно объединяй prompt-only, fixture-only,
   test-only и helper-only задачи с consuming capability.

   До записи посчитай объяснимый budget: preparation + contract + число
   независимо наблюдаемых capabilities + действительно разных shared
   foundations + final parity. Количество source-файлов, prompts, helpers,
   schemas и tests этот budget само по себе не увеличивает.

   Для medium prototype нормальный ориентир — примерно 8–18 задач этапа A,
   включая optional preparation, contract и финальную parity verification.
   Размер определяй по числу observable capabilities и boundaries, а не по
   числу файлов или ресурсов. Это диагностический диапазон, не цель и не hard
   cap. Если после merge-pass осталось больше 20 задач, приложи exception table
   для КАЖДОЙ задачи плана: независимый result, verification,
   dependency/approval boundary и причина, почему merge с ближайшим consumer
   ухудшит безопасность. Без такого обоснования объединяй.

5. **Покажи план пользователю ПЕРЕД записью.** Список задач с title, цельным
   проверяемым результатом, ported_from и целевыми slots. Покажи coverage gaps,
   итог merge-pass и exception table при числе задач >20. Дождись подтверждения
   или корректировки. Не записывай молча.

6. **Запиши в `docs/harness/tasks.json`** в `current_sprint` (или `backlog`,
   если пользователь так просит). Существующие задачи не затирай.

7. **Отчёт:** сколько задач создано, какой порядок, что в контракте, как
   observed inventory покрыт slices и почему каждый оставшийся slice независим.

Если для сравнения нужно реализовать runner/fixtures, это отдельный
`harness-prototype-port` slice. Последней задачей плана всегда поставить само
итоговое доказательство: `use_skill: harness-eval`,
`skill_mode: prototype-parity`, после завершения всей port queue.

## Шаблон задачи переноса

```json
{
  "id": "T-00N",
  "title": "Перенести <capability/foundation> из прототипа",
  "type": "feat",
  "priority": "high",
  "status": "open",
  "plan_id": "prototype-a-<12-hex-from-exact-prototype-revision>",
  "stage": "A",
  "use_skill": "harness-prototype-port",
  "verification_skills": ["harness-governance-gates:prototype-contract"],
  "depends_on": ["<only real prerequisite task IDs>"],
  "files_hint": [
    "<implementation slot>",
    "<related prompt/resource slots>",
    "<tests/fixtures slots>"
  ],
  "slot_provenance": {
    "<implementation slot>": "docs/harness/project_structure.md:<section>",
    "<related prompt/resource slots>": "<exact team template path>",
    "<tests/fixtures slots>": "docs/harness/project_structure.md:<section>"
  },
  "ported_from": [
    "prototype-analysis.md: <capability/contract keys>",
    "<all owned source paths/ranges>"
  ],
  "acceptance_criteria": [
    "Перенести полный <slice> из prototype-analysis.md, сохранив логику точно.",
    "LLM-параметры/схемы/retry идентичны прототипу (см. prototype-analysis.md).",
    "Все implementation/prompts/helpers/state/interface cascade и tests этого slice согласованы.",
    "Каждый files_hint имеет provenance из project_structure.md/template.",
    "Scoped tests проверяют вход → поведение → state/output/fallback без реальных внешних вызовов."
  ],
  "notes": "Опромышленность: не упрощать, не оптимизировать. Все files_hint подтверждены project_structure.md/шаблоном. См. harness-prototype-port."
}
```

## Последняя задача — всегда parity verification

```json
{
  "id": "T-<next-free-numeric>",
  "title": "Доказать prototype parity этапа A",
  "type": "feat",
  "priority": "high",
  "status": "open",
  "plan_id": "prototype-a-<same-plan-id>",
  "stage": "A",
  "use_skill": "harness-eval",
  "skill_mode": "prototype-parity",
  "depends_on": ["<all preparation/contract/implementation task IDs>"],
  "files_hint": ["docs/harness/evals/prototype-parity.md"],
  "slot_provenance": {
    "docs/harness/evals/prototype-parity.md": "harness-eval:prototype-parity canonical report"
  },
  "ported_from": [
    "docs/harness/prototype-contract.json",
    "docs/harness/prototype-analysis.md"
  ],
  "acceptance_criteria": [
    "После завершения всех port-задач выполнен harness-eval:prototype-parity на зафиксированных prototype/target revisions.",
    "Отчёт содержит hashes, manifest, правило сравнения, repeatability, discrepancies и остаточные Stage-B gaps.",
    "Расхождения отсутствуют либо оформлены как intentional deviations с exact owner approval."
  ],
  "notes": "Verification task, не harness-prototype-port; запускать только после всей port queue."
}
```

## Первая port-задача — всегда контракт

```json
{
  "id": "T-<next-free-numeric>",
  "title": "prototype-contract.json baseline",
  "type": "feat",
  "priority": "high",
  "status": "open",
  "plan_id": "prototype-a-<same-plan-id>",
  "stage": "A",
  "use_skill": "harness-prototype-port",
  "depends_on": ["<preparation task IDs, if any>"],
  "files_hint": ["docs/harness/prototype-contract.json", "docs/harness/prototype-analysis.md"],
  "slot_provenance": {
    "docs/harness/prototype-contract.json": "harness-prototype-plan canonical artifact",
    "docs/harness/prototype-analysis.md": "existing harness-source-analysis artifact"
  },
  "ported_from": ["docs/harness/prototype-analysis.md", "<оригинал прототипа>"],
  "acceptance_criteria": [
    "Создан docs/harness/prototype-contract.json: prompts(SHA256), schemas, llm_calls, constants, retry/error handling, entrypoints, observed boundary signatures/fakes, File IO semantics, существующие integration mappings и terminal/publish rules.",
    "Каждая observed-запись с provenance из прототипа; будущая target boundary не выдаётся за часть prototype contract.",
    "Покрытие = все позиции prototype-analysis.md секций LLM/Схемы/Конфигурация.",
    "Отсутствующие параметры кодируются как null, не выдумываются.",
    "После создания выполнена секция Prototype contract из harness-governance-gates; результат приложен в evidence."
  ],
  "notes": "Машинный снимок логики ДО переноса. harness-governance-gates сверяет по нему остальные задачи. Числовые id без суффиксов."
}
```

## Hard Limits

- НЕ декомпозировать из догадок — только из prototype-analysis.md и
  подтверждённого ds-precheck.md.
- НЕ терять находки ds-precheck: Ф входит в port queue; П требует exact owner
  decision/provenance и не превращается в behavior-change port task; О не
  блокирует перенос.
- НЕ использовать число файлов, prompts или source modules как основание для
  split. Делить только по independently verifiable parity boundary.
- НЕ создавать prompt-only/test-only/fixture-only/helper-only задачи, если у них
  нет отдельного потребителя, контракта и проверки.
- НЕ показывать план до coverage audit и обязательного merge-pass.
- НЕ оставлять больше 20 задач без exception table для КАЖДОЙ задачи плана с
  независимым result, verification, dependency/approval boundary и причиной
  невозможности merge с ближайшим consumer.
- НЕ ставить суффиксы-буквы в id (branch-regex tasks-mcp их отвергает).
- НЕ записывать tasks.json без показа плана пользователю.
- НЕ затирать существующие задачи в tasks.json.
- НЕ ставить перед prototype-contract другую задачу ПЕРЕНОСА. Перед ним
  допустимы только доказанно необходимые подготовительные задачи target.
- НЕ блокировать создание плана из-за ещё не запущенных install/test/build:
  применимая проверка выполняется в задаче, которой она нужна.
- НЕ хардкодить `T-001`: выбрать следующий свободный numeric id и проверить
  отсутствие коллизии во всех секциях tasks.json.
- НЕ планировать adapter по предположению. Для существующей интеграции без
  contract — только observed interface/fake и production gap. Для отсутствующей
  в прототипе boundary — только post-parity gap, без unrouted target-design task;
  её отсутствие не блокирует parity port.
- `files_hint` указывает на слоты развёрнутого шаблона. Если responsibility
  slice не ложится ни в один существующий слот — вопрос пользователю, НЕ новый
  слот.
- Для каждого `files_hint` записывать exact `slot_provenance`; общего текста
  «взято из template» недостаточно.
- В `depends_on` записывать только реальные prerequisites. Финальная
  prototype-parity task зависит от всех preparation/contract/implementation
  tasks; искусственная цепочка «каждая от предыдущей» запрещена.
- Все задачи одного Stage-A плана имеют один `plan_id` и `stage: "A"`;
  переносить позднюю delta-задачу в другой plan_id ради обхода финального gate
  запрещено.
- Не зашивать layout в skill: даже типичный runner/service slot должен быть
  подтверждён project_structure.md/template и записан в files_hint.

## Output

- План задач показан и подтверждён (с целевыми слотами);
- `docs/harness/tasks.json` заполнен (current_sprint);
- Отчёт: число задач, порядок, contract первым, coverage map, merge-pass и карта
  слотов; для >20 задач — exception table.

## Связь со скиллами

- ПЕРЕД: `harness-source-analysis` создаёт prototype-analysis.md, затем
  `harness-ds-precheck` создаёт ds-precheck.md. Human checkpoint нужен только
  для П-находок или реального конфликта.
- Слоты для files_hint берутся из развёрнутого шаблона (репо рядом) + project_structure.md.
- ПОСЛЕ: `harness-work-session` → роутит на `harness-prototype-port` по `use_skill`.
- ПОСЛЕ зелёного `harness-eval` с `skill_mode=prototype-parity`: передать
  inventory границ и конкретные gaps из паспорта/технической карты в
  `harness-extract-prod`, затем `harness-production-plan`. Получение контракта и
  проектирование новой границы относятся к этапу B; static Stage-B template не
  копировать.
- У contract-задачи основной `use_skill` остаётся `harness-prototype-port`;
  porter выполняет `harness-governance-gates:prototype-contract` как вложенную
  verification step по `verification_skills`, а не как второй route. Её id
  определяется из tasks.json, а не из текста skill.

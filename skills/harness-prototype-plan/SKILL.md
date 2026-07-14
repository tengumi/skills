---
name: harness-prototype-plan
description: >
  Генерирует задачи переноса прототипа в docs/harness/tasks.json на основе
  docs/harness/prototype-analysis.md и подтверждённого ds-precheck.md. Создаёт первой ЗАДАЧЕЙ ПЕРЕНОСА
  prototype-contract
  baseline, затем декомпозирует перенос по модулям (1-3 файла на задачу), каждая с
  use_skill: harness-prototype-port, ported_from и files_hint в существующий
  КАНОНИЧЕСКИЙ слот. Слоты берёт только из развёрнутого team template +
  project_structure.md и не зашивает общую карту папок в методологию.
  Используется ПОСЛЕ harness-source-analysis и ПЕРЕД выполнением задач, чтобы пользователю
  не приходилось описывать декомпозицию и раскладку вручную.
---

# harness-prototype-plan

## Цель

Превратить `docs/harness/prototype-analysis.md` и подтверждённый
`docs/harness/ds-precheck.md` в готовую очередь задач переноса в
`docs/harness/tasks.json`. Это убирает необходимость пользователю вручную
расписывать декомпозицию — скилл делает её из доказательств двух pre-flight шагов.

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
- `harness-doctor` дал `GO`; canonical service/package identity подтверждён,
  template tokens не остались в исполняемых/build/CI путях, `make install` и
  import smoke воспроизводимы.
- Нужно создать задачи переноса перед их выполнением.

НЕ применять: для нового функционала (это `harness-template` / ручные задачи),
для production-доводки (её applicability matrix и queue строит
`harness-production-plan`).

## Жёсткое правило декомпозиции

- **Одна задача = один модуль/слой**, 1-3 файла (реализация + тесты + опц. helper).
- **Первая задача ПЕРЕНОСА — ВСЕГДА prototype-contract baseline**. Environment/
  identity preflight выполняется до неё и не конкурирует за тот же id.
- **Числовые id без суффиксов-букв** (T-001, T-002…) — суффиксы ломают branch-regex tasks-mcp.
- ID брать как следующий свободный numeric id из существующего `tasks.json`;
  никогда не предполагать, что `T-001` свободен.
- Каждая задача переноса: `use_skill: harness-prototype-port` + `ported_from` + `files_hint` в слот шаблона.
- Acceptance ссылается на конкретные функции/секции из prototype-analysis.md.
- Acceptance явно содержит «сохранить логику прототипа точно».

## Workflow

0. **Проверь preflight.** Если doctor/identity/install/import baseline не зелёный,
   не создавать port queue. Вернуть отдельный preflight blocker/task; contract
   не должен сниматься на нестабильной или полу-переименованной репе.

1. **Прочитай `prototype-analysis.md` и `ds-precheck.md` целиком.** Выдели:
   schemas, LLM-вызовы,
   core workflow, helpers, entrypoints, File IO, существующие внешние
   интеграции, отсутствующие будущие boundaries и конфигурацию. Перенеси
   Ф-находки в соответствующие port-задачи; approved П-находки — только в
   отдельные behavior-change задачи после parity baseline; О-находки — в backlog.

2. **Сгруппируй в слои переноса** по естественным границам прототипа:
   - схемы / доменные модели
   - наблюдаемые источники данных и временные parity adapters
   - LLM-провайдеры + промпты + structured outputs
   - core workflow / граф / pipeline
   - вспомогательные services (parsing, coverage, logging helpers)
   - entry points (CLI / scripts)
   - только реально существующие external boundaries и source-specific routes
   - e2e тесты + quality gates
   Не каждый слой обязателен — бери из того, что реально есть в анализе.

   **Замапь каждый слой в КАНОНИЧЕСКИЙ слот развёрнутого template**. Для каждого
   `files_hint` укажи provenance: точную секцию `project_structure.md` или path в
   template. Не выводи ORM/API/services layout из имени сущности. Если источники
   дают несколько слотов или не дают ни одного — вопрос пользователю, не
   методологический default. `files_hint` должен быть конкретным существующим
   path, чтобы porter не выбирал место сам.

3. **Построй очередь задач.** Порядок — от листьев к корню (schemas раньше
   workflow, который их использует). Первой port-задачей — контракт. Границы
   планировать по их текущему состоянию из analysis:

   - `FILE_IO_OBSERVED`: сохранить file-backed/in-memory parity adapter и
     observed file semantics; replacement записать как отдельный production gap;
   - `EXTERNAL_CONTRACT_OBSERVED`: планировать adapter по подтверждённому contract;
   - `EXTERNAL_CONTRACT_UNKNOWN`: перенести только наблюдаемый interface/fake и
     записать contract-acquisition как production gap; неизвестный live contract
     не блокирует port бизнес-логики;
   - `NO_EXTERNAL_BOUNDARY`: не создавать предполагаемый adapter или design task
     в port queue. Записать production gap для post-parity data-boundary
     checkpoint.

   Все задачи этого плана остаются port-задачами с
   `use_skill: harness-prototype-port`. Target boundary решения и acquisition/
   implementation tasks принадлежат этапу B после parity; здесь они только
   перечисляются как gaps, не получают фиктивный route.

   Если задача меняет интерфейс/Protocol, в acceptance перечислить весь каскад:
   interface → implementations → fakes → DI providers → callers → fixtures/golden.
   Transport mapping (headers, aliases, dates, absent/null/empty) тестировать на
   boundary отдельно от frozen business output.

4. **Покажи план пользователю ПЕРЕД записью.** Список задач с title + ported_from
   + целевой слот (files_hint). Дождись подтверждения или корректировки. Не записывай молча.

5. **Запиши в `docs/harness/tasks.json`** в `current_sprint` (или `backlog`,
   если пользователь так просит). Существующие задачи не затирай.

6. **Отчёт:** сколько задач создано, какой порядок, что в контракте, в какие слоты лягут.

## Шаблон задачи переноса

```json
{
  "id": "T-00N",
  "title": "Перенести <слой> из прототипа",
  "type": "feat",
  "priority": "high",
  "status": "open",
  "use_skill": "harness-prototype-port",
  "verification_skills": ["harness-governance-gates:prototype-contract"],
  "files_hint": ["<resolved existing target slot from project_structure/template>"],
  "ported_from": [
    "prototype-analysis.md: <секция>",
    "<путь в оригинале прототипа>"
  ],
  "acceptance_criteria": [
    "Перенести <функции> из prototype-analysis.md, сохранив логику точно.",
    "LLM-параметры/схемы/retry идентичны прототипу (см. prototype-analysis.md).",
    "Код размещён ровно в files_hint; provenance слота — project_structure.md/template.",
    "Тесты мокают внешние границы (LLM/RAG/DB), без реальных сетевых вызовов."
  ],
  "notes": "Опромышленность: не упрощать, не оптимизировать. Слот files_hint взят из project_structure.md/шаблона. См. harness-prototype-port."
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
  "use_skill": "harness-prototype-port",
  "files_hint": ["docs/harness/prototype-contract.json", "docs/harness/prototype-analysis.md"],
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
- НЕ терять находки ds-precheck: Ф входит в port queue, П требует записанного
  решения человека и отдельной задачи, О не блокирует перенос.
- НЕ создавать задачу крупнее 1-3 файлов; крупный слой дробить.
- НЕ ставить суффиксы-буквы в id (branch-regex tasks-mcp их отвергает).
- НЕ записывать tasks.json без показа плана пользователю.
- НЕ затирать существующие задачи в tasks.json.
- НЕ ставить перед prototype-contract другую задачу ПЕРЕНОСА. Doctor/identity
  preflight находятся до port queue.
- НЕ хардкодить `T-001`: выбрать следующий свободный numeric id и проверить
  отсутствие коллизии во всех секциях tasks.json.
- НЕ планировать adapter по предположению. Для существующей интеграции без
  contract — только observed interface/fake и production gap. Для отсутствующей
  в прототипе boundary — только post-parity gap, без unrouted target-design task;
  её отсутствие не блокирует parity port.
- `files_hint` указывает на слот развёрнутого шаблона. Если слой прототипа не
  ложится ни в один существующий слот — вопрос пользователю, НЕ новый слот.
- Не зашивать layout в skill: даже типичный runner/service slot должен быть
  подтверждён project_structure.md/template и записан в files_hint.

## Output

- План задач показан и подтверждён (с целевыми слотами);
- `docs/harness/tasks.json` заполнен (current_sprint);
- Отчёт: число задач, порядок, контракт первым, карта слотов.

## Связь со скиллами

- ПЕРЕД: `harness-source-analysis` создаёт prototype-analysis.md, затем
  `harness-ds-precheck` создаёт ds-precheck.md и проходит human checkpoint.
- Слоты для files_hint берутся из развёрнутого шаблона (репо рядом) + project_structure.md.
- ПОСЛЕ: `harness-work-session` → роутит на `harness-prototype-port` по `use_skill`.
- ПОСЛЕ зелёного `harness-eval` с `skill_mode=prototype-parity` и
  data-boundary checkpoint: `harness-extract-prod`, затем
  `harness-production-plan`; static Stage-B template не копировать.
- У contract-задачи основной `use_skill` остаётся `harness-prototype-port`;
  porter выполняет `harness-governance-gates:prototype-contract` как вложенную
  verification step по `verification_skills`, а не как второй route. Её id
  определяется из tasks.json, а не из текста skill.

---
name: harness-prototype-port
description: >
  Переносит код из прототипа (notebook/proto-repo/script) в production-обёртку с
  СОХРАНЕНИЕМ бизнес-логики и размещением в КАНОНИЧЕСКИЕ слоты шаблона команды.
  Жёстко запрещает упрощать LLM-вызовы, схемы данных, retry-параметры, менять
  промпты или провайдеров. Кладёт код только в готовые files_hint, подтверждённые
  project_structure.md/team template, и не несёт собственной карты папок. Использует
  docs/harness/prototype-analysis.md и подтверждённый ds-precheck как спецификацию.
  Применяется только к задаче из harness-prototype-plan для задач
  опромышленности — когда цель не написать лучше, а обернуть рабочее в production.
---

Твоя задача — **опромышленность кода**. Это специфический режим работы который требует особой дисциплины.

**Главное правило: точная семантика прежде всего.**

Опромышленность ≠ рефакторинг. Опромышленность ≠ оптимизация. Опромышленность ≠ “написать лучше”.

Опромышленность = взять работающий прототип и обернуть в production-структуру
**без изменения бизнес-логики**. Количество шагов, runtime-параметры и retry
policy берутся из наблюдаемого контракта, а не из представления о «лучших»
значениях.

## Когда применять

- Задача `tasks.json` явно говорит “перенести X из прототипа”
- `docs/harness/prototype-analysis.md` существует и описывает источник
- `docs/harness/ds-precheck.md` прошёл human checkpoint, а задача создана
  `harness-prototype-plan` и несёт `ported_from`, `files_hint`, `use_skill`
- Цель — production-готовность, не функциональное улучшение

**НЕ применять:**

- Новый функционал (используй обычный `harness-work-session`)
- Bug fix (отдельная логика, не перенос)
- Рефакторинг существующего production-кода

-----

## Шаг 1: загрузить контекст

Обязательно прочитать перед началом:

1. **`docs/harness/prototype-analysis.md`** — спецификация. Если её нет — STOP. Запустить `harness-source-analysis` сначала.
2. **`docs/harness/ds-precheck.md` + human decisions** — если их нет, STOP:
   выполнить `harness-ds-precheck`, checkpoint и `harness-prototype-plan`.
3. **Исходный прототип** — не доверяй только analysis, открой оригинал
4. **Текущая задача в `tasks.json`** — она должна быть из подтверждённого plan и
   содержать `ported_from`, `files_hint`, `use_skill: harness-prototype-port`.
   Если provenance плана отсутствует — STOP, не превращать ad-hoc task в port.
5. **Шаблон команды** — репозиторий рядом с прототипом, из которого развёрнута целевая репа. Это источник целевой СТРУКТУРЫ (слотов), НЕ бизнес-логики. Сверять раскладку с ним и с `docs/harness/project_structure.md`.
6. **`docs/harness/prototype-contract.json`** — если существует, это машинный
   снимок логики. Сверяй с ним. Если НЕ существует и это первая задача
   переноса — твоя задача его создать (см. ниже).
7. **Data-boundary/interface inventory** из `prototype-analysis.md`. Сначала
   различить `FILE_IO_OBSERVED`, существующий external contract,
   `EXTERNAL_CONTRACT_UNKNOWN` и `NO_EXTERNAL_BOUNDARY`. Exact route/tool,
   headers и payload требуются только для реально существующей интеграции;
   неизвестный contract блокирует её adapter, но не перенос бизнес-логики.

## Целевая раскладка — слоты шаблона команды 

Целевая репа развёрнута из team template: slots уже существуют. Единственная
карта размещения — read-only `project_structure.md` + фактические paths template.
Для каждого `files_hint` план обязан хранить provenance слота. Код кладётся
ровно туда. Если responsibility не ложится в указанный slot, источники
конфликтуют или path отсутствует — STOP и вопрос пользователю. Не создавать
«очевидный» services/providers/utils/db/api слой из общих представлений.

## Контракт как закон (prototype-contract.json)

`prototype-contract.json` — машинная фиксация наблюдаемого контракта: prompts
(SHA256), schemas, llm_calls (provider/model/path/response_format/timeout/retries/
temperature/multi_step), constants, retry/error handling, entrypoints, boundary
signatures/test doubles, observed File IO semantics, реально существующие
integration operations/source routing и terminal/publish rules. Будущая
production boundary хранится в отдельном target contract и не подменяет
prototype parity.

- **Если контракта ещё нет и это первая задача переноса** — создай его из
  prototype-analysis.md + оригинала ПЕРЕД переносом кода. Затем подгрузи
  `harness-governance-gates` и выполни только его секцию Prototype contract как
  nested verification, приложив результат в evidence. Основной route/use_skill
  задачи при этом не меняется. Это страховой полис.
- **Если контракт есть** — после переноса сверь: prompts/schemas/llm_calls/
  constants не должны измениться. Если изменились без записи в
  `intentional_deviations` — это БАГ переноса, откатись.
- Разрешённые отклонения (секреты в config, entrypoint-обёртка) фиксируй в
  `intentional_deviations` контракта с обоснованием.

Между задачами переноса: `git diff` + сверка что контракт не сдвинулся.

-----

## Шаг 2: построить чек-лист переноса

Для функций которые переносишь, выпиши из `prototype-analysis.md`:

```
Функция: <name>
□ Сигнатура совпадает
□ Все параметры присутствуют
□ Все return-поля присутствуют
□ Все LLM-вызовы того же количества (multi-step сохранён)
□ Параметры LLM: timeout, temperature, retries, profanity_check — точно те же
□ Provider и model имеют те же точные значения, что в прототипе
□ Error handling того же типа (exception, sentinel, retry, terminal state, …)
□ Side effects того же типа
□ Магические константы сохранены или вынесены в config без изменения значений
□ Код размещён в КАНОНИЧЕСКИЙ слот по files_hint / «Целевой раскладке»
□ Для interface change обновлён весь каскад: Protocol/ABC, implementations,
  fakes, DI providers, callers и fixtures
□ Для observed external boundary exact route/tool, headers, request/response и
  absent/null/empty/date/enum semantics подтверждены источником
□ Для File IO сохранены format/schema/lifecycle/error semantics; transport
  fields отмечены N/A, а будущий adapter не придуман внутри port-задачи
```

Это твой контроль качества. После каждой функции — пройдись по чек-листу.

-----

## Шаг 3: что МОЖНО менять

Без явного approval допустимо:

- **Разделение на модули ПО СЛОТАМ template** — только по files_hint с
  provenance из project_structure.md/template; skill не назначает папку сам.
- **Извлечение в классы** — функции на одной структуре данных можно собрать в класс
- **Type hints** — добавлять там где не было
- **Docstrings** — добавлять
- **Логирование** — добавлять structured logging, не убирать существующие print/log
- **Тесты** — добавлять unit-тесты с моками для LLM
- **Константы в config** — выносить hardcoded values в pydantic Settings, **с сохранением значений**
- **Импорты** — упорядочивать, использовать абсолютные
- **Имена переменных** — переименовать `x` в `document` для читаемости (но **не** менять имена API-функций без причины)

-----

## Шаг 4: что НЕЛЬЗЯ менять без явного approval

Эти изменения требуют **отдельной задачи в tasks.json** с пометкой “behavior change”:

### LLM-вызовы

- **Multi-step → single-step.** Если прототип делает `invoke_text` → `invoke_structured` — оставить два шага. НЕ заменять на один `with_structured_output`.
- **Параметры модели.** Сохранять все точные значения из прототипа.
- **Provider.** Сохранять точный provider/model из прототипа. Не унифицировать
  «потому что общий gateway удобнее».
- **Prompts.** Текст промпта переносится дословно. Не “переформулировать для ясности”.
- **Sertificate paths / API keys.** Сами не копировать в код. Но **формат** и **способ** загрузки сохранить — env vars или config те же.

### Схемы данных

- **Все поля сохраняются.** Production-версия содержит полный набор полей
  наблюдаемой schema, а не только поля, которые выглядят используемыми.
- **Типы полей те же.** `Optional[str]` остаётся `Optional[str]`, не упрощается до `str`.
- **Имена полей те же.** Не переименовывать `<old_field>` в `<new_field>`
  только ради краткости.

### Retry / Error handling

- **Количество ретраев то же.** Не уменьшать и не увеличивать его без отдельного решения.
- **Backoff та же.** Если экспоненциальный — оставить экспоненциальный.
- **Какие исключения retry’ятся** — тот же список.
- **Что происходит при сбое** — сохранить тот же return/exception/terminal
  contract. Не заменять одно другим как «улучшение».

### Бизнес-логика

- **Магические константы.** Сохранять наблюдаемые значения до отдельного
  behavior-change решения.
- **Условные ветки.** Каждый if/else прототипа сохраняется. Не “эту ветку явно никогда не достигнут”.
- **Side effects.** На parity-этапе сохранить наблюдаемую файловую/сетевую
  семантику. Замена File IO промышленной boundary выполняется отдельной
  design+implementation задачей после зелёного prototype-parity, подготовки
  технической карты и согласования target contract. Quality golden для этого не
  требуется.

- НЕ менять prototype-contract.json кроме как через явные intentional_deviations.
  Изменившиеся prompt hashes / schema fields / llm params без deviation = баг.

### Размещение по слотам (структурное; контракт остаётся зелёным)

Это не смена поведения, но и не свобода выбора. Следовать конкретному
`files_hint`; проверить, что он существует и ссылается на точную секцию
project_structure.md/path template. Skill не решает, где «обычно» живут models,
contracts, orchestration или helpers. Нет подтверждённого слота → вопрос.

-----

## Шаг 5: процесс переноса

Для каждой функции:

1. **Найти оригинал** в прототипе (по `prototype-analysis.md` есть точная ссылка)
1. **Прочитать оригинал** глазами, не доверять анализу — анализ может пропускать детали
1. **Реализовать в production-структуре** в КАНОНИЧЕСКОМ слоте (по `files_hint` / «Целевой раскладке») с соблюдением чек-листа из шага 2
1. **Написать тест** который проверяет ту же логику что прототип
1. **В коммите указать** ссылку на оригинал

Для изменения сигнатуры сначала построить interface impact list. Нельзя
добавить параметр только в production implementation: fake/golden может остаться
зелёным на другом provider path и скрыть drift. Для существующей интеграции
использовать sanitized real response/spec fixture с provenance. Для отсутствующей
в прототипе boundary не писать adapter в port-задаче: сначала отдельный
утверждённый target contract, затем spec-first fixture и implementation.

Пример хорошего описания evidence без доменной конкретики:

```
<task-id>: port <function> from <source>:<range>

- Two-step LLM call preserved (text analysis → structured output)
- Provider/model/runtime parameters совпадают с прототипом
- Retry policy вынесена в config без изменения значений
- Все поля исходной schema сохранены
- Наблюдаемая error/fallback semantics сохранена
- Размещено ровно в <files_hint> (provenance: project_structure/template)

См. docs/harness/prototype-analysis.md секция "<function>"
```

-----

## Шаг 6: evidence для submit_task

В `evidence` обязательно указать:

```json
{
  "branch": "<task-branch>",
  "commit_sha": "...",
  "tests_passed": true,
  "lint_passed": true,
    "contract_diff": "none",
    "ported_from": [
      "<source>:<range>",
      "<helper-source>:<range>"
    ],
    "logic_preservation_checklist": {
      "llm_calls_count_same": true,
      "llm_parameters_identical": true,
      "schema_fields_complete": true,
      "retry_policy_identical": true,
      "error_handling_identical": true,
      "placed_in_template_slot": true,
      "interface_implementations_and_fakes_synced": true,
      "external_contract_provenance_recorded": true
    },
  "intentional_deviations": [],
  "notes": "..."
}
```

Это flat extension общего `submit_task(..., evidence={...})` из
`harness-work-session`, не второй вложенный объект `evidence`.

Если есть **намеренные** отклонения (с approval пользователя) — перечислить в `intentional_deviations` с обоснованием.

-----

## Шаг 7: golden validation (если применимо)

Если в задаче есть golden tests (сравнение outputs с прототипом на эталонных входах):

1. Подготовить входы — те же что у прототипа
2. Запустить прототип на этих входах → сохранить outputs
3. Запустить новый код на тех же входах
4. Сравнить outputs — должны быть идентичны (для детерминированной логики) или близки (для LLM-частей)
5. Расхождения зафиксировать и обсудить с пользователем

Это **финальная проверка** что опромышленность не изменила поведение.

Static golden доказывает parity на своих fixtures, но не доказывает clean
install, production entrypoint registration, frozen bundle или production data
boundary. Существующий endpoint проверяется, а отсутствующая boundary сначала
проектируется на этапе `harness-production-readiness`.

-----

## Что делать когда замечаешь “это можно улучшить”

Когда соблазн оптимизировать высок:

1. **Зафиксируй идею вне diff текущей задачи** — в отчёте/evidence; не создавай
   backlog task или `improvement-ideas.md` внутри текущей ветки
2. **Не делай оптимизацию сейчас**
3. **После завершения текущей задачи** — обсуди с пользователем
4. Если он согласен — запусти отдельный planning pass, который добавит
   **отдельную задачу** “improve X behavior” по queue schema
5. Эта новая задача — уже не опромышленность, обычный harness-work-session

Принцип: **сначала опромышли как есть, потом улучшай отдельно с осознанным решением.**

-----

## Запрещённые фразы в твоих рассуждениях

Эти фразы — красный флаг. Если ловишь себя на них — стоп, проверь себя:

- “Современные LLM поддерживают structured output, поэтому…”
- “Один шаг будет эффективнее…”
- “Эти поля выглядят избыточно…”
- “Прототип использует deprecated API, заменим на…”
- “Лучшая практика — это…”
- “Сделаю гибче на будущее…”
- “Положу пока куда удобнее, потом на уборке разберусь…” — нет, следуй files_hint.
- “Эта папка обычно подходит…” — общая привычка не заменяет team template.
- “Создам новый слой, потому что существующие неудобны…” — нет подтверждённого
  слота → вопрос пользователю.

Каждая из этих фраз ведёт к изменению поведения или к структурному дрейфу. Опромышленность — не место для них.

-----

## Когда сомневаешься — спрашивай

Если непонятно “это намеренно или баг прототипа?” — спроси пользователя. Не угадывай.

Если расходятся golden, документация, sanitized real payload или код коллеги —
зафиксируй конфликт четырьмя отдельными строками и останови затронутую boundary.
Нельзя выбирать источник по удобству и молча переснимать golden.

Пример хорошего вопроса:

> В прототипе `<function>` повторяет вызов после `<exception>` (см. analysis).  
> Это отличается от подтверждённой retry policy других границ.  
> Нужно сохранить наблюдаемое поведение или согласовать отдельное изменение?
> 
> Вариант A: переносим как есть.  
> Вариант B: создаём отдельную behavior-change задачу.
> 
> По умолчанию выберу A (точная семантика прототипа), если не скажешь иначе.

-----

## Связь с другими скиллами

- **Перед `harness-prototype-port`**: `harness-source-analysis` →
  `harness-ds-precheck` + human checkpoint → `harness-prototype-plan`; porter
  выполняет только полученную task.
- Целевая структура приходит из шаблона (A2, репо рядом с прототипом) + `project_structure.md`. Порт кладёт код в слоты СРАЗУ, а не оставляет уборке.
- **`harness-prototype-port` использует**: `harness-request-exec` для verify,
  только если watcher задан AGENTS/policy, direct runtime недоступен или
  пользователь явно попросил; `harness-pre-commit-check` — перед коммитом.
- **`harness-team-layout-alignment`** теперь — коррекция ДРЕЙФА и аудит, а не первичное структурирование. Если порт клал по слотам, двигать почти нечего.
- **После `harness-prototype-port`** для production-доводки (OTel, Docker, CI/CD): другие скиллы, не этот
- **`harness-context` в режиме `refresh`** запускается после серии перенесённых
  задач, чтобы обновить AGENTS.md

-----

## Summary

|Опромышленность это            |Опромышленность это НЕ      |
|-------------------------------|----------------------------|
|Точный перенос логики          |Рефакторинг                 |
|Сохранение всех параметров     |Оптимизация                 |
|Сохранение всех полей схем     |Применение best practices   |
|Сохранение multi-step pipelines|Унификация под общий gateway|
|Размещение в слот шаблона сразу |Структура поздней уборкой   |
|Production-структура поверх    |Лучший код                  |

Твоя работа — обёртка, не переписывание.

---
name: harness-source-analysis
description: "Создаёт проверяемый prototype-analysis.md: функции, entrypoints, interfaces/fakes, LLM-вызовы, schemas, retries, filesystem IO и существующие external contracts. Используй перед harness-ds-precheck и harness-prototype-plan; отличай observed File IO, реально существующую интеграцию с неизвестным контрактом и отсутствующую в прототипе будущую production boundary."
---

Ты создаёшь **карту прототипа** — документ который точно описывает что есть в исходнике. Это не рефакторинг и не code review. Это инвентаризация.

Цель: дать `harness-prototype-port` точную спецификацию, против которой можно проверять каждую перенесённую функцию.

**Принцип: документируй то, что есть, не то, что должно быть.** Записывай
точные наблюдаемые provider/model/runtime values и странные константы, не
заменяя их «разумными» значениями.

## Вход: где источник и куда писать

- **source_path** — папка прототипа (анализируется, только чтение).
- **target_repo** — целевая репа, куда писать `docs/harness/prototype-analysis.md`.
  Если не указана пользователем — спроси ОДИН раз: «куда положить анализ:
  в текущую папку или в целевую репу <путь>?». Не угадывай молча.

Результат ВСЕГДА пишется в `<target_repo>/docs/harness/prototype-analysis.md`.
Если target_repo == source_path (анализируем прямо в целевой) — это допустимо,
но обычно прототип и целевая репа разные.

Перед анализом прочитай
`<target_repo>/docs/harness/pre-industrialization-spec.md`, если он есть. Из него
брать точную версию эталона и предоставленные сведения о будущих interfaces,
внешних системах, БД и deploy. Назначение агента, business flows, входы, выходы
и фактические интеграции вывести из прототипа самостоятельно. Target-пожелание
не является evidence того, что механизм уже существует в prototype.

Входную spec не редактировать. Все найденные границы записать в
`prototype-analysis.md`; совпадения и gaps относительно будущих подключений
явно перечислить для последующего заполнения `data-boundaries.md` на этапе B.

## Шаг 1: понять формат источника

Сначала определи **что именно** перед тобой:

- **Notebooks only** — папка с `.ipynb` файлами
- **Python project** — папка с `.py` файлами, возможно `pyproject.toml`/`requirements.txt`, без полноценной production-структуры (нет тестов или они минимальные, нет CI, монолитные модули)
- **Mixed** — notebooks + supporting Python files
- **Script-like** — один-два скрипта без чёткой структуры

Действия:

```bash
# Структура
find <source_path> -type f \( -name "*.ipynb" -o -name "*.py" \) | head -50
ls -la <source_path>

# Зависимости
cat <source_path>/requirements.txt 2>/dev/null
cat <source_path>/pyproject.toml 2>/dev/null
cat <source_path>/Pipfile 2>/dev/null

# Документация
cat <source_path>/README.md 2>/dev/null
```

Зафиксируй формат в начале анализа. От него зависит как разбираешь дальше.

-----

## Шаг 2: прочитать ВСЁ

Не пропускай файлы. Не «достаточно понятно, дальше похоже». Полный обход:

- **Для notebooks:** прочитать каждую ячейку. Markdown-ячейки тоже — там часто комментарии про логику.
- **Для py-файлов:** прочитать каждый файл целиком, не только функции с громкими именами.

Цель этого шага — понять архитектуру перед документированием. Если объём большой — можно делать по группам, но **все** функции должны быть просмотрены.

-----

## Шаг 3: создать `<target_repo>/docs/harness/prototype-analysis.md`

Используй этот шаблон. Каждая секция обязательна. Если данных нет — пиши “не используется” или “отсутствует”, не пропускай.

```markdown
# Prototype Analysis: <название>

## Источник

- Path: <абсолютный путь к источнику>
- Format: <notebooks | python | mixed | script>
- Files analyzed: <количество и список>
- Last commit / modification date: <если можно определить>
- Exact source snapshot: <git revision либо deterministic content fingerprint
  файлов из inventory; не только mtime>

## Назначение

<2-3 предложения: что делает этот прототип бизнесу. Что входит, что выходит.>

## Entry points

Откуда начинается выполнение:
- <файл / cell> → функция `X()` → дальше что вызывает

Отдельно перечислить все режимы выполнения, даже если прототип запускает не все:
- CLI/script;
- API/app factory;
- worker task registration/target;
- scheduler/beat;
- init/migration hooks.

Для каждого дать runtime-trace до бизнес-сервиса и внешних границ. Import string
из конфигурации/Makefile считать entrypoint, даже если прямых Python-ссылок нет.

## Архитектура потока данных

<простая схема: вход → обработка → выход. Используй ASCII или маркированный список.>

## Наблюдаемая capability/use map

Это не план задач, а группировка фактов по наблюдаемому результату. Для каждого
entrypoint/capability перечислить вход, результат/terminal state, вызываемые
функции, prompts, schemas/state, boundaries и shared foundations. Один helper
может быть shared; не превращать каждый helper или prompt в capability.

| Capability ID | Entrypoint/trigger | Observable result | Functions | Prompts/schemas | Boundaries | Shared dependencies |
|---|---|---|---|---|---|---|
| C-01 | ... | ... | F-... | P-... / S-... | B-... | ... |

## Функции — детальная карта

Для каждой функции назначь стабильный inventory ID (`F-001`, `F-002`, ...):

### F-NNN — `function_name(args) -> return_type`

- **Location**: `<file>:<line>` или `<notebook>:cell N`
- **Purpose**: одна строка что делает
- **External calls**: какие функции вызывает (свои + внешние)
- **Side effects**: запись в файлы, обращения к сети, изменение global state
- **Notable details**: магические константы, странные параметры, hacks

Повтори для каждой функции включая helpers. Скрывать ничего нельзя.

## LLM-вызовы — критичная секция

Каждый вызов LLM документируется отдельно:

### LLM-NNN — <имя или контекст>

- **Provider**: точное имя из кода/effective config
- **Model**: точное имя из кода/effective config
- **Base URL**: если есть (для self-hosted)
- **Credentials**: cert_file/key_file/api_key — пути или env var имена
- **Parameters**:
  - `timeout`: точное число
  - `temperature`: точное число
  - `profanity_check`: True/False
  - `verify_ssl_certs`: True/False
  - другие параметры — все которые установлены явно
- **Retry logic**: MAX_RETRIES, backoff, какие исключения retry'ятся
- **Multi-step?**: если вызов из нескольких этапов (text → structured, prompt + parse, etc) — описать каждый этап
- **Prompt template**: где лежит, какие переменные подставляются
- **Output schema**: для structured output — точная схема (pydantic model или dict)
- **Actual request contract**: provider path, `response_format`, JSON schema/name,
  provider-specific `extra_body`/filter flags и sanitized outgoing payload. Фраза
  в prompt «верни JSON» не считается structured-output механизмом.
- **Error handling**: что происходит при сбое LLM

Если вызовов несколько — повторить для каждого. **Особое внимание multi-step pipelines** — это место где Codex чаще всего "оптимизирует" в один шаг.

## Схемы данных

Для каждой структуры данных (pydantic, dict, dataclass):

### S-NNN — `SchemaName`

- **Defined in**: где в коде
- **Fields**: точный список всех полей с типами
  - `field_name: type` — описание
- **Used by**: какие функции читают/пишут

**Не упрощай** даже если поля выглядят избыточно (`status` + `verdict` — оставь оба, прототип так работает).

## Конфигурация

- Env vars: какие используются и где
- Config files: пути
- Hardcoded constants: магические числа и строки, где
- Feature flags: если есть

## Зависимости

- **Production dependencies**: список с версиями если указаны
- **LLM provider SDKs**: какие
- **Special**: все необычные runtime/dependency requirements с точным evidence

## Внешние интеграции

До таблицы классифицировать текущее состояние каждой границы:

- `FILE_IO_OBSERVED` — прототип читает/пишет локальные файлы;
- `EXTERNAL_CONTRACT_OBSERVED` — внешняя интеграция и её контракт наблюдаются;
- `EXTERNAL_CONTRACT_UNKNOWN` — есть evidence существующей интеграции, но точный
  контракт не получен;
- `NO_EXTERNAL_BOUNDARY` — внешней интеграции в прототипе нет; возможная
  production boundary будет спроектирована отдельно.

`UNKNOWN` запрещено использовать как синоним отсутствующего endpoint. Кроме
LLM, составить таблицу только по реально существующим внешним границам:

| Boundary | Protocol | Exact URL/path/tool/topic | Method | Auth/headers | Request/path/body | Response shape | Source branch | Preconditions/side effects | Error/terminal semantics | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|

Для каждой наблюдаемой external boundary отдельно зафиксировать lifecycle, не
смешивая side-effect-free object с активным соединением:

| Package/SDK | Manifest constraint | Locked version | Local/cluster access | Object scope | Session/stream scope | Create/close event | Startup/readiness critical | Retry owner | Failure boundary | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|

Evidence — точный файл/строка, version/hash OpenAPI, sanitized real sample или
runtime log. Документацию, код и реальный payload хранить раздельно; конфликт не
«нормализовать», а вынести в `Открытые вопросы`. Нельзя выводить REST path из
имени сервиса или считать MCP tool REST-endpoint.

Для request/response явно проверить absent/null/empty/malformed/valid, aliases,
enum/date encoding, tenant/source headers и внешние prerequisites. Для Protocol/
ABC перечислить implementations, fakes, DI providers и callers: изменение
сигнатуры должно иметь известный blast radius.

Файловые операции вынести отдельным IO inventory: read/write, input/storage/
output, path, format/schema, encoding, lifecycle, ordering, atomicity,
idempotency, error semantics и текущая abstraction boundary. Для protocol,
method, route и headers писать `N/A — not present in prototype`, не `UNKNOWN`.
Если target replacement уже подтверждён, сослаться на отдельный target contract;
если нет — отметить `GREENFIELD_BOUNDARY_NOT_DESIGNED` без догадки о механизме.

## Странности и hacks

Это **критичная** секция. Здесь документируется всё что выглядит "не лучшая практика" но **работает** и должно быть сохранено:

- Магические константы без объяснения
- Закомментированный код который явно нужен
- Try/except вокруг очевидно стабильного кода (значит был случай когда падало)
- Двойные вызовы LLM с похожими промптами (обычно есть бизнес-причина)
- Странный порядок операций
- Hardcoded пути или ID

Для каждого — пометка "не упрощать без understanding why".

## Что НЕ переносить

Явно перечислить:
- Сертификаты, ключи API
- Notebook outputs, checkpoints
- Локальные test данные с PII
- .DS_Store, __pycache__, .ipynb_checkpoints
- Подтверждённые personal experiments/dead code — только после evidence и
  человеческого решения. Неясный кандидат остаётся в анализе и идёт в
  двухтактный dead-code audit; не исключать его догадкой.

## Открытые вопросы

Если что-то непонятно — НЕ домысливай. Списком зафиксировать:
- Почему наблюдаемое runtime-значение отличается от командной конвенции?
- Зачем прототип использует несколько последовательных LLM-вызовов?
- Что является корректным terminal outcome для неописанной ветки?

Эти вопросы потом задаются методологу/автору прототипа **до** переноса.
```

-----

## Шаг 4: проверить полноту

Перед тем как считать analysis готовым:

1. **Каждая функция в источнике упомянута** — даже helpers и однострочники
2. **Каждый LLM-вызов документирован отдельно** — не «вообще используется один provider»
3. **Все поля каждой схемы перечислены** — не “стандартная pydantic-модель”
4. **Магические константы с конкретными значениями** — не “разумный таймаут”
5. **Открытые вопросы записаны** — лучше зафиксировать неясности чем угадать
6. **Каждая реально существующая внешняя граница имеет provenance** — exact
   route/tool, headers, request/response либо `EXTERNAL_CONTRACT_UNKNOWN` с
   evidence самого факта интеграции. File IO имеет transport fields `N/A`, а
   отсутствующая будущая boundary — `NO_EXTERNAL_BOUNDARY`, не `UNKNOWN`
7. **Каждый интерфейс имеет implementation/fake/caller inventory**, если такие
   реализации существуют
8. **Каждая граница описана и классифицирована** одним из канонических состояний:
   `FILE_IO_OBSERVED`, `EXTERNAL_CONTRACT_OBSERVED`,
   `EXTERNAL_CONTRACT_UNKNOWN` или `NO_EXTERNAL_BOUNDARY`, чтобы следующий
   planning pass мог перенести факт в `data-boundaries.md` и предложить блок
   решения человеку. Будущий endpoint не записывается как существующий
   prototype contract
9. **Capability/use map покрывает inventory**: каждая функция, prompt, schema,
   LLM-вызов и boundary принадлежит наблюдаемой capability либо явно помечена
   `shared`/`inactive`. Это coverage для будущего grouping, не список tasks
10. **Source snapshot воспроизводим**: записан exact revision или content
    fingerprint. Пока он не изменился, downstream skills могут повторно
    использовать analysis; после изменения source analysis считается stale
11. **Для observed external client разделены object и active-session lifecycle**:
    constraint/lock, access, create/close, startup criticality, retry owner и
    failure boundary имеют evidence; `APP` scope объекта не переносится молча на
    активное сетевое соединение

Запусти простую проверку:

```bash
# Сколько функций в источнике
grep -c "^def \|^    def " <source>/**/*.py 2>/dev/null
# или для notebooks — посчитай вручную в основных cells

# Сколько функций в analysis
grep -c "^### F-" docs/harness/prototype-analysis.md
```

Числа должны быть сопоставимы. Если в источнике 50 функций а в анализе 10 — что-то пропущено.

-----

## Шаг 5: согласовать с пользователем

После создания файла — покажи пользователю:

```
✓ prototype-analysis.md создан (<N> строк)

✓ prototype-analysis.md записан в: <target_repo>/docs/harness/prototype-analysis.md

Найдено:
- <K> функций
- <L> LLM-вызовов (multi-step: <M>)
- <P> схем данных
- <Q> открытых вопросов

Открытые вопросы требуют внимания перед планированием переноса:
<список>

Следующий шаг: harness-ds-precheck.
```

Если есть открытые вопросы — пользователь решает: задать автору прототипа, или интерпретировать самому, или зафиксировать как риск.
Если открытых вопросов, требующих решения, нет и skill вызван из
`harness-productionize`, сразу вернуть управление оркестратору для запуска
`harness-ds-precheck`; не создавать отдельный checkpoint между анализом и
precheck.

-----

## Что важно

- **Точность > краткости.** Лучше длинный документ с деталями чем короткий с догадками.
- **Не интерпретируй.** Если код выглядит странно — пиши как есть, не «вероятно автор имел в виду».
- **Не упрощай.** Богатая схема с 8 полями — документируй все 8, не своди к “verdict + reason”.
- **Не оптимизируй на этом этапе.** Это карта местности, не план улучшений.
- **Не пропускай.** Каждая функция, каждый параметр, каждая константа.

-----

## Что НЕ делать

- **НЕ редактировать сам прототип.** Только чтение.
- **НЕ комментировать качество кода.** “Этот код плохо написан” — не относится к делу. Документируй что есть.
- **НЕ предлагать улучшения.** Анализ — нейтральная инвентаризация; кандидаты
  идут в cleanup/optimization ledger `harness-ds-precheck` и только после parity
  могут попасть в backlog отдельным planning pass. С port-задачей их не смешивать.
- **НЕ догадывать пропущенное.** Лучше пометить как open question.
- **НЕ дописывать во входную spec догадки или наблюдаемые факты.** Она хранит
  предоставленные production-реквизиты; факты анализа принадлежат
  `prototype-analysis.md` и `data-boundaries.md`.

-----

## Примеры применения

### Пример 1: notebooks

Вход: `~/projects/my-prototype/` содержит 3 `.ipynb`

Действия:

1. Прочитать каждую ячейку каждого notebook
2. Markdown-ячейки → use case и комментарии в “Назначение”
3. Code-ячейки → функции и логика
4. Cell outputs → не учитывать (не код, побочный результат)
5. Создать `docs/harness/prototype-analysis.md`

### Пример 2: Python-прото-репа

Вход: `~/projects/my-prototype-py/` содержит `main.py`, `helpers.py`, `config.py`

Действия:

1. Прочитать все `.py` файлы целиком
2. Парсить функции, классы, константы
3. `main.py` → entry point
4. Зафиксировать импорты и зависимости из `requirements.txt`
5. Создать `docs/harness/prototype-analysis.md`

### Пример 3: смешанный

Вход: notebooks для exploration + `pipeline.py` с production-кодом

Действия:

1. Сначала прочитать `pipeline.py` — это production-логика
2. Потом notebooks — там может быть exploration без переноса в код
3. В analysis отметить какие функции из notebooks **уже** в `pipeline.py`, какие — нет
4. Открытый вопрос: что из notebooks должно остаться, что не нужно

-----

После того как `prototype-analysis.md` готов — переходи к
`harness-ds-precheck`. Human checkpoint нужен только для реальных открытых
вопросов или П-находок; если их нет, оркестратор сразу переходит к
`harness-prototype-plan`.
К `harness-prototype-port` переходят только задачи из подтверждённого плана.

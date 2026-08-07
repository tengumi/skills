---
name: harness-context
description: "Создаёт или безопасно обновляет harness-контекст. Используй bootstrap-minimal для target с team docs либо явно переданным team_docs_source, bootstrap-full только при подтверждённом отсутствии официальных docs, refresh — для дельта-обновления auto-owned секций без изменения командных документов и task lifecycle."
---

Ты реализуешь **harness-методологию** для AI-ассистированной разработки в этом репозитории.
Твоя цель: сделать эту кодовую базу максимально навигируемой и продуктивной для AI-кодера в каждой будущей сессии.

**Основной принцип — репозиторий как источник истины**: всё, что нужно агенту, должно быть обнаружимо из самого репо.

---

## Как работает этот скилл

Ты **интеллектуально определяешь уровень детализации** по доступному контексту:

| Контекст | Действие |
|----------|----------|
| Достаточно информации | Генерируй полный контекст сразу |
| Недостаточно информации | Задавай уточняющие вопросы |
| Есть cross-repo API | Запрашивай детали взаимодействия |
| Моно-репозиторий | Анализируй связи между сервисами |

Сначала определить режим:

- `bootstrap-minimal` — team docs/template уже существуют в target либо передан
  точный `team_docs_source`: сохранить существующие docs; из явного source после
  проверки отсутствия collisions автоматически скопировать только отсутствующие
  team-owned файлы, записать их hashes/provenance, затем создать/обновить
  `AGENTS.md` и при отсутствии пустой `tasks.json`. Сам вызов
  `harness-productionize` разрешает эти scoped bootstrap-записи; отдельное
  подтверждение плана не нужно;
- `bootstrap-full` — harness и официальные team docs отсутствуют: предложить
  полный набор repo-owned артефактов и показать план до записи;
- `refresh` — harness уже существует: обновить только доказанно устаревшие
  auto-owned секции. Для этого режима полностью прочитать и выполнить
  [references/refresh.md](references/refresh.md), а bootstrap-шаги ниже не
  выполнять.

Файлы команды `architecture.md`, `configuration.md`, `conventions.md`,
`dev-setup.md`, `project_structure.md`, `rules.md`, `mle-pep8.md` read-only в
любом режиме, если они уже предоставлены командой. Обнаруженное расхождение
оформить вопросом/proposal, не правкой. `bootstrap-full` может создать только
отсутствующие repo-owned аналоги, когда официального источника действительно нет.
При `team_docs_source` не перезаписывать одноимённый target-файл: показать
collision и оставить target до решения владельца. Для скопированного snapshot
создать `docs/harness/team-docs-source.json` с source label и SHA256 без secrets
или персонального absolute path.

В `bootstrap-minimal` human checkpoint нужен только при collision,
противоречащих team sources или необходимости создать/изменить не входящий в
этот bounded scope файл. Отсутствующие `AGENTS.md`, `tasks.json` и exact-source
team docs сами по себе checkpoint не создают.

---

## Шаг 1: Анализ контекста

### Определи тип репозитория:
- **Single repo**: один сервис, нет cross-repo зависимостей
- **Monorepo**: несколько сервисов, есть cross-repo API
- **Service with external deps**: зависит от внешних сервисов (базы, брокеры и т.д.)

### Определи уровень детализации:
- **Basic**: уже есть документация, нужно только обновить/добавить AGENTS.md
- **Extended**: нужно проанализировать код, но без деталей cross-repo API
- **Full**: нужен полный анализ с cross-repo boundaries и архитектурными решениями

---

## Шаг 2: Интерактивный диалог (если нужно)

Если контекста недостаточно — задавай вопросы:

В `bootstrap-minimal` с точным team template/docs source этот общий опрос не
проводить. Неизвестные cross-repo, deploy или production-boundary детали
фиксируются как gaps для этапа B и не задерживают создание минимального
контекста или анализ прототипа. Спрашивать только о collision/конфликте
источников либо о факте, без которого невозможно определить сам target.

```
> Для точного анализа мне нужно уточнить:
> 
> 1. Есть ли у этого сервиса cross-repo API (взаимодействие с другими репозиториями)?
>    - REST/GRPC клиенты к другим сервисам?
>    - Event producers/consumers?
> 
> 2. Какой тип деплоя?
>    - Docker/Kubernetes?
>    -裸-metal/vm?
>    - Serverless?
> 
> 3. Есть ли CI/CD конфиг?
```

---

## Шаг 3: Анализ перед генерацией

Прочитай в этом порядке:
1. Все top-level файлы: README, pyproject.toml / package.json / pom.xml / build.gradle / go.mod / Cargo.toml
2. Структура директорий (2 уровня глубины)
3. Главные точки входа (entry points)
4. Существующие тестовые файлы (для понимания покрытия и паттернов)
5. Любые CI-конфиги (.github/workflows/, .gitlab-ci.yml, Jenkinsfile)
6. Любая существующая документация

**Если в коде есть workflow/state-machine/orchestration слой** (например LangGraph, Airflow, Celery workflow, Temporal, custom graph):
7. Найди entry point workflow, список основных узлов/шагов, условия переходов, форму state/context и внешние tools/dependencies, которые вызываются из workflow. Описывай это в `architecture.md` как скелет и контракт workflow, а не как построчный пересказ бизнес-логики.

**Если моно-репозиторий:**
8. Найди cross-repo API:
   - REST клиенты (grep `RestTemplate`, `httpx`, `axios`, `feign`, `requests.get`)
   - gRPC клиенты (`.proto` файлы, generated code)
   - Event producers/consumers (Kafka topics, RabbitMQ queues, SNS/SQS)
   - Shared libraries (внешние зависимости в `pom.xml`/`requirements.txt`)

---

## Шаг 4: Генерация `AGENTS.md`

Создай или обнови `AGENTS.md` в корне репозитория.
**Жёсткий лимит: ≤120 строк.** Это навигационная карта, а не документация.

```
# [Название сервиса]

## Назначение
[2–3 предложения: что делает этот сервис, кто его потребляет, где он находится в общей системе]

## Стек
- Язык: [имя + версия]
- Фреймворк: [имя + версия]
- Ключевые зависимости: [3–5 самых важных]
- Runtime: [Docker / venv / JVM / Node / etc]

## Быстрые команды
```
make install    # установить / развернуть зависимости
make dev        # запустить dev-сервер или агента
make test       # полный набор тестов
make lint       # линтеры + проверка типов
make verify     # полный repo-gate на capability/bundle границе
```

## Карта кода
[путь]   → [одна строка назначение]
[путь]   → [одна строка назначение]
[путь]   → [одна строка назначение]
...

## Соглашения
- [3–7 конкретных соглашений, специфичных для этой кодовой базы]

## Что НЕ делать
- [2–3 анти-паттерна, которые вызывали баги или путаницу в этом коде]

## Протокол сессии
1. Прочитать AGENTS.md и текущую задачу
2. Запустить `harness-work-session` для ОДНОЙ задачи; claim/submit выполняет tasks-mcp
3. Зафиксировать baseline до правок
4. Реализовать только acceptance текущей задачи
5. Выполнить уровень проверки из задачи; watcher использовать только если этого требует окружение
6. Пройти harness-pre-commit-check и submit_task с evidence

## Подробная документация
- [docs/harness/architecture.md](docs/harness/architecture.md) — системный дизайн, поток данных, компоненты
- [docs/harness/conventions.md](docs/harness/conventions.md) — стандарты кода, паттерны, анти-паттерны
- [docs/harness/dev-setup.md](docs/harness/dev-setup.md) — настройка окружения с нуля
- [docs/harness/tasks.json](docs/harness/tasks.json) — бэклог задач (машиночитаемый)
```

В эту секцию включать только реально существующие файлы. Например,
`cicd.md`/`team-patterns-production.md` добавлять после их появления, а не
создавать broken link в `bootstrap-minimal`.

---

## Шаг 5: Генерация директории `docs/harness/`

В режиме `bootstrap-full` предложи создать отсутствующие repo-owned файлы ниже. В режиме
`bootstrap-minimal` этот шаг пропустить: создать только отсутствующий пустой
`tasks.json`; team-owned docs не дополнять.

### `docs/harness/architecture.md`
- ASCII или prose-диаграмма системы
- Ответственность компонентов
- Workflow/state-machine слой, если есть: entry point, основные узлы/шаги, условия переходов, state/context, внешние tools/dependencies и где лежит реализация
- Поток данных (входы → обработка → выходы)
- Внешние интеграции и зависимости
- Ключевые архитектурные решения с обоснованием
- Известные ограничения

### `docs/harness/conventions.md`
- Стиль кода и правила форматирования
- Соглашения об именовании (файлы, классы, функции, переменные)
- Паттерны обработки ошибок
- Соглашения по логированию
- Паттерны тестирования и что мокать vs не мокать
- Анти-паттерны, явно запрещённые в этом коде

### `docs/harness/dev-setup.md`
- Предварительные требования (требуемые версии)
- Пошаговая настройка окружения с чистой машины
- Как запустить сервис локально
- Как запустить набор тестов
- Распространённые проблемы и их решения

### `docs/harness/cicd.md`
- Структура CI/CD пайплайна
- Как проходят тесты и линты
- Процесс деплоя
- Как локально воспроизвести CI-окружение

### `docs/harness/tasks.json`
```json
{
  "last_updated": "YYYY-MM-DD",
  "current_sprint": [],
  "completed_sprint": [],
  "backlog": [],
  "discovered_bugs": [],
  "tech_debt": []
}
```

Формат задачи:
```json
{
  "id": "T-001",
  "title": "краткое повелительное описание",
  "type": "feat | fix | refactor | debt | bug",
  "priority": "high | medium | low",
  "status": "open",
  "acceptance_criteria": ["проверяемый критерий готовности"],
  "approvals": [],
  "notes": "опциональный контекст для агента"
}
```

В persisted `tasks.json` каноническое поле — `acceptance_criteria`. После claim
tasks-mcp может возвращать его нормализованным как `task.acceptance`; это одно и
то же содержимое, а не два параллельных контракта.
`approvals` опционально хранит уже выданные разрешения с точным scope,
provenance/owner и датой; один `files_hint` или общий task scope разрешением на
protected path не считается.

---

## Шаг 6: Генерация или обновление `Makefile`

Только в режиме `bootstrap-full` и при явном scope предложи реальные команды. Если команда
неизвестна, Makefile не менять: зафиксировать пробел в отчёте/отдельной задаче.
Комментарий `TODO` не превращает нерабочую target в допустимую.

```makefile
.PHONY: install dev test lint build verify

install:
	[реальная команда]

dev:
	[реальная команда]

test:
	[реальная команда]

lint:
	[реальная команда]

verify: lint test
	@echo "✓ Baseline verified"
```

Stack-specific дефолты:
- **Python**: `ruff check src/ tests/` для линта, `mypy src/` для типов, `pytest tests/ -v` для тестов
- **Java**: `./mvnw verify` или `./gradlew check`
- **Node/TS**: `eslint src/`, `tsc --noEmit`, `vitest run` или `jest`

---

## Шаг 7: Отчёт

После работы выведи mode-aware отчёт. Перечислять только фактически созданные,
обновлённые, скопированные или сохранённые файлы; отсутствующий `cicd.md` и
Makefile в `bootstrap-minimal` не выдавать за результат.

```
## Harness Context Сгенерирован

✓ AGENTS.md — [N строк]
✓ <path> — [создан | обновлён | скопирован из <source> | сохранён без изменений]
… только actual touched/kept paths

## Cross-repo API (если анализировал)
- [service-name]: REST → [endpoint] in [file]
- [service-name]: Kafka → [topic] in [file]

## Пробелы — требует человеческого ввода
- [ ] [пробел: напр. "не удалось определить цель развертывания"]
- [ ] [пробел: напр. "набор тестов не найден — цель make test заглушка"]

## Рекомендуемые следующие шаги
1. Проверь AGENTS.md и добавь доменные знания, которые не раскрывает код
2. Запусти documented verify-команду, если она существует
3. Сформируй задачи первого спринта профильным planning-skill и добавь их в очередь
4. Закоммить: `harness: добавить слой контекста`
```

---

## Жёсткие ограничения

- AGENTS.md должен быть ≤120 строк — это карта, а не инструкция
- Никогда не пиши заглушки — каждая цель Makefile должна выполнять реальные команды
- Никогда не перезаписывай существующую документацию — только дополняй
- В `bootstrap-minimal` не редактируй team docs и Makefile вообще
- В `refresh` следуй ownership-маркерам, сначала покажи план, сделай backup и
  не изменяй `tasks.json`; детали обязательны из `references/refresh.md`
- После bootstrap не меняй вручную lifecycle-поля существующих задач (`status`,
  `claimed_by`, `attempts`, `evidence`): их ведёт tasks-mcp. Planning-skills могут
  добавить новые `open` задачи после показа плана человеку, сохраняя схему и не
  переписывая существующие записи.
- Отмечай любые проблемы безопасности (захардкоженные секреты, отсутствие валидации)
- Если в репо есть существующие паттерны — следуй им — не навязывай новые без пометки пробела

---

## Примеры поведения

### Сценарий 1: Мало контекста
```
Пользователь: harness-context
Контекст: nothing

> Меня зову harness-context. Чтобы сгенерировать контекст для вашего репозитория,
> мне нужно понять его структуру.
> 
> 1. Это monorepo с несколькими сервисами?
> 2. Есть ли cross-repo API (взаимодействие с другими репозиториями)?
> 3. Какой тип деплоя (Docker/Kubernetes/bare-metal)?
```

### Сценарий 2: Достаточно контекста
```
Пользователь: harness-context
Контекст: путь к репо, README.md, структура

> Анализирую репозиторий...
> Найдены: README.md, pyproject.toml, src/, tests/, .github/workflows/
> 
> ✓ Генерирую AGENTS.md
> ✓ Генерирую docs/harness/
```

### Сценарий 3: Cross-repo API
```
Пользователь: harness-context
Контекст: monorepo с несколькими сервисами

> Обнаружена monorepo структура с несколькими сервисами.
> Анализирую cross-repo API...
> 
> 1. В файле src/service-a/client.py найден REST-клиент к service-b
> 2. В файле src/service-c/producer.py найден Kafka producer
> 
> Уточните:
> - API endpoint для service-b?
> - Kafka topic для service-c?
```

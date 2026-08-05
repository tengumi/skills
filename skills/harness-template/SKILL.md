---
name: harness-template
description: "Создаёт scaffold только для true greenfield. Если существует официальный team template или задача переносит прототип, инстанцирует именно его и не применяет generic src/.github/health defaults. Используй generic stacks лишь при явном отсутствии team template и подтверждении пользователя."
---

Ты создаёшь **новый сервис с нуля** с использованием harness-методологии.
Это greenfield — создавай каждый файл с реальным, рабочим контентом. Нет заглушек. Нет TODO, которые не отслеживаются в tasks.json.

Для опромышливания существующего прототипа official team template обязателен и
имеет приоритет над всеми generic секциями ниже. Прими `template_path`, скопируй
его структуру, затем выполни классифицированный rename, проверь scaffold и после
initial baseline commit передай управление `harness-productionize`.

---

## Разбор входных данных

Извлеки из аргументов:
- `name`: имя сервиса → используй `kebab-case` для директории, `snake_case` для Python-пакетов, `PascalCase` для Java
- `stack`: один из `python-agent`, `python-service`, `java-service`, `frontend`

Если что-то отсутствует — уточни перед началом.

Перед генерацией спроси/найди `template_path`. Если задача относится к team
productionization, а официальный template неизвестен — STOP; generic scaffold
не является безопасной заменой.

---

## Проверка источников структуры и team patterns

Приоритет источников: **official team docs/template → human-approved
team-patterns.json → generic true-greenfield defaults**. Patterns не могут
переопределить официальный шаблон или командную документацию.

Перед генерацией любого кода проверь наличие `team-patterns.json` в корне workspace
(родительская директория того места, где будет создан новый сервис, или текущая директория).

**Если `team-patterns.json` существует и `review.status == "approved"`:**
Прочитай его. Используй как дополнительный источник для решений, не заданных
official docs/template:
- Зависимости → используй версии и библиотеки из списка, а не generic дефолты
- Naming conventions → следуй разделу `naming` точно
- Структура проекта → следуй `project_structure.source_dir` паттерну
- Паттерн конфигурации → используй подход из `config_pattern.approach` с примером
- Логирование → используй библиотеку и настройку из `logging_pattern`
- Обработка ошибок → следуй паттерну `error_handling`
- Паттерны агентов → следуй разделу `agent_patterns` (определение инструментов, локация промпта и т.д.)
- Паттерны тестирования → следуй разделу `test_patterns` (стратегия моков, стиль фикстур, async режим)
- Git-соглашения → используй формат коммитов из `git_conventions`

Паттерн с `confidence: low` не применять автоматически. Он допустим только если
его точный JSON path перечислен в `review.approved_low_confidence`; иначе это
coverage gap и вопрос владельцу, а не стандарт scaffold.

**Если файл существует, но review отсутствует или status не `approved`:**
считать его evidence/candidate only. Не применять к коду; запросить review либо
продолжить по более приоритетному official source.

**Если одобренного `team-patterns.json` нет:**
Продолжай с generic дефолтами только для подтверждённого true greenfield без
official team template.
Добавь примечание в сгенерированный AGENTS.md:
```
> Запусти `harness-extract-patterns` в корне workspace для генерации team-specific conventions.
> Затем перегенерируй этот scaffold для версии с team-style.
```

---

## Стек: `python-agent`

Создай эту структуру с полным контентом в каждом файле:

```
{name}/
├── AGENTS.md
├── Makefile
├── pyproject.toml
├── .pre-commit-config.yaml
├── .github/
│   └── workflows/
│       └── ci.yml
├── src/
│   └── {name_snake}/
│       ├── __init__.py
│       ├── agent.py            ← основной класс агента + точка входа
│       ├── config.py           ← настройки из env vars (pydantic-settings)
│       ├── tools/
│       │   ├── __init__.py
│       │   └── base.py         ← абстрактный класс BaseTool
│       └── prompts/
│           └── system.md       ← шаблон system prompt
├── tests/
│   ├── conftest.py
│   ├── test_agent.py
│   └── test_tools.py
└── docs/harness/
    ├── architecture.md
    ├── conventions.md
    ├── dev-setup.md
    ├── cicd.md
    └── tasks.json
```

**Обрати внимание:** структура `docs/harness/` используется в обоих случаях — как для новых, так и для существующих сервисов.

### `pyproject.toml`
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []  # добавь LLM SDK сюда

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
    "mypy>=1.9",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
strict = false

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

### `Makefile`
```makefile
.PHONY: install dev test lint build verify

install:
	pip install -e ".[dev]"

dev:
	python -m src.{name_snake}.agent

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/
	mypy src/

verify: lint test
	@echo "✓ Baseline verified"
```

### `src/{name_snake}/agent.py`
Напиши реальный минимальный класс агента:
- `__init__` с приемом config
- метод `run(task: str) -> str`
- точка входа `if __name__ == "__main__"`
- Type hints на все методы

### `src/{name_snake}/config.py`
Используй pydantic-settings или dataclass:
- Загрузка из переменных окружения
- Как минимум: `model_name`, `log_level`

### `src/{name_snake}/tools/base.py`
Абстрактный базовый класс `BaseTool`:
- свойство `name: str`
- свойство `description: str`
- абстрактный метод `run(input: str) -> str`

### `tests/conftest.py`
Напиши реальные фикстуры:
- фикстура `agent`, возвращающая инициализированного агента
- любые общие тестовые утилиты

### `tests/test_agent.py`
Напиши реальные тесты (не заглушки):
- Тест инициализации агента без ошибок
- Тест `run()` с простым входом
- Отметь медленные/integration тесты `@pytest.mark.integration`

### `.github/workflows/ci.yml`
```yaml
name: CI
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: make install
      - run: make verify
```

### `AGENTS.md`
Создай AGENTS.md в корне репозитория со следующей структурой:

```markdown
# {name} — Agent Guide

## Quick Start
1. Read `docs/harness/architecture.md` for domain map.
2. Read `docs/harness/conventions.md` for code patterns.
3. Read `docs/harness/cicd.md` for build & deploy context.
4. Run `make dev` to boot environment.
5. Check `docs/harness/tasks.json` for current work queue.

## Boundaries
- [ ] DO NOT add new external dependencies without human approval
- [ ] DO NOT change database schema without migration file
- [ ] DO NOT modify CI/CD pipeline without human approval
- [ ] DO NOT use placeholder implementations

## Key Locations
- Entry point: `src/{name_snake}/agent.py`
- Tests: `tests/` — run with `make test`
- Config: `src/{name_snake}/config.py`
- CI/CD: `.github/workflows/ci.yml`
- Dockerfile: `Dockerfile`

## Emergency Recovery
- Broken build? Остановить задачу, показать `git diff/status` и last known good;
  destructive reset выполняет человек только по явному решению.
```

---

## Стек: `python-service`

То же, что `python-agent`, но замени `agent.py` на FastAPI приложение:

```
src/{name_snake}/
├── __init__.py
├── app.py              ← фабрика FastAPI app
├── config.py
├── routers/
│   ├── __init__.py
│   └── health.py       ← endpoint GET /health
├── models/
│   ├── __init__.py
│   └── schemas.py      ← Pydantic модели запроса/ответа
└── services/
    ├── __init__.py
    └── base.py         ← слой бизнес-логики
```

Дополнительные файлы:
- `Dockerfile` — multi-stage build, non-root user
- `docker-compose.yml` — сервис + любые зависимости (бд, кэш)

Дополнительные dev-зависимости: `fastapi`, `uvicorn[standard]`, `httpx`, `pytest-httpx`

Цель `dev` в Makefile: `uvicorn src.{name_snake}.app:app --reload --port 8000`

Добавь тест для `GET /health`, возвращающего `{"status": "ok"}`.

---

## Стек: `java-service`

```
{name}/
├── AGENTS.md
├── Makefile
├── pom.xml             ← Spring Boot parent, Java 21
├── .github/
│   └── workflows/
│       └── ci.yml
├── src/
│   ├── main/
│   │   └── java/com/example/{NamePascal}/
│   │       ├── {NamePascal}Application.java
│   │       ├── config/
│   │       ├── controller/
│   │       ├── service/
│   │       └── repository/
│   └── test/
│       └── java/com/example/{NamePascal}/
│           └── {NamePascal}ApplicationTests.java
└── docs/harness/
    ├── architecture.md
    ├── conventions.md
    ├── dev-setup.md
    ├── cicd.md
    └── tasks.json
```

Makefile оборачивает Maven:
```makefile
verify:
	./mvnw verify

dev:
	./mvnw spring-boot:run

test:
	./mvnw test

lint:
	./mvnw checkstyle:check
```

---

## Стек: `frontend`

```
{name}/
├── AGENTS.md
├── Makefile
├── package.json        ← Vite + React/Vue + TypeScript
├── tsconfig.json
├── .eslintrc.json
├── .github/workflows/ci.yml
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   └── components/
├── tests/
│   └── App.test.tsx
└── docs/harness/
    ├── architecture.md
    ├── conventions.md
    ├── dev-setup.md
    ├── cicd.md
    └── tasks.json
```

Makefile:
```makefile
install:
	npm ci

dev:
	npm run dev

test:
	npm run test

lint:
	npm run lint
	npx tsc --noEmit

verify: lint test
	@echo "✓ Baseline verified"
```

---

## После генерации

Сначала проверь сам сгенерированный scaffold: clean `make install`, import smoke
и `make verify` должны проходить сразу. После review, инициализации репозитория и
первого baseline commit передай управление `harness-productionize` для переноса
прототипа либо `harness-work-session` для обычной очереди. Отдельная повторная
проверка окружения не нужна: зелёное evidence scaffold переиспользуется.

Вывод:
```
## Scaffold Created: {name} ({stack})

Files generated:
[list all files]

Run:
  cd {name}
  make install
  make verify

Next: open AGENTS.md and fill in the Purpose section with domain context.
Then run `harness-context` to review and augment if needed.
```

---

## Жёсткие ограничения

- Каждый файл должен иметь реальный рабочий контент — нет заглушек
- Все Makefile цели должны выполнять реальные команды
- AGENTS.md должен быть ≤120 строк — это карта, а не инструкция
- docs/harness/ должен быть заполнен полезной документацией
- tasks.json должен быть заполнен реальными задачами первого спринта
- Для team productionization generic структуры/health/CI из этого skill
  запрещены: использовать official template и exact team docs.
- Rename выполнять по identity inventory, не глобальной заменой: service/package/
  repo/CI/image/queue/schema tokens меняются отдельно; domain/external names
  сохраняются.

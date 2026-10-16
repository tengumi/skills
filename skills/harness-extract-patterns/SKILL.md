---
name: harness-extract-patterns
description: "Сравнивает репозитории workspace и создаёт team-patterns.json/team-conventions.md как наблюдаемые паттерны для harness-template. Используй только когда официальных team docs/template недостаточно; majority не становится стандартом без проверки владельца."
---

Ты выполняешь **извлечение паттернов через репозитории** в workspace.
Цель: синтезировать то, что *фактически делает команда*, в машиночитаемый и человекочитаемый стандарт,
чтобы новые сервисы могли генерироваться в стиле команды — а не generic scaffold.

Это отличается от `harness-scan`: он инвентаризирует, что существует;
`harness-extract-patterns` читает код
и понимает, как команда строит вещи.

---

## Шаг 1: Поиск репозиториев

Используй `workspace.json`, если он существует в корне workspace (произведён `harness-scan`).
Иначе найди репы самостоятельно: директории, содержащие `.git`, `pyproject.toml`, `pom.xml`, `package.json`, `go.mod`.

Пропускай: `node_modules/`, `.venv/`, `__pycache__/`, `target/`, `dist/`.

Сгруппируй обнаруженные репы по стеку для отдельного анализа.

---

## Шаг 2: Чтение каждого репозитория

Для каждой репы прочитай следующее. Не пропускай репы — паттерны надёжны только при извлечении из
полного набора.

**Python репы — прочитай:**
- `pyproject.toml` или `setup.py` или `requirements.txt` — список зависимостей
- `src/` или top-level пакет — первые 2 уровня структуры
- Один представительный исходный файл (главный модуль или класс агента)
- `tests/conftest.py` и один тестовый файл
- `Makefile` если присутствует
- `.pre-commit-config.yaml` если присутствует
- Настройка логирования (поиск `import logging`, `from loguru`, `structlog`)
- Класс config/settings (поиск `BaseSettings`, `dataclass`, `os.environ`)
- Обработка ошибок (поиск `except`, `raise`, кастомные exception классы)
- Git log: `git log --oneline -20` для стиля сообщений коммитов

**Java репы — прочитай:**
- `pom.xml` или `build.gradle` — зависимости и версии
- Главный класс приложения
- Один controller и один service класс
- Один тестовый класс
- `application.yml` или `application.properties`

**Frontend репы — прочитай:**
- `package.json` — deps, scripts
- `tsconfig.json`
- `.eslintrc.*`
- Один файл компонента
- Один тестовый файл

---

## Шаг 3: Извлечение паттернов по стеку

Для каждого стека (Python / Java / Frontend) определи следующее.
Для каждого паттерна зафиксируй:
- Значение (что делает команда)
- Confidence: `high` (консистентно по ≥70% реп), `medium` (50–70%), `low` (<50% или смешано)
- Source repos (какие репы демонстрируют этот паттерн)
- Divergences (репы, которые отклоняются — это кандидаты на tech debt)

### Python паттерны для извлечения

**Структура проекта:**
- Расположение source директории (`src/{name}/` vs flat `{name}/` vs `app/`)
- Где живут агенты vs сервисы vs утилиты
- Структура директории тестов
- Есть ли отдельное место для вспомогательной automation/CLI tooling

**Зависимости:**
- LLM SDK: какой реально используется и как команда фиксирует его версии
- HTTP client: httpx, requests, aiohttp
- Config: pydantic-settings, dynaconf, python-dotenv, os.environ напрямую
- Logging: loguru, structlog, stdlib logging
- Testing: pytest плагины использованные
- Code quality: ruff, black, flake8, mypy, pyright

**Naming conventions:**
- Именование файлов: snake_case, kebab-case, mixed
- Именование классов: PascalCase, суффиксы используемые (Agent, Service, Tool, Handler, Manager)
- Именование функций: verb_noun паттерн, async префиксы
- Именование тестов: `test_<what>_<condition>` vs `test_<method_name>` vs другие

**Config/settings паттерн:**
- Как config загружается (env vars, .env файл, yaml, hardcoded)
- Структура класса settings
- Обязательные vs опциональные поля подход
- Обработка секретов

**Logging паттерн:**
- Setup logger (module-level, class-level, global)
- Формат лога (структурированный JSON, plain text)
- Что логируется (записи, выходы, только ошибки или verbose)
- Используемые уровни логов

**Error handling:**
- Иерархия кастомных exceptions (да/нет, глубина)
- Где ошибки ловятся vs распространяются
- Форма HTTP error ответов (если применимо)
- Паттерны retry логики

**Agent-specific паттерны (критично для этой команды):**
- Паттерн определения инструмента (класс vs функция vs dict)
- Типы input/output инструментов
- Расположение и формат system prompt (inline string, .md файл, .txt файл)
- Структура agent loop (while loop, рекурсивный, framework-managed)
- Как агенты получают задачи (CLI аргументы, API, очередь)
- Управление состоянием между ходами (stateless, in-memory, persistent)
- Как инструменты регистрируются в агенте

**Test паттерны:**
- Что мокается vs тестируется с реальными реализациями
- Организация фикстур (conftest.py conventions)
- Разделение integration тестов (marks, директории)
- Подход к тестовым данным (factories, fixtures, hardcoded)
- Обработка async тестов

**Git conventions (из git log):**
- Формат сообщений коммитов (conventional commits, free-form, issue number prefix)
- Именование веток если обнаружено
- Granularity коммитов (большие коммиты vs маленькие атомарные)

### Java паттерны для извлечения

- Версия Spring Boot и стиль конфигурации
- Глубина и именование package структуры
- DTO vs entity именование
- Паттерны service layer (interfaces + impls vs прямые классы)
- Обработка исключений (ControllerAdvice, кастомные exceptions)
- Подход к тестам (unit vs integration ratio, Mockito usage)
- Подход к API versioning
- Framework логирования и формат

### Frontend паттерны для извлечения

- Структура компонентов (только функциональные, с hooks и т.д.)
- Управление состоянием (local, Context, Redux, Zustand)
- Паттерны API вызовов (fetch, axios, react-query)
- Подход к тестам (RTL, Playwright, цели coverage)
- Подход к стилизации (CSS modules, Tailwind, styled-components)

---

## Шаг 4: Запись `team-patterns.json`

Запиши в `{workspace_root}/team-patterns.json`:

```json
{
  "extracted_at": "YYYY-MM-DD",
  "workspace_root": "/абсолютный/путь",
  "sources_analyzed": ["service-a", "service-b", "..."],
  "review": {
    "status": "pending",
    "approved_by": null,
    "approved_at": null,
    "approved_low_confidence": []
  },
  "python": {
    "project_structure": {
      "source_dir": "src/{name}",
      "test_dir": "tests/",
      "has_scripts_dir": false,
      "confidence": "high",
      "note": "все репы используют src layout"
    },
    "dependencies": {
      "llm_sdk": {"name": "observed-llm-sdk", "version": "<observed constraint>"},
      "http_client": "httpx",
      "config": "pydantic-settings",
      "logging": "loguru",
      "testing": ["pytest", "pytest-asyncio"],
      "linting": ["ruff", "mypy"],
      "confidence": "high"
    },
    "naming": {
      "files": "snake_case",
      "classes": "PascalCase",
      "class_suffixes": {
        "agents": "Agent",
        "tools": "Tool",
        "services": "Service"
      },
      "functions": "snake_case_verb_first",
      "test_functions": "test_{what}_{condition}",
      "confidence": "medium"
    },
    "config_pattern": {
      "approach": "pydantic-settings с .env файлом",
      "class_name": "Settings",
      "location": "config.py или settings.py",
      "example": "class Settings(BaseSettings): model_name: str = Field(..., env='MODEL_NAME')",
      "confidence": "high"
    },
    "logging_pattern": {
      "library": "loguru",
      "setup": "module-level logger = logger.bind(service=name)",
      "format": "structured",
      "confidence": "medium"
    },
    "error_handling": {
      "custom_exceptions": true,
      "base_class": "AppError(Exception)",
      "catch_boundary": "service layer",
      "confidence": "low",
      "note": "смешано — некоторые репы используют bare except, отмечено как divergences"
    },
    "agent_patterns": {
      "tool_definition": "класс, наследующий BaseTool с run(self, input: str) -> str",
      "tool_registration": "список, передаваемый в конструктор агента",
      "system_prompt": "файл prompts/system.md, загружается при инициализации",
      "agent_loop": "while loop с вызовами функций",
      "task_input": "CLI аргумент или FastAPI endpoint",
      "state": "stateless per call",
      "confidence": "high"
    },
    "test_patterns": {
      "mocking_strategy": "мокать внешние API только, реальные инструменты",
      "fixtures": "conftest.py в корне tests/",
      "integration_mark": "@pytest.mark.integration",
      "async_mode": "asyncio_mode = auto",
      "confidence": "medium"
    },
    "git_conventions": {
      "commit_format": "conventional commits",
      "examples": ["feat: добавить retry логику", "fix: обработка таймаута в tool X"],
      "confidence": "medium"
    }
  },
  "java": {
    "framework": "Spring Boot 3.x",
    "package_root": "com.example",
    "structure": "controller / service / repository / dto",
    "exception_handling": "GlobalExceptionHandler с @ControllerAdvice",
    "test_approach": "JUnit5 + Mockito для unit, @SpringBootTest для integration",
    "confidence": "high"
  },
  "frontend": {},
  "divergences": [
    {
      "service": "service-name",
      "issue": "использует print() вместо loguru",
      "severity": "low",
      "suggested_action": "tech-debt task"
    }
  ],
  "coverage_gaps": [
    "Нет последовательного retry паттерна по всем Python агентам",
    "Java сервисы не имеют общего формата error response"
  ]
}
```

---

## Шаг 5: Запись `team-conventions.md`

Запиши в `{workspace_root}/team-conventions.md`.
Это человекочитаемая версия для ревью и корректировки командой.

```markdown
# Team Conventions
*Извлечено из [N] репозиториев [дата]*
*Проверь этот файл и исправь всё, что не отражает намерение, затем закоммить его.*

---

## Python Сервисы и Агенты

### Структура проекта
[опиши что было найдено]

### Зависимости (de facto стандарт)
| Назначение | Библиотека | Версия |
|---------|---------|---------|
| LLM | ... | ... |
| Config | ... | ... |
| Logging | ... | ... |
| Testing | ... | ... |
| Linting | ... | ... |

### Naming Conventions
[опиши паттерны с примерами]

### Agent Patterns
[опиши как агенты строятся в этой кодовой базе]

### Error Handling
[опиши подход]

### Test Patterns
[опиши что мокается, как работают фикстуры]

### Git Conventions
[опиши формат коммитов с примерами]

---

## Java Сервисы
[резюме Java паттернов]

---

## Divergences (Tech Debt)
Эти репы отклоняются от team standard. Рассмотри задачи на cleanup.

| Сервис | Проблема | Severity | Действие |
|---------|-------|----------|--------|
| ... | ... | low/medium/high | ... |

---

## Coverage Gaps
Области, где нет консистентного паттерна — требуется решение команды:
- [gap 1]
- [gap 2]

---

*После проверки владелец меняет `review.status` на `approved`, заполняет
`approved_by`/`approved_at` и при необходимости перечисляет явно одобренные
low-confidence JSON paths. Только после этого файл может направлять `harness-template`.*
```

---

## Шаг 6: Обновление использования `harness-template`

После записи обоих файлов выведи:

```
## Извлечение Паттернов Завершено

Проанализировано: [N] реп ([N] Python, [N] Java, [N] Frontend)

Файлы записаны:
  team-patterns.json   ← машинночитаемые кандидаты; pending до human approval
  team-conventions.md  ← человекочитаемый, проверь и исправь перед коммитом

Консистентные паттерны (используются напрямую в новых scaffolds):
  ✓ [паттерн 1]
  ✓ [паттерн 2]

Средне/низко консистентные паттерны (проверь в team-conventions.md):
  ~ [паттерн 3]
  ~ [паттерн 4]

Найдено divergences: [N] (см. team-conventions.md)
Coverage gaps: [N] (требуется решение команды)

Следующие шаги:
  1. Проверь team-conventions.md — исправь всё неверное
  2. После review выставь review.status=approved и заполни данные approval
  3. Закоммить: `harness: добавить team conventions`
  4. Примени harness-template с <name> <stack>
```

---

## Критические ограничения

- Читай реальный код, не только конфиг файлы — паттерны живут в реализации
- Не выдумывай паттерны, не найденные в коде
- Найденный majority pattern — наблюдение, не норматив. Official team docs и
  approved template имеют приоритет; legacy/divergence не передавать в новый
  scaffold только потому, что оно встречается часто.
- Сам skill всегда создаёт `review.status: pending` и не может одобрить свой
  результат. Low-confidence pattern применяется только если его JSON path явно
  добавлен человеком в `review.approved_low_confidence`.
- Уровни консистентности должны быть честными — смешанные паттерны получают `low`, не `high`
- Divergences — это наблюдения, не суждения — перечисляй их фактологически
- Если репа не имеет тестов,注明и это как gap, не как "test pattern = none"
- `team-patterns.json` должен быть валидным JSON — никаких комментариев внутри блока JSON

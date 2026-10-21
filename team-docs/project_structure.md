# Структура проекта

sberorm-agent-<service>/
- pyproject.toml          # uv-Workspace корень
- uv.lock                 # Блокировки зависимостей
- Makefile                # Сборка, тесты, деплой
- .gitignore
- .pre-commit-config.yaml
- docs/harness/          # Документация для кодового агента
- libs/
  - sber_orm_agent_<service>_api/  # API-клиент этого сервиса для сторонних сервисов, генерируется автоматически
    - pyproject.toml
    - sber_orm_agent_<service>_api/
      - __init__.py
      - client.py
      - openapi.yaml
    - tests/test_import.py
- projects/sber_orm_agent_<service>/  # Основной сервис
  - pyproject.toml
  - scripts/           # Утилиты (generate.py и др.)
  - tests/conftest.py, unit/
  - sber_orm_agent_<service>/
    - __init__.py
    - app.py
    - main.py        # Запуск приложения, beat и worker
    - di.py          # Настройка dishka контейнеров для DI
    - exceptions.py  # Кастомные исключения
    - utils          # Функции -утилиты
    - alembic.ini    # Настройки Alembic
    - api/           # FastAPI endpoints (routes/)
    - db/  # Всё что относится к работе с БД
      - migrations/ # Миграции БД
      - models.py      # SQLAlchemy модели данных
    - providers/     # DI-провайдеры
    - repositories/  # Доступ к БД
    - services/   # Классы-сервисы, содержат бизнес-логику
    - agent/  # Всё что относится к работе laggraph агента, если он используется в проекте
      - agent.py   # LangGraph-агент
      - nodes/     # Узлы графа
      - state.py       # Typed State для LangGraph
    - configs/       # Конфиги
    - resources/
      - prompts/   # LLM промпты
      - templates/ # Jinja2 (.j2) - шаблоны для промптов
      - tables/    # Справочники
      - api/       # OpenAPI внешних сервисов для генерации по ним клиента с помощью openapi-generator-cli
      - tokenizer/ # Файлы для использования локальным токенайзером
      - application{,-dev,-prod,-test,-local,-uft,-build}.yaml - конфигурационные файлы для разных стендов
- generated/sber_orm_*_api/  # Сгенерированные API-клиенты
- .run/                  # IDE конфигурации запуска с секретами

## Ключевые модули
| Файл/Директория | Назначение                         |
|---------------|------------------------------------|
| `main.py`     | Точка входа                        |
| `app.py`      | FastAPI конфигурация               |
| `di.py`       | Dishka Dependency Injection        |
| `services/`   | Доменная логика                    |
| `providers/`  | DI-провайдеры (DB, LLM, API)       |
| `repositories/` | Данные (PostgreSQL)                |
| `api/routes/` | HTTP endpoints по доменам          |
| `db/`         | Миграции + модели                  |
| `resources/`  | Промпты, шаблоны, конфиги, OpenAPI |
| `Makefile`    |  Сборка, тесты, деплой             |



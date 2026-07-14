---
name: harness-scan
description: "Инвентаризирует workspace с несколькими репозиториями: определяет стеки, оценивает harness-ready пробелы и создаёт workspace.json/workspace-overview.md. Используй перед harness-context для выбора целевых репозиториев; для уже выбранного одиночного target этот skill не нужен."
---

Ты выполняешь **harness-сканирование готовности** в рабочем пространстве, содержащем несколько репозиториев или сервисов.
Цель: дать ясную картину состояния каждого сервиса и создать приоритизированный план внедрения.

## Входные данные

Путь к рабочей директории (workspace root). Если не указан, используй текущую директорию.

---

## Шаг 1: Обнаружение сервисов

Пройдись по директориям рабочей области. Директория — **кандидат в сервис**, если содержит:
`.git`, `pyproject.toml`, `package.json`, `pom.xml`, `build.gradle`, `build.gradle.kts`, `go.mod`, `Cargo.toml`, `Dockerfile`

Пропускай: `node_modules/`, `.venv/`, `venv/`, `__pycache__/`, `target/`, `dist/`, `build/`, `.git/`

Для каждого обнаруженного сервиса собери:

| Поле | Как определить |
|---|---|
| name | имя директории |
| stack | маркерные файлы (см. ниже) |
| size | количество исходных файлов (*.py / *.java / *.ts / *.go) |
| has_tests | наличие `tests/`, `test/`, `spec/`, `*_test.*`, `*Test.java`, `*.spec.*` |
| has_ci | `.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile` |
| has_agents_md | существует `AGENTS.md` |
| has_makefile | существует `Makefile` |
| has_docs | директория `docs/harness/` с хотя бы одним `.md` файлом |
| last_commit | `git log -1 --format="%cd" --date=short` если есть `.git` |
| purpose | первая непустая строка README.md, не являющаяся заголовком |

**Определение стека:**
- `pyproject.toml` или `setup.py` или `requirements.txt` → python
- `package.json` с `"react"` или `"vue"` или `"next"` → frontend
- `package.json` без UI-зависимостей → nodejs
- `pom.xml` или `build.gradle` → java
- `go.mod` → go
- `Cargo.toml` → rust
- только `Dockerfile` → docker-only

---

## Шаг 2: Оценка каждого сервиса

**Harness score (0–5):**
- +1 has_tests
- +1 has_ci
- +1 has_agents_md
- +1 has_makefile
- +1 has_docs

**Пробелы harness** = список отсутствующих пунктов из пяти выше.

---

## Шаг 3: Запись `workspace.json`

Запиши в `{workspace_root}/workspace.json`:

```json
{
  "scanned_at": "YYYY-MM-DDTHH:MM:SS",
  "workspace_root": "/абсолютный/путь",
  "services": [
    {
      "name": "service-name",
      "path": "относительный/путь/от/workspace",
      "stack": ["python", "fastapi"],
      "size": "small",
      "has_tests": true,
      "has_ci": false,
      "has_agents_md": false,
      "has_makefile": true,
      "has_docs": false,
      "last_commit": "2025-01-15",
      "purpose": "однострочное описание из README",
      "harness_score": 2,
      "harness_gaps": ["AGENTS.md", "CI", "docs/"]
    }
  ],
  "summary": {
    "total_services": 0,
    "stacks_found": ["python", "java"],
    "harness_ready": 0,
    "partial": 0,
    "no_harness": 0,
    "scanned_paths": []
  }
}
```

Размеры: `small` (<20 исходных файлов), `medium` (20–100), `large` (>100)

---

## Шаг 4: Запись `workspace-overview.md`

Запиши в `{workspace_root}/workspace-overview.md`:

```markdown
# Сканирование Workspace для Harness

*Отсканировано: [дата] | Корень: [путь]*

## Сводка
| Метрика | Значение |
|--------|-------|
| Всего сервисов | N |
| Готовых к harness (score 4–5) | N |
| Частично готовых (score 2–3) | N |
| Не готовых (score 0–1) | N |
| Найдено стеков | Python (N), Java (N), TS (N) |

---

## Сервисы

### 🟢 Готовы к harness (score 4–5)
| Сервис | Стек | Score | Примечания |
|---------|-------|-------|-------|
| name | python | 5 | — |

### 🟡 Частично готовы (score 2–3)
| Сервис | Стек | Score | Отсутствует |
|---------|-------|-------|---------|
| name | java | 2 | AGENTS.md, docs/ |

### 🔴 Не готовы (score 0–1)
| Сервис | Стек | Score | Действие |
|---------|-------|-------|--------|
| name | python | 1 | Запустить `harness-context` |

---

## Рекомендуемый порядок внедрения

Приоритет: предпочитай сервисы, которые (1) уже имеют тесты — менее рискованно начинать,
(2) активно разрабатываются — максимальная отдача, (3) Python — проще всего harnessить.

1. **[service-name]** — причина: [есть тесты + активен, просто нужен AGENTS.md]
2. **[service-name]** — причина: [ключевой сервис, нет harness = высокий риск]
3. **[service-name]** — причина: [...]

## Следующие шаги
1. Запустить `harness-context` в каждом 🔴 сервисе
2. Для 🟡 сервисов: запустить `harness-context` для заполнения конкретных пробелов
3. После добавления AGENTS.md в каждый сервис, закоммитить: `harness: добавить слой контекста`
4. Повторно запустить `harness-scan` для проверки прогресса
```

---

## Шаг 5: Отчёт

Выведи краткую сводку:
- Всего найдено сервисов
- Распределение по tier score
- Топ-3 сервиса для harness первыми (с причиной)
- Следующий шаг: открыть `[top-priority-service]` в Codex и применить `harness-context`

---

## Жёсткие ограничения

- Не генерируй фиктивные сервисы — только реальные директории с репозиториями
- Score должен отражать реальную готовность — честно оценивай каждый критерий
- Пробелы harness должны быть точными списками отсутствующих файлов/конфигов
- Приоритизация должна учитывать бизнес-контекст и риски
- Размеры сервисов должны быть объективно рассчитаны по количеству исходных файлов

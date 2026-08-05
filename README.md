# Harness team kit

Канонический командный комплект для переноса прототипов AI-агентов в
production. Здесь лежит всё, что нужно для запуска и сопровождения Harness;
проектные прототипы, секреты и результаты конкретных прогонов сюда не входят.

## Быстрый старт

1. Подключить каталоги из `skills/` к Codex принятым в команде способом. Перед
   обновлением сравнить существующие версии и не перезаписывать ручные изменения
   без review.
2. Настроить [`tasks-mcp`](mcp-servers/tasks-mcp/README.md).
   Все рабочие ветки Harness используют только формат
   `feature/<TICKET>[-short-description]` независимо от типа задачи.
3. Создать target из официального team template и оставить prototype read-only.
   Если template не содержит полного `docs/harness/`, вручную скопировать только
   отсутствующие team docs, `templates/tasks.json`,
   `templates/data-boundaries.md` под именем `docs/harness/data-boundaries.md` и
   `PRE-INDUSTRIALIZATION-SPEC.md` под именем
   `docs/harness/pre-industrialization-spec.md`. Существующие target-файлы не
   перезаписывать; техническую карту заполняет Codex, не человек.
4. В `docs/harness/pre-industrialization-spec.md` указать эталонную версию
   прототипа и недостающие сведения о production-подключениях: нужные операции
   и контракты, адреса стендов/config keys, ссылки на secrets без значений,
   БД/хранилища и Jenkins/deploy, если они применимы. Назначение агента, его
   логику и детали доступных контрактов Codex извлекает сам.
5. Прочитать [ONBOARDING.md](ONBOARDING.md) и запустить один entrypoint:

> Используй `$harness-productionize`: prototype=`<path>`, target=`<path>`,
> team_template=`<path>`, team_docs=`<harness-kit/team-docs>` при отсутствии
> docs в template. Дойди до ближайшего human checkpoint.

`harness-watcher` нужен только там, где команды нельзя выполнять в среде Codex
или это требует политика. Он не является обязательной частью каждого прогона.

## Что лежит в комплекте

| Путь | Назначение |
|---|---|
| [`PRE-INDUSTRIALIZATION-SPEC.md`](PRE-INDUSTRIALIZATION-SPEC.md) | короткий паспорт интерфейсов, внешних систем, БД и deploy-реквизитов |
| `skills/` | 19 универсальных Harness skills |
| `templates/` | стартовые repo artifacts и безопасные примеры конфигурации |
| `team-docs/` | read-only архитектура и соглашения, переданные разработчиком |
| `mcp-servers/tasks-mcp/` | claim/submit, evidence и stuck detection без feature-diff по умолчанию |
| `harness-watcher/` | опциональный файловый transport для удалённого выполнения |

Внешнее подключение можно реализовать после того, как техническая карта содержит
точную операцию, versioned contract, auth mechanism и проверяемый mapping.
Разрешение на live-вызов, изменение общей БД или deploy запрашивается отдельно
непосредственно перед рискованным действием.

Происхождение восстановленных runtime-компонентов и границы достоверности
описаны в [PROVENANCE.md](PROVENANCE.md).

## Скиллы

Для полного прогона человек вызывает только `harness-productionize`. Он
определяет текущее состояние по артефактам и передаёт следующий шаг нужному
скиллу. В `tasks.json` записывается точный исполнительный `use_skill` и, если
нужно, `skill_mode`.

### Управление процессом и контекст

- **harness-productionize** — единая точка входа: ведёт весь перенос от
  подготовки до ближайшего решения человека и умеет продолжать после паузы.
- **harness-scan** — инвентаризирует workspace с несколькими репозиториями и
  показывает, какие из них готовы к Harness. Для уже выбранного target не нужен.
- **harness-context** — создаёт или безопасно обновляет `AGENTS.md` и
  `docs/harness/`, не перезаписывая командные документы и ручные правки.
- **harness-template** — разворачивает официальный шаблон команды; generic
  scaffold создаёт только для настоящего greenfield без team template.
- **harness-extract-patterns** — извлекает повторяющиеся архитектурные и кодовые
  соглашения из репозиториев, если официальной документации недостаточно.

### Этап A — перенос прототипа без потери логики

- **harness-source-analysis** — фиксирует фактическое устройство прототипа:
  функции, входы, схемы, prompts, LLM-параметры, retries, File IO и интеграции.
- **harness-ds-precheck** — сверяет прототип с правилами DS/MLE-кода и разделяет
  замечания на форму, изменение поведения и отдельные оптимизации; код не меняет.
- **harness-prototype-plan** — строит план этапа A из связанных проверяемых
  функциональных блоков, начиная с машинного контракта исходной логики; не
  дробит prompts, helpers и tests по числу файлов.
- **harness-prototype-port** — переносит одну часть прототипа в правильный слот
  team template, не меняя бизнес-логику, prompts, схемы и параметры моделей.

### Этап B — production-доводка

- **harness-extract-prod** — извлекает подтверждённые production-паттерны из
  team template, выбранного production-сервиса и release reference.
- **harness-production-plan** — определяет применимые production-срезы и создаёт
  только реально нужные задачи этапа B вместо фиксированного списка T-101…T-120.
- **harness-production-readiness** — выполняет одну задачу этапа B: контракт,
  adapter, config, process, БД, observability, deploy, runbook или проверку стенда.
- **harness-team-layout-alignment** — приводит уже работающий сервис к структуре,
  именованию и форме кода команды без изменения его поведения.

### Выполнение и безопасность

- **harness-work-session** — выполняет одну задачу из `tasks.json` по полному
  циклу claim → реализация → проверки → commit → submit.
- **harness-request-exec** — запускает команды через `harness-watcher`, когда
  безопасный локальный runtime недоступен или этого требует политика окружения.
- **harness-pre-commit-check** — проверяет конкретный diff перед коммитом:
  scope, тесты, секреты, runtime-артефакты, защищённые файлы и соглашения команды.
- **harness-governance-gates** — добавляет постоянные repo/CI-защиты от секретов,
  запрещённых зависимостей и незадокументированного изменения логики прототипа.

### Golden и проверки

- **harness-golden** — создаёт новый воспроизводимый golden-датасет из
  референсов и независимого oracle, проверяет неоднозначность и сохраняет provenance.
- **harness-eval** — запускает проверки по уже определённому эталону в одном из
  режимов: `prototype-parity`, `golden` или разрешённая `live`-проверка.

`harness-golden` создаёт эталон, а `harness-eval` измеряет по нему качество.
Golden-контур необязателен для каждого опромышливания и не заменяет проверку
сохранения поведения прототипа.

## Источники истины

- `team-docs/` принадлежат команде и не переписываются skills;
- prototype и `prototype-contract.json` определяют сохраняемое поведение;
- `pre-industrialization-spec.md` хранит недостающие production-реквизиты и
  ссылки на официальные контракты; значения секретов в него не попадают;
- `data-boundaries.md` — техническая карта, которую Codex строит из прототипа,
  паспорта подключений и официальных описаний интеграций;
- versioned target contracts определяют новые API/tool/queue/DB boundaries;
- `tasks.json` хранит план, а tasks-mcp по умолчанию хранит lifecycle
  out-of-band;
- production neighbour и release reference дают evidence, но не становятся
  архитектурой target автоматически.

Перед распространением комплекта вручную проверить структуру skills, ссылки,
JSON-шаблоны и отсутствие локальных/runtime-артефактов.

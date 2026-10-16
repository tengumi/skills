# tasks-mcp

Локальный stdio MCP-сервер для очереди `docs/harness/tasks.json`. Он даёт
Агенту шесть операций: посмотреть открытые задачи, claim, submit с evidence,
записать попытку, сообщить blocker и дождаться отчёта harness-watcher.

## Как хранится очередь

По умолчанию включён безопасный режим `out_of_band`:

- versioned `docs/harness/tasks.json` остаётся источником определений задач;
- `status`, claim, attempts, blocker и evidence пишутся во внешний overlay;
- overlay накладывается по `task.id`, поэтому новые определения из
  `tasks.json` появляются без сброса уже накопленного lifecycle;
- claim/submit не создают и не меняют файлы внутри feature checkout.

Overlay по умолчанию лежит в
`~/.local/state/harness/tasks-mcp/`. Другой внешний каталог задаётся через
`HARNESS_TASKS_STATE_DIR`. Сервер отвергает каталог состояния внутри самой
репы.

`submit_task` принимает evidence только из ветки
`feature/<ID>[-short-description]`. `ID` — ticket, если он уже указан, иначе id
задачи из очереди, например `feature/T-004-config`. Это единое правило для
feature, bugfix и hotfix-задач; другие branch prefixes отклоняются сервером.

Режим `tracked` включается только явно:

```bash
HARNESS_QUEUE_STORAGE_MODE=tracked python3 server.py
```

Он меняет сам `tasks.json` и предназначен только для команды, которая ведёт
lifecycle отдельным coordination commit/channel. Для feature-веток оставляйте
режим по умолчанию.

## Запуск и подключение

Runtime-зависимостей нет, нужен Python 3.10+:

```bash
python3 server.py
```

Минимальная конфигурация любого stdio MCP-клиента (замените placeholder на
путь к командной копии harness-kit):

```json
{
  "command": "python3",
  "args": ["<HARNESS_KIT_PATH>/mcp-servers/tasks-mcp/server.py"],
  "env": {
    "HARNESS_QUEUE_STORAGE_MODE": "out_of_band",
    "HARNESS_TASKS_STATE_DIR": "<EXTERNAL_TEAM_STATE_DIR>"
  }
}
```

`HARNESS_TASKS_STATE_DIR` можно не задавать, если подходит каталог по
умолчанию. Не кладите в task/evidence секреты и сырые пользовательские данные.
Overlay привязан к resolved path репозитория: после перемещения checkout нужно
осознанно перенести его lifecycle либо выполнить claim заново.

Handshake согласует запрошенную опубликованную версию MCP; текущий preferred
protocol — `2025-11-25`, legacy `2024-11-05` поддерживается для старых stdio
клиентов.

## Контракт

| Tool | Назначение |
|---|---|
| `list_open_tasks` | Open subset; с `include_all=true` также полная merged queue и summary |
| `claim_task` | Перевод в `in_progress`; возвращает полный task context |
| `submit_task` | Проверка evidence и перевод в `completed_sprint`; optional `artifacts` хранит repo-relative report paths |
| `record_attempt` | История запуска и stop после трёх одинаковых ошибок |
| `report_blocker` | Перевод в `blocked` с причиной |
| `wait_for_report` | Ожидание JSON-отчёта harness-watcher |

Если определение содержит `acceptance_criteria`, ответы дополнительно содержат
runtime alias `acceptance`. Source-файл при этом не переписывается.

Для возобновления сессии вызывайте `list_open_tasks` с `include_all=true`.
Ответ сохраняет совместимые `count`/`tasks` для открытой выборки и добавляет
`all_tasks` (включая done/blocked) и `summary.by_status` /
`summary.by_category`.

## Проверка

```bash
python3 -m pip install -e '.[test]'
pytest
python3 -m py_compile server.py
```

## Происхождение

Исходный `server.py` восстановлен из последовательности полных create/patch
событий исторической migration-конверсии. В составе harness-kit это не
byte-identical архив: сервер отдельно проаудирован и обновлён — добавлен
out-of-band overlay по умолчанию, валидация queue/JSON-RPC и тестовый пакет.

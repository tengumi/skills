---
name: harness-request-exec
description: "Выполняет make/test/lint и другие команды через файловый transport harness-watcher и ждёт отчёт через tasks-mcp. Используй только когда watcher задан environment/repo policy, прямой runtime недоступен или пользователь явно просит удалённое выполнение; при доступном безопасном local runtime этот skill не нужен."
---

# harness-request-exec

## Цель

Заменить прямой вызов команд через `bash` на цикл «положи exec-request — дождись exec-report — прочитай результат». Это нужно если ты работаешь в среде где запуск команд запрещён или невозможен (нет Python для тестов, нет компилятора, политика безопасности).

Цикл занимает несколько секунд: harness-watcher на рабочей станции пользователя поллит папку с requests, выполняет команды локально, кладёт отчёт обратно.

## Когда применять

Подгружается когда нужно выполнить команду на текущей репе, а прямой `bash` недоступен. Чаще всего из `harness-work-session` шага verify. Также можно звать напрямую: «запусти make verify через harness», «прогони тесты на рабочей станции».

Если прямой `bash` работает и команда безопасна — этот скилл не нужен, выполни напрямую.

## Шаги

**1. Сформируй request_id.**
Формат: `{timestamp}-{task_id}` если есть task, иначе `{timestamp}-manual`. Timestamp в формате `YYYY-MM-DDTHH:MM:SS` без миллисекунд, без часового пояса — этого достаточно для уникальности в рамках одного дня.

**2. Определи команды.**
Команды бери из нормализованного `task.acceptance` после claim (в persisted
`tasks.json` это `acceptance_criteria`), из секции "Быстрые команды" в AGENTS.md
или из запроса пользователя. Не выдумывай команды — если непонятно, спроси.

Диагностическая команда не должна печатать `env`, credential files или полный
config dump. Для effective config использовать allowlist полей и redaction:
provider/model/base URL/source/timeout/TLS mode допустимы, tokens/passwords/cert
contents — нет. stdout/stderr попадут в audit files.

Формат команды: `{"cmd": "make verify", "cwd": "."}`. `cwd` — относительно корня репы.

**3. Определи нужен ли sync.**
Поле `sync` в request:
- `"pull"` — синхронизировать код из control-plane/repository copy на рабочую
  станцию ПЕРЕД exec. Нужно, если правки должны попасть в execution environment.
- `"none"` — не синхронизировать. Например для проверки версии Python (`python --version`) или для команды которая не зависит от твоего кода.
- `"both"` — pull перед, push после. Push нужен, если команда генерирует
  артефакты, которые должны вернуться в control-plane copy.
- `"push"` — только push после. Редкий случай.

По умолчанию для команд типа `make verify`, `pytest`, `lint` — используй `"pull"`. Для информационных команд (`--version`, `which`) — `"none"`.

**4. Сформируй и запиши request.**

Создай файл `docs/harness/exec-requests/{request_id}.json` с содержимым:

```json
{
  "request_id": "2026-05-21T14:00:00-T-001",
  "task_id": "T-001",
  "commands": [
    {"cmd": "make install", "cwd": "."},
    {"cmd": "make verify", "cwd": "."}
  ],
  "timeout_seconds": 600,
  "stop_on_failure": true,
  "sync": "pull",
  "context": {
    "branch": "agent/TICKET-001",
    "purpose": "verify before commit"
  }
}
```

`timeout_seconds` — на всю цепочку команд. По умолчанию 600 (10 минут), для длинных тестов можно больше.

`stop_on_failure: true` — остановиться на первой ошибке. Обычно так и нужно.

**5. Дождись report.**

Вызови `tasks-mcp.wait_for_report(repo_path, request_id, timeout_seconds)`. `timeout_seconds` — чуть больше чем в request (например +60 секунд на overhead sync и сети).

Возможные результаты:
- `status: "ok"` с полем `report` — нормальный случай, переходи к разбору
- `status: "timeout"` — watcher не работает или команда зависла дольше чем ожидалось
- `status: "error"` — request файл не нашёлся, что-то с путями

**6. Разбери report.**

Поле `report.overall_status` показывает общий результат:
- `"success"` — все команды прошли с exit_code=0
- `"failure"` — одна или несколько команд упали
- `"timeout"` — одна из команд превысила таймаут
- `"error"` — что-то с самим выполнением (escape cwd, executor exception)

В поле `report.results` — массив результатов каждой команды с `exit_code`, `stdout`, `stderr`, `duration_ms`. Их и читай чтобы понять что произошло.

**7. Если failure — task lifecycle или manual report.**

Если request связан с task и `overall_status == "failure"` или `"timeout"`,
вызови `tasks-mcp.record_attempt`:

```
tasks-mcp.record_attempt(
    repo_path=<repo>,
    task_id=<id>,
    command=<последняя упавшая команда из report>,
    exit_code=<exit_code из report>,
    error_output=<stderr последней команды>,
)
```

Если ответ `action: "stop"` — это зацикливание, остановись и вызови `report_blocker`. Если `action: "continue"` — попробуй понять что в stderr и поправить код, потом снова в этот же цикл (новый request_id).

Для `{timestamp}-manual` без task не вызывать `record_attempt`/`report_blocker`
с выдуманным id. Вернуть пользователю command, request/report id, redacted
failure/timeout и безопасный следующий шаг; сам report остаётся audit evidence.

**8. Не запускай больше одного request за раз.**

Дождись report перед тем как делать следующий request. Параллельные requests на одной задаче ломают логику stuck-detector.

## Хард-лимиты

- НЕ выполняй команды через локальный `bash` если в AGENTS.md написано использовать harness-watcher. Это политика безопасности репозитория, не обходи.
- НЕ удаляй файлы из `docs/harness/exec-requests/` и `exec-reports/` — это очередь, она обрабатывается watcher'ом.
- НЕ пиши `sync: "push"` если не уверен — можно перетереть файлы control-plane
  копии результатом с execution workstation.
- НЕ генерируй много requests подряд без дождавшись report — нагружаешь watcher.
- НЕ кэшируй report между сессиями — каждая команда требует свежего exec-request.
- НЕ помещай секреты в `context` или в `cmd` — request видим в репе и попадает в audit log.
- НЕ запускать `env`, `printenv`, `set` или dump всего settings object. Если
  упавшая команда случайно вывела secret-bearing output, не копировать его в
  `record_attempt`/evidence; сообщить о redaction incident пользователю.

## Output

При успехе:
- Один файл в `docs/harness/exec-requests/{request_id}.json` (потом watcher переместит в `exec-processed/`)
- Один файл в `docs/harness/exec-reports/{request_id}.json` с результатом
- Понимание прошло ли verify, что показали тесты
- Готовность вернуть управление в harness-work-session (или ответить пользователю)

При timeout/error:
- Task mode: запись через `record_attempt`, возможный `report_blocker`
- Manual mode: report id и redacted ошибка пользователю без task lifecycle
- Сообщение пользователю что нужен человек

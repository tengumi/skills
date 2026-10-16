---
name: harness-request-exec
description: "Выполняет make/test/lint и другие команды через файловый transport harness-watcher и ждёт отчёт через tasks-mcp. Используй только когда watcher задан environment/repo policy, прямой runtime недоступен или пользователь явно просит удалённое выполнение; при доступном безопасном local runtime этот skill не нужен."
---

# harness-request-exec

## Цель

Заменить прямой вызов команд через `bash` на цикл «положи exec-request — дождись exec-report — прочитай результат». Это нужно если ты работаешь в среде где запуск команд запрещён или невозможен (нет Python для тестов, нет компилятора, политика безопасности).

Watcher опрашивает очередь каждые несколько секунд. Полный цикл включает
синхронизацию, возможную подготовку окружения, выполнение команд и возврат отчёта;
первая установка зависимостей может занять несколько минут.

## Когда применять

Подгружается когда нужно выполнить команду на текущей репе, а прямой `bash` недоступен. Чаще всего из `harness-work-session` шага verify. Также можно звать напрямую: «запусти make verify через harness», «прогони тесты на рабочей станции».

Если прямой `bash` работает и команда безопасна — этот скилл не нужен, выполни напрямую.

## Шаги

До формирования request вызывающий workflow определяет, нужен ли новый запуск:
`harness-pre-commit-check` может доказать применимость прежнего gate по
неизменившимся входам. Тогда вернуть исходный report и отдельное основание reuse,
не создавать request и не переименовывать его source/key. Ниже exact-key reuse
означает повтор того же исполнения; watcher сам не вычисляет применимость gate
к изменившемуся дереву и его transport-протокол не меняется.

**1. Сформируй request_id.**
Формат: `{timestamp}-{task_id}-{attempt}` если есть task, иначе
`{timestamp}-manual-{attempt}`. Timestamp — UTC
`YYYYMMDDTHHMMSSffffffZ`, attempt — `a1`, `a2`, ... . Разрешены только
`[A-Za-z0-9._-]`: двоеточия, пробелы и path separators запрещены. Перед записью
проверить, что request/report с таким id не существует; id никогда не
переиспользовать.

**2. Определи команды.**
Команды бери из нормализованного `task.acceptance` после claim (в persisted
`tasks.json` это `acceptance_criteria`), из секции "Быстрые команды" в AGENTS.md
или из запроса пользователя. Не выдумывай команды — если непонятно, спроси.

Watcher — исполнитель проверок, а не канал чтения окружения рабочей станции.
Диагностическая команда не должна читать или печатать значения environment
variables, `.env*`, credential files, secret stores или полный config dump.
Запрещены в том числе `grep`/`rg`/`cat` по `.env`, `echo "$TOKEN"`, inline
`os.environ`/`process.env`, `env`, `printenv` и их аналоги. Имена настроек брать
из config-кода, схем и командных документов; `.env.example` — только если его
разрешает действующая файловая policy. Допустимы только:

- проверка наличия с фиксированным результатом/exit code, например
  `test -n "${API_TOKEN+x}"`, без значения;
- обычный запуск приложения или теста, который получает секрет штатным
  разрешённым способом и не выводит его;
- redacted effective config по явному allowlist: provider/model/base
  URL/source/timeout/TLS mode допустимы, tokens/passwords/cert contents — нет.

stdout/stderr и исходный request являются audit artifacts, поэтому значение
секрета не должно попадать в команду даже временно.

Watcher 0.7 использует фильтр команд без ОС-песочницы и дополнительного CLI.
Он отклоняет явные сетевые команды (`curl`, `wget`, `ssh`, сетевые операции Git),
удаление (`rm`, `find -delete`, `git clean`) и чтение секретов. Не запрашивай эти
действия и не переноси их в helper/Makefile/тест ради обхода. Обычные тесты и
сборка разрешены, но их внутренние действия фильтр не изолирует: они выполняются
с правами пользователя. Старый `--protected` не включает отдельную защиту.
Установка из сохранённого владельцем профиля использует offline-настройки;
отсутствующие пакеты готовит владелец. Настройка — в
[инструкции watcher](../../harness-watcher/SETUP-GUIDE.md).

Формат команды: `{"cmd": "make verify", "cwd": "."}`. `cwd` — относительно корня репы.

Собери все команды одной verification wave с одинаковыми sync/profile/safety
условиями в **один** request и сохрани порядок. Например scoped lint+tests либо
единственный bundle batch `clean install → full verify → build → smoke`.
Не создавать отдельный watcher round-trip на каждую команду. Разделять requests
только если отличаются sync direction, execution profile, разрешение/side
effects или предыдущий результат нужен для формирования следующих команд.

**Исключение для обновления `uv.lock` в профиле с автоподготовкой (watcher 0.4+).**
При отсутствующем или устаревшем lock автоматический `uv sync --locked` может
остановить request ещё до его команд. Если изменение зависимостей входит в
согласованную задачу, сначала отправь отдельный request с единственной командой
`{"cmd": "uv lock", "cwd": "."}`. Допустимы также `--offline` и `--check`;
`--check` только проверяет lock, не исправляет его. Не объединяй эту команду с
install/tests через `&&` или вторую запись: такой batch не является maintenance.
В корне target уже должен быть `pyproject.toml`.

В текущем watcher `push` и `both` запрещены. Не рассчитывай на автоматический
возврат lock: после следующего `pull` локальные изменения могут исчезнуть.
Для изменения lock используй разрешённую среду целевого репозитория либо
согласуй с владельцем отдельный перенос и проверку именно этого файла.
Не возвращай его через дамп содержимого или обход фильтра. После появления
проверенного lock в target создай request с проверками и `sync: "pull"`.
Статус `maintenance` в поле
`environment.status` не подтверждает готовность окружения или прохождение тестов;
следующий обычный request выполнит подготовку заново. Старый TOML-режим такой
автоподготовки не имеет. Детали — в
[настройке watcher](../../harness-watcher/SETUP-GUIDE.md#5-как-подготавливается-окружение).

**3. Определи нужен ли sync.**
Поле `sync` в request:

- `"pull"` — синхронизировать код из control-plane/repository copy на рабочую
  станцию ПЕРЕД exec. Нужно, если правки должны попасть в execution environment.
- `"none"` — не синхронизировать. Например для проверки версии Python (`python --version`) или для команды которая не зависит от твоего кода.
- `"both"` и `"push"` — запрещены текущей версией watcher; возврат полного
  дерева может перезаписать чужие файлы. Reports доставляются отдельно.

По умолчанию для команд типа `make verify`, `pytest`, `lint` — используй `"pull"`. Для информационных команд (`--version`, `which`) — `"none"`.

Для первого запроса нового профиля с автоподготовкой нужен `pull`, даже если
команда только проверяет версию: установка требует исходников в зеркале.
`none` выбирай, только когда нужные исходники там уже есть или автоподготовка
отключена; это не способ обойти установку.

**4. Сформируй и запиши request.**

Создай файл `docs/harness/exec-requests/{request_id}.json` с содержимым:

```json
{
  "request_id": "20260521T140000123456Z-T-001-a1",
  "task_id": "T-001",
  "commands": [
    {"cmd": "make install", "cwd": "."},
    {"cmd": "make verify", "cwd": "."}
  ],
  "timeout_seconds": 600,
  "stop_on_failure": true,
  "sync": "pull",
  "context": {
    "branch": "feature/T-001-config",
    "purpose": "verify before commit",
    "verification_level": "bundle",
    "tree_fingerprint": "<expected 64 hex, если уже известен>",
    "lock_fingerprint": "<expected 64 hex или N/A, если уже известен>",
    "execution_profile": "<observed profile прошлого report, если уже известен>",
    "commands_fingerprint": "<expected normalized command hash, если уже известен>"
  }
}
```

`timeout_seconds` — на цепочку команд, без времени sync и автоподготовки
watcher. По умолчанию 600 (10 минут), для длинных тестов можно больше.

`stop_on_failure: true` — остановиться на первой ошибке. Обычно так и нужно.

Четыре fingerprints в request — optional expected hints, не placeholders:
неизвестное поле опустить и никогда не угадывать. `commands_fingerprint` —
SHA-256 compact JSON (`sort_keys=true`, separators `,`/`:`) от ordered массива
`[{"cmd": <exact string>, "cwd": <POSIX-normalized path>}]`. Для
`execution_profile` использовать только `evidence.observed` прошлого report
того же watcher profile. Canonical фактический key всегда вычисляет watcher.

Перед созданием request разрешено переиспользовать существующий успешный report
только при точном совпадении `tree_fingerprint`, `lock_fingerprint`,
`execution_profile` и нормализованного ordered command list. Совпадение branch,
commit SHA или task id недостаточно. Если одно поле отсутствует/не доказано,
создать новый request.

**5. Дождись report.**

Вызови `tasks-mcp.wait_for_report` для созданного `request_id`. Общий бюджет
ожидания: **подготовка окружения + timeout request + запас на sync и доставку**.
Бюджет подготовки бери из переданных несекретных параметров профиля
(`environment.timeout_seconds`, по умолчанию 600 с). Учитывай его не только
в первый раз: изменение входов может вызвать повторную установку. Если режим
неизвестен, закладывай эти 600 с; для подтверждённого TOML/`none` или отдельного
lock-maintenance они не нужны. Например: 600 с установки + 600 с команд + 60 с
на небольшой sync = 1260 с общего ожидания. Для большого дерева увеличь запас.

Жди ограниченными вызовами (обычно по 30–60 с, с учётом лимита инструмента),
сохраняя один общий дедлайн. Таймаут отдельного вызова не обнуляет этот бюджет
и не создаёт новый request: продолжай ждать **тот же ID**.

Возможные результаты:

- `status: "ok"` с полем `report` — нормальный случай, переходи к разбору
- `status: "timeout"` — отчёт пока не получен; установка, команды или доставка
  могут ещё идти. Это **не** `report.overall_status: "timeout"`, не failed test
  attempt и не основание повторять исполнение либо вызывать `record_attempt`
- `status: "error"` — request файл не нашёлся, что-то с путями

Если общий дедлайн истёк, повторно проверь наличие парного report и безопасные
признаки работы watcher/доставки. До выяснения исхода не отправляй дубликат и
не меняй lifecycle как после упавших тестов. Человек нужен только если
восстановление требует недоступного подключения, доступа или нового решения,
а не из-за одного истёкшего ожидания.

**6. Разбери report.**

Поле `report.overall_status` показывает общий результат:

- `"success"` — все команды прошли с exit_code=0
- `"failure"` — одна или несколько команд упали
- `"timeout"` — одна из команд превысила таймаут
- `"error"` — что-то с самим выполнением (escape cwd, executor exception)

В поле `report.results` — массив результатов каждой команды с `exit_code`, `stdout`, `stderr`, `duration_ms`. Их и читай чтобы понять что произошло.

Если `environment.status` равен `error` или `sync.push.reason` равен
`environment_failed`, подготовка остановилась **до** команд: это не падение
тестов, `record_attempt` не вызывай. Исправь подтверждённую причину в разрешённом
объёме и лишь затем отправь новый ID. Статусы `ready`/`reused` подтверждают
только подготовку среды; `maintenance` — обслуживание lock, `disabled` —
отключённую автоподготовку. Отсутствие поля у старого watcher не означает ошибку.
Скрытый вывод установки не пытайся получить чтением env/секретов или дампами.

Если `request_identity`/`sync.reason` сообщает `duplicate_request_id`,
`invalid_request_identity` или `idempotency_state_unavailable`, команды не
выполнялись и это не ошибка кода задачи. Не записывать такой результат как
failed test attempt: использовать существующий отчёт исходного ID либо после
исправления state/формата создать новый канонический `request_id`; старый ID
никогда не переисполнять.

Для reusable evidence report обязан вернуть исходный безопасный `context`,
фактический runtime tree/lock fingerprint после sync, execution profile,
ordered commands fingerprint и sync status. `evidence.observed` — canonical key.
Любой `requested_matches.<field> == false` означает mismatch; `null` означает,
что expected hint не передавался. Первый успешный запуск с green pull и без
`false` не повторять только ради `requested_matches.all=true`: для следующего
reuse сравнить текущий требуемый key с его `evidence.observed`. При `sync: pull`
sync failure означает, что команды не должны были запускаться. Report без
observed key годится только для диагностики.

**7. Если failure — task lifecycle или manual report.**

Если request связан с task и **полученный report** содержит
`overall_status == "failure"` или `"timeout"`,
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

`overall_status == "error"` с причиной `command policy` (ранее `secret-safety policy`) означает, что
команда не запускалась и тест не падал. Не вызывать `record_attempt` и не менять
lifecycle задачи: сформировать безопасную presence-only/redacted проверку с
новым `request_id`. Policy нельзя обходить другим shell/runtime.

Если ответ `action: "stop"` — это зацикливание, остановись и вызови `report_blocker`. Если `action: "continue"` — попробуй понять что в stderr и поправить код, потом снова в этот же цикл (новый request_id).

Для `{timestamp}-manual` без task не вызывать `record_attempt`/`report_blocker`
с выдуманным id. Вернуть пользователю command, request/report id, redacted
failure/timeout и безопасный следующий шаг; сам report остаётся audit evidence.

**8. Не запускай больше одного request за раз.**

Дождись report перед тем как делать следующий request. Параллельные requests на одной задаче ломают логику stuck-detector.

## Хард-лимиты

- НЕ выполняй команды через локальный `bash` если в AGENTS.md написано использовать harness-watcher. Это политика безопасности репозитория, не обходи.
- НЕ удаляй файлы из `docs/harness/exec-requests/` и `exec-reports/` — это очередь, она обрабатывается watcher'ом.
- НЕ пиши `sync: "push"` или `"both"`: текущий watcher их запрещает.
- НЕ генерируй много requests подряд без дождавшись report — нагружаешь watcher.
- НЕ переиспользуй report по task id, branch, commit или похожему названию
  команды. Повтор того же исполнения требует exact tree/lock/profile/ordered-
  commands key и успешного sync/execution status; доказанный workflow-level gate
  reuse выше не превращает старый report в запуск на новом дереве.
- НЕ помещай секреты в `context` или в `cmd` — request видим в репе и попадает в audit log.
- НЕ читать значения env/secrets через watcher или direct shell: никакого
  `grep`/`rg`/`cat` по `.env*`, `env`, `printenv`, bare `set`, `echo/printf` с
  env-переменной, inline runtime dump, чтения credential/secret-store values.
  Наличие проверять только фиксированным статусом; названия брать из кода,
  документации; `.env.example` — только при разрешённом доступе к нему.
- Если watcher вернул `command policy` или `secret-safety policy`, не обходить её переименованием
  команды, другим интерпретатором или вспомогательным файлом. Исправить проверку
  на presence-only/redacted validation.
- Если упавшая команда случайно вывела secret-bearing output, не копировать его
  в `record_attempt`/evidence; сообщить пользователю об инциденте и необходимости
  ротации, если значение могло сохраниться в request/report/audit.

## Output

При успехе:

- Один файл в `docs/harness/exec-requests/{request_id}.json` (потом watcher переместит в `exec-processed/`)
- Один файл в `docs/harness/exec-reports/{request_id}.json` с результатом
- Понимание прошло ли verify, что показали тесты
- Reusable verification key: exact tree/lock/profile/ordered commands либо
  явное `not reusable`
- Готовность вернуть управление в harness-work-session (или ответить пользователю)

При timeout/error:

- Timeout ожидания без report: продолжить ожидание того же ID в общем бюджете;
  после его исчерпания — диагностика доставки без дубликата и смены lifecycle
- Task mode: фактические failure/timeout команд из report записываются через
  `record_attempt`; ошибки подготовки, transport и command policy не
  считаются failed test attempt. Новый request — после выяснения исхода прежнего
  и исправления причины, а не автоматически по таймауту ожидания
- Manual mode: report id и redacted ошибка пользователю без task lifecycle
- Запрос человеку — только если действительно не хватает доступа или решения

# Настройка harness-watcher

Этот мануал настраивает командный сценарий: Агент пишет exec-request в удалённый
репозиторий, а watcher на рабочей станции выполняет команды и возвращает exec-report.
Примеры намеренно не содержат реальных хостов, пользователей и путей команды.

## 1. Сначала зафиксируйте границы

До установки определите:

- какой удалённый репозиторий имеет право отправлять команды;
- какая рабочая станция будет их выполнять;
- кто владеет SSH-доступом и watcher-процессом;
- разрешён ли перенос файлов обратно (`push`/`both`);
- какие команды, секреты и пути запрещены правилами команды.

`harness-watcher` выполняет произвольные shell-команды из доверенной очереди.
Не подключайте его к репозиторию, куда могут писать недоверенные пользователи.

Проверка host key включена по умолчанию и должна оставаться включённой для
командного и production-использования. Получите fingerprint хоста от доверенного
владельца и сверьте его по независимому каналу до первого подключения.

## 2. Проверьте требования

На рабочей станции нужны:

- Python 3.9+;
- `bash`, `ssh`, `scp`, `tar`;
- SSH-ключ, подходящий для неинтерактивного `BatchMode=yes`;
- проверенная запись host key в стандартном или выделенном `known_hosts`;
- сетевой доступ к удалённой машине;
- отдельная папка для одноразового локального зеркала.

На удалённой машине нужны `tar`, shell и права чтения/записи в репозитории.
`rsync` не требуется: рабочий poller переносит дерево через `tar` поверх SSH.

Проверьте локальные зависимости:

```bash
python3 --version
bash --version
ssh -V
command -v scp
tar --version
```

## 3. Установите пакет

Из папки `harness-watcher`:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/harness-watcher --help
```

В рабочем окружении можно установить пакет выбранным командой способом. Для
разработки optional dependency `dev` добавляет pytest; runtime-зависимостей кроме
стандартной библиотеки нет.

## 4. Создайте конфиг

```bash
mkdir -p ~/.config/harness-watcher
cp watcher.toml.example ~/.config/harness-watcher/config.toml
chmod 600 ~/.config/harness-watcher/config.toml
```

Минимальные поля:

```toml
[remote]
ssh_host = "executor@example.internal"
ssh_port = 22
ssh_key = "~/.ssh/team_exec"
strict_host_key_checking = true
user_known_hosts_file = ""
remote_repo_root = "/srv/team/service"

[local]
local_repo_root = "/work/harness-mirrors/service"
```

`ssh_host` имеет формат, который принимает системный `ssh`: hostname или
`user@hostname`. Не копируйте в командный шаблон персональные alias и пути.

При пустом `user_known_hosts_file` OpenSSH использует свои стандартные файлы.
Для выделенного файла укажите существующий путь: конфиг fail-closed отклонит
несуществующий файл. Наполнение файла должно происходить утверждённым командой
способом после независимой проверки fingerprint.

`strict_host_key_checking=false` разрешён только как осознанный высокорисковый
opt-out в изолированном тесте. Не используйте его для общей очереди, CI или production.

Укажите альтернативный конфиг через переменную окружения:

```bash
HARNESS_WATCHER_CONFIG=/secure/path/watcher.toml .venv/bin/harness-watcher --check
```

## 5. Подготовьте локальное зеркало и окружение

Если `sync_before_exec=true`, watcher перед выполнением удаляет `local_repo_root`,
создаёт его заново и распаковывает туда tar-поток с удалённой машины. Поэтому:

- `local_repo_root` должен быть выделенным одноразовым зеркалом;
- не редактируйте в нём важные файлы вручную;
- не размещайте внутри него venv, ключи, кеши или несохранённые данные;
- всё, что перечислено в `[rsync].exclude`, не попадёт в зеркало.

Название `[rsync]` — совместимость старой схемы. Список `exclude` используется
текущими функциями tar-sync.

Внешнее окружение можно подготовить, например, так:

```bash
python3 -m venv /work/harness-envs/service
/work/harness-envs/service/bin/pip install -r /secure/path/requirements.txt
```

Конкретную команду установки зависимостей выбирайте из документации сервиса;
watcher не должен угадывать package manager или production extras.

Если синхронизация не нужна, установите `sync_before_exec=false` и самостоятельно
поддерживайте `local_repo_root` в нужном состоянии.

## 6. Настройте pre_exec_hook

`pre_exec_hook` запускается перед каждой командой request. Executor формирует:

```bash
set -e
<pre_exec_hook>
<command>
```

Типовой пример:

```toml
[executor]
sync_before_exec = true
sync_after_exec = false
pre_exec_hook = "source /work/harness-envs/service/bin/activate && export PATH=$HOME/.local/bin:$PATH"
```

Если hook завершается с ненулевым кодом, сама команда не выполняется. Не помещайте
секреты прямо в TOML, если они могут попасть в диагностику или резервные копии;
используйте утверждённый командой secret injection.

## 7. Проверьте SSH и права

```bash
.venv/bin/harness-watcher --check
```

Успешная диагностика подтверждает:

- SSH-подключение;
- существование `remote_repo_root`;
- право создать и удалить тестовый файл.

В начале вывода проверьте `strict_host_key_checking: True` и ожидаемый
`user_known_hosts_file`. Ошибка `Host key verification failed` означает, что нужно
проверить identity хоста и корректно обновить known_hosts, а не отключать проверку.

Вывод также содержит `remote_rsync_available`. Это legacy-поле: актуальная
синхронизация использует `tar`, поэтому `False` само по себе не является ошибкой.
Проверить tar отдельно можно разрешённой командой вашей SSH-конфигурации:

```bash
ssh -p 22 -i ~/.ssh/team_exec executor@example.internal "tar --version"
```

Запускайте `--check -v` только для диагностики: он добавляет подробный SSH debug,
который может содержать инфраструктурные сведения.

## 8. Запустите watcher

Для первого прогона используйте verbose-режим:

```bash
.venv/bin/harness-watcher -v
```

Другие команды:

```bash
.venv/bin/harness-watcher --once
.venv/bin/harness-watcher --status
.venv/bin/harness-watcher --audit-tail 50 --status
```

При старте watcher создаёт на удалённой стороне:

```text
docs/harness/exec-requests/
docs/harness/exec-reports/
docs/harness/exec-processed/
```

В обычном режиме он опрашивает очередь каждые `poll_interval_seconds`.

## 9. Выполните smoke-request

Создайте файл `docs/harness/exec-requests/smoke-001.json` в тестовой удалённой
копии репозитория:

```json
{
  "request_id": "smoke-001",
  "task_id": "WATCHER-SMOKE",
  "commands": [
    {"cmd": "python --version", "cwd": "."},
    {"cmd": "pwd", "cwd": "."}
  ],
  "timeout_seconds": 60,
  "stop_on_failure": true,
  "sync": "pull"
}
```

Ожидаемый результат:

1. В verbose-логе появляются download, tar-sync, execute и upload.
2. Создаётся `docs/harness/exec-reports/smoke-001.json`.
3. Request перемещается в `docs/harness/exec-processed/smoke-001.json`.
4. Report содержит `overall_status`, результаты команд, `sync`, фактический
   `source_snapshot`, duration, hostname и `watcher_version`.

Не начинайте с `push` или `both`: сначала подтвердите только pull + execute + report.

## 10. Формат выполнения

Request поддерживает:

- `request_id` — идентификатор пары request/report;
- `task_id` — необязательная связь с задачей harness;
- `commands` — список объектов `{cmd, cwd}`;
- `timeout_seconds` — общий бюджет request;
- `stop_on_failure` — остановка после первой ошибки;
- `sync` — `pull`, `push`, `both` или `none`;
- `context` — метаданные, не участвующие в исполнении. В report возвращаются только
  `branch`, `commit`, `source_revision`, `ticket`, `execution_mode`, `profile`,
  `purpose`, `verification_level`, а также `tree_fingerprint`, `lock_fingerprint`,
  `execution_profile` и `commands_fingerprint`; прочие поля отбрасываются.

Новый `request_id` использует только `[A-Za-z0-9._-]`, а filename равен
`{request_id}.json` без преобразований. Claim сохраняется в локальный state до
sync/exec, поэтому один ID не выполняется повторно даже после перезапуска watcher.
Для повторного запуска сформируйте новый ID/attempt.

Legacy-переход: старый ID с `:` ещё принимается при буквальном совпадении filename
stem и `request_id`. Вариант, где двоеточия заменены дефисами только в filename,
отклоняется до выполнения. После обновления producer используйте лишь новый формат.

Если `sync` отсутствует, используются настройки `sync_before_exec` и
`sync_after_exec`. Каждая команда запускается через `bash -lc`. `cwd` разрешён
только внутри `local_repo_root`; попытка выйти наружу помечается как error.

Watcher сам вычисляет canonical key в `evidence.observed`. Поле
`evidence.requested_matches` проверяет только переданные expected hints:
`false` — mismatch и такой запуск нельзя связывать с ожидаемым tree; `null` —
hint не был известен заранее. Для будущего reuse сравнивайте текущий требуемый
tree/lock/profile/commands key с `evidence.observed`, а не требуйте повторного
запуска только ради `all=true`. Transport-папки watcher и типовые cache/build
artifacts не входят в content fingerprint.

Общий `timeout_seconds` уменьшается после каждой команды. Одна команда не может
работать дольше `default_timeout_seconds`. После превышения timeout вся группа
процессов команды получает TERM, а затем KILL, если не завершилась.

## 11. Streaming, truncation и noise filter

В verbose-режиме stdout и stderr передаются построчно в окно watcher во время
выполнения. Итоговый report ограничивает размер каждого потока настройками:

```toml
[poller]
stdout_max_chars = 8000
stderr_max_chars = 4000
```

При обрезке сохраняется хвост — обычно именно там находится результат тестов.

Фильтр:

- работает только для stdout успешных команд;
- может убрать ANSI, известные сообщения uv и настроенные `extra_patterns`;
- не применяет regex к упавшей команде;
- возвращает исходный stdout, если фильтрация оставила бы меньше одной строки.

Для временного отключения:

```toml
[filter]
enabled = false
```

Проектный шум добавляйте локально в `extra_patterns`; не вносите в командный
шаблон имена конкретного сервиса без необходимости.

## 12. Работа через harness

Скилл `harness-request-exec` создаёт request и ждёт парный report, когда правила
конкретного workspace требуют внешний исполнитель. Watcher — условная интеграция:
если команды можно безопасно выполнить непосредственно в рабочем окружении, файловый
мост не нужен.

Таймаут клиентского ожидания должен быть больше `timeout_seconds` request с запасом
на polling, tar-sync и SCP. Конкретное поле настройки клиента зависит от используемой
интеграции и должно быть задокументировано рядом с её конфигом.

## 13. Диагностика

### SSH connection failed

Проверьте host, port, key, права на ключ и неинтерактивный вход:

```bash
ssh -p 22 -i ~/.ssh/team_exec executor@example.internal "echo PING"
```

### remote_repo_root does not exist / no write permission

Путь должен существовать и быть доступен пользователю SSH. Не подставляйте новый
deploy path наугад — получите его у владельца окружения.

### tar-sync failed

Проверьте `tar` с обеих сторон, свободное место и права на локальное зеркало.
Посмотрите audit log и `sync.pull.error` в report. При запрошенном pull watcher
работает fail-closed: не запускает команды на старом локальном зеркале, загружает
error-report и переносит request в `exec-processed/`. `rsync` устанавливать не требуется.

### Команда не находит Python, uv или зависимости

Проверьте `pre_exec_hook`, расположение внешнего venv и PATH. Выполните ту же связку
локально через `bash -lc`, потому что именно так запускает executor.

### Команда завершилась по timeout

Согласуйте три величины: `timeout_seconds` request, `default_timeout_seconds` watcher
и таймаут ожидания report у клиента. Не повышайте лимиты без понимания зависшей
команды.

### Report не появился

Проверьте по порядку:

1. watcher запущен;
2. request лежит в `exec-requests/` и имеет расширение `.json`;
3. `--status` не показывает download/parse/upload error;
4. request не числится обработанным в локальном `state.json`;
5. пользователь SSH может писать в `exec-reports/` и `exec-processed/`.

Для безопасного повторения создайте request с новым `request_id` и именем файла,
не переписывая историю выполненного запроса.

### Вывод слишком шумный или слишком короткий

Проверьте `[filter]`, `stdout_max_chars` и `stderr_max_chars`. При ошибках regex-фильтр
не скрывает stdout, поэтому разница между успешным и упавшим запуском ожидаема.

## 14. Состав реализации и проверки

```text
harness-watcher/
├── README.md
├── SETUP-GUIDE.md
├── pyproject.toml
├── watcher.py
├── watcher.toml.example
├── lib/
│   ├── __init__.py
│   ├── audit.py
│   ├── config.py
│   ├── executor.py
│   ├── filter.py
│   ├── poller.py
│   └── remote_fs.py
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_executor.py
    ├── test_filter.py
    └── test_remote_fs.py
```

Модули:

- `config.py` — TOML, defaults и валидация обязательных путей;
- `remote_fs.py` — SSH/SCP и tar-sync (также содержит legacy rsync helpers,
  которые текущий poller не вызывает), а также единые secure SSH/SCP options;
- `executor.py` — последовательный запуск, hook, streaming, timeout и truncation;
- `filter.py` — безопасная фильтрация stdout;
- `poller.py` — очередь request/report, sync и state;
- `audit.py` — JSONL audit log;
- `watcher.py` — CLI.

Проверка пакета:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q watcher.py lib tests
```

Unit-тесты не заменяют smoke-тест SSH/SCP/tar на разрешённом стенде.

## 15. Эксплуатационный чек-лист

Перед командным rollout:

- [ ] источник requests ограничен доверенными участниками;
- [ ] локальное зеркало выделено и может безопасно очищаться;
- [ ] venv и секреты находятся вне зеркала;
- [ ] политика `push`/`both` утверждена;
- [ ] host fingerprint независимо проверен, strict checking включён;
- [ ] audit/state paths защищены правами ОС;
- [ ] request/report не содержат секретов;
- [ ] пройдены unit-тесты и smoke на тестовом репозитории;
- [ ] назначены владелец процесса и порядок остановки/ротации.

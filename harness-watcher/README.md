# harness-watcher

`harness-watcher` — локальный мост для случаев, когда Агент работает с репозиторием
на удалённой машине, а команды нужно выполнить на рабочей станции команды.
Он читает файловую очередь через SSH/SCP, при необходимости переносит код через
`tar` поверх SSH, последовательно выполняет команды и возвращает JSON-отчёт.

> Источник пакета — последняя восстановленная историческая реализация. Это
> переиспользуемая база, а не свидетельство уже проверенного team deployment.
> Перед общим использованием проверьте её на тестовом репозитории и вашей SSH-схеме.

## Как устроен обмен

Удалённый репозиторий содержит три служебные папки:

```text
docs/harness/
├── exec-requests/   # входящие *.json
├── exec-reports/    # отчёты с тем же именем
└── exec-processed/  # обработанные запросы
```

Один цикл watcher:

1. Находит новый request на удалённой машине и скачивает его через SCP.
2. По `sync` переносит удалённую копию в `local_repo_root` через `tar` поверх SSH.
   Если запрошенный pull не удался, команды не запускаются: watcher возвращает
   error-report и завершает request.
3. После sync считает SHA-256 фактического локального дерева, затем запускает
   команды по очереди через `bash -lc` внутри `local_repo_root`.
4. Стримит stdout/stderr в verbose-режиме и собирает ограниченный по размеру отчёт.
5. Фильтрует известный шум только в stdout успешных команд.
6. При `push`/`both` переносит артефакты обратно через `tar`.
7. Загружает report через SCP и перемещает request в `exec-processed/`.

Фактический poller не использует `rsync`. Имя секции `[rsync]` сохранено для
совместимости старого формата конфига; её `exclude` применяется к tar-sync.
Поле `remote_rsync_available` в выводе `--check` — также legacy-диагностика и
не является требованием для работы watcher.

## Быстрый старт

Требуются Python 3.9+, `bash`, `ssh`, `scp` и `tar` локально и `tar` на удалённой
машине.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
mkdir -p ~/.config/harness-watcher
cp watcher.toml.example ~/.config/harness-watcher/config.toml
```

Заполните конфиг, затем:

```bash
.venv/bin/harness-watcher --check
.venv/bin/harness-watcher -v
```

Другие режимы:

```bash
.venv/bin/harness-watcher --once
.venv/bin/harness-watcher --status
HARNESS_WATCHER_CONFIG=/path/to/config.toml .venv/bin/harness-watcher --check
```

Полная настройка и диагностика описаны в [SETUP-GUIDE.md](SETUP-GUIDE.md).

## Формат request

```json
{
  "request_id": "verify-001",
  "task_id": "T-001",
  "commands": [
    {"cmd": "make verify", "cwd": "."},
    {"cmd": "python -m pytest -q", "cwd": "."}
  ],
  "timeout_seconds": 900,
  "stop_on_failure": true,
  "sync": "pull",
  "context": {
    "branch": "feature/T-001",
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "purpose": "verify before commit",
    "verification_level": "bundle",
    "tree_fingerprint": "<ожидаемые 64 hex, если уже известны>",
    "lock_fingerprint": "<ожидаемые 64 hex или N/A, если уже известны>",
    "execution_profile": "<из прошлого observed report, если уже известен>",
    "commands_fingerprint": "<ожидаемые 64 hex, если уже известны>"
  }
}
```

`sync` принимает `pull`, `push`, `both` или `none`. Если поле отсутствует,
используются `sync_before_exec` и `sync_after_exec` из конфига. `cwd` обязан
оставаться внутри `local_repo_root`; выход через `..` блокируется.

Для новых запросов `request_id` должен соответствовать `[A-Za-z0-9._-]+`, а имя
файла обязано быть ровно `{request_id}.json`. Watcher сохраняет claim по
`request_id` **до** sync и запуска команд. Повторно появившийся ID никогда не
исполняется: существующий report сохраняется, request только переносится в
`exec-processed/`; если report отсутствует, создаётся terminal duplicate-error.
Повреждённый state также блокирует выполнение.

Переходная совместимость: старые ID с двоеточиями принимаются только если имя
файла совпадает с ними буквально. Преобразование `:` в `-` и другие неявные
нормализации запрещены, поскольку именно они могут создать две формы одного ID.
Новые requests всегда создавайте в каноническом формате без двоеточий.

В report из `context` возвращаются только безопасные координационные поля:
`branch`, `commit`, `source_revision`, `ticket`, `execution_mode`, `profile`,
`purpose`, `verification_level` и четыре `*_fingerprint` из примера. Остальные
поля отбрасываются. Секреты нельзя передавать даже в разрешённых полях.

`pre_exec_hook` выполняется перед каждой командой после `set -e`. Его удобно
использовать для PATH, активации venv и переменных окружения. Общий бюджет задаёт
`timeout_seconds`; отдельная команда дополнительно ограничена
`default_timeout_seconds`. При таймауте watcher посылает `TERM`, затем `KILL`
всей группе процессов команды, включая запущенные ею дочерние процессы.

## Фильтрация и отчёты

- В `-v` виден живой поток stdout/stderr.
- В report сохраняются последние `stdout_max_chars` и `stderr_max_chars` символов.
- `sync` в report показывает фактический результат pull/push, а `source_snapshot`
  содержит вычисленный после sync `tree_sha256`, число файлов/байт и, когда
  локальное зеркало содержит `.git`, фактические `git_head`, `git_tree` и dirty-флаг.
  Значение `context.commit` остаётся только заявленным контекстом и не считается
  доказательством проверенной ревизии.
- `evidence.observed` содержит фактически вычисленные `tree_fingerprint`,
  `lock_fingerprint`, `execution_profile` и `commands_fingerprint`.
  `evidence.requested_matches` сравнивает каждый из них с request и выставляет
  `all=true` только когда все четыре expected hints были переданы и совпали.
  Отсутствующий hint даёт `null`, а не ошибку; `false` означает реальное
  несовпадение и запрещает использовать запуск как evidence ожидаемого tree.
  Для будущего reuse сравнивают текущий требуемый key с `evidence.observed`,
  поэтому первый успешный запуск не нужно повторять только ради заполнения
  `execution_profile` в request.
- Content fingerprint всегда исключает `.git`, transport-папки
  `docs/harness/exec-{requests,reports,processed}`, venv, build output и типовые
  Python/Node cache-файлы. Поэтому появление report не меняет проверяемый hash.
- Lock fingerprint считается по известным dependency manifests/locks
  (`uv.lock`, `pyproject.toml`, requirements, Poetry/Pipenv, Node, Go и Cargo);
  при их отсутствии значение равно `N/A`.
- Execution profile — стабильный SHA-256 версии watcher/Python, безопасных
  execution-настроек и хешей выбранного окружения. Сам `pre_exec_hook` и его
  значения в report не раскрываются.
- Regex-фильтр применяется только к stdout команд с exit code `0`.
- Для упавших команд regex-фильтр не применяется; при включённом `strip_ansi`
  удаляются только управляющие ANSI-последовательности.
- Если фильтр удалил бы весь полезный вывод, исходный stdout сохраняется.

## Состав пакета

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

Unit-тесты покрывают конфиг, безопасные SSH/SCP options, idempotency по request ID,
fail-closed sync, fingerprint дерева, process-group timeout, исполнение,
`pre_exec_hook`, ограничение `cwd`, обрезку вывода и noise filter. SSH/SCP/tar требуют отдельного smoke-теста
на разрешённом удалённом стенде.

## Ограничения безопасности

- `local_repo_root` при pull-синхронизации очищается и создаётся заново. Используйте
  только выделенное одноразовое зеркало; venv и важные файлы держите вне него.
- `sync_after_exec=true` или request с `push`/`both` изменяет удалённую копию.
- Команды выполняются с правами пользователя, запустившего watcher.
- Проверка host key включена по умолчанию (`strict_host_key_checking=true`) и
  использует стандартный `known_hosts` OpenSSH либо явно заданный существующий
  `user_known_hosts_file`.
- Сначала получите fingerprint удалённого host key от доверенного владельца и
  проверьте его по независимому каналу. Не принимайте неизвестный ключ вслепую.
- `strict_host_key_checking=false` — явный высокорисковый opt-out только для
  изолированного теста; для командного и production-использования он запрещён.
- Не храните секреты в request, report, конфиге репозитория или audit log.
- Watcher должен принимать requests только из доверенного репозитория и SSH-контура.

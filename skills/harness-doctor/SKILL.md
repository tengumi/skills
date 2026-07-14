---
name: harness-doctor
description: "Проверяет среду, checkout и воспроизводимый baseline ДО первой задачи harness: git root/HEAD/branchability, обязательные инструменты, UV_PROJECT_ENVIRONMENT, watcher/tasks-mcp round-trip, clean install, import smoke и исходный verify/format state. Используй один раз на новом окружении или репозитории, после смены execution path и при подозрении на executor/environment failure."
---

# harness-doctor

## Цель

Отделить дефект среды от дефекта кода до claim первой задачи. Результат —
`GO` или `NO-GO` с доказательствами; красный doctor блокирует перенос, но ничего
не «чинит» глобально сам.

## Workflow

### 1. Execution control plane (сначала read-only)

Проверить и записать:

- фактический repo root, `git status --short --branch`, наличие HEAD и обычного
  checkout, возможность создать task branch без изменения protected branch;
- ошибки ownership/safe.directory как executor blocker; отсутствие git metadata,
  HEAD или чистого baseline — task-workflow blocker. Для только что созданного
  scaffold сначала завершить review/initial commit, затем повторить doctor; не
  выдавать task-ready `GO` по незакоммиченному дереву;
- `make`, целевой Python и `uv` через `command -v`/документированный абсолютный
  путь. Не предполагать наличие `rtk`, shell aliases или чтение `.bashrc`;
- значение и существование `UV_PROJECT_ENVIRONMENT`, не раскрывая секреты;
- доступность tasks-mcp lifecycle и его `queue_storage_mode`. Допустимы
  `out_of_band` либо `tracked` только с документированным отдельным MCP
  coordination commit/channel; обычная правка tracked `tasks.json` в working
  tree feature-ветки — `NO-GO`, потому что claim/submit загрязнят task diff.
  Harmless watcher round-trip (`pwd`, версии
  runtime, `sync: none`) обязателен только если watcher задан AGENTS/policy,
  direct runtime недоступен или пользователь выбрал watcher execution mode; в
  direct-exec repo отсутствие watcher не является `NO-GO`.

Снять canonical identity inventory: repository/service/distribution/Python
package/workspace member/image/Jenkins job/queue/schema. Выполнить negative `rg`
по старым template/service tokens в code/build/CI/resources; доменные поля и
имена внешних сервисов классифицировать отдельно и не переименовывать глобально.

### 2. Reproducible install

Использовать команду установки из `AGENTS.md`/Makefile в новом или очищенном
внешнем venv. Тёплая `.venv` не является доказательством. Затем выполнить import
smoke корневого проекта, workspace-пакетов и production entrypoint без реальной
сети. Если install или lock не воспроизводятся — `NO-GO`; не продолжать за счёт
пакетов, случайно оставшихся в окружении.

### 3. Baseline качества

До изменений запустить штатный `make verify` и полный format/lint check,
который использует CI. Зафиксировать точные counts и разделить:

- зелёный baseline;
- pre-existing failure/format debt;
- executor/environment failure.

Не форматировать всё дерево и не исправлять долг в doctor.

### 4. Отчёт и чистый handoff

Создать `docs/harness/environment-doctor.md`:

- timestamp, repo root/HEAD/branch;
- runtime/tool paths и версии;
- watcher request/report id;
- install/import/verify/format команды и исходы;
- `GO` либо `NO-GO`, blocker owner и следующий безопасный шаг.

Это preflight-артефакт, не часть первой feature/port-задачи. До task-ready `GO`
повторно проверить `git status`: отчёт должен быть либо уже сохранён отдельным
preflight commit, либо находиться в явно настроенном audit/ignored path по
политике репозитория. Не добавлять ignore-правило молча и не оставлять doctor
report в dirty diff будущей задачи. Если handoff не оформлен, результат —
`NO-GO` для claim с понятным следующим шагом.

## Hard Limits

- Не claim-ить первую задачу при `NO-GO`.
- Не менять global git config, safe.directory, PATH или системный Python без
  явного решения пользователя/администратора.
- Не подменять отсутствующий инструмент похожей командой и не считать локальный
  bash эквивалентом watcher execution mode.
- Не скрывать pre-existing failures и не смешивать их с регрессией задачи.
- Не писать секретные значения, credentials или содержимое env в отчёт.
- Не выдавать task-ready `GO`, если собственный doctor report оставил checkout
  dirty; сначала оформить отдельный preflight handoff.
- Не выдавать `GO`, пока не доказано, что claim/submit не оставляют
  `docs/harness/tasks.json` в task diff: lifecycle хранится out-of-band либо MCP
  синхронизирует его отдельным coordination commit/channel.

## Output

`environment-doctor.md`, итог `GO/NO-GO`, воспроизводимый baseline, чистый
handoff и явные blockers до начала переноса.

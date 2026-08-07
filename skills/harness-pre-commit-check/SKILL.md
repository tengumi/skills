---
name: harness-pre-commit-check
description: "Проверяет конкретный diff перед локальным commit: scope, актуальное verify evidence, секреты/runtime artifacts, protected paths и Git-конвенции. Автоматически пропускает зелёный task/preflight commit без отдельного human confirmation, наследует уже выданные approvals и останавливается только на реальном safety/scope blocker. Используй из harness-work-session, harness-productionize или по прямому запросу проверить/закоммитить изменения."
---

# harness-pre-commit-check

## Цель

Не запросить разрешение на каждый commit, а доказать, что конкретный diff можно
безопасно зафиксировать. В активной change/build/productionize работе локальная
ветка и commit являются обычным обратимым шагом. Отдельный human checkpoint нужен
только для нового решения или риска, а не для нажатия `git commit`.

## Режим

Определить режим по вызывающему workflow:

- `task` — есть claimed task; scope берётся из acceptance, approved plan и
  recorded approvals;
- `preflight` — активный `harness-productionize`, context/analysis/plan
  handoff до первой task; scope — созданные Harness artifacts и явно одобренные
  preflight changes;
- `direct-review` — пользователь попросил только проверить; commit не выполнять;
- `direct-commit` — пользователь прямо попросил закоммитить указанный diff.

Не считать весь dirty tree разрешённым. Если нельзя выделить один связный diff,
остановиться с точным списком неоднозначных paths.

## Наследование разрешений

Считать действующим разрешением для текущего scope любое из следующего:

- активный запрос/goal на change, build, fix или productionize;
- claimed task с acceptance;
- approved plan/decision packet;
- `task.approvals` с owner, provenance и подходящим scope;
- явное разрешение пользователя в текущем запуске.

Разрешение наследуется следующими шагами той же задачи и не запрашивается
повторно перед branch, commit или submit. Более узкое или более позднее решение
имеет приоритет. Явные `не коммить`, review-only или ограничение scope всегда
побеждают.

Общий change/build goal разрешает обычные локальные in-scope commits, но не
разрешает сам по себе live/deploy/shared-DB/destructive action и не расширяет
protected scope за пределы approved task/plan.

## Проверка

### 1. Ветка и идентификатор

Проверить `git branch --show-current`.

- task branch: `feature/<task.ticket|task.id>[-short-description]`;
- preflight branch: `feature/T-000[-short-description]` либо exact approved
  preflight branch.

Если ветку надо создать, сформировать short-description самостоятельно из task
title в lowercase kebab-case. Не спрашивать Jira ID, когда доступен `task.id`, и
не предлагать `NOJIRA`.

Не коммитить в protected branch.

### 2. Выбрать diff и проверить scope

Использовать staged diff, если index непустой; иначе working diff. Сопоставить
каждый path и существенный hunk с текущим scope.

Разрешить в `preflight`:

- `AGENTS.md` и `docs/harness/*.md` analysis/context/planning/audit artifacts;
- versioned planning changes в `docs/harness/tasks.json`;
- запись уже принятого owner decision/approval;
- другие exact paths из approved preflight plan.

В `tasks.json` разрешены определения/acceptance/dependencies/approvals, созданные
planning workflow. Claim/submit lifecycle-поля остаются MCP-owned и не входят в
feature commit при `out_of_band` mode.

Не включать unrelated cleanup, formatter churn, raw watcher transport, runtime
outputs или изменения другой задачи. Очевидный лишний path убрать из index и
продолжить; спрашивать человека только когда принадлежность scope действительно
неоднозначна.

### 3. Проверить protected paths и approvals

Взять protected paths из применимых `AGENTS.md`/team policy. Для CI, migrations,
build/dependency files, generated artifacts и других защищённых путей найти
подходящее действующее approval.

Approved plan на механический identity rename считается approval для
перечисленных exact paths и rename mapping. Не запрашивать его повторно перед
commit. `files_hint` без approved plan/decision approval не заменяет.

Остановиться только если protected изменение:

- отсутствует в действующем scope;
- меняет семантику сверх approved plan;
- добавляет dependency, migration behavior, deploy/live/DB side effect без
  отдельного разрешения.

### 4. Использовать verification pyramid и минимально достаточное evidence

Сначала найти уже зелёное evidence с точным ключом:
`runtime tree fingerprint + dependency/lock fingerprint + execution profile +
normalized command list`. Все четыре части должны совпасть. Не повторять
команду из-за новой сессии, нового commit SHA с тем же runtime tree, изменения
только analysis docs или повторного вызова pre-check. Branch/commit сам по себе
не доказывает и не инвалидирует результат. Если хотя бы один fingerprint или
список команд нельзя доказать — evidence не переиспользовать.

Сначала прочитать `task.verification_level` и выбрать проверки по уровню:

- docs-only/preflight: `git diff --check`, parse/schema изменённых JSON/YAML и
  secret/runtime-artifact scan; полный test/build не нужен;
- `scoped`: touched lint/import/tests;
- `capability`: scoped checks + цельный observable capability contract suite;
- `runtime`: capability checks + production process/DI/lifespan smoke;
- `bundle`: clean install, canonical full verify, build/package inventory и
  применимый source/frozen process smoke;
- dependency/lock ниже bundle: только resolution/import compatibility check;
- migrations: source/dist inventory и разрешённая безопасная проверка без
  shared-DB mutation;
- external boundary: sanitized contract/mock check; live только по отдельному
  разрешению.

`make verify` не заменяет применимый layer-specific gate, но и не дублировать
lint/format/test, уже входящие в canonical verify.

В одном `plan_id` bundle имеет ровно одного владельца, если он применим. Build
или clean install не запускать повторно для scoped/capability/runtime task.
Packaging diff в task, которая не является согласованным bundle owner, — это
planning mismatch, а не причина молча повысить уровень проверки.

Если обязательное evidence отсутствует или красное, вернуть управление в
исполняющий workflow для исправления/проверки. Не превращать это автоматически в
human checkpoint.

### 5. Секреты и runtime artifacts

Проверить только добавленные строки и changed paths штатным repo guard либо
точечным поиском:

- private keys, JWT/cloud-key patterns и реальные token/password/secret values;
- `.env*` кроме разрешённого `.env.example`, cert/private-key material, logs,
  raw RAG/LLM/domain dumps;
- несанационные PII fixtures.

При вызове `rg` с pattern, начинающимся на `-`, обязательно ставить `--` перед
pattern, чтобы scan не завершился ложной ошибкой CLI.

Найденный реальный секрет — hard blocker: не печатать значение, не коммитить и
не разрешать обход подтверждением. Сообщить только path/line и способ удалить или
заменить секрет.

### 6. Незавершённый код и конвенции

Проверить добавленные строки на debug prints/breakpoints, закомментированный код,
непривязанные TODO/FIXME/HACK/XXX, голые/глушащие exceptions и нарушение
repo/team conventions.

Очевидный in-scope дефект исправить автоматически и повторить затронутую
проверку. Подтверждённый template marker или task-tracked debt оставить с
evidence. Спрашивать человека только если исправление меняет поведение либо
существуют два несовместимых team rules.

### 7. Commit message

Сформировать сообщение самостоятельно по Git-конвенции:

- prefix: `task.ticket`, иначе `task.id`; для preflight — `T-000`;
- текст: кратко, в повелительном наклонении, по фактическому diff.

Если repo задаёт иной точный формат, использовать его. Спрашивать формат только
когда его нельзя вывести ни из policy, ни из истории. Не спрашивать
«коммитить?» в `task`, `preflight` или `direct-commit` после зелёного результата.

### 8. Размер diff

Diff больше 500 строк или 10 файлов считать review warning, не checkpoint.
Разбить автоматически, если существуют независимые атомарные scopes. Связный
generated/template/preflight handoff оставить одним commit и отметить размер в
отчёте.

## Решение

### PASS_AUTO

Выдать, если все обязательные проверки зелёные и действующее разрешение
покрывает diff:

```text
status: PASS_AUTO
commit_authorized: true
commit_message: <message>
evidence_reused: <reports or none>
verification_key: <tree/lock/profile/commands>
warnings: <non-blocking list>
```

В `task`, `preflight` и `direct-commit` немедленно вернуть управление caller со
словами «продолжить commit без дополнительного подтверждения». Caller выполняет
commit и дальнейший lifecycle. Не создавать human checkpoint.

В `direct-review` выдать `PASS_REVIEW_ONLY`; commit не выполнять и разрешение не
подразумевать.

### BLOCKED

Выдать только при hard blocker:

- реальный secret/runtime artifact;
- out-of-scope diff, который нельзя безопасно отделить;
- отсутствующее обязательное verify/layer evidence после попытки получить его;
- protected semantic change без подходящего approval;
- protected branch или невозможность определить commit scope/message.

Если blocker можно исправить локально в scope, исправить и повторить check без
человека. Human decision packet нужен только для нового behavior/architecture,
protected scope, dependency, live/deploy/DB разрешения или конфликта team rules.

## Hard limits

- Не коммитить из protected/non-`feature/` branch.
- Не коммитить реальные секреты, raw confidential artifacts или несанационные
  PII.
- Не коммитить несвязанный diff только потому, что tests зелёные.
- Не считать `files_hint` самостоятельным protected approval.
- Не повторять уже действующее approval и не запрашивать разрешение только на
  локальный commit.
- Не выполнять commit, если пользователь явно попросил только review или
  запретил commit.

## Output

Вернуть `PASS_AUTO`, `PASS_REVIEW_ONLY` или `BLOCKED`, выбранный diff, commit
message, использованное evidence, warnings и только реальные действия для
устранения blocker.

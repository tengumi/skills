---
name: harness-work-session
description: "Выполняет одну задачу из docs/harness/tasks.json от claim до submit через harness-протокол и routes по exact use_skill/skill_mode. Используй по запросам 'возьми задачу', 'начни/продолжи T-NNN' или 'harness-work-session'; применяет tasks-mcp, профильные harness-skills и harness-pre-commit-check."
---

# harness-work-session

## Цель

Выполнить ОДНУ задачу из `docs/harness/tasks.json` целиком: claim → ветка → реализация → verify → commit → submit. Оставить за собой ветку с одним коммитом и обновлённую очередь.

Ты — исполнитель в живом репозитории. Действуй пошагово. Конвенции репозитория живут в `AGENTS.md` и `docs/harness/` — этот скилл не дублирует их, а ссылается.

## Когда применять

Подгружается когда пользователь говорит «возьми задачу», «начни работу»,
«продолжи T-NNN», или явно зовёт `harness-work-session`. Если задача поставлена
в чате без id — сначала предложи завести её в `tasks.json`, иначе нечего будет
submit'ить.

Если ты уже в середине задачи (есть `in_progress` с твоим claimed_by) — не запускай скилл заново, продолжи с того шага где остановился.

## Шаги

**1. Прочитай контекст.**
Если `AGENTS.md` ещё не в контексте — прочитай его в корне репы. Прочитай `docs/harness/conventions.md` чтобы знать формат коммитов, имена веток, команды verify.
Отдельный environment preflight не требуется. Доступность нужных команд и
исходный baseline проверяй внутри текущей задачи минимально достаточными
командами; не создавай для этого отдельный report или commit.

В непрерывном orchestrated run не перечитывать стабильный контекст после каждой
task. Повторно использовать уже прочитанные AGENTS/conventions/plan/analysis,
если их exact content fingerprints не изменились; перечитывать только changed
artifact и непосредственно нужные task inputs. Новая сессия сама по себе не
инвалидирует доказанно неизменный контекст.

**2. Выбери задачу.**
Если `harness-productionize` передал exact `task_id` из свежего merged lifecycle
snapshot, не вызывать повторно `list_open_tasks`, не показывать список и не
просить выбрать задачу: оркестратор уже выполнил scheduling. Использовать
переданную definition/approval context; если передан только id, сразу claim и
сверить возвращённую definition до первой правки.

В standalone-режиме вызвать `tasks-mcp.list_open_tasks(repo_path)`. Если задач
нет — сообщить пользователю и остановиться. Если id указан — выбрать exact
definition и перейти к pre-claim проверке 2.5. Если id не указан — показать
список и спросить, какую брать.

До claim проверь возвращённый `queue_storage_mode`: claim/submit не должны
оставлять tracked `tasks.json` в feature-diff. Для `out_of_band` продолжай;
`tracked` допустим только при уже определённом отдельном coordination channel.

Если указанный id отсутствует среди `open`, вызвать `list_open_tasks(...,
include_all=true)` только для диагностики. `blocked`, `in_progress` или `done`
задачу не claim-ить повторно, даже если текущая реализация tasks-mcp технически
это допускает для `blocked`.

Если task содержит `depends_on`, использовать переданный оркестратором fresh
merged lifecycle snapshot; только в standalone-режиме получить его через
`list_open_tasks(..., include_all=true)`. Проверить, что каждый указанный id
имеет status `done`. Пока хотя бы один prerequisite не завершён, task не
claim-ить; показать только точный список незавершённых зависимостей. Не выводить
dependency из порядка массива или свободного текста notes.

Для `harness-eval:prototype-parity` статического `depends_on` недостаточно.
Task обязана иметь `stage: A` и `plan_id`. По merged lifecycle динамически
проверь ВСЕ tasks с тем же `plan_id`/stage и не claim-ить parity, пока любая
другая из них не `done`. Незавершённая `harness-prototype-port` task без
`plan_id` считается ambiguous Stage-A scope и также блокирует claim до
исправления definition. Для каждой завершённой task этого plan проверь
`evidence.commit_sha` и `git merge-base --is-ancestor <commit_sha> HEAD`: parity
запускается только на target revision, реально содержащей все task commits.
Если после создания parity добавлена Stage-A delta-task с тем же `plan_id`, она
автоматически входит в этот gate, даже если отсутствует в старом `depends_on`.

**2.5. Проверь route, mode и human gate ДО claim.**
Используй полную task definition из standalone `list_open_tasks` либо из
orchestrator context; если productionize передал только exact id, claim может
вернуть definition, но до её проверки нельзя менять файлы. Примени allowlist из шага 3.5.
Для Stage-B routes до claim прочитай
`docs/harness/pre-industrialization-spec.md` и matching-секцию
`docs/harness/data-boundaries.md`, если она уже существует. Для parity/live
примени отдельные prerequisites ниже:

| Route/mode | Что должно быть подтверждено до claim |
|---|---|
| `harness-eval:prototype-parity` | актуальные prototype/target revisions, `prototype-contract.json` и возможность собрать sanitized/synthetic input manifest; live authority нужна только при внешнем вызове |
| `harness-production-readiness:contract` | найденная boundary зарегистрирована; задача ограничена получением contract facts или подготовкой design proposal |
| `harness-production-readiness:adapter` | matching-секция `data-boundaries.md` не ниже `MAPPED`: exact operation/revision/auth/mapping известны, material conflicts отсутствуют |
| остальные Stage-B readiness modes | авторизованный план задачи и применимое разрешение для protected scope |
| `harness-eval:live` | отдельное текущее approval/policy/task evidence с exact environment/data/call/side-effect scope |
| `harness-production-readiness:stand` с external call/side effect | дополнительно то же текущее live authorization |
| `harness-golden` | released input/truth sources, oracle probe и data policy из `golden-spec.yaml` |
| `harness-eval:golden` | released dataset/audit/hash и evaluation data policy; при external call дополнительно текущее live authorization |

Для `contract` незаполненная техническая секция — ожидаемый вход, а не blocker:
до claim нужны зарегистрированная граница и ограниченный scope. Для остальных
перечисленных routes отсутствующий обязательный contract fact, незаполненная
matching-секция или несовпадение разрешённого scope с задачей → STOP до claim и
contract/design/authorization handoff. Specialist затем смыслово сверяет
официальный contract/revision и mapping.

Авторизованный applicability/capability plan вместе с recorded approvals
покрывает все перечисленные в нём safe offline dependency и protected-path
изменения. Authorization может происходить из исходного автоматического
safe-offline запроса либо из одного последующего подтверждения плана.
Не запрашивать повторное approval на claim, branch, edit, verify, commit или
submit внутри этого exact scope. Новый checkpoint нужен только при material
выходе за scope, конфликте источников либо live/shared-DB/deploy действии.

**3. Claim задачу.**
Вызови `tasks-mcp.claim_task(repo_path, task_id)` только при подтверждённом
out-of-band/MCP-managed queue mode. Получишь полный контекст:
`acceptance`, `files_hint`, `ticket`, `notes`. `task.acceptance` — нормализованное
представление persisted `acceptance_criteria`; если MCP вернул raw task, читай
`acceptance_criteria`, но не объединяй два разных списка. Если claim вернул error —
задача занята, остановись.

Запомни идентификатор для ветки и коммита: используй `task.ticket` если задано, иначе `task.id`.

**3.5. Проверь use_skill и skill_mode — роутинг.**
После claim посмотри поля задачи `use_skill`, `skill_mode` и `ported_from`:

- Если `use_skill` задано (напр. `harness-prototype-port`, `harness-production-readiness`,
  `harness-golden`, `harness-eval`, `harness-team-layout-alignment`) — ОСТАНОВИ
  обычный `harness-work-session` и переключись на указанный скилл. Дальнейшие шаги
  (реализация, evidence) ведёт он, не `harness-work-session`. Ветку/claim/submit
  механику `harness-work-session` при этом сохрани, но реализацию и hard limits бери
  из `use_skill`; `task.skill_mode` передай профильному скиллу без переименования
  или неявной подмены.
- Если `use_skill` не задано, но есть `ported_from` (задача переноса без
  явного скилла) — по умолчанию переключись на `harness-prototype-port`.
- Если ни того, ни другого — продолжай обычный `harness-work-session`.

Если существующая задача содержит `use_skill`, который не начинается с
`harness-`, считать это invalid legacy id. Нормализовать его только когда есть
однозначное совпадение с exact frontmatter name, отметить data-quality issue
очереди и не создавать новых задач с alias.

Mode обязателен для многорежимных routes:

- `harness-context`: `bootstrap-minimal`, `bootstrap-full` или `refresh`;
- `harness-production-readiness`: `dependency`, `config`, `contract`, `adapter`,
  `process`, `db`, `observability`, `deploy`, `runbook` или `stand`;
- `harness-eval`: `golden`, `prototype-parity` или `live`.

`harness-golden` не имеет `skill_mode`. Legacy task
`use_skill=harness-eval, skill_mode=synthesize` до claim мигрировать отдельной
planning-правкой в `use_skill=harness-golden` без mode; не исполнять alias.

Если для такого `use_skill` поле `skill_mode` отсутствует, не входит в allowlist
или конфликтует с acceptance, остановить выполнение и вернуть задачу в
`harness-production-plan`/соответствующий planning pass. Не выводить mode из
title, notes, файлов или прежнего имени retired skill. Для остальных routes
лишний `skill_mode` тоже считать data-quality issue: mode должен иметь владельца.

Это критично для опромышленности: задачи с ported_from требуют точного
сохранения логики, а дефолтный `harness-work-session` к этому не обязывает.

**4. Создай ветку.**
Создай ветку только в формате `feature/{TICKET}` либо
`feature/{TICKET}-{short-description}`. `TICKET` — `task.ticket`, если он задан,
иначе `task.id`. Префиксы `agent/`, `codex/`, `fix/`, `hotfix/` и любые другие
запрещены даже для bug/fix-задач. Никогда не работай в защищённых ветках — что
является защищённой, описано в AGENTS.md, обычно `main`, `master`, `develop`,
`release/*`.

**5. Изучи код.**
Прочитай файлы из `task.files_hint`. Если их нет — найди релевантные через grep по `task.title` и `task.notes`. Не меняй ничего, пока не понимаешь область.

Если видишь модули, похожие на нужные, но AGENTS.md помечает их как deprecated или о них ничего не сказано — спроси пользователя что активно. Не угадывай.

До первой правки зафиксируй одну observable capability/foundation и её
verification boundary. Связанный каскад нескольких слоёв внутри этой capability
не дробить, но unrelated capability не добавлять. Сними минимальный baseline
уровня `task.verification_level`: `git diff/status`, применимый contract/golden и
точные counts. Не запускать `make verify` или build как универсальный baseline
для scoped/capability task. Pre-existing failure не чинить «заодно»; оформить
отдельный blocker/task.

Если golden/docs/real payload/код reference расходятся, перечисли версии и
provenance, назначь decision owner и останови затронутую boundary. Не выбирать
источник по удобству.

**6. Если нужны новые зависимости — проверь scope разрешения.**
Если exact dependency и затрагиваемые manifest/lock paths уже перечислены в
авторизованном applicability/capability plan или `task.approvals`, отдельное
подтверждение не требуется: это обычная safe offline реализация approved task.
Если package/version/major или paths выходят за этот scope, опиши изменение и
дождись подтверждения. Не расширяй dependency scope молча.

**7. Реализуй минимально.**
Следуй `task.acceptance` буквально. Не делай больше чем просят, не рефактори
соседнее «заодно». Если обнаружил баг по пути — зафиксируй его в отчёте/evidence,
не чини и не меняй очередь в этой ветке. После submit передай finding в отдельный
planning pass, который добавит `open` задачу в `discovered_bugs`.

Стиль кода, паттерны, naming, обработка ошибок — всё это в `docs/harness/conventions.md`. Следуй ему. Если конвенция не описана — спроси пользователя, не выдумывай свою.

**8. Запусти verify по `task.verification_level`.**

Использовать пирамиду и не повторять более тяжёлый уровень в каждой task:

- `scoped` — lint/import и тесты затронутого поведения;
- `capability` — scoped checks + полный тест observable capability contract;
- `runtime` — capability checks + настоящий production process/DI/lifespan
  smoke с разрешёнными protocol-faithful stubs;
- `bundle` — единственный владелец clean install, canonical full verify,
  build/package inventory и source/frozen process smoke.

Если `verification_level` отсутствует в legacy task, выбрать минимально
достаточный уровень по acceptance и зафиксировать data-quality finding; новый
план обязан задавать его явно. В одном `plan_id` clean build выполняет только
одна task уровня `bundle`; task другого уровня не повышать до bundle из
осторожности — вернуть несогласованную packaging acceptance планировщику.

Для dependency/lock на уровнях ниже bundle выполнить только необходимый
resolution/import compatibility check; общий clean install остаётся bundle
owner. Для migrations — source/dist heads inventory и разрешённая безопасная
проверка без shared-DB mutation; external boundary — sanitized contract/mock
check. Полный format debt отделять от touched files.

Зелёное evidence можно переиспользовать только при точном совпадении runtime
tree fingerprint, dependency/lock fingerprint, execution profile и
нормализованного списка команд. Branch, commit message или новая сессия не
являются ключом. Если хотя бы одно поле нельзя доказать, выполнить проверку.

**9. Если verify упал — record_attempt.**
Вызови `tasks-mcp.record_attempt(repo_path, task_id, command, exit_code, error_output)`. Если ответ `action: "continue"` — попробуй починить и запусти заново. Если ответ `action: "stop"` — это зацикливание, НЕ пытайся снова.

При `stop` вызови `tasks-mcp.report_blocker(repo_path, task_id, reason)` с описанием что повторяется. Сообщи пользователю что нужен человек, остановись.

**10. Harness pre-commit check.**
Подгрузи скилл `harness-pre-commit-check` и пройди его до конца. Если что-то не
прошло — исправь и пройди заново. Не коммить, пока
`harness-pre-commit-check` не зелёный.
Каждый changed path должен быть связан с acceptance. Несвязанные docs/harness,
migrations, Makefile, generated files или cleanup удалить из task diff либо
вынести в отдельную задачу.

**11. Коммит.**
Формат сообщения коммита возьми из `docs/harness/conventions.md` или из секции "Git" AGENTS.md. Не выдумывай свой формат. Сообщение в повелительном наклонении, отражает суть изменения.

**12. Submit.**
Получи `commit_sha` через `git rev-parse HEAD`. Имя ветки — то которое ты создал на шаге 4. Вызови:

```
tasks-mcp.submit_task(repo_path, task_id, evidence={
    "commit_sha": "<sha>",
    "tests_passed": true,
    "branch": "<branch_name>",
    "lint_passed": true,
    "notes": "<краткое резюме; verification level + tree/lock/profile/commands key>",
    "artifacts": ["<repo-relative canonical report, если он создан>"]
})
```

Если профильный skill создал canonical report/manifest, добавить его
repo-relative path в необязательный `evidence.artifacts`; для `harness-golden`
и `harness-eval` это обязательно.
`verification_level` и ключ переиспользования записывать в `evidence.notes` и
подтверждать указанным report, не придумывать новые поля Tasks MCP evidence.

Если acceptance задачи требует итогового решения о выпуске, submit допустим
только после зелёного release/stand report и ответа владельца. Решение
`APPROVE`/`DEFER`, имя или роль, дата, scope и путь к report записываются в
`evidence.notes` и `evidence.artifacts`; отдельное непредусмотренное поле MCP не
добавлять. Codex не выбирает решение сам.

Если MCP вернул `reject` — посмотри какие именно поля не прошли валидацию,
исправь и повтори. Если `ok` — задача логически переедет в `completed_sprint` в
merged MCP lifecycle state. При `out_of_band` raw `tasks.json` остаётся
versioned definition-файлом и не обязан менять category/status.
После submit `git status` по task branch должен оставаться чистым. Если появился
`docs/harness/tasks.json`, это runtime/configuration failure: не коммить второй
queue commit в feature branch, зафиксировать blocker владельцу tasks-mcp.

**13. Заверши task.**
В standalone-режиме кратко сообщить пользователю: какая задача закрыта, какие
файлы изменены, какой commit и ветка. В orchestrated `harness-productionize`
режиме после обычного успешного submit сразу вернуть control с compact machine
summary и перейти к следующей dependency-ready task: не создавать human
checkpoint, не ждать подтверждения commit/submit и не печатать промежуточный
handoff. Остановиться только при выходе за approved scope, material conflict,
live/shared-DB/deploy действии или действительно недостающем owner decision.

## Хард-лимиты

- НЕ работать в защищённых ветках (см. AGENTS.md — обычно main/master/develop/release/*) — только в собственной ветке задачи.
- НЕ создавать и не submit'ить ветку с префиксом, отличным от `feature/`.
- НЕ помечать задачу done без вызова `submit_task` с валидным evidence.
- НЕ добавлять зависимости вне exact approved plan/task scope без подтверждения;
  уже approved safe offline dependency change повторно не подтверждать.
- НЕ продолжать после `record_attempt → stop` — это зацикливание, нужен человек.
- НЕ менять CI/CD, миграции БД, файлы билда без исходной safe-offline
  authorization либо заранее записанного task approval с точным path/scope,
  owner и provenance. Миграционный side effect, shared DB и deploy execution
  всегда требуют отдельного текущего решения. `files_hint`/acceptance сами по
  себе не authorization.
- НЕ выдумывать конвенции — если их нет в `docs/harness/`, спроси пользователя.
- До правки снять scoped baseline внутри текущей задачи и не выдавать
  pre-existing failure за регрессию. Красный baseline блокирует задачу только
  если из-за него невозможно проверить её acceptance; иначе сохранить finding
  отдельно и продолжить в подтверждённом scope.
- НЕ смешивать несвязанные capabilities. Несколько технических слоёв одного
  capability-slice (prompts/schemas/helpers/interface/DI/tests) держать вместе;
  file/layer count не является причиной дробления.
- НЕ обновлять golden expected вслед за падением текущей задачи без отдельного
  approved behavior-change решения и provenance.
- НЕ выбирать задачу самостоятельно в standalone-режиме. В orchestrated режиме
  исполнять exact task_id, выбранный `harness-productionize`, без повторного
  list/show/select checkpoint.
- НЕ выполнять задачу с `use_skill` или `ported_from` обычным путём —
  переключиться на указанный (или `harness-prototype-port` по умолчанию) скилл.
  Дефолтный `harness-work-session` не гарантирует сохранение логики прототипа.
- НЕ исполнять многорежимный `use_skill` без допустимого `task.skill_mode` и не
  заменять его догадкой из title/notes; передавать поле профильному skill как есть.
- НЕ включать MCP lifecycle state из `docs/harness/tasks.json` в task commit;
  queue должна быть out-of-band или синхронизироваться MCP отдельным channel.

## Output

При успехе:
- Одна ветка с одним коммитом
- Задача в merged MCP state имеет category `completed_sprint`, status `done` и
  evidence; raw `tasks.json` меняется только в осознанном tracked mode
- Поле `attempts` хранится в lifecycle state (полезно для разбора потом)
- Краткий отчёт пользователю

При блокере:
- Задача в статусе `blocked` с `blocker.reason`
- Сообщение пользователю о необходимости вмешательства человека

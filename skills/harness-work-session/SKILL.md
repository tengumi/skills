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
Проверь `docs/harness/environment-doctor.md`: для первой задачи/нового execution
path нужен свежий task-ready `GO`. Нет doctor, он красный или его отчёт всё ещё
лежит незакоммиченным в task diff — сначала завершить отдельный preflight
handoff, не claim. Doctor report никогда не подмешивается в feature/port commit.
Doctor также должен подтвердить `queue_storage_mode`: claim/submit не имеют
права оставлять tracked `tasks.json` в working-tree diff задачи.

**2. Выбери задачу.**
Вызови `tasks-mcp.list_open_tasks(repo_path)`. Если задач нет — сообщи
пользователю и остановись. Если id указан — выбери exact definition и перейди к
pre-claim проверке 2.5. Если нет — покажи список и спроси, какую брать. Не
выбирай сам.

Если указанный id отсутствует среди `open`, вызвать `list_open_tasks(...,
include_all=true)` только для диагностики. `blocked`, `in_progress` или `done`
задачу не claim-ить повторно, даже если текущая реализация tasks-mcp технически
это допускает для `blocked`.

**2.5. Проверь route, mode и human gate ДО claim.**
Используй полную task definition, уже возвращённую `list_open_tasks`; не жди
ответа `claim_task`, чтобы впервые увидеть route. Примени allowlist из шага 3.5.
Для Stage-B routes до claim прочитай
`docs/harness/pre-industrialization-spec.md` и matching-секцию
`docs/harness/data-boundaries.md`, если она уже существует. Для parity/live
примени отдельные prerequisites ниже:

| Route/mode | Что должно быть подтверждено до claim |
|---|---|
| `harness-eval:prototype-parity` | актуальные prototype/target revisions, `prototype-contract.json` и возможность собрать sanitized/synthetic input manifest; live authority нужна только при внешнем вызове |
| `harness-production-readiness:contract` | найденная boundary зарегистрирована; задача ограничена получением contract facts или подготовкой design proposal |
| `harness-production-readiness:adapter` | matching-секция `data-boundaries.md` не ниже `MAPPED`: exact operation/revision/auth/mapping известны, material conflicts отсутствуют |
| остальные Stage-B readiness modes | подтверждённый план задачи и применимое разрешение для protected scope |
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
Имя ветки и формат бери из `docs/harness/conventions.md` или из секции "Boundaries" в AGENTS.md. По умолчанию — `agent/{TICKET}`. Никогда не работай в защищённых ветках — что является защищённой, описано в AGENTS.md, обычно `main`, `master`, `develop`, `release/*`.

**5. Изучи код.**
Прочитай файлы из `task.files_hint`. Если их нет — найди релевантные через grep по `task.title` и `task.notes`. Не меняй ничего, пока не понимаешь область.

Если видишь модули, похожие на нужные, но AGENTS.md помечает их как deprecated или о них ничего не сказано — спроси пользователя что активно. Не угадывай.

До первой правки классифицируй ровно один слой задачи: source/business contract,
config/dependency, bundle, DB/migrations, process/wiring, external boundary,
provider или deployment. Сними baseline: `git diff/status`, contract verifier,
`make verify`, применимый golden и точные counts. Pre-existing failure не чинить
«заодно»; оформить отдельный blocker/task.

Если golden/docs/real payload/код reference расходятся, перечисли версии и
provenance, назначь decision owner и останови затронутую boundary. Не выбирать
источник по удобству.

**6. Если нужны новые зависимости — спроси.**
Добавление пакетов в `pyproject.toml`/`requirements.txt`/`package.json` требует approval. Опиши пользователю что хочешь добавить и зачем, дождись подтверждения. Не ставь молча.

**7. Реализуй минимально.**
Следуй `task.acceptance` буквально. Не делай больше чем просят, не рефактори
соседнее «заодно». Если обнаружил баг по пути — зафиксируй его в отчёте/evidence,
не чини и не меняй очередь в этой ветке. После submit передай finding в отдельный
planning pass, который добавит `open` задачу в `discovered_bugs`.

Стиль кода, паттерны, naming, обработка ошибок — всё это в `docs/harness/conventions.md`. Следуй ему. Если конвенция не описана — спроси пользователя, не выдумывай свою.

**8. Запусти verify.**
Сначала scoped lint/tests затронутого, затем команда verify из AGENTS.md/Makefile.
Если изменены dependencies/lock — clean install + import smoke; entrypoints/
PyInstaller/resources — build + frozen process smoke; migrations — source/dist
heads inventory; external boundary — sanitized live/mock contract check. Полный
format debt отделять от форматирования touched files.

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
    "notes": "<краткое резюме>"
})
```

Если профильный skill создал canonical report/manifest, добавить его
repo-relative path в необязательный `evidence.artifacts`; для `harness-golden`
и `harness-eval` это обязательно.

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

**13. Финальный отчёт.**
Кратко пользователю: какая задача закрыта, какие файлы изменены, какой коммит, какая ветка. Напомни что merge в защищённую ветку делает человек, не агент.

## Хард-лимиты

- НЕ работать в защищённых ветках (см. AGENTS.md — обычно main/master/develop/release/*) — только в собственной ветке задачи.
- НЕ помечать задачу done без вызова `submit_task` с валидным evidence.
- НЕ добавлять зависимости без подтверждения пользователя.
- НЕ продолжать после `record_attempt → stop` — это зацикливание, нужен человек.
- НЕ менять CI/CD, миграции БД, файлы билда без явного approval пользователя
  в текущей сессии либо заранее записанного task approval с точным path/scope,
  owner и provenance. `files_hint`/acceptance сами по себе не approval.
- НЕ выдумывать конвенции — если их нет в `docs/harness/`, спроси пользователя.
- НЕ начинать с красным/неизвестным baseline и не выдавать pre-existing failure
  за регрессию текущей задачи.
- НЕ смешивать несколько runtime layers в одной правке; новый лог после фикса
  классифицировать как следующий слой.
- НЕ обновлять golden expected вслед за падением текущей задачи без отдельного
  approved behavior-change решения и provenance.
- НЕ выбирать задачу самостоятельно, если пользователь не указал какую.
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

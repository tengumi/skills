---
name: harness-productionize
description: "Оркестрирует полный prototype-to-production маршрут Harness по состоянию durable artifacts и останавливается на следующем human checkpoint. Используй когда пользователь просит начать, продолжить или возобновить опромышливание целиком, не заставляя его вручную выбирать specialist skills."
---

# harness-productionize

## Цель

Дать команде один публичный entrypoint. Этот skill не дублирует правила анализа,
порта или hardening: он определяет состояние прогона, вызывает следующий
specialist skill и останавливается на ближайшем человеческом решении.

Не использовать `harness-productionize` как `tasks.json.use_skill`. Задачи всегда
получают точный implementation route.

## Вход

Минимально нужны:

- `prototype` — read-only источник логики;
- `target` — целевой repository, развёрнутый из team template;
- `team_template` или явное подтверждение, что target уже создан из него.
- `target/docs/harness/pre-industrialization-spec.md`, созданный из kit
  template. Это короткий паспорт недостающих production-подключений: точные
  операции и versioned contracts, адреса/config keys, auth/secret references
  без значений, БД/хранилища и Jenkins/deploy-реквизиты. Наблюдаемые факты и
  детали доступных контрактов Codex извлекает сам.

Если исходный запрос прямо разрешает автоматические безопасные offline-правки
внутри target, сохранить его как `safe_offline_authorization` с provenance. Это
не отдельный технический параметр и не разрешение на live/shared DB/migration
side effect/deploy, но оно убирает повторные вопросы перед планами и локальными
задачами.

Если в target нет нормативных docs, дополнительно нужен точный `team_docs`
source. Его передать `harness-context` как `team_docs_source`; существующие
target files не перезаписывать.

Для этапов B/C дополнительно использовать явно названные `production_neighbour` и
`release_reference`, если они есть. Не выбирать их по сходству имён.

## Сначала определить состояние

Прочитать существующие target `AGENTS.md`, `docs/harness/` и git status. Если
`docs/harness/tasks.json` уже существует, вызвать
`tasks-mcp.list_open_tasks(repo_path, include_all=true)`; если его ещё нет,
сначала создать минимальный context и только затем обращаться к очереди. Raw
`tasks.json` содержит versioned definitions, но при out-of-band queue не является
полным lifecycle state. Не повторять завершённый этап только из-за отсутствия
слова в чате. Сопоставить durable evidence:

Сначала достаточно проверить, что prototype читается, target доступен и
официальный team template/source определён. Для prototype использовать
commit/tag, а если source не является Git-репозиторием — детерминированный hash
его значимых файлов без cache, outputs и runtime artifacts. Отсутствие Git HEAD
у prototype само по себе не является blocker.

| Состояние | Доказательство | Следующее действие |
|---|---|---|
| Context target неполон | нет repo `AGENTS.md` или обязательных team docs | `harness-context`, `bootstrap-minimal`, с exact `team_docs_source` при необходимости |
| Паспорт подключений отсутствует | нет `pre-industrialization-spec.md` | скопировать шаблон kit без перезаписи target; Stage A не блокировать, недостающие production-реквизиты запросить перед зависимым шагом B |
| Эталон не определён | prototype argument и evidence не дают commit/tag либо воспроизводимый content hash источника | запросить точный path/source; затем зафиксировать commit/tag или вычислить content hash, не угадывая источник |
| Prototype не описан | нет `prototype-analysis.md` | `harness-source-analysis` |
| Precheck отсутствует | нет `ds-precheck.md` | `harness-ds-precheck`; checkpoint только при П-находке или конфликте, иначе сразу план A |
| План A отсутствует | нет авторизованной port queue | `harness-context` bootstrap-minimal, затем `harness-prototype-plan`; обнаруженные identity/install/import gaps оформить обычными подготовительными задачами в этой же очереди |
| Port не завершён | есть open plan-A task | одна task через `harness-work-session` |
| Parity не доказан | нет green `docs/harness/evals/prototype-parity.md` для текущих hashes | `harness-eval`, `skill_mode=prototype-parity` |
| Production baseline отсутствует | нет `team-patterns-production.md` | `harness-extract-prod` |
| План B/C отсутствует/устарел | нет applicability matrix; версии паспорта/технической карты изменились; у B/C tasks нет общего `plan_id`/`stage`/`phase`/`verification_level`; либо применимый B plan не имеет ровно одного runtime и одного bundle owner | `harness-production-plan` |
| Следующая задача реализует внешнее подключение, но данные неполны | в `data-boundaries.md` нет точной операции/revision/auth/mapping либо есть material conflict | только contract-acquisition/design; implementation не claim-ить |
| Hardening не завершён | есть dependency-ready open Stage-B task с доказанными prerequisites | одна task через `harness-work-session` |
| Stage B code завершён, offline runtime не доказан | все обязательные implementation tasks done, но нет green real-app evidence для текущего HEAD | выполнить единственную `offline-runtime-lifecycle` task через `harness-production-readiness`, `skill_mode=process`; не использовать runtime mode в `harness-eval` |
| Offline runtime зелёный, bundle не доказан | real `create_app`/`app` + production DI/lifespan зелёные, но нет актуального clean install/build/inventory/artifact smoke | выполнить единственную Stage-B `runtime-bundle` task |
| Stage B завершён, Stage C не завершён | B code/runtime/bundle зелёные, но CI/deploy identity, isolated external state, live/stand, runbook или release decision ещё нужны | объявить Stage B complete; выполнить только dependency-ready Stage-C tasks, а при отсутствии входов оставить C deferred/blocked без возврата B в incomplete |
| Следующая задача вызывает стенд, но разрешения нет | нет отдельного текущего approval/policy/task evidence на exact environment/call/data/side effects | запросить разрешение непосредственно перед вызовом; остальные задачи не блокировать |
| Выпуск не доказан | нет clean release/stand evidence либо C3 owner decision | завершить plan-generated C2 stand/live tasks; затем выполнить C3 operations-handoff task и запросить итоговое решение |

Если evidence конфликтует, остановиться с таблицей конфликтов; не выбирать более
удобный статус.

## Оркестрация

1. Объявить найденную фазу, доказательство и ближайший checkpoint. Перед
   `source-analysis` проверить точную версию или content hash эталона; parity manifest и правило
   сравнения строит `harness-eval` из prototype contract, тестов и безопасных
   примеров. Перед adapter проверить паспорт и техническую карту
   `data-boundaries.md`; перед live-вызовом — отдельное текущее разрешение.
   Итог выпуска проверять в release task/evidence. Не требовать от человека
   повторно описывать факты, доступные в коде или документах.
2. Вызвать ровно один specialist workflow за раз. После каждого результата
   заново проверить durable state и автоматически выбрать следующий шаг, пока
   не достигнут human checkpoint, blocker или запрошенный конечный этап. При
   последовательном выполнении задач никогда не держать несколько claims
   одновременно; после каждого submit проверить clean handoff.
   Context, analysis, precheck и авторизованный план разрешено оформить одним
   подготовительным handoff до первой task. Не создавать отдельные commits или
   checkpoints только ради проверки окружения.
   Перед `harness-work-session` отфильтровать dependency-ready open tasks текущей
   фазы по structured `depends_on` и merged lifecycle Tasks MCP. Выбрать
   детерминированно по phase/order, priority и numeric id и передать exact
   `task_id`; не спрашивать человека между равно безопасными задачами. Запросить
   выбор только для взаимоисключающих архитектурных вариантов. Если готовых задач
   нет, сообщить blockers. Сам work-session не должен угадывать task.
   Передать вместе с task её exact `verification_level`; не повышать его до
   полного build по умолчанию.
   Для `harness-eval:prototype-parity` дополнительно применить динамический
   plan-gate из `harness-work-session`: все tasks того же `plan_id`/`stage: A`
   завершены, их commit SHA входят в текущий target HEAD, ambiguous untagged
   port-задач нет. Позиция task в массиве и первоначальный `depends_on` сами по
   себе readiness не доказывают.
3. Не расширять scope task. Новый слой, incident или неизвестный owner возвращать
   в соответствующий planner/delta-plan.
4. Перед каждым human checkpoint дать компактный decision packet: факты,
   варианты, последствия, рекомендуемый безопасный default и какие задачи
   разблокируются.
5. После решения записать только предусмотренный planning artifact и продолжить
   по просьбе пользователя.

Явное разрешение в исходном запросе на автоматический safe-offline прогон
распространяется на exact dependency/lock и protected-file изменения Stage B,
которые планировщик выводит из prototype, team template/docs и versioned contracts.
Authorization basis и итоговый exact scope записываются в plan artifact/tasks и
действуют при последующих claim без повторных вопросов. Если такого разрешения
не было, достаточно одного подтверждения applicability/capability plan. Выход
за scope, конфликт/новая boundary, live, shared DB/migration side effect и
deploy execution требуют нового решения непосредственно перед действием.

## Human checkpoints

Всегда остановиться до кода или следующей фазы, если нужно:

- принять class-П/behavior deviation или разрешить конфликт прототипа;
- спроектировать новую data boundary либо разрешить конфликт schema/versioning,
  auth или topology;
- разрешить dependency/protected CI, Docker или generated-file scope, только
  если exact safe offline изменение не входило в подтверждённый план;
- разрешить migration side effect, shared-DB или deploy execution;
- выбрать между конфликтующими team sources;
- санкционировать конкретный live-вызов, изменение общей БД, deploy или другой
  опасный side effect;
- подтвердить applicability matrix перед записью задач B/C, только если исходный
  запрос не разрешал автоматический safe-offline прогон.

Показ плана до записи, предусмотренный specialist skill, остаётся обязательным,
но при исходной safe-offline авторизации это информационный update, а не
checkpoint. Без такой авторизации план подтверждается один раз. Повторное
подтверждение каждой task запрещено.

Для внешней системы `docs/harness/pre-industrialization-spec.md` даёт нужную
операцию, официальный источник/revision, адрес или config key и способ
авторизации без значения секрета. `docs/harness/data-boundaries.md` Codex
заполняет схемами, ошибками, mapping и проверками. `НЕИЗВЕСТНО` не заменять
догадкой; оно блокирует только зависящее подключение.

## Stage B / C status contract

После каждого B/C handoff показывать независимые статусы:

- `Stage B code: COMPLETE | INCOMPLETE` — обязательные implementation
  capabilities завершены;
- `Stage B offline runtime: COMPLETE | NOT_GREEN | NOT_STARTED` — настоящий
  `create_app`/`app`, production DI/lifespan и применимые API/worker paths
  проверены network-free. Bare `FastAPI()`, fake provider/session или test-only
  DI не дают `COMPLETE`;
- `Stage B bundle: COMPLETE | NOT_APPLICABLE | NOT_GREEN | NOT_STARTED` — один
  актуальный clean install/build/inventory/artifact-process gate;
- `Stage B overall: COMPLETE | INCOMPLETE` — `COMPLETE`, когда code, offline
  runtime и применимый bundle зелёные. External release inputs не возвращают B
  в `INCOMPLETE`;
- `Stage C: NOT_STARTED | IN_PROGRESS | COMPLETE | DEFERRED | BLOCKED` —
  CI/deploy identity, isolated external-state checks, live/stand, operations
  handoff и release decision;
- `Release ready: YES | NO` — `YES` только после обязательных Stage-C gates и
  явного решения владельца. При deferred C писать: «Stage B complete; Stage C
  deferred; release ready: no».

Offline runtime — режим `harness-production-readiness:process`. Не создавать для
него новый `harness-eval` mode; `harness-eval:live` означает только реальные
разрешённые системы Stage C.

## Completion

Stage B завершён, когда code, real-app offline runtime и применимый bundle
зелёные. Полный прогон и release readiness завершены только когда:

- prototype contract и parity зелёные либо deviations явно одобрены;
- каждый production boundary имеет exact versioned contract и проверенный mapping;
- временный File IO отсутствует в production path либо осознанно сохранён;
- real-app offline runtime/lifecycle gate зелёный для production DI/lifespan и
  всех применимых API/worker paths;
- clean install, verify, build и все применимые source/artifact processes зелёные;
- authorized stand smoke подтверждает terminal states и side effects, если
  внешний gate применим;
- оставшиеся risks имеют owner и решение retain/defer.

Quality golden по внешнему стандарту не является обязательной частью parity.
При отдельном запросе создать датасет через `harness-golden`. Запуск агента и
метрики по released dataset — отдельная task через `harness-eval`,
`skill_mode=golden`.

## Hard limits

- Не заменять specialist skills пересказом их правил.
- Не создавать код или tasks напрямую, если это обязанность planner/executor.
- Не переходить из A в B без parity evidence.
- Не придумывать отсутствующие реквизиты подключения и не считать наличие
  файла разрешением на live-вызов или side effect.
- Не claim-ить adapter task без contract readiness, а live task — без отдельного
  текущего authorization, даже если tasks-mcp показывает задачу как `open`.
- Не запрашивать повторно safe offline dependency/protected authorization, уже
  записанную из исходного запроса или подтверждённого
  applicability/capability plan.
- Не объявлять выпуск завершённым без итогового решения владельца в release
  task/evidence.
- Не считать один `make verify` доказательством deploy/stand readiness.
- Не считать B завершённым по unit/contract evidence без real-app offline
  runtime/lifecycle и применимого bundle gate. Не возвращать B в incomplete
  из-за deferred/blocked Stage-C external gates.
- Не исполнять B/C task без `verification_level` и не создавать больше одного
  применимого Stage-B runtime/bundle owner в одном plan.
- Не скрывать blockers ради автоматического продолжения.
- Не использовать optional workspace/greenfield utilities без фактической нужды.

## Output

Сообщить текущую фазу, прочитанные evidence, выполненный specialist step,
ближайший checkpoint и точный безопасный запрос для продолжения.

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
- human-owned `target/docs/harness/pre-industrialization-spec.md`, созданный из
  kit template. Агент может заполнить наблюдаемые facts и подготовить proposal,
  но `APPROVED`/`VERIFIED` ставит только названный человек-владелец.

Если в target нет нормативных docs, дополнительно нужен точный `team_docs`
source. Его передать `harness-context` как `team_docs_source`; существующие
target files не перезаписывать.

Для этапа B дополнительно использовать явно названные `production_neighbour` и
`release_reference`, если они есть. Не выбирать их по сходству имён.

## Сначала определить состояние

Прочитать target `AGENTS.md`, `docs/harness/`,
`tasks-mcp.list_open_tasks(repo_path, include_all=true)` и git status. Raw
`tasks.json` содержит versioned definitions, но при out-of-band queue не является
полным lifecycle state. Не повторять завершённый этап только из-за отсутствия
слова в чате. Сопоставить durable evidence:

| Состояние | Доказательство | Следующее действие |
|---|---|---|
| Context target неполон | нет repo `AGENTS.md` или обязательных team docs | `harness-context`, `bootstrap-minimal`, с exact `team_docs_source` при необходимости; review и preflight handoff |
| Intake spec отсутствует | нет `pre-industrialization-spec.md` | скопировать kit template без перезаписи target; human checkpoint |
| Stage-A intake не утверждён | `stage_a_intake` не `APPROVED/VERIFIED` или разделы intake неполны | показать только недостающие human facts/owners; не начинать анализ или port |
| Target не готов | нет clean baseline/doctor GO | `harness-doctor` после template review/initial commit |
| Prototype не описан | нет `prototype-analysis.md` | `harness-source-analysis` |
| Precheck не решён | нет `ds-precheck.md` или human decisions | `harness-ds-precheck`, затем checkpoint |
| План A отсутствует | нет подтверждённой port queue | `harness-context` bootstrap-minimal, затем `harness-prototype-plan` |
| Port не завершён | есть open plan-A task | одна task через `harness-work-session` |
| Parity inputs не утверждены | `parity_inputs` не `APPROVED/VERIFIED` или scope fixtures/invariants не подтверждён | human data/parity checkpoint; не запускать parity eval |
| Parity не доказан | нет green `docs/harness/evals/prototype-parity.md` для текущих hashes | `harness-eval`, `skill_mode=prototype-parity` |
| Stage-B boundary plan не утверждён | `stage_b_plan` не `APPROVED/VERIFIED` либо boundary owner/mechanism остаются unresolved | human architecture checkpoint; заполнить spec и индекс `data-boundaries.md` |
| Production baseline отсутствует | нет `team-patterns-production.md` | `harness-extract-prod` |
| План B отсутствует/устарел | нет актуальной applicability matrix | `harness-production-plan` |
| Adapter task следующая, contract gate закрыт | `adapter_implementation` не `APPROVED/VERIFIED` или exact boundary card не покрывает task | только contract-acquisition/decision; implementation не claim-ить |
| Hardening не завершён | есть dependency-ready open plan-B task, разрешённая соответствующим spec gate | одна task через `harness-work-session` |
| Live task следующая, live gate закрыт | `live_validation` не `APPROVED/VERIFIED` или environment/data/action scope не покрывает вызов | human live-authorization checkpoint; не выполнять внешний вызов |
| Release не доказан | `release` не `APPROVED/VERIFIED` либо clean release/stand evidence не зелёные | human release inputs либо plan-generated release/stand task; при live — `harness-eval` mode live |

Если evidence конфликтует, остановиться с таблицей конфликтов; не выбирать более
удобный статус.

## Оркестрация

1. Объявить найденную фазу, доказательство и ближайший checkpoint.
   Перед `source-analysis`, parity, plan B, adapter implementation, live и
   release вручную прочитать соответствующий status, применимые разделы и human
   sign-off в spec. Убедиться, что в обязательных полях нет unresolved markers и
   scope approval точно покрывает действие; затем смыслово сверить contract с
   authoritative evidence. При несоответствии остановиться на human checkpoint.
2. Вызвать ровно один specialist workflow за раз. После каждого результата
   заново проверить durable state и автоматически выбрать следующий шаг, пока
   не достигнут human checkpoint, blocker или запрошенный конечный этап. При
   последовательном выполнении задач никогда не держать несколько claims
   одновременно; после каждого submit проверить clean handoff.
   Context/bootstrap и doctor artifacts оформить отдельным preflight handoff до
   первой feature/port task.
   Перед `harness-work-session` отфильтровать dependency-ready open tasks текущей
   фазы: если она одна, передать её exact `task_id`; если их несколько, показать
   короткий список и запросить выбор; если ни одной, сообщить blockers. Сам
   work-session не должен угадывать task.
3. Не расширять scope task. Новый слой, incident или неизвестный owner возвращать
   в соответствующий planner/delta-plan.
4. Перед каждым human checkpoint дать компактный decision packet: факты,
   варианты, последствия, рекомендуемый безопасный default и какие задачи
   разблокируются.
5. После решения записать только предусмотренный planning artifact и продолжить
   по просьбе пользователя.

## Human checkpoints

Всегда остановиться до кода или следующей фазы, если нужно:

- принять class-П/behavior deviation или разрешить конфликт прототипа;
- утвердить data boundary, owner, schema/versioning, auth или topology;
- разрешить dependency/protected CI, Docker, migration или generated-file scope;
- выбрать между конфликтующими team sources;
- санкционировать live external call, shared DB или опасный side effect;
- подтвердить applicability matrix перед записью задач B.
- сменить любой gate входной спеки на `APPROVED`/`VERIFIED`.

Показ плана до записи, предусмотренный specialist skill, остаётся обязательным.

Для data-boundary checkpoint человек утверждает точную карточку в human-owned
`docs/harness/pre-industrialization-spec.md`. Repo-owned
`docs/harness/data-boundaries.md` хранит короткий индекс: data flow, prototype
evidence, target mechanism, owner, status и ссылку на карточку/spec revision.
`OPEN` не заменять догадкой. Это planning artifacts, а не unrouted task этапа A.

## Completion

Прогон завершён только когда:

- prototype contract и parity зелёные либо deviations явно одобрены;
- каждый production boundary имеет owner, approved contract и проверенный mapping;
- временный File IO отсутствует в production path либо осознанно сохранён;
- clean install, verify, build и все применимые source/artifact processes зелёные;
- authorized stand smoke подтверждает terminal states и side effects;
- оставшиеся risks имеют owner и решение retain/defer.

Quality golden по внешнему стандарту не является обязательной частью parity.
При отдельном запросе создать датасет через `harness-golden`. Запуск агента и
метрики по released dataset — отдельная task через `harness-eval`,
`skill_mode=golden`.

## Hard limits

- Не заменять specialist skills пересказом их правил.
- Не создавать код или tasks напрямую, если это обязанность planner/executor.
- Не переходить из A в B без parity evidence.
- Не редактировать human sign-off от имени владельца и не считать наличие файла
  разрешением: проверять нужный gate перед соответствующим действием.
- Не claim-ить adapter/live/release task при закрытом gate, даже если tasks-mcp
  показывает задачу как `open`: queue пока не обеспечивает эти prerequisites
  машинно.
- Не считать один `make verify` доказательством deploy/stand readiness.
- Не скрывать blockers ради автоматического продолжения.
- Не использовать optional workspace/greenfield utilities без фактической нужды.

## Output

Сообщить текущую фазу, прочитанные evidence, выполненный specialist step,
ближайший checkpoint и точный безопасный запрос для продолжения.

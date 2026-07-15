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
| Паспорт подключений отсутствует | нет `pre-industrialization-spec.md` | скопировать шаблон kit без перезаписи target; Stage A не блокировать, недостающие production-реквизиты запросить перед зависимым шагом B |
| Эталон не определён | prototype argument и git evidence не дают точную версию источника | запросить точный path/repository + commit/tag; не анализировать неоднозначный источник |
| Target не готов | нет clean baseline/doctor GO | `harness-doctor` после template review/initial commit |
| Prototype не описан | нет `prototype-analysis.md` | `harness-source-analysis` |
| Precheck не решён | нет `ds-precheck.md` или human decisions | `harness-ds-precheck`, затем checkpoint |
| План A отсутствует | нет подтверждённой port queue | `harness-context` bootstrap-minimal, затем `harness-prototype-plan` |
| Port не завершён | есть open plan-A task | одна task через `harness-work-session` |
| Parity не доказан | нет green `docs/harness/evals/prototype-parity.md` для текущих hashes | `harness-eval`, `skill_mode=prototype-parity` |
| Production baseline отсутствует | нет `team-patterns-production.md` | `harness-extract-prod` |
| План B отсутствует/устарел | нет applicability matrix либо зафиксированные в ней версии паспорта подключений/технической карты уже изменились | `harness-production-plan` |
| Следующая задача реализует внешнее подключение, но данные неполны | в `data-boundaries.md` нет точной операции/revision/auth/mapping либо есть material conflict | только contract-acquisition/design; implementation не claim-ить |
| Hardening не завершён | есть dependency-ready open plan-B task с доказанными prerequisites | одна task через `harness-work-session` |
| Следующая задача вызывает стенд, но разрешения нет | нет отдельного текущего approval/policy/task evidence на exact environment/call/data/side effects | запросить разрешение непосредственно перед вызовом; остальные задачи не блокировать |
| Выпуск не доказан | нет clean release/stand evidence или итогового решения владельца в release task/evidence | выполнить plan-generated release/stand task; при live — `harness-eval` mode live; затем запросить итоговое решение |

Если evidence конфликтует, остановиться с таблицей конфликтов; не выбирать более
удобный статус.

## Оркестрация

1. Объявить найденную фазу, доказательство и ближайший checkpoint. Перед
   `source-analysis` проверить точную версию эталона; parity manifest и правило
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
- спроектировать новую data boundary либо разрешить конфликт schema/versioning,
  auth или topology;
- разрешить dependency/protected CI, Docker, migration или generated-file scope;
- выбрать между конфликтующими team sources;
- санкционировать конкретный live-вызов, изменение общей БД, deploy или другой
  опасный side effect;
- подтвердить applicability matrix перед записью задач B.

Показ плана до записи, предусмотренный specialist skill, остаётся обязательным.

Для внешней системы `docs/harness/pre-industrialization-spec.md` даёт нужную
операцию, официальный источник/revision, адрес или config key и способ
авторизации без значения секрета. `docs/harness/data-boundaries.md` Codex
заполняет схемами, ошибками, mapping и проверками. `НЕИЗВЕСТНО` не заменять
догадкой; оно блокирует только зависящее подключение.

## Completion

Прогон завершён только когда:

- prototype contract и parity зелёные либо deviations явно одобрены;
- каждый production boundary имеет exact versioned contract и проверенный mapping;
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
- Не придумывать отсутствующие реквизиты подключения и не считать наличие
  файла разрешением на live-вызов или side effect.
- Не claim-ить adapter task без contract readiness, а live task — без отдельного
  текущего authorization, даже если tasks-mcp показывает задачу как `open`.
- Не объявлять выпуск завершённым без итогового решения владельца в release
  task/evidence.
- Не считать один `make verify` доказательством deploy/stand readiness.
- Не скрывать blockers ради автоматического продолжения.
- Не использовать optional workspace/greenfield utilities без фактической нужды.

## Output

Сообщить текущую фазу, прочитанные evidence, выполненный specialist step,
ближайший checkpoint и точный безопасный запрос для продолжения.

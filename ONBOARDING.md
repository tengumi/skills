# Опромышливание с Harness — первый запуск

Harness помогает перенести прототип AI-агента в production и не потерять его
поведение по дороге. Для первого прогона не нужно выбирать один из 20 skills:
начните с `harness-productionize`, а он приведёт к следующему проверяемому
этапу и остановится там, где требуется решение человека.

## Главная идея

Работа разделена на две фазы:

1. **Сохранить бизнес-логику прототипа.** Входы, результаты, prompts, схемы,
   порядок шагов, параметры LLM, retries, ошибки и terminal states не меняются
   незаметно.
2. **Заменить прототипную оболочку production-механизмами.** Добавляются только
   утверждённые data boundaries, процессы, конфигурация, наблюдаемость, сборка и
   deploy.

В прототипе часто нет endpoint, protocol, очереди или БД: он просто читает и
пишет файлы. Это нормально и не блокирует перенос логики. Новый API, MCP tool,
queue, DB или object storage нельзя «угадать» по файлам — механизм, owner,
schema, auth и error semantics проектируются и утверждаются отдельно.

Коротко:

```text
файл в прототипе ──сохраняем смысл данных──> утверждённая production boundary
                  не копируем transport       API / tool / queue / DB / storage
```

## Что нужно до старта

- read-only prototype;
- target, развёрнутый из официального team template;
- вручную скопированный в target `docs/harness/pre-industrialization-spec.md` из
  [шаблона kit](PRE-INDUSTRIALIZATION-SPEC.md) и заполненный минимум до gate
  `stage_a_intake`; существующий target-файл не перезаписывать;
- подключённые Harness skills и `tasks-mcp`;
- team docs в target `docs/harness/`: обычно их даёт template; если нет,
  после review вручную скопировать только отсутствующие файлы из kit и не
  перезаписывать target;
- clean baseline target и человек, который может утвердить data/deploy решения;
- `harness-watcher` — только если локальный runtime недоступен или его требует
  политика окружения.

`tasks-mcp` должен сообщать `queue_storage_mode=out_of_band`. Режим `tracked`
допустим только при отдельном coordination channel: claim/submit не должны
оставлять `tasks.json` в feature-diff.

Не нужно до старта изобретать endpoint для file-only prototype. В спеках
prototype-поля endpoint/auth будут `N/A`; отдельно заполняется будущая target
boundary. До Stage A достаточно утвердить intake и parity inputs. Точные
request/response/error/auth обязательны до реализации production adapter, а
доступ к stand и side effects — только до live-проверки.

## Самый простой запуск

Из рабочей области, где доступны prototype и target, попросите:

> Используй `$harness-productionize`: prototype=`<path>`, target=`<path>`,
> team_template=`<path>`, team_docs=`<harness-kit/team-docs>` если target их не
> содержит. Дойди до ближайшего human checkpoint.

После каждого checkpoint подтвердите решение и попросите продолжить. Skill
смотрит на файлы и очередь, поэтому после паузы не начинает процесс заново.

## Что произойдёт по шагам

### 0. Входная спека и человеческие полномочия

До первого запуска вручную скопируйте шаблон в
`docs/harness/pre-industrialization-spec.md`, если файла ещё нет. Человек
указывает источники истины, owners, data policy и доступ к prototype. Перед
каждым следующим этапом он заполняет применимые разделы и утверждает нужный
status. Агент может собрать факты и предложить формулировки, но не ставит
`APPROVED`/`VERIFIED` от имени владельца.

| Этап | Обязательный gate |
|---|---|
| Начало анализа и переноса | `stage_a_intake` |
| Prototype parity | `parity_inputs` |
| План этапа B | `stage_b_plan` |
| Реализация adapter | `adapter_implementation` |
| Внешняя live-проверка | `live_validation` |
| Выпуск | `release` |

Перед продолжением вручную убедитесь, что нужный status и все применимые
prerequisites имеют `APPROVED`/`VERIFIED`, указаны approver/date/evidence, в
обязательных разделах нет неразрешённых placeholders, `TODO`, `TBD`, `UNKNOWN`
и запрещённых для этапа `OPEN`, а scope решения точно покрывает действие. Если
нет — Harness останавливается на human checkpoint. Формальный status не
заменяет смысловую проверку authoritative contract человеком.

### 1. Preflight target

`harness-doctor` проверит checkout, clean baseline, install/import/verify,
tasks-mcp и применимый execution path. До результата `GO` port-задачи не
начинаются.

Если в team template нет repo `AGENTS.md`, оркестратор сначала вызовет
`harness-context` в режиме `bootstrap-minimal`. Карту нужно просмотреть и
оформить отдельным preflight commit, затем запускать doctor.

Результат: `docs/harness/environment-doctor.md`.

### 2. Анализ prototype

`harness-source-analysis` зафиксирует реальное поведение, включая File IO и
фактически существующие интеграции. Несуществующие endpoints и protocols он не
выдумывает. `harness-ds-precheck` отдельно разложит замечания на:

- изменение формы — можно планировать без изменения смысла;
- изменение поведения — нужен human checkpoint;
- оптимизацию — не подмешивать в parity port.

Результаты: `prototype-analysis.md` и `ds-precheck.md`.

### 3. План этапа A

`harness-context` создаст минимальную карту target, а
`harness-prototype-plan` покажет тонкий план до записи. Первая port-задача
фиксирует `prototype-contract.json`; следующие переносят по одному слою в слоты
team template.

Новый production adapter не прячется внутри обычной port-задачи. Для parity
можно временно сохранить file-backed или in-memory boundary.

### 4. Перенос и parity

`harness-work-session` берёт одну задачу, вызывает её точный `use_skill`,
проверяет scope и завершает её через evidence. Несколько задач одновременно не
claim-ятся.

После этапа A `harness-eval` с `skill_mode=prototype-parity` сравнит prototype и
target на одинаковых логических входах. Одинаковый transport не требуется;
обязательные поля, ошибки и terminal states должны сохраниться.

Канонический отчёт: `docs/harness/evals/prototype-parity.md`. Именно его hashes,
threshold и статус использует оркестратор при возобновлении прогона.

Зелёный parity доказывает сохранение логики, но ещё не production readiness.

### 5. Решение о production boundary

До замены File IO или другого временного adapter human checkpoint фиксирует
точный contract в `docs/harness/pre-industrialization-spec.md`, а
`docs/harness/data-boundaries.md` остаётся коротким индексом решений и ссылок на
карточки boundary. Нужно определить:

- owner и source of truth;
- механизм: API, tool, queue, DB, storage или другой;
- schema/versioning, auth и mapping;
- ordering, idempotency, errors, retries и timeouts;
- способ contract и live проверки.

Если интеграция существует, но contract недоступен, Stage B создаёт только
contract-acquisition task с owner; adapter блокируется до заполненной карточки
и `adapter_implementation=APPROVED`. Если интеграции ещё нет, checkpoint сначала
утверждает mechanism/owner — на `stage_b_plan=APPROVED` они уже не могут быть
`OPEN`; после этого production plan создаёт contract/design
и implementation tasks. Port queue этапа A таких задач не содержит. Сам анализ
и parity уже могут быть завершены.

### 6. План и выполнение этапа B

`harness-extract-prod` раздельно читает team template и, если предоставлены,
явно выбранные production neighbour и release reference. Затем
`harness-production-plan` строит
applicability matrix для dependencies, boundaries, processes, DB, config,
observability, bundles, CI/deploy, governance, stand и runbook.

Для каждого слоя ставится один статус: `required`, `already_satisfied`,
`not_applicable` или `blocked`. Универсальный список `T-101…T-120` не копируется;
создаются только доказанно нужные задачи с динамическими ID, resolved paths,
`use_skill` и `skill_mode`.

`harness-work-session` выполняет задачи по одной. Production-срезы идут через
`harness-production-readiness`; deploy — его режим `deploy`, а разрешённая live
проверка — `harness-eval` с `skill_mode=live`.

### 7. Clean release и stand

Финальная проверка подтверждает clean install, verify, build, все применимые
entrypoints, boundary mapping и безопасный stand smoke. Success-log процесса не
считается доказательством business success: проверяются результаты, terminal
states и разрешённые side effects.

## Когда Harness остановится

Решение человека обязательно, если:

- предлагается изменить наблюдаемое поведение prototype;
- не утверждены boundary, owner, schema/auth или process topology;
- team sources противоречат друг другу;
- требуется protected CI/Docker/migration/dependency scope;
- нужен live вызов, shared DB или опасный side effect.

Остановка — часть процесса, а не ошибка. После решения оно записывается в
planning artifact, и оркестратор продолжает со следующего состояния.

## Когда работа закончена

- contract и parity зелёные либо отклонение явно одобрено;
- human-owned spec имеет соответствующие `APPROVED`/`VERIFIED` gates;
- каждая production boundary имеет owner, contract и проверенный mapping;
- временный File IO не остался в production path без явного решения;
- clean install, verify, build и применимые процессы зелёные;
- authorized stand smoke подтверждает terminal states и side effects;
- оставшиеся риски имеют owner и решение `retain` или `defer`.

Quality golden по внешнему стандарту — отдельная необязательная задача:
`harness-golden` создаёт released dataset; следующая отдельная задача
`harness-eval`, `skill_mode=golden` измеряет agent по нему. Это не заменяет
prototype parity и не является обязательным gate опромышливания.

## Где читать детали

| Нужно | Skill |
|---|---|
| Вести весь прогон | [harness-productionize](skills/harness-productionize/SKILL.md) |
| Заполнить входные решения и contracts | [PRE-INDUSTRIALIZATION-SPEC.md](PRE-INDUSTRIALIZATION-SPEC.md) |
| Проверить окружение | [harness-doctor](skills/harness-doctor/SKILL.md) |
| Разобрать prototype | [harness-source-analysis](skills/harness-source-analysis/SKILL.md) |
| Построить планы A/B | [harness-prototype-plan](skills/harness-prototype-plan/SKILL.md), [harness-production-plan](skills/harness-production-plan/SKILL.md) |
| Выполнить одну задачу | [harness-work-session](skills/harness-work-session/SKILL.md) |
| Создать oracle-verified golden dataset | [harness-golden](skills/harness-golden/SKILL.md) |
| Проверить released golden/parity/live | [harness-eval](skills/harness-eval/SKILL.md) |
| Выполнить production slice | [harness-production-readiness](skills/harness-production-readiness/SKILL.md) |

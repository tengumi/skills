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
  [шаблона kit](PRE-INDUSTRIALIZATION-SPEC.md); для этапа A достаточно точной
  версии эталонного прототипа. До зависимого шага B добавьте недостающие ссылки
  на контракты, операции, БД и deploy-реквизиты. Существующий target-файл не
  перезаписывать;
- `templates/data-boundaries.md`, скопированный как
  `docs/harness/data-boundaries.md`, если team template его не создал. Человек
  его не заполняет;
- подключённые Harness skills и `tasks-mcp`;
- team docs в target `docs/harness/`: обычно их даёт template; если нет,
  после review вручную скопировать только отсутствующие файлы из kit и не
  перезаписывать target;
- clean baseline target и человек, который может дать недостающие ссылки,
  идентификаторы или решение по новой интеграции;
- `harness-watcher` — только если локальный runtime недоступен или его требует
  политика окружения.

`tasks-mcp` должен сообщать `queue_storage_mode=out_of_band`. Режим `tracked`
допустим только при отдельном coordination channel: claim/submit не должны
оставлять `tasks.json` в feature-diff.

Не нужно до старта описывать назначение агента, переписывать его входы, тексты
запросов к модели, параметры модели или дублировать OpenAPI/Jenkinsfile. Всё
наблюдаемое Codex извлечёт сам. Человек даёт точную ссылку и нужную операцию, а
если формального контракта нет — только минимальные сведения, без которых
подключение невозможно реализовать.

## Самый простой запуск

Из рабочей области, где доступны prototype и target, попросите:

> Используй `$harness-productionize`: prototype=`<path>`, target=`<path>`,
> team_template=`<path>`, team_docs=`<harness-kit/team-docs>` если target их не
> содержит. Дойди до ближайшего human checkpoint.

После каждого checkpoint подтвердите решение и попросите продолжить. Skill
смотрит на файлы и очередь, поэтому после паузы не начинает процесс заново.

## Что произойдёт по шагам

### 0. Паспорт подключений

До первого запуска вручную скопируйте шаблон в
`docs/harness/pre-industrialization-spec.md`, если файла ещё нет. Это не анкета
согласований, а короткий технический паспорт того, чего нет в прототипе и team
docs:

- точная версия эталонного прототипа;
- интерфейсы нового сервиса и нужные endpoints/tools/topics;
- вызываемые внешние системы и ссылки на versioned contracts;
- БД, хранилища и ссылки на DDL/migrations;
- Jenkins, стенд и deploy-идентификаторы, если они не заданы template;
- config/credential/secret references без значений секретов.

Если официальное описание полное, достаточно ссылки, версии и нужной операции:
тела запросов, ошибки и поля Codex извлечёт сам. Неизвестное помечается
`НЕИЗВЕСТНО` и блокирует только зависящее подключение; анализ и перенос
внутренней логики продолжаются.

Codex записывает найденные факты и mapping в
`docs/harness/data-boundaries.md`, не дописывая догадки во входную spec.
Разрешение на live-вызов, запись в общую БД, миграцию или deploy запрашивается
отдельно непосредственно перед действием и сохраняется в task/evidence.

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

Harness сам собирает безопасный input manifest из тестов, примеров и
`prototype-contract.json`. Детерминированные поля сравниваются точно; для LLM
отдельно фиксируются обязательные поля, статусы и variance. Применённое правило
записывается в отчёт. Человек подключается только если сравнение невозможно без
защищённых данных или реального внешнего вызова.

Канонический отчёт: `docs/harness/evals/prototype-parity.md`. Именно его hashes,
threshold и статус использует оркестратор при возобновлении прогона.

Зелёный parity доказывает сохранение логики, но ещё не production readiness.

### 5. Подготовка production boundary

После анализа Codex сопоставляет найденные потоки с паспортом подключений. Для
готовой интеграции человеку достаточно указать официальный versioned contract и
нужную операцию. Codex сам извлекает точные схемы, ошибки, авторизацию и строит
mapping в `docs/harness/data-boundaries.md`; OpenAPI или тела запросов вручную
переписывать не нужно.

Adapter готов к реализации, когда известны точная операция, версия контракта,
способ авторизации, mapping и отсутствуют существенные противоречия источников.
Это определяется по технической карте и evidence, а не по ручному статусу в
анкете.

Если официального описания нет или проектируется новая boundary, Stage B
создаёт ограниченную задачу на получение контракта или инженерное решение.
Блокируется только зависимое подключение; анализ, перенос внутренней логики и
остальные production-срезы продолжаются.

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
- отсутствуют существенные сведения о boundary, schema/auth или process topology;
- team sources противоречат друг другу;
- требуется protected CI/Docker/migration/dependency scope;
- нужен live вызов, shared DB или опасный side effect.

Остановка — часть процесса, а не ошибка. После решения оно записывается в
planning artifact, и оркестратор продолжает со следующего состояния.

## Когда работа закончена

- contract и parity зелёные либо отклонение явно одобрено;
- необходимые человеческие решения и разрешения подтверждены;
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
| Заполнить паспорт подключений | [PRE-INDUSTRIALIZATION-SPEC.md](PRE-INDUSTRIALIZATION-SPEC.md) |
| Проверить окружение | [harness-doctor](skills/harness-doctor/SKILL.md) |
| Разобрать prototype | [harness-source-analysis](skills/harness-source-analysis/SKILL.md) |
| Построить планы A/B | [harness-prototype-plan](skills/harness-prototype-plan/SKILL.md), [harness-production-plan](skills/harness-production-plan/SKILL.md) |
| Выполнить одну задачу | [harness-work-session](skills/harness-work-session/SKILL.md) |
| Создать oracle-verified golden dataset | [harness-golden](skills/harness-golden/SKILL.md) |
| Проверить released golden/parity/live | [harness-eval](skills/harness-eval/SKILL.md) |
| Выполнить production slice | [harness-production-readiness](skills/harness-production-readiness/SKILL.md) |

# Режим `live`

## Назначение

Проверить реальный approved production boundary или process через LLM, RAG, DB,
API, MCP tool, очередь либо другой внешний runtime и доказать business outcome,
а не только успешный framework call.

## Preconditions

- Прочитать human-owned `docs/harness/pre-industrialization-spec.md` и вручную
  убедиться, что `live_validation=APPROVED/VERIFIED`, human sign-off содержит
  approver/date/evidence, а environment/data/call/side-effect scope точно
  покрывает этот прогон.
- Получить explicit live flag или approval на secure stage, data scope и side
  effects. Watcher/direct transport не заменяет это разрешение.
- Назвать approved source/provider, boundary classification, owner, exact
  route/tool/topic/schema и external prerequisites, если они применимы.
- Выбрать sanitized/near-real inputs и правила хранения reports.
- Подтвердить process topology и безопасный DB/migration mode до startup.

Не угадывать placeholder path. Сначала найти documented data; если их нет,
записать assumption/blocker в report.

Если frontmatter одобрен, но карточка boundary или authorization section не
покрывает фактический вызов, gate считать закрытым и остановиться. Агент не
расширяет approval и не меняет его статус от имени владельца.

## Workflow

1. Зафиксировать redacted effective config в том же режиме исполнения, который
   проверяется: API, worker, scheduler, source, frozen artifact или image.
2. Запустить точный entrypoint и доказать цепочку
   `entrypoint → registry/task/node → DI/service → approved boundary → terminal
   state → publish/side effect`.
3. Записать provider/source, route/tool/topic, sanitized headers/payload shape,
   status, prerequisites и side-effect result. Framework success-log без
   terminal/publish evidence считать недостаточным.
4. Для structured LLM output зафиксировать provider path, model,
   `response_format`, непустые schema/name и sanitized outgoing payload.
5. Проверить expected invariants: required fields, error remains error, publish
   происходит только при approved success, ordering/idempotency/retry/timeout и
   boundary mapping соблюдены.
6. Выполнить repeatability для нестабильных LLM/external paths и отделить
   variance от deterministic defect.
7. Сохранить только sanitized artifacts и report в
   `docs/harness/evals/live/<task-id-or-request-id>.md`; path добавить в task
   evidence. Raw documents, RAG logs, LLM dumps, responses с PII, credentials,
   certs и `.env` не коммитить.

## Gating и предел доказательства

Live eval никогда не входит в default unit CI. Failure внешнего prerequisite не
маскировать как code defect или success: зафиксировать состояние и owner.
Mock/static test не заменяет фактическое process registration, artifact/image
startup или boundary proof.

При destructive или migration-capable side effect использовать только
isolated/confirmed-owned target либо доказанный read-only/migration-disabled
режим. При отсутствии ownership/authorization остановиться до запуска.

## Дополнение к общему report

Включить:

- approval/live flag и secure-stage identity;
- exact execution mode и redacted effective config;
- source/provider/boundary, route/tool/topic, status и prerequisite state;
- process-chain evidence до terminal/publish outcome;
- expected versus actual side effects;
- repeatability results и безопасные artifact locations.

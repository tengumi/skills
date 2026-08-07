---
name: harness-eval
description: "Запускает проверяемый агент или target на уже определённом oracle и выполняет три вида оценки: released golden dataset, prototype-parity либо live production boundary/process. Считает task-specific metrics, repeatability и discrepancies, сохраняет sanitized reports; используй с одним явным skill_mode: golden, prototype-parity или live. Не используй для генерации новых golden cases — это harness-golden."
---

# harness-eval

## Контракт режима

До чтения данных или запуска команд потребовать ровно один `skill_mode`:

| `skill_mode` | Источник истины и результат | Обязательная инструкция |
|---|---|---|
| `golden` | Released golden dataset → метрики agent under test | [references/golden.md](references/golden.md) |
| `prototype-parity` | Наблюдаемое поведение prototype → parity target | [references/prototype-parity.md](references/prototype-parity.md) |
| `live` | Approved real boundary/process → business/runtime proof | [references/live.md](references/live.md) |

Если mode отсутствует, невалиден или смешивает цели — **STOP**. Прочитать
выбранную инструкцию полностью. Не выполнять другие modes в той же task.

Legacy `skill_mode=synthesize` не исполнять: перед claim мигрировать task на
`use_skill=harness-golden` без `skill_mode` отдельной planning-правкой.

## Общий вход

Перед выполнением:

1. Прочитать `AGENTS.md`, task, применимые team docs и существующие
   `docs/harness/evals/`/`tests/integration` artifacts.
2. Записать один проверяемый `eval_question`, класс inputs, source of truth,
   expected invariants, metric/equivalence rule и threshold.
3. Зафиксировать revisions/hashes агента, dataset/contract и runtime config.
4. Классифицировать PII/confidential data, sanitization, storage и side effects.
5. Зафиксировать execution environment. Использовать `harness-request-exec`
   только при watcher policy или недоступном direct runtime.

Watcher — transport, не authorization. Любая сеть, LLM, RAG, DB, API, queue или
иной side effect требует explicit approval/approved secure stage. Released
golden dataset сам по себе такого разрешения не даёт.

## Общие gates

- Быстрый deterministic shape/schema/contract test без сети и judge может быть
  в default `make verify`.
- Полный golden/LLM/live eval запускать gated-командой; live не включать в
  default CI.
- Для deterministic logic требовать exact/field-level equality либо explicit
  equivalence rule.
- Для LLM сочетать required fields/status/error, semantic signal и repeatability.
- Semantic similarity не может скрывать пропущенные обязательные поля.
- Один LLM run не доказывает regression; измерять variance отдельно.
- Mock/static golden не доказывает install/build/registration/frozen resources,
  production boundary или process wiring.
- Network-free запуск real `create_app`/`app` с production DI/lifespan и
  protocol-faithful transport stub выполняет
  `harness-production-readiness:process`, а не новый eval mode.
- `skill_mode=live` использует реальную отдельно разрешённую внешнюю систему;
  local protocol stub является только offline preflight. В полном
  productionize-маршруте live task относится к Stage C и не меняет уже зелёный
  статус offline Stage B.
- Threshold брать из task/spec; не применять универсальный процент.

## Report contract

Сохранить sanitized report:

| `skill_mode` | Канонический path |
|---|---|
| `golden` | `docs/harness/evals/golden/<task-id-or-run-id>.md` |
| `prototype-parity` | `docs/harness/evals/prototype-parity.md` |
| `live` | `docs/harness/evals/live/<task-id-or-request-id>.md` |

Machine-readable sidecar с тем же basename и `.json` допустим. При task-run
добавить artifacts в submit evidence. Report актуален только для записанных
revisions и dataset/contract/prompt/schema/config hashes.

В report включить:

- mode, question, input manifest и source of truth;
- command/request id, execution mode и sanitized environment assumptions;
- revisions/hashes;
- metric, threshold/equivalence rule, expected/actual и result;
- discrepancies, repeatability/variance и excluded/quarantined cases;
- sanitization/data policy, limitations и unresolved assumptions;
- recommendation `close | investigate | rerun`.

Для prototype/live дополнительно записать prototype root/hash либо exact
boundary/process evidence. Не коммитить raw documents, raw RAG/LLM dumps,
credentials, certificates, `.env`, PII или confidential outputs.

## Hard limits

- Не генерировать и не переписывать golden expected outputs; это отдельный
  `harness-golden` run и human/release decision.
- Не выдумывать paths, contracts, owners или environment status.
- Не смешивать golden, parity и live side effects в одной task.
- Не принимать protocol stub или fake provider/DI за `live` evidence.
- Не считать framework success-log business success.
- Не закрывать result ниже task threshold.
- Брать domain facts/correctness только из task/spec/sources.

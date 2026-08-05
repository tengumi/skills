# Режим `prototype-parity`

## Назначение

Доказать, что target сохраняет наблюдаемое поведение прототипа на одинаковых
логических входах. Transport может различаться только после отдельного approved
boundary change; смысл входа, результата, ошибок, terminal states и side effects
остаётся сравнимым.

## Preconditions

- Назвать prototype root/commit и target revision.
- Проверить dynamic Stage-A plan gate: все задачи того же `plan_id` завершены,
  а их `evidence.commit_sha` являются предками проверяемой target revision.
- Иметь `prototype-contract.json` либо эквивалентный зафиксированный контракт.
- Зафиксировать prompt, schema и runtime-config hashes без secret values.
- Собрать sanitized input manifest из существующих тестов, примеров и
  `prototype-contract.json`; если безопасных примеров нет, создать минимальные
  synthetic fixtures, сохраняющие схемы и важные края.
- Зафиксировать правило сравнения в отчёте: deterministic fields — exact;
  schemas, errors и terminal states — обязательное совпадение; для LLM —
  несколько повторов, required fields и variance обеих сторон.
- Если прогоны вызывают реальные внешние systems, получить live authorization;
  само имя этого режима его не даёт.

## Workflow

1. Сформировать manifest одинаковых логических inputs и объяснить допустимое
   transport mapping.
2. Снять baseline каждой системы отдельно: status/error, required schema fields,
   terminal state, side effects и publish condition.
3. Запустить prototype и target в сопоставимом environment. Для structured
   output зафиксировать provider path, model, `response_format`, непустые
   schema/name и sanitized outgoing payload; инструкция «верни JSON» не
   является гарантией structured output.
4. Сравнить exact deterministic fields, schema coverage, verdict/status,
   errors, terminal/publish behavior и только затем semantic similarity.
5. Для LLM выполнить N повторов с одним input. Сначала измерить variance внутри
   prototype и внутри target, затем межсистемное различие. Низкий exact match
   при высокой исходной variance не объявлять code regression автоматически.
6. Объяснить каждый non-match: deterministic defect, allowed variance,
   approved boundary mapping, data/config mismatch либо unresolved conflict.
7. Сохранить sanitized report и recommendation в
   `docs/harness/evals/prototype-parity.md`. Match ниже threshold оставляет
   задачу открытой; path добавить в task evidence.

## Gating и предел доказательства

Быстрый network-free deterministic contract regression на sanitized fixtures
может входить в default `make verify`. Полный quality/LLM прогон выполнять
отдельно. Mocked parity не доказывает clean install, build, registry/DI wiring,
frozen resources или production boundary — для этого нужны соответствующие
runtime gates либо `skill_mode=live`.

Для deterministic logic требовать exact или явное field-level equality. Для
LLM использовать несколько сигналов: success/error, required fields, coverage,
semantic closeness и repeatability. Если сам prototype нестабилен, показать его
variance и не делать вывод по одному mismatch.

## Дополнение к общему report

Включить:

- `ported_from`, prototype root/commit и target revision;
- input manifest и transport mapping;
- prompt/schema/config hashes и LLM summary без secrets;
- prototype/target table по fields, errors, terminal states и side effects;
- run count и variance каждой стороны;
- contract diff или явное подтверждение его отсутствия.

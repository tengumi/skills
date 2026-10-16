# Режим `golden`

## Назначение

Запустить agent under test на released golden dataset и посчитать метрики по
declared comparison/equivalence rule. Не создавать cases и не менять expected
outputs во время evaluation.

## Preconditions

- Назвать dataset manifest/revision/hash и записи проверок synthesis. Для
  `compact-v2` это `run.json`, `cases.jsonl` и `audit.jsonl`; отдельный synthesis
  report не требовать.
- Для `compact-v2` использовать только `selected_case_ids` из run с
  `mode=benchmark_release` и `scoring_ready=true`. Все выбранные cases должны
  иметь `status=ready`; `pending` и `quarantined` не входят в оценку. Статус
  отдельного case не заменяет готовность всего набора и внешнюю приёмку, если
  она требуется. Для legacy-наборов использовать их зафиксированный формат
  и эквивалентные подтверждения release, не мигрировать их автоматически.
- Зафиксировать agent code/model/config revision и exact input/output adapter.
- Прочитать compare method, equivalence, metric, threshold и repeatability rule.
- Подтвердить data policy и authorization для внешних calls/side effects.

Если dataset не имеет independently derived expected output, oracle/version,
evidence/provenance или hard-gate status, не объявлять его production-grade.
Вернуть blocker либо выполнить отдельный `harness-golden` synthesis/release run.

Для `compact-v2` запустить `scripts/validate_run.py RUN_DIR` из папки
`harness-golden` и дополнительно проверить выполнение `run.verification_policy`,
требуемую внешнюю приёмку и действительность проверок. Audit должен связывать
финальные input, `run.evaluation` и expected по трём SHA-256; `superseded` записи
не подтверждают текущую версию. Успех validator подтверждает структуру и привязки,
но не семантическую правильность, реальную независимость или release policy.
`business_review_draft` не выдавать за scoring-ready benchmark; для повышения
до release выполнять только недостающие проверки, сохраняя действительные.
Наличие ключа `expected` проверять отдельно от его значения: `null` допустим,
если это разрешает контракт. Внешние входные файлы сверять с `run.files` по
содержимому и SHA-256, а не только по hash JSON-объекта `input`.

## Workflow

1. Проверить manifest integrity, duplicate ids, fixture readability, expected
   schema и отсутствие quarantine в run set.
2. Зафиксировать deterministic run order и execution environment.
3. Для каждого case передать агенту только fixture по его input contract. Не
   раскрывать expected output, oracle evidence, private plans или case label.
   В `compact-v2` брать `input` выбранного case и только объявленный разрешённый
   контекст/внешние входные файлы. `expected` оставлять evaluator; `results/`
   может содержать ответы для человека и не передаётся агенту целиком.
4. Сохранить sanitized actual output и runtime status/error/terminal state.
5. Применить declared compare method:
   - exact/field-level для deterministic outputs;
   - coverage для обязательных fields/units;
   - execution match для исполнимого результата в безопасной среде;
   - semantic только как дополнительный signal;
   - independent judge только по explicit rubric.
6. Для nondeterministic path выполнить spec-defined repeats и показать per-case
   variance; не скрывать flaky cases average score.
7. Посчитать task-specific aggregate и slices по axis/difficulty/coverage family.
   Не навязывать универсальные labels или баланс.
8. Классифицировать discrepancies: agent defect, runtime/config mismatch,
   ambiguous dataset, invalid fixture или external prerequisite failure.
9. Сохранить report. Dataset defect не чинить внутри eval task: quarantine/handoff
   в отдельный `harness-golden` run с новым revision.

## Gating и предел доказательства

Golden result доказывает качество только на released dataset/distribution и
записанном execution mode. Он не доказывает production registration, packaging,
boundary mapping или live side effects.

Не включать full evaluation/LLM judge/external calls в default CI. Допустим
маленький deterministic regression subset с immutable expected values, если это
разрешено team policy.

## Дополнение к report

Включить:

- dataset/run id, hash, accepted count и excluded quarantine count;
- synthesis audit/oracle versions и verification strength;
- agent/model/config revision;
- compare/equivalence rules и threshold;
- overall metric и slices;
- repeatability/variance;
- discrepancy table и recommended owner/action;
- подтверждение, что expected outputs не менялись.

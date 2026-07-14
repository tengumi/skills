# Режим `golden`

## Назначение

Запустить agent under test на released golden dataset и посчитать метрики по
declared comparison/equivalence rule. Не создавать cases и не менять expected
outputs во время evaluation.

## Preconditions

- Назвать dataset manifest/revision/hash и synthesis audit report.
- Использовать только released/accepted cases; quarantine исключить.
- Зафиксировать agent code/model/config revision и exact input/output adapter.
- Прочитать compare method, equivalence, metric, threshold и repeatability rule.
- Подтвердить data policy и authorization для внешних calls/side effects.

Если dataset не имеет independently derived expected output, oracle/version,
evidence/provenance или hard-gate status, не объявлять его production-grade.
Вернуть blocker либо выполнить отдельный `harness-golden` synthesis/release run.

## Workflow

1. Проверить manifest integrity, duplicate ids, fixture readability, expected
   schema и отсутствие quarantine в run set.
2. Зафиксировать deterministic run order и execution environment.
3. Для каждого case передать агенту только fixture по его input contract. Не
   раскрывать expected output, oracle evidence, private plans или case label.
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

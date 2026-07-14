---
name: harness-golden
description: "Синтезирует воспроизводимые golden eval-датасеты из input references, truth sources и явного intent: строит реалистичные fixtures, независимо выводит expected outputs максимально сильным oracle, изолирует verifier, отправляет неоднозначные cases в quarantine и сохраняет evidence/provenance. Используй для генерации новых эталонов качества по стандарту, спецификации, чек-листу, executable rule или размеченным ответам; не используй для parity с выходом прототипа или запуска агента по уже готовому датасету."
---

# harness-golden

## Цель и границы

Создать проверяемый golden-датасет, где правильность определяется внешними
truth sources и операционализированным correctness rule, а не выходом прототипа,
тестируемого агента или намерением генератора.

Skill выполняет только synthesis: fixtures, independently derived expected
outputs, quality gates, quarantine и отчёт. Запуск агента по выпущенному
датасету и расчёт его метрик выполняет `harness-eval` с `skill_mode=golden`.
Регрессию относительно поведения прототипа выполняет `harness-eval` с
`skill_mode=prototype-parity`.

## Обязательный вход

До массовой генерации получить и полностью прочитать:

1. Предпочтительно `golden-spec.yaml` или semantic-equivalent spec.
2. Контракт входа и выхода агента под тестом.
3. Все input references и truth sources из spec.
4. Применимые `AGENTS.md`, `docs/harness/conventions.md`, data policy и прежний
   golden-validation report, если он существует.

Spec обязан однозначно задавать:

- intent и требуемое число accepted cases;
- input references для реалистичности;
- truth sources и их приоритет для определения истины;
- correctness rule, expected-output shape и equivalence/ambiguity policy;
- seed либо разрешение создать и зафиксировать seed;
- допустимый oracle и внешние prerequisites;
- sanitization, хранение evidence и запрещённые данные.

Имена полей могут отличаться, если смысл однозначно восстанавливается. Если
форма I/O или правильность не операционализируются, выполнить probe/запросить
решение и остановиться до batch generation.

## Разделение ролей

Не смешивать:

- **input references** — форма, стиль, структура и распределение реалистичных
  входов;
- **truth sources** — правила, факты или исполнимый источник правильного ответа;
- **intent** — нужные сценарии, покрытие и сложность;
- **agent interface** — допустимая форма fixture и expected output;
- **oracle** — способ заново получить правильный ответ из готового fixture.

Input reference становится truth source только при явном объявлении размеченной
пары/эталонного ответа. Выбирать максимально сильный oracle:

1. executable;
2. rule-grounded;
3. reference-answer;
4. independent judge.

Judge-only batch остаётся `calibration`, пока не прошёл независимую калибровку.
Конфликт truth sources без приоритета блокирует затронутый case.

## Обязательная инструкция

Перед работой полностью прочитать
[references/SYNTHESIS.md](references/SYNTHESIS.md) и выполнить все применимые
phases, stop conditions и invariants. Не заменять reference кратким пересказом.

Минимальный маршрут:

1. Скомпилировать runtime task profile и проверить oracle probe-case.
2. Снять reference distribution; разделить anchors и hold-out, если данных
   достаточно.
3. Детерминированно построить coverage/assignment из зафиксированного seed.
4. Подготовить private generation plans и изолировать их от verifier inputs.
5. Сгенерировать fixtures без answer leakage, raw PII и копирования истины.
6. В свежем контексте заново вывести `derived expected output` из готового
   fixture. Intended output генератора не является gold.
7. Выполнить hard gates и quality audits; disagreement/ambiguity отправить в
   quarantine.
8. Выпустить только accepted cases вместе с evidence и provenance.

Для нового типа агента, oracle или набора sources сначала выполнить небольшой
pilot. Значения `limit_units: 5` и `review.sample_rate: 0.4` — рекомендуемые
стартовые defaults, а не универсальные quality thresholds. Масштабировать batch
только после проверки realism, oracle stability и verifier agreement.

## Исполнение и внешние системы

Детерминированные подсчёты, assignment, sampling и ids выполнять кодом с seed,
не просить модель «случайно выбрать». Одноразовые runtime tools сохранять с
hash/provenance запуска; не превращать их автоматически в team-owned scripts.

Использовать `harness-request-exec`, только если watcher задан policy или direct
runtime недоступен. Watcher — transport, не разрешение. External DB/API/LLM,
конфиденциальные sources или изменяющие side effects требуют approved
environment/data scope; при его отсутствии остановиться или применить явно
разрешённый substitute.

Для независимого verifier при возможности использовать отдельную сессию или
subagent, передавая raw fixture, truth sources, rules/schema и разрешённые oracle
tools. Не передавать private plan, intended output, transformation, assignment,
предыдущие ответы или output тестируемого агента.

## Выход

Адаптировать runtime paths к conventions репозитория. Сохранить как минимум:

- task/reference profiles и frozen assignment;
- accepted fixtures и independently derived expected outputs;
- quarantine с причинами и конфликтующими evidence;
- oracle/version, seed, anchors/templates и runtime-tool hashes;
- hard-gate и quality-audit results;
- verification strength, ambiguity/equivalence decisions;
- canonical summary `docs/harness/evals/golden-synthesis.md` с paths на dataset,
  manifests и reports.

Минимальная semantic-equivalent запись case:

```yaml
case_id: unique-id
fixture: path-or-inline-value
expected_output: structured-value
oracle:
  kind: executable-or-rule-grounded-or-reference-answer-or-judge
  version: source-version-or-hash
evidence:
  fixture: []
  truth_source: []
provenance:
  run_id: run-id
  seed: 0
  template: template-id
  anchors: []
quality:
  verification_strength: strong-or-weak
  gates: {}
```

Task-specific fields и vocabularies задавать через spec. Не заставлять разные
агенты использовать один verdict schema.

## Hard limits

- Не брать expected output из прототипа или тестируемого агента, если они явно
  не объявлены authoritative truth source.
- Не считать intended output генератора готовым gold.
- Не передавать verifier private generation context.
- Не ослаблять hard gates ради требуемого количества или красивой метрики.
- Не маскировать обязательные поля semantic similarity.
- Не форсировать заранее красивое распределение labels вопреки evidence.
- Не зашивать предметные критерии, папки, статусы и мутации в общий skill.
- Не коммитить raw PII, secrets, confidential fragments или private plans.
- Не включать synthesis, judge или полный quality eval в default `make verify`.
- Не угадывать нечитаемый источник: использовать approved extractor/OCR либо
  вернуть blocker.

## Связь с другими skills

- `harness-eval`, `skill_mode=golden` — запускает agent under test на released
  dataset и считает метрики, не меняя expected outputs.
- `harness-eval`, `skill_mode=prototype-parity` — сравнивает target с prototype;
  это другой источник истины.
- `harness-governance-gates` — проверяет sanitization, secrets/PII и permanent
  guards для committed fixtures.
- `harness-work-session` — claim/submit wrapper для plan-generated synthesis task;
  `harness-golden` не требует `skill_mode`.

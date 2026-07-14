# Golden synthesis

## Содержание

1. [Назначение и понятия](#назначение-и-понятия)
2. [Разделение источников](#разделение-источников)
3. [Минимальный входной контракт](#минимальный-входной-контракт)
4. [Иерархия oracle](#иерархия-oracle)
5. [Phase 0 — Discover and compile](#phase-0--discover-and-compile)
6. [Phase 1 — Harvest reference distribution](#phase-1--harvest-reference-distribution)
7. [Phase 2 — Build coverage and assignment](#phase-2--build-coverage-and-assignment)
8. [Phase 3 — Derive transformations and plan](#phase-3--derive-transformations-and-plan)
9. [Phase 4 — Generate fixtures](#phase-4--generate-fixtures)
10. [Phase 5 — Evolve and normalize](#phase-5--evolve-and-normalize)
11. [Phase 6 — Re-derive expected output](#phase-6--re-derive-expected-output)
12. [Phase 7 — Audit quality](#phase-7--audit-quality)
13. [Phase 8 — Release or quarantine](#phase-8--release-or-quarantine)
14. [Изоляция verifier](#изоляция-verifier)
15. [Runtime evidence](#runtime-evidence)
16. [Stop conditions](#stop-conditions)
17. [Инварианты](#инварианты)

## Назначение и понятия

Синтезировать воспроизводимый golden-датасет из пользовательского intent,
референсных входов и источников истины. Создавать реалистичные fixtures и
выводить expected outputs из **готовых** fixtures максимально сильным доступным
oracle.

Не использовать output тестируемого агента как источник истины, если
пользователь явно не объявил его эталоном. Не считать mutation plan или
intended output готовым gold.

Применять методологию к любому типу артефакта. Крупный артефакт разбивать на
units, небольшой обрабатывать одним unit. Не зашивать доменные папки, критерии,
форматы, мутации или vocabularies: получать их из spec и sources текущего run.

Основные понятия:

- **fixture** — синтетический вход agent under test;
- **expected output** — правильный ответ для финального fixture;
- **golden case** — fixture, expected output и evidence после release gates;
- **input reference** — пример входа, задающий форму и распределение;
- **truth source** — источник, из которого выводится правильность;
- **oracle** — исполнимый или проверяемый способ получить expected output;
- **unit** — минимальная независимо генерируемая/проверяемая часть;
- **anchor** — reference fragment того же типа, что создаваемый unit;
- **structural template** — форма reference без его конкретного содержания;
- **attribute** — характеристика формы или содержания fixture;
- **transformation** — контролируемое изменение, выведенное из oracle/rules;
- **intended output** — плановый ответ генератора;
- **derived output** — ответ, заново выведенный oracle из готового fixture;
- **quarantine** — cases с конфликтом, неоднозначностью или проваленным gate.

## Разделение источников

Не смешивать роли:

1. Использовать input references только для реалистичности и разнообразия.
2. Использовать truth sources для определения правильности.
3. Использовать intent для покрытия сценариев и сложности.
4. Использовать agent interface для формы input/output.

Считать reference truth source только при явном объявлении размеченной пары или
эталонного ответа. Не выводить correctness из стилистического сходства.

При конфликте truth sources применять объявленный приоритет. Если приоритет не
задан и конфликт влияет на ответ, остановить case и поместить его в quarantine.

## Минимальный входной контракт

Принимать preferred `golden-spec.yaml` либо semantic-equivalent структуру. Не
требовать точных YAML key names, если смысл однозначен.

Получить как минимум:

- intent;
- input references;
- truth sources и precedence;
- описание правильного ответа;
- agent input/output contract;
- требуемое число accepted cases;
- seed или разрешение создать/зафиксировать seed;
- equivalence и ambiguity rules;
- data/storage policy.

Если после чтения agent contract и sources форма input/output остаётся
неизвестной, запросить решение. Не начинать batch, пока правильность нельзя
операционализировать.

## Иерархия oracle

Выбирать максимально сильный доступный oracle:

1. **Executable** — выполнение запроса, теста, валидатора, симулятора,
   компилятора или иной программы.
2. **Rule-grounded** — стандарт, политика, спецификация, схема или формальные
   правила с evidence.
3. **Reference-answer** — размеченные input–answer пары и объявленное правило
   переноса разметки.
4. **Judge** — независимый human/model judge с явной рубрикой.

Комбинировать oracles, если они проверяют разные свойства. Не заменять сильный
oracle judge-проверкой без evidence. Judge-only качество помечать `calibration`,
пока нет независимой калибровки.

## Phase 0 — Discover and compile

Прочитать spec, agent interface, input references и truth sources. Проверить
существование, revision и читаемость всех обязательных ресурсов.

Скомпилировать runtime task profile:

- `artifact_kind`;
- `agent_input_contract` и `expected_output_shape`;
- `evaluation_unit`;
- `oracle_kind` и `oracle_inputs`;
- `correctness_rule`;
- `equivalence_rule`;
- task-specific evaluation dimensions, vocabularies и связи;
- `decision_rule_cards` с исходным evidence, `all_of`/`any_of`, modality,
  blocking и допустимостью functional analog;
- `ambiguity_policy`;
- `coverage_dimensions`;
- `size_contract` и способ измерения;
- `quality_level` и ограничения run.

Сохранить профиль в `work/<run_id>/task-profile.yaml`. Считать его evidence run,
а не новым team-owned источником доменных правил.

Проверить oracle на known-good reference/minimal probe и содержательно изменённом
probe. Подтвердить, что oracle:

- принимает предполагаемый fixture;
- возвращает expected shape;
- различает корректный и изменённый case;
- создаёт достаточное evidence.

При провале probe не генерировать batch. Зафиксировать blocker и недостающий
contract.

Не упрощать `all_of` до `any_of`, не превращать functional analog в запрет и не
повышать рекомендацию до blocking requirement. Невосстановимую семантику truth
source отправлять в quarantine.

## Phase 1 — Harvest reference distribution

Извлечь из input references только свойства, необходимые для synthesis:

- structural templates;
- типы и порядок units;
- размеры и плотность;
- форматы, допустимые значения и связи;
- стиль, терминологию и устойчивые паттерны;
- естественные неровности и ограничения;
- reference families и потенциальные attributes.

Выполнять подсчёты, parsing, sampling и статистику детерминированно. При
необходимости сохранить одноразовый runtime tool в `work/<run_id>/tools/` с
hash/version.

Не просить модель случайно выбрать файл/комбинацию. Не нормализовать references
до единого идеального шаблона, если различия важны для realism.

Если references достаточно, разделить их на:

- anchor pool для generation;
- hold-out pool для blind realism baseline.

Никогда не использовать hold-out как anchor. При малом числе references не
выдумывать hold-out: уменьшить batch или confidence realism-аудита, но не
считать это автоматическим blocker.

Сохранить `reference-profile.yaml` и extracted templates как runtime evidence.

## Phase 2 — Build coverage and assignment

Вывести оси покрытия из intent, agent interface и oracle. Рассмотреть, когда
применимо:

- structural family;
- expected-result family;
- difficulty/borderline;
- attributes;
- transformation family;
- допустимый distractor context;
- комбинации независимых свойств;
- size buckets.

Не навязывать positive/negative классы, если они не следуют из correctness rule.

Построить coverage matrix и назначить cases детерминированно:

- использовать seed из spec;
- распределять templates/attributes стратифицированным round-robin или другим
  объявленным алгоритмом;
- декоррелировать structural template от intended output;
- не позволять одному anchor/profile доминировать случайно;
- распределять size buckets независимо от intended output;
- сохранить assignment до generation.

По умолчанию изолировать один case на одной evaluation unit. Multi-property case
разрешать только при явном coverage plan и независимой разметке каждого
свойства.

Сохранить `assignment.yaml`. Не менять его во время написания fixture, кроме
явно записанной замены quarantined case.

## Phase 3 — Derive transformations and plan

Получить task-specific transformations из correctness rule и truth sources.
Использовать универсальные семьи только как рамку:

- сохранить семантику при изменении поверхности;
- удалить необходимый элемент;
- изменить значение или границу;
- ослабить ограничение/обязательность;
- изменить связь, mapping или роль;
- нарушить порядок, состояние или зависимость;
- создать контролируемое противоречие;
- добавить релевантный distractor;
- объединить совместимые независимые изменения.

Для transformation определить:

- какие oracle rules она затрагивает;
- какой intended output должна вызвать;
- какие units изменить согласованно;
- что сохранить;
- какие реализации раскрывают answer или выглядят искусственно;
- как oracle подтвердит результат.

Не считать список закрытым каталогом. Добавлять task-specific операции, если
они выводятся из oracle и сохраняют invariants.

Для каждого candidate создать private generation plan:

- template/anchors;
- attributes;
- transformation и units;
- semantic facts/consistency ledger;
- intended output;
- realism/anti-copy limits;
- provenance каждого элемента.

Хранить plan отдельно от fixture и verifier inputs. Не включать intended output,
transformation name или defect hint в тестовый вход.

## Phase 4 — Generate fixtures

Для составного артефакта выполнять unit-wise generation:

1. Составить outline и semantic ledger.
2. Для каждого unit выбрать назначенный anchor того же типа.
3. Создать оригинальное содержание с reference-like формой/плотностью без
   дословного переноса предметных фактов.
4. Применить только назначенные transformations.
5. После unit обновить ledger и проверить cross-unit links.
6. Собрать fixture и повторить global checks.

Для небольшого артефакта выполнить те же проверки одним unit без искусственного
outline.

Если spec задаёт размер, измерить финальный serialized fixture объявленным
способом. Доводить размер содержательными units и допустимыми приложениями, а не
повторами, пустым boilerplate или нерелевантным текстом. После изменения размера
повторить consistency, leakage и oracle verification.

Запретить в fixture:

- слова/метакомментарии о benchmark, gold, expected output, transformation или
  verdict;
- объяснение собственной корректности/некорректности;
- указание намеренно удалённого требования;
- готовый answer из truth source;
- неестественные hints ради оценки;
- secrets, PII и запрещённые fragments references.

Сохранять raw candidate до verification. Не считать его accepted по внешней
правдоподобности.

## Phase 5 — Evolve and normalize

Для длинных/структурных fixtures при необходимости выполнить отдельный pass:

- приблизить style и естественные неровности к reference distribution;
- убрать монотонность и повторяющиеся конструкции;
- восстановить внутренние ссылки;
- проверить format/numbering/required structure;
- убрать synthetic tells и чрезмерно явные отрицания;
- сохранить semantic facts oracle.

Не добавлять случайный noise ради разнообразия. Каждая неровность должна быть
reference-valid и не менять semantics без фиксации. После evolution повторить
structural, consistency, leakage и oracle checks. Для небольшого fixture
пропустить phase, если нет измеримой пользы.

## Phase 6 — Re-derive expected output

Заново получить expected output из готового fixture. Не копировать intended
output из private plan.

Запустить verifier в свежем контексте/процессе, если среда позволяет. Передать
только:

- готовый fixture;
- truth sources;
- correctness/equivalence rules;
- expected-output schema;
- разрешённые oracle tools.

Не передавать:

- intended output;
- assignment outcome;
- transformation name;
- private generation plan;
- предполагаемый defect;
- предыдущие verifier outputs;
- output agent under test.

Для executable oracle сохранить machine result. Для rule-grounded проверить
каждую обязательную часть и сохранить fixture/truth evidence. Для
reference-answer применить equivalence rule. Для judge выполнить независимые
passes по spec и сохранить disagreement.

Сформировать `derived output`, evidence, confidence и ambiguity notes. Только
после завершения verifier сравнить derived и intended outputs.

Expected output сохранять в task-specific shape. Не вводить общий обязательный
verdict vocabulary или связь между независимыми axes.

Если derived и intended неэквивалентны:

1. Не переписывать expected под намерение generator.
2. Не использовать output тестируемого агента как арбитра.
3. Поместить candidate в quarantine либо выполнить не больше разрешённого repair
   budget.
4. После repair запустить новый verifier без предыдущего ответа/private plan.

Если свежий контекст недоступен, пометить verification strength как `weak`. Не
объявлять такой batch production-grade без дальнейшей независимой проверки.

## Phase 7 — Audit quality

Применить hard gates. Не компенсировать провал hard gate высоким average score.

Обязательные hard gates:

- fixture читается и соответствует agent input contract;
- final size соответствует `size_contract`;
- expected output соответствует output schema;
- oracle успешно применён к финальному fixture;
- каждый значимый вывод имеет точное evidence;
- compiled rule cards сохраняют operator/modality/blocking/functional analog;
- нет unresolved truth-source conflict;
- нет неучтённой ambiguity;
- нет непредусмотренного cross-unit contradiction;
- fixture не раскрывает expected output;
- criterion-like отрицания не раскрывают intended gap;
- нет запрещённых данных;
- verifier не видел private plan;
- derived и intended outputs эквивалентны.

Оценить дополнительные свойства:

- **realism** — близость к hold-out/reference distribution;
- **diversity** — отсутствие duplicates/доминирующего family;
- **anti-copy** — отсутствие чрезмерного anchor overlap;
- **coverage** — выполнение frozen matrix;
- **difficulty** — заявленный диапазон;
- **balance** — отсутствие нежелательного перекоса expected outputs;
- **leakage** — невозможность угадывать answer по synthetic tells;
- **reproducibility** — seed, assignment и provenance.

Калибровать thresholds по spec/references, не использовать универсальные
магические значения. Для малого pilot выводить descriptive results и не делать
сильных статистических выводов.

Для blind realism audit смешать synthetic fixtures с hold-out и скрыть origin.
Не использовать anchor как hold-out baseline.

Для semantic leakage искать не только слова `gold`, `expected`, verdict, но и
перефразы correctness rule, прямо объявляющие отсутствие нужного механизма.
Повторяющиеся отрицательные формулы считать основанием для repair.

## Phase 8 — Release or quarantine

Включать в final dataset только cases после всех hard gates. Для accepted case
сохранить:

- fixture/path;
- derived expected output;
- oracle kind/version;
- fixture и truth-source evidence;
- equivalence/ambiguity decisions;
- seed, template, anchors и runtime-tool hashes;
- quality gates;
- verification strength.

Для quarantined case сохранить reason, failure phase, conflicting outputs и
available evidence. Не включать quarantine в метрики agent under test.

Если нужен exact accepted count, генерировать replacements только в пределах
candidate budget. Не ослаблять gates. При исчерпании budget вернуть фактическое
число и причины.

## Изоляция verifier

Создать allowlist manifest verifier inputs. Проверить отсутствие private plans,
intended outputs и предыдущих answers.

При независимых сессиях/subagents передавать raw artifacts и минимальный
task-local context, не диагнозы generator и не просьбу подтвердить ответ.

При двух и более verifiers:

- нормализовать outputs;
- отделить различие формы от смысла;
- автоматически принять case только по agreement rule из spec;
- отправить semantic disagreement в quarantine/adjudication;
- не выбирать большинство без evidence, если доступен более сильный oracle.

## Runtime evidence

Использовать рекомендуемую, но не обязательную team-owned структуру:

```text
work/<run_id>/
├── task-profile.yaml
├── reference-profile.yaml
├── assignment.yaml
├── tools/
├── private-plans/
├── candidates/
├── verifier-inputs/
├── verifier-evidence/
└── audits/

fixtures/<run_id>/
report/<run_id>-dataset.jsonl
report/<run_id>-audit.yaml
report/<run_id>-quarantine.yaml
```

Адаптировать paths к conventions. Не менять team-owned layout. Runtime tools и
plans считать evidence run, а не постоянными assets общего skill.

Минимальная semantic-equivalent запись:

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

Добавлять task-specific fields через spec.

## Stop conditions

Остановить run или case, если:

- обязательный ресурс недоступен;
- correctness description нельзя превратить в rule;
- truth sources конфликтуют без precedence;
- output equivalence неизвестна и влияет на label;
- oracle probe не проходит;
- verifier нельзя изолировать от generation plan;
- обнаружена expected-output leakage;
- repair/candidate budget исчерпан;
- обязательная external system недоступна без approved substitute;
- человек должен принять доменное решение, меняющее истину.

Малое число references не является автоматическим blocker. Зафиксировать
ограничение diversity/realism confidence и уменьшить batch либо запросить data.

## Инварианты

Каждый run обязан сохранять:

1. Correctness задаётся truth sources/rule, не prototype.
2. References задают input distribution, не скрытую истину.
3. Randomness, balance и assignment выполняются кодом с seed.
4. Intended output не является gold до independent derivation.
5. Verifier не получает private generation context.
6. Ambiguity/conflict отправляются в quarantine.
7. Synthetic fixture выражает сценарий содержанием, не метакомментарием.
8. Domain facts остаются в spec/user sources.
9. Accepted dataset содержит evidence/provenance для каждого case.
10. Quality gates не ослабляются ради количества или красивой метрики.

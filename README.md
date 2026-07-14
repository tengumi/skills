# Harness team kit

Канонический командный комплект для переноса прототипов AI-агентов в
production. Здесь лежит всё, что нужно для запуска и сопровождения Harness;
проектные прототипы, секреты и результаты конкретных прогонов сюда не входят.

## Быстрый старт

1. Подключить каталоги из `skills/` к Codex принятым в команде способом. Перед
   обновлением сравнить существующие версии и не перезаписывать ручные изменения
   без review.
2. Настроить [`tasks-mcp`](mcp-servers/tasks-mcp/README.md).
3. Создать target из официального team template и оставить prototype read-only.
   Если template не содержит полного `docs/harness/`, вручную скопировать только
   отсутствующие team docs, `templates/tasks.json` и
   `PRE-INDUSTRIALIZATION-SPEC.md` под именем
   `docs/harness/pre-industrialization-spec.md`. Существующие target-файлы не
   перезаписывать.
4. Заполнить созданный в target
   `docs/harness/pre-industrialization-spec.md`: кто утверждает решение, какие
   данные сохраняются и, для каждой production boundary, точные endpoint/tool,
   request/response/error/auth contracts. Отсутствующие в prototype endpoints
   отмечаются `N/A`, а будущие не угадываются.
5. Прочитать [ONBOARDING.md](ONBOARDING.md) и запустить один entrypoint:

> Используй `$harness-productionize`: prototype=`<path>`, target=`<path>`,
> team_template=`<path>`, team_docs=`<harness-kit/team-docs>` при отсутствии
> docs в template. Дойди до ближайшего human checkpoint.

`harness-watcher` нужен только там, где команды нельзя выполнять в среде Codex
или это требует политика. Он не является обязательной частью каждого прогона.

## Что лежит в комплекте

| Путь | Назначение |
|---|---|
| [`PRE-INDUSTRIALIZATION-SPEC.md`](PRE-INDUSTRIALIZATION-SPEC.md) | human-owned шаблон входной спеки: endpoints, тела, owners, runtime/deploy и разрешения |
| `skills/` | 20 универсальных Harness skills |
| `templates/` | стартовые repo artifacts и безопасные примеры конфигурации |
| `team-docs/` | read-only архитектура и соглашения, переданные разработчиком |
| `mcp-servers/tasks-mcp/` | claim/submit, evidence и stuck detection без feature-diff по умолчанию |
| `harness-watcher/` | опциональный файловый transport для удалённого выполнения |

Перед каждым этапом человек и Агент вручную сверяют соответствующий статус во
frontmatter `pre-industrialization-spec.md`, заполненность применимых разделов и
точный scope human sign-off. Наличие статуса само по себе не доказывает
смысловую корректность контракта.

Происхождение восстановленных runtime-компонентов и границы достоверности
описаны в [PROVENANCE.md](PROVENANCE.md).

## Почему skills 20, но выбирать их не нужно

Для полного прогона человек вызывает только `harness-productionize`. Он
определяет состояние по durable artifacts и передаёт следующий шаг точному
skill. В `tasks.json` оркестратор не записывается: каждая задача получает
исполнительный `use_skill` и, если нужен, `skill_mode`.

Основной маршрут использует:

- preflight и контекст: `harness-doctor`, `harness-context`;
- этап A: `harness-source-analysis`, `harness-ds-precheck`,
  `harness-prototype-plan`, `harness-prototype-port`;
- этап B: `harness-extract-prod`, `harness-production-plan`,
  `harness-production-readiness`;
- выполнение и доказательства: `harness-work-session`, `harness-eval`,
  `harness-pre-commit-check`, `harness-governance-gates`.

Опциональный quality-контур разделён намеренно: `harness-golden` создаёт и
oracle-проверяет новый датасет, а `harness-eval` с `skill_mode=golden` запускает
по уже released датасету agent under test. Parity и live остаются другими modes
`harness-eval`; expected outputs во время оценки не переписываются.

Legacy tasks мигрируются до claim: `harness-eval + skill_mode=synthesize` →
`harness-golden` без `skill_mode`. Старый mode не является runtime alias.

Оставшиеся skills — situational utilities для workspace scan, team template,
извлечения недостающих паттернов, layout alignment и watcher transport. Они не
добавляют обязательные этапы в каждый прогон.

## Источники истины

- `team-docs/` принадлежат команде и не переписываются skills;
- prototype и `prototype-contract.json` определяют сохраняемое поведение;
- `pre-industrialization-spec.md` принадлежит людям-владельцам решений; Агент
  может подготовить evidence, но не ставит себе `APPROVED`;
- approved target contracts определяют новые API/tool/queue/DB boundaries;
- `tasks.json` хранит план, а tasks-mcp по умолчанию хранит lifecycle
  out-of-band;
- production neighbour и release reference дают evidence, но не становятся
  архитектурой target автоматически.

Перед распространением комплекта вручную проверить структуру skills, ссылки,
JSON-шаблоны и отсутствие локальных/runtime-артефактов.

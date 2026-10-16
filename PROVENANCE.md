# Provenance

Этот файл не задаёт методологию; он объясняет происхождение содержимого kit.

- `skills/` и `ONBOARDING.md` — актуализированная командная методология. Старые
  routes объединены, публичный entrypoint — `harness-lead`.
  `harness-golden` синхронизирован 2026-10-16 с рабочим проектом
  `harness-golden`; synthesis отделён от потребляющего его `harness-eval`.
- `team-docs/` — документация, переданная разработчиком. Она сохранена как
  team-owned/read-only; неоднозначности перечислены в её README и не исправлены
  скрыто.
- `harness-watcher/` — сверенный 2026-08-07 с исходником, который фактически
  использует команда. Kit сохраняет строгую проверку SSH host key и добавляет
  fail-closed pull, идемпотентность по `request_id`, проверяемые
  source/lock/profile/commands fingerprints и завершение всей process group по
  timeout. Это совместимое усиление, а не утверждение о live-проверке на
  конкретной рабочей станции.
- `mcp-servers/tasks-mcp/` — восстановленный шеституловый MCP prototype, после
  аудита дополненный безопасным out-of-band lifecycle, тестами и документацией.
  Он не заявлен как побайтовая копия ранее установленного runtime.
- `templates/` — универсальные стартовые artifacts, выведенные из текущих skill
  contracts; это не архитектура конкретного агента.
- `PRE-INDUSTRIALIZATION-SPEC.md` — короткий паспорт production-подключений,
  добавленный после прошлого прогона, где endpoints и внешние контракты пришлось
  уточнять уже после переноса. Человек даёт ссылки, точные операции и недостающие
  реквизиты БД/Jenkins/deploy; детали доступных контрактов извлекает Кодовый агент.

При расхождении production runtime и этого kit сначала сохранить evidence и
версию обеих сторон, затем обновлять kit отдельной проверяемой правкой.

## Harness Golden — snapshot 2026-10-16

Источник: проект `harness-golden`, каталог
`/Users/razi/Documents/harness/harness-golden-vnext`. Его `AGENTS.md` указывает
этот каталог как рабочую методологию; соседние копии и ZIP не использовались.
Источник не имеет зафиксированной Git-версии этих файлов, поэтому snapshot
идентифицирован SHA-256. Все четыре файла перенесены побайтово в
`skills/harness-golden/`; исходный проект и существующие golden runs не менялись.

| Файл относительно skill | SHA-256 |
|---|---|
| `SKILL.md` | `24e0bf4b9e2beb73667609a6aea33639eb489b3aa95c1528679bf26b4fd24f44` |
| `references/SYNTHESIS.md` | `0194dbbaabcd66c6cb19aa0308c34220758d8a3b8b9d4e78172c83b37537f0ec` |
| `references/TEMPLATES.md` | `7d16227d3bb86e40298216196d9de9405c70df2174f9220e972d52106784efdf` |
| `scripts/validate_run.py` | `a332e30555abf4c118fd35bf6f33a127d665e5b4326f75357b5121b071f9b9fe` |

`agents/openai.yaml` — локальные UI-метаданные kit, согласованные с новым
entrypoint. Совместимость `harness-eval`, условия claim и optional spec обновлены
в kit отдельно, без изменения канонической методологии Golden. Структурные
проверки упаковки не равны semantic review или экспертной приёмке эталонов.

# Механика плана и handoff

Использовать при подготовке/изменении очереди, фиксации выбранных входов или
передаче состояния. Не запускать все команды после каждой задачи. Это утилита
оркестратора, не doctor, не новая задача и не новый human checkpoint.

`TOOL` ниже — путь к `harness-lead/scripts/harness_artifacts.py` в подключённом
комплекте. `SCHEMA` — путь к каноническому `harness-kit/templates/tasks.schema.json`.
Пути передавать в кавычках. Нужны Python 3.12 и POSIX (Linux/macOS); безопасный
доступ без symlinks на Windows пока не реализован. Для validate-tasks/handoff один раз
установить `scripts/requirements.txt` в среду инструментов; manifest использует
только стандартную библиотеку. Это не зависимость опромышливаемого сервиса,
Tasks MCP или watcher.

## Проверка очереди

```bash
python "$TOOL" validate-tasks --tasks "$TARGET/docs/harness/tasks.json" --schema "$SCHEMA"
```

Проверяются настоящий JSON Schema, уникальность ID во всех секциях,
существование зависимостей и циклы, соответствие этапа/фазы и владельцы
runtime/bundle. Ошибки содержат пути полей и коды, не содержимое полей.

Эта команда только проверяет данные. Для локальной автоматической цепочки
`validate → fresh lifecycle → claim` использовать отдельный
[guarded runner](../../../tools/route-runner/README.md). Нельзя продолжать к claim
после ненулевого exit code validator. Runner не добавляет в `harness_artifacts.py`
операций записи lifecycle и не заменяет смысловой pre-claim gate.

Для полного плана B, где оба gate применимы, добавить:

```bash
--plan-id production-bc-<id> --require-runtime --require-bundle
```

Без этих флагов отсутствие owner не трактуется как доказанная ошибка:
применимость определяет планировщик. Это удобно для черновой очереди и
частичных/delta-планов. Проверять полную очередь с существующими задачами,
а не только добавляемый фрагмент. Утилита не проверяет смысл декомпозиции,
coverage, контракты, разрешения и свежесть результатов. `valid: true` не
означает готовность к claim или выпуску. Ошибки генерации исправить самостоятельно
в рамках плана, не передавать человеку как новый blocker.

## Снимок выбранных файлов

```bash
python "$TOOL" manifest --root "$TARGET" --file docs/harness/pre-industrialization-spec.md --file docs/harness/data-boundaries.md --file docs/harness/team-patterns-production.md --output "$TARGET/.tmp/harness/plan-inputs.json"
```

Повторять `--file` для точных относительных путей; без него выбираются только
Git-tracked файлы. Для прототипа без Git указать файлы явно. Рекурсивного чтения
всего workspace и раскрытия env нет. Секретные имена, кеши, сборки и symlinks
фильтруются до открытия; пропуски видны в manifest. При явном выборе запрещённого
или отсутствующего файла команда завершается ошибкой, не пишет частичный успех.
Не выбирать временные отчёты как входы собственного manifest.

`content_sha256` — hash отсортированной карты относительный путь → SHA-256 bytes.
Время/mtime в hash не входят. Покрытие входов выбирает исполнитель: hash не
доказывает сохранение поведения, полноту карты или отсутствие всех видов секретов.
Для contracts/evidence сохранить также роль источника и Git revision в существующем
плане; не заменять ими artifact hash и не менять старые evidence при reuse.

## Короткий handoff

Сохранить свежий ответ `tasks-mcp.list_open_tasks(include_all=true)` в безопасный
JSON-файл без env/сырых логов. Затем:

```bash
python "$TOOL" handoff --tasks "$TARGET/docs/harness/tasks.json" --schema "$SCHEMA" --lifecycle "$TARGET/.tmp/harness/tasks-export.json" --output "$TARGET/.tmp/harness/handoff.json" --markdown "$TARGET/.tmp/harness/handoff.md"
```

Сводка строится по merged lifecycle, не по `open` в versioned definitions.
Неполный или не совпадающий с определениями экспорт отклоняется. Выводятся
статусы, зависимости и только структурированные claims evidence; свободные
заметки, тексты ошибок и секреты из них в отчёт не копируются.

Это снимок переданных данных, не проверка актуального сервера: даже все `done`
не выставляют B/C complete или release ready. Оркестратор отдельно оценивает
source/evidence/approvals по существующим правилам. Кандидаты по зависимостям
не являются разрешением выполнить задачу. Никаких claim/submit, Git-команд
записи или запуска tests/build утилита не делает.

Выходные файлы создаются только по указанным путям и по умолчанию не
перезаписываются. Для осознанного обновления собственного отчёта есть `--replace`.
Входные tasks/schema/lifecycle и выбранный source manifest перезаписать нельзя.
JSON и Markdown записываются атомарно каждый по отдельности, не как одна транзакция.
Коды выхода: 0 — операция выполнена, 1 — очередь невалидна, 2 — ошибка входа/I/O.

## Проверка утилиты при изменении kit

Из корня kit workspace: установить `harness-kit/skills/harness-lead/scripts/requirements.txt`
в dev-среду, затем выполнить `python -m pytest harness-kit/skills/harness-lead/tests -q`.
Тесты используют только синтетические файлы и собственные временные Git-репозитории.
Повторный полный прогон сервиса для изменения этой утилиты не требуется.

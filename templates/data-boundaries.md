# Data boundaries — index

Этот файл — короткий repo-owned индекс решений о production-доступе к данным.
Точные endpoint/tool/topic, request/response/error/auth schemas и human sign-off
живут в `docs/harness/pre-industrialization-spec.md`; здесь они не дублируются.
Наблюдения из prototype и target design не смешиваются.

| Boundary id / data flow | Prototype classification, mechanism and evidence | Target mechanism | Owner/source of truth | Exact spec card + revision/hash | Mapping test/report | Status |
|---|---|---|---|---|---|---|
| `B-001 / <input/output>` | `<FILE_ONLY/EXISTING_EXTERNAL/NONE + path>` | `<API/tool/queue/DB/storage/FILE/OPEN>` | `<owner>` | `<pre-industrialization-spec.md#... + revision>` | `<test/report/OPEN>` | `<proposed/approved/blocked/verified>` |

## Decision log

| Date | Scope | Decision | Owner/approver | Evidence | Consequence |
|---|---|---|---|---|---|
| `<date>` | `<boundary>` | `<decision>` | `<owner>` | `<path/ticket>` | `<unblocked tasks>` |

`N/A` означает, что transport/endpoint действительно отсутствовал в prototype.
`OPEN` означает, что production-решение ещё не утверждено; это блокирует adapter,
но не анализ и parity port. Строка `approved` без точной карточки, revision и
human sign-off не считается утверждённым контрактом.

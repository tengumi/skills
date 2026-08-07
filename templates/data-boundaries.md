# Внешние границы данных — техническая карта

Этот файл заполняет Harness. Человек указывает ссылки и нужные операции в
`docs/harness/pre-industrialization-spec.md`, а Codex извлекает технические
детали из прототипа и официальных контрактов.

Источники фактов: код прототипа, integration spec, versioned OpenAPI/MCP/
AsyncAPI/DDL, team template и runtime evidence. Неизвестное не заменяется
примером из соседнего сервиса.

Состояния:

- `OBSERVED` — граница найдена только в прототипе;
- `DOCUMENTED` — найдена точная операция и версия официального контракта;
- `MAPPED` — описано соответствие данных прототипа и production-контракта;
- `VERIFIED` — mapping и contract checks прошли;
- `BLOCKED` — отсутствует существенный факт или источники противоречат друг другу.

## Краткий список

| ID и поток данных | Что наблюдается в прототипе | Целевая операция | Официальный источник | Состояние | Чего не хватает |
|---|---|---|---|---|---|
| `B-001 / <вход или выход>` | `<файл / вызов + path:line>` | `<METHOD /path, tool, topic, database.schema>` | `<путь/ссылка + версия>` | `<OBSERVED / DOCUMENTED / MAPPED / VERIFIED / BLOCKED>` | `<точный gap или НЕТ>` |

## B-001 — `<название операции>`

- Наблюдение в прототипе: `<факт и path:line/cell>`
- Запись во входной spec: `<раздел или строка>`
- Официальное описание: `<путь/ссылка + версия или НЕИЗВЕСТНО>`
- Состояние: `<...>`
- Blocker: `<конкретно чего не хватает или НЕТ>`

### Что извлечено из официального описания

| Операция | Точный адрес/tool/topic | Входная схема | Выходная схема и ошибки | Авторизация |
|---|---|---|---|---|
| `<...>` | `<...>` | `<ссылка/раздел>` | `<ссылка/раздел>` | `<механизм и config/secret reference без значения>` |

### Соответствие данных и важные края

| Данные прототипа | Поле внешней системы | Преобразование | Null/empty/error | Доказательство |
|---|---|---|---|---|
| `<...>` | `<...>` | `<без потерь или явно описанное правило>` | `<...>` | `<тест/пример>` |

- Повторные попытки и таймаут: `<из контракта или НЕИЗВЕСТНО>`
- Идемпотентность и порядок: `<из контракта или НЕИЗВЕСТНО>`
- Успешное завершение и обязательный callback: `<...>`

### Runtime lifecycle

| SDK constraint / lock | Transport | Local / cluster access | Object scope | Active session scope | Create / close | Startup / readiness critical | Retry owner | Failure boundary | Доказательство |
|---|---|---|---|---|---|---|---|---|---|
| `<manifest + locked version>` | `<HTTP / SSE / queue / ...>` | `<port-forward/proxy/VPN / service address>` | `<APP / request / task>` | `<request / task / process>` | `<events>` | `<yes/no + source>` | `<SDK/adapter/orchestrator>` | `<request/task/process>` | `<path/revision/test>` |

`APP` scope допустим для side-effect-free config/factory/client object. Активный
session/stream/handshake открывать на request/task, если официальный контракт не
делает boundary обязательной для startup. Lower-bound-only dependency не
подтверждает совместимость со следующим major.

### Проверки

| Проверка | Результат и ссылка |
|---|---|
| Точная операция и версия контракта | `<...>` |
| Схема и обязательные поля | `<...>` |
| Mapping, включая null/empty/error | `<...>` |
| Contract test | `<...>` |
| Protocol/lifecycle test через production client + DI | `<...>` |
| Real-app offline startup/request/task/close | `<...>` |
| Live-проверка, если отдельно разрешена | `<... или НЕ ВЫПОЛНЯЛАСЬ>` |

Adapter можно реализовать при состоянии не ниже `MAPPED`, если известны точная
операция, версия контракта, авторизация и отсутствуют существенные конфликты.
`VERIFIED` ставится только по evidence, а не по ручному статусу в анкете.

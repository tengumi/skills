---
name: harness-governance-gates
description: "Проектирует постоянные repo/CI governance gates: secret/runtime-artifact guard, dependency policy, prototype-contract verification и sanitization checks. Используй для добавления или аудита автоматических защит; проверку конкретного diff перед commit выполняет harness-pre-commit-check."
---

# harness-governance-gates

## Цель

Сделать так, чтобы агент не мог случайно пронести в репозиторий секреты, raw runtime data, запрещённые зависимости или незадокументированное отклонение от прототипа.

Этот skill дополняет `harness-pre-commit-check`: он проектирует и добавляет постоянные gates в repo/CI, а не только разово смотрит diff.

## Что Проверять

### Secrets и runtime artifacts

Блокировать:

- `.env`, `.env.*` кроме `.env.example`
- `*.pem`, `*.key`, private cert/key material
- `certs*/`, `secrets/`
- `logs/`, `results/`, raw LLM/RAG dumps
- raw domain-result JSON/JSONL, notebook outputs с confidential data
- JWT/API tokens/passwords/private keys in diff

Разрешать только sanitized fixtures, если это явно documented в `docs/harness/golden-validation.md` или аналогичном документе.

### Dependency governance

Перед добавлением dependency:

1. Проверить, нужна ли она реально.
2. Проверить team patterns (`team-conventions.md`, соседние repos).
3. Проверить внутренний registry/allowlist, если есть `deps-mcp` или documented process.
4. Зафиксировать причину в task evidence.
5. Сравнить root/project manifests, workspace sources и lock. Release список —
   baseline для diff/merge, не замена: agent-specific dependencies сохраняются,
   shared-package pin не меняется без owner approval.
6. После sync отличать import в venv от включения в frozen artifact; для
   dynamically loaded module нужен отдельный bundle smoke.

Если allowlist недоступен — спросить approval перед изменением `pyproject.toml`/lock files.

### Prototype contract

Для ported-prototype repos создать или поддерживать `docs/harness/prototype-contract.json` когда задача требует машинной проверки.

Минимальные поля контракта:

- LLM provider/model/base_url class
- timeout/retry/temperature/top_p/top_k/min_p/profanity_check/verify flags
- prompt template hashes
- schema field lists
- magic constants
- workflow steps / multi-step contract
- error handling mode per boundary
- public entrypoints и production process targets
- boundary protocol signatures, implementations и test doubles/fakes
- observed File IO semantics and exact operations for integrations that actually
  exist in the prototype; route/tool, headers, source routing and mappings are
  `N/A`, not `UNKNOWN`, when no external boundary existed
- approved target contract for any newly designed production boundary, stored
  separately from prototype parity
- terminal-state и publish-on-success rules

Gate должен падать, если contract изменился без `intentional_deviations` и approval.
`intentional_deviations` документирует уже одобренное решение, но не является
разрешением менять behavior внутри port/layout задачи. Golden expected нельзя
обновлять автоматически вслед за красным contract gate.

### CI/pre-commit integration

Добавляй checks в существующий стиль repo:

- `.pre-commit-config.yaml`, если repo уже использует pre-commit;
- `Makefile` target, например `make governance` или включение в `make verify`;
- CI pipeline, если задача разрешает менять CI.

## Workflow

1. Прочитай `AGENTS.md`, `docs/harness/conventions.md`, `cicd.md`, `env-vars.md`, `golden-validation.md`.
2. Собери текущие protected paths и artifact patterns.
3. Проверь `.gitignore` и existing pre-commit/CI.
4. Реши, нужен ли постоянный repo/CI guard или достаточно
   documentation/checklist в рамках утверждённой политики команды.
5. Если меняешь protected files (`Jenkinsfile`, `.github`, `Dockerfile`,
   `pyproject.toml`) — нужен current user approval или recorded task approval с
   exact path/scope, owner и provenance. `files_hint`/acceptance недостаточно.
6. Реализуй gate с тестами там, где логика нетривиальна.
7. Запусти verify через `harness-request-exec`, если watcher задан AGENTS/policy,
   direct runtime недоступен или пользователь явно попросил; иначе — штатно
   напрямую.
8. Если baseline требует обновить `AGENTS.md`/`docs/harness/cicd.md`, передай
   работу в `harness-context` с режимом `refresh`: ownership classification,
   показ плана, backup и
   human approval остаются обязательными. Team-owned/read-only doc получает
   proposal, а не прямую правку из governance task.

## Recommended Gate Set

Минимальный набор для Python agent/service:

- `.gitignore` covers runtime artifacts.
- `.env.example` contains placeholders only.
- `make verify` runs lint/tests.
- `make governance` or CI step scans forbidden artifacts.
- pre-commit scans obvious secrets and formatting.
- prototype contract check exists for `harness-prototype-port` repos.
- live integration outputs are excluded from commit or sanitized.

## Hard Limits

- Не печатать секретные значения в ответе пользователю; указывать file/path/pattern, но не раскрывать secret body.
- Не удалять runtime files пользователя без явной просьбы. Добавляй ignore/checks, а не стирай данные.
- Не менять dependency versions или lock files без current user approval либо
  recorded task approval с exact path/scope, owner и provenance.
- Не ослаблять existing CI/pre-commit checks.
- Не считать sanitized fixture безопасной без явного документа с правилами sanitization.

## Evidence

В task evidence укажи:

- gates added/updated;
- protected patterns;
- dependency policy result;
- prototype contract result, если применимо;
- verify command/report;
- intentional exceptions, если есть.

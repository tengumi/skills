# Deploy slice

Использовать только при `skill_mode=deploy`. Этот режим создаёт или изменяет
build/container/CI/DevSecOps artifacts по уже утверждённой target topology.

## Источники

Прочитать `AGENTS.md`, `cicd.md`, `dev-setup.md`, architecture, read-only team
docs, `team-patterns-production.md`, production-applicability и текущую задачу.
Template задаёт scaffold/runtime stack, production neighbour — implementation
pattern, release reference — build/CI baseline. Каждый факт хранить с ролью и
точным path; конфликт оставить OPEN.

Не выбирать API/worker/protocol по форме прототипа и не искать «похожий» sibling
без явного указания в задаче.

## Preflight

1. Подтвердить deploy archetype: library, CLI/frozen binary, API, worker,
   scheduler или их утверждённая комбинация.
2. Снять inventory Makefile, manifests/lock, entrypoints, generated clients,
   resources, migrations, dynamic imports и secrets/config requirements.
3. Составить identity matrix: repository, service, distribution, package,
   workspace member, artifact/image, CI job, queue и schema.
4. Выполнить negative search по старым template tokens. Доменные и external
   service names классифицировать отдельно; глобально не заменять.
5. Проверить task approvals на каждый protected path и dependency.

Неизвестные base image, CI shared library, credentials/inventory ids, SM id/name,
secret/mount names или schema owner — blocker до записи исполняемого artifact.
Placeholder/TODO не является решением.

## Реализация

Менять только применимые файлы из task scope: Dockerfile, build/freeze config,
Makefile targets, CI/Jenkins, DevSecOps config и deployment docs. Не создавать
generic файлы, если team baseline использует другой механизм.

Сохранять target dependencies: release manifest служит источником сравнения, а
не готовой заменой agent-specific списка. Новая dependency требует approval.

Для frozen/runtime artifact раздельно доказать:

1. dependency установлена в clean build environment;
2. static/dynamic module включён в bundle;
3. prompts, templates, OpenAPI, tokenizer и иные runtime data присутствуют;
4. Alembic `env.py`/versions и другие динамически загружаемые ресурсы включены,
   если они применимы;
5. каждый утверждённый entrypoint запускается из самого artifact/image.

Наличие `dist/` или успешный image build без process smoke недостаточно.

## Проверка

Выполнить воспроизводимую цепочку:

`clean install → import smoke → verify → build → artifact inventory → process smoke`

Проверить отдельно API, worker, scheduler и init/migration targets, если они
применимы. Startup, способный менять БД, разрешён только на isolated или
подтверждённо owned schema либо в доказанном migration-disabled/read-only mode.

CI не должен запускать live LLM/RAG/external-system tests без отдельного secure
stage и explicit authorization. Для live proof использовать `harness-eval` с
`skill_mode=live`.

## Hard limits

- Protected CI/Docker/build paths менять только по recorded approval с exact
  path, scope, owner и provenance; `files_hint` не является approval.
- Не писать fake identifiers, credentials, secrets, certs или `.env`.
- Не менять prompts, schemas, LLM parameters, retry или business workflow.
- Не удалять generated/runtime artifacts вне явной cleanup task.
- Не закрывать deploy-ready без clean install и запуска production entrypoints.
- Не запускать migration-capable artifact против unknown/shared DB.
- Один deploy task не должен одновременно исправлять config, DB, integration и
  business logic; новый слой возвращается в delta-plan.

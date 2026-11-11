# Railway — защищённая демонстрация на синтетических данных

Подготовлено 11 ноября 2026. Это существующее приложение; методы аналитики не меняются.
Локальные демонстрации и их PostgreSQL не используются как источник облачной базы.

## Сервисы и сборка

Workspace: `hjwkw452v7-dev's Projects`. Project: `data-driven-curriculum`
(`b923b3fc-0cfc-462d-9ac6-10bf310a8412`). Environment: `production`
(`85f18e00-33f7-4ed1-a600-d92a452a1357`). Все сервисы в регионе `iad`.

| Сервис | Root Directory / контекст Docker | Источник / запуск | Сеть |
|---|---|---|---|
| Postgres | шаблон Railway PostgreSQL, постоянный `postgres-volume` | PostgreSQL 18, Railway template | Только private networking; без TCP proxy |
| backend | `/backend`, `Dockerfile` в этом каталоге | `sh start.sh` → `python -m app.serve` | Private, `PORT=8080` |
| frontend | `/frontend`, `Dockerfile` в этом каталоге | `sh start.sh` → production `next start` | HTTPS domain, `PORT=8080` |

Backend ID: `50f9d304-e83f-4cb1-a473-16f185b234d8`.
Frontend ID: `e69f600a-c3e0-45d8-9967-0214ea8f3088`.
Postgres ID: `93b55c3d-64a3-4609-aa64-51bd97f5a376`.

Сервисам задаются Root Directory и Dockerfile через Railway API/Settings; весь репозиторий не является
контекстом каждой сборки. `COPY requirements.txt` и `COPY package*.json` разрешаются внутри соответствующего root.
Railway сообщил, что настройка `railwayConfigFile` для `railway.toml/json` устарела; поэтому эти файлы не добавлены.
Настройки применяются непосредственно к сервисам. Не запускать `dev.sh` в Railway.

Frontend: `npm ci` и `npm run build` внутри Docker build. Google Fonts/Inter загружается при холодной сборке;
нужен исходящий HTTPS. Не использовать локальный `.next` как доказательство облачной сборки.
В Dockerfile нет `ARG` с секретами. `API_URL`, `API_TOKEN`, Basic Auth читаются сервером во время выполнения.
`.dockerignore` исключает `.env*`, логи и локальные зависимости/кэши.

## Запуск и private networking

Railway передаёт `PORT`; оба entrypoint его учитывают. Значения по умолчанию сохраняют локальные порты
8010/3010. Shell выполняет `exec`, поэтому сигналы завершения доходят до Python/Node.
Backend создаёт явный dual-stack IPv6 socket (`IPV6_V6ONLY=0`), принимает IPv4 и IPv6; при отсутствии поддержки
IPv6 используется IPv4. Next.js слушает `::` (в Node dual-stack по умолчанию).
Новые Railway environments имеют A и AAAA записи; старые могут иметь только AAAA.
Подтверждение доступности — запрос frontend readiness к private backend и проверка БД, не только лог запуска.
Браузер использует относительные `/api/*` того же HTTPS origin; private HTTP не попадает в браузер.

## Переменные — без значений секретов

Backend:

- `DATABASE_URL=${{Postgres.DATABASE_URL}}` — приватная база этого environment.
- `API_TOKEN` — новый случайный облачный токен, не локальный.
- `PORT=8080`, `RUN_MIGRATIONS_ON_START=false`, `ENABLE_DATA_RESET=false`.
- `MAX_UPLOAD_MB=10`, `MAX_UPLOAD_ROWS=200000`, `PREVIEW_TTL_MINUTES=60`.
- `CORS_ORIGINS` пуст: браузер общается с Next.js того же origin, а не напрямую с backend.
- `LLM_PROVIDER=none`, `LLM_API_KEY` пуст — до безопасной настройки **нового** Gemini-ключа.
- Для последующего подключения: `LLM_PROVIDER=openai_compatible`,
  `LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`,
  `LLM_MODEL=gemini-3.8-flash`, `LLM_TIMEOUT_SECONDS=60`.

Frontend:

- `API_URL=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:${{backend.PORT}}`.
- `API_TOKEN=${{backend.API_TOKEN}}` — reference variable, то же значение.
- `DEMO_BASIC_AUTH_USER`, `DEMO_BASIC_AUTH_PASSWORD` — отдельный доступ посетителя.
- `PORT=8080`.

Никаких `NEXT_PUBLIC_*` с секретами. LLM-ключ, DATABASE_URL и admin token не задаются frontend.
Reset выключен; ADMIN_TOKEN не нужен. Basic Auth защищает HTML, данные, PDF и статические файлы из public;
внутренние статические assets Next остаются доступны как в существующей политике приложения.
Единственное специальное исключение приложения — точный `/api/health`: минимальная готовность без данных.

Секреты доступны владельцу в Railway → нужный сервис → Variables. Новые локальные данные доступа сохранены в
игнорируемом `verification/railway-private.env`, права 0600. Не коммитить, не прикреплять в отчёты и не пересылать
этот файл. Для выдачи доступа судьям используйте защищённый канал/менеджер паролей, только пару Basic Auth,
а не внутренний API token. Прежний Gemini-ключ не переносить; его ротация не подтверждена.

## Миграции

Backend Pre-deploy Command: `alembic upgrade head`, timeout 180 секунд. Эта команда выполняется отдельным
контейнером в private network после сборки, до подачи трафика. Ошибка блокирует deployment.
`RUN_MIGRATIONS_ON_START=false` исключает повторный запуск миграций каждым worker/при рестарте. Один replica,
один worker; не запускать параллельные деплои backend. При масштабировании/параллельных release нужна отдельная
координация миграций. На standalone/Compose значение по умолчанию `true` сохраняет прежний migrate-on-start.

Settings меняет только префиксы `postgres://`/`postgresql://` на `postgresql+psycopg://`: percent-encoding пароля,
IPv6 и query остаются неизменными. Alembic экранирует `%` для ConfigParser, не изменяя реальный URL.
Базовые строки с паролями в логи не выводить. Том PostgreSQL не пересоздавать при обновлениях приложения.

## Готовность и домен

Обоим приложениям: Healthcheck Path `/api/health`, timeout 180 секунд, restart `ON_FAILURE`, max retries 3,
один replica, sleep выключен. Backend возвращает 503 при ошибке `SELECT 1`. Frontend делает private запрос
к backend с timeout 5 секунд и возвращает только `{"status":"ready"}` / `{"status":"unavailable"}`.
Неудачный ответ, недоступная БД или некорректный JSON дают 503, не ложный зелёный статус.
Обычные `/api/meta`, `/reports` и страницы без Basic Auth должны возвращать 401.

Сгенерировать Railway HTTPS domain **только для frontend**, target port 8080. Не генерировать домен backend и
не создавать публичный TCP proxy PostgreSQL. Railway deployment healthcheck не является постоянным мониторингом.
Домен и проверенный commit фиксируются в итоговом отчёте о фактическом запуске.

## Первый импорт и безопасная приёмка

После проверки, что DATABASE_URL ссылается на новый Postgres этого проекта, получить meta через защищённый
frontend. Если база пустая, один раз загрузить `backend/app/assets/data/synthetic_assessments.csv` через
`POST /api/imports/preview`, проверить `ok`, предупреждения и synthetic, затем `POST /api/imports/{id}/commit`.
Ожидаемый набор: 15 830 строк, 199 учеников, 8 классов, 8 оцениваний. Это синтетические данные.
Не импортировать на каждом старте и не переносить содержимое локальных баз.

Через HTTPS проверить: anonymous 401, корректный вход, health 200, meta/overview/фильтры/topics/textbooks;
создать отдельную рекомендацию для Математика/7, проверить ограничения; запросить пояснения и проверить
реальное поле `mode`, не только HTTP 200; создать отчёт, скачать PDF с кириллицей. В браузере проверить
основные страницы, отсутствие mixed content и localhost-запросов. Сканировать выдаваемые ресурсы на новые
облачные секреты, не выводя сами значения. Не запускать разрушающий E2E против этой базы.
После повторного deployment проверить сохранность meta/overview и сохранённых объектов.

## Обновления, диагностика и откат

1. Проверить clean tree, соответствующие unit/regression tests, typecheck, lint, production build.
2. Обычный commit/push с сохранением истории. Не использовать force push.
3. Подключить оба сервиса к точному GitHub commit SHA; pin делает обновление явным, push сам по себе не меняет
   pinned deployment. Обновлять pin для обоих сервисов; затем дождаться сборок, миграции и readiness.
4. Проверить Railway deployment metadata commitHash для обоих сервисов и приёмку через HTTPS.
5. При ошибке смотреть build/deploy/pre-deploy logs; не выгружать сырой лог в общие отчёты без проверки секретов.
   Private DNS/порт/состояние Postgres → миграция → backend health → frontend private fetch → Basic Auth/domain.

Откат приложения: выбрать ранее проверенный commit/image и повторно развернуть. Миграции требуют отдельной
проверки совместимости: кодовый rollback не отменяет изменение схемы. Не делать автоматический downgrade,
reset или удаление тома. Резервные копии и их восстановление требуют отдельной настройки/проверки; не объявлять
их выполненными без фактического теста. При ограничениях тарифа/кредитов остановиться и сообщить пользователю,
не менять тариф и не подключать необязательные дополнения.

## Фактически выполненные локальные проверки

- 24 backend-теста (Railway regressions, API и boundaries), отдельная `ddc_verification_test`, порт 55434.
- 66 frontend unit tests; typecheck и lint — pass.
- Изолированная production-сборка Next.js — pass, без API/LLM/Basic Auth секретов.
- Тестируются URL с экранированными credentials/IPv6/query, Alembic interpolation, health 503 и token protection,
  реальное подключение к socket по обеим IP families; frontend readiness и Basic Auth исключение.
- Docker daemon локально отсутствует. Сборки образов и реальная private связь подтверждаются только результатами
  Railway, которые следует отделять от этих локальных тестов.

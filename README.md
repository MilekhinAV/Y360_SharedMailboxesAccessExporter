# Yandex 360 Shared Mailboxes Access Exporter

Python-скрипт для аудита доступов пользователей к общим почтовым ящикам в Яндекс 360.

Скрипт собирает:

- список сотрудников организации;
- список общих почтовых ящиков;
- подробную информацию по каждому общему ящику;
- список ящиков, доступных каждому сотруднику;
- роли доступа сотрудников к общим ящикам.

На выходе формируется CSV-отчет, удобный для проверки в Excel, LibreOffice Calc или BI-системе.

---

## Что решает скрипт

В API Яндекс 360 общий ящик часто отображается через технический `resourceId`, например:

```text
1130000069717324
````

Но в GUI панели администратора удобнее искать общий ящик по человекочитаемым данным:

```text
admins@domain.ru
Отдел администрирования
```

Поэтому скрипт дополнительно получает карточку каждого общего ящика и добавляет в CSV:

* email общего ящика;
* название общего ящика;
* описание;
* дату создания;
* дату обновления.

Итоговый отчет показывает связку:

```text
общий ящик → email общего ящика → название общего ящика → пользователь → email пользователя → ФИО → роли доступа
```

---

## Используемые API-методы

Скрипт использует методы API360.

### 1. Получение списка сотрудников

```http
GET https://api360.yandex.net/directory/v1/org/{orgId}/users
```

Метод возвращает сотрудников организации. В скрипте используется постраничная загрузка с `perPage=1000`, чтобы корректно работать с большими организациями.

Документация: UserService_List.

---

### 2. Получение списка общих ящиков

```http
GET https://api360.yandex.net/admin/v1/org/{orgId}/mailboxes/shared
```

Метод возвращает список общих ящиков организации.

Пример ответа:

```json
{
  "resources": [
    {
      "resourceId": "1130000069717324",
      "count": 3
    }
  ]
}
```

---

### 3. Получение карточки общего ящика

```http
GET https://api360.yandex.net/admin/v1/org/{orgId}/mailboxes/shared/{resourceId}
```

Метод возвращает подробную информацию об общем ящике.

Пример ответа:

```json
{
  "id": "1130000069717324",
  "email": "admins@ya-test360.ru",
  "name": "Отдел администрирования",
  "description": "",
  "createdAt": "2025-08-01T08:07:01.081Z",
  "updatedAt": "2025-08-01T08:07:00.576Z"
}
```

---

### 4. Получение ящиков, доступных сотруднику

```http
GET https://api360.yandex.net/admin/v1/org/{orgId}/mailboxes/resources/{actorId}
```

Где `actorId` — это `id` сотрудника из метода списка пользователей.

Метод возвращает общие и делегированные ящики, к которым у сотрудника есть доступ.

Пример ответа:

```json
{
  "resources": [
    {
      "resourceId": "1130000072126407",
      "type": "shared",
      "roles": [
        "shared_mailbox_owner"
      ]
    }
  ]
}
```

Скрипт берет только ресурсы с:

```text
type=shared
```

---

## Что делает скрипт по шагам

1. Получает список всех сотрудников организации.
2. Получает список всех общих ящиков.
3. По каждому `resourceId` общего ящика получает карточку ящика.
4. Формирует индекс общих ящиков по `resourceId`.
5. По каждому сотруднику вызывает метод получения доступных ему ящиков.
6. Оставляет только ящики типа `shared`.
7. Сопоставляет `resourceId` из доступов пользователя со списком общих ящиков.
8. Добавляет в отчет данные общего ящика и данные пользователя.
9. Сохраняет основной CSV-отчет.
10. Сохраняет дополнительный CSV со списком общих ящиков, по которым не найдено пользователей при обходе.

---

## Требования

* Python 3.8+
* Доступ к API360
* OAuth-токен с нужными правами
* Библиотека `requests`

---

## Установка

Склонируйте репозиторий:

```bash
git clone https://github.com/example/y360-shared-mailboxes-access-exporter.git
cd y360-shared-mailboxes-access-exporter
```

Создайте виртуальное окружение:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Установите зависимости:

```bash
python3 -m pip install requests
```

---

## Настройка переменных окружения

Скрипт использует переменные окружения:

```bash
export Y360_ORG_ID="ваша_orgID"
export Y360_TOKEN="y0_example_token_do_not_commit"
```

Где:

```text
Y360_ORG_ID
```

Идентификатор организации Яндекс 360.

```text
Y360_TOKEN
```

OAuth-токен с правами на чтение сотрудников и прав доступа к почтовым ящикам.

---

## Настройка rate limits

Скрипт содержит защиту от превышения лимитов API:

* пауза перед каждым запросом;
* повторные попытки при временных ошибках;
* обработка `429 Too Many Requests`;
* экспоненциальный backoff;
* учет заголовка `Retry-After`, если API его вернул.

Базовая настройка:

```bash
export REQUEST_DELAY_SECONDS="0.5"
export MAX_RETRIES="6"
export BACKOFF_FACTOR="2"
export MAX_BACKOFF_SECONDS="60"
```

Для больших организаций лучше использовать более спокойный режим:

```bash
export REQUEST_DELAY_SECONDS="1.0"
export MAX_RETRIES="8"
export BACKOFF_FACTOR="2"
export MAX_BACKOFF_SECONDS="120"
```

---

## Описание переменных rate limit

```text
REQUEST_DELAY_SECONDS
```

Пауза перед каждым API-запросом.

```text
MAX_RETRIES
```

Максимальное количество повторных попыток.

```text
BACKOFF_FACTOR
```

Коэффициент увеличения задержки между повторными попытками.

```text
MAX_BACKOFF_SECONDS
```

Максимальная задержка между повторными попытками.

---

## Повторяемые ошибки

Скрипт повторяет запросы при следующих HTTP-статусах:

```text
429 Too Many Requests
500 Internal Server Error
502 Bad Gateway
503 Service Unavailable
504 Gateway Timeout
```

---

## Запуск

```bash
python3 y360_shared_mailboxes_access.py
```

---

## Результат работы

После успешного запуска появятся два CSV-файла.

Основной отчет:

```text
y360_shared_mailboxes_access.csv
```

Дополнительный отчет:

```text
y360_shared_mailboxes_without_matched_users.csv
```

---

## Основной CSV-отчет

Файл:

```text
y360_shared_mailboxes_access.csv
```

Содержит найденные связки:

```text
общий ящик → пользователь → роли доступа
```

---

## Колонки основного CSV

```text
shared_mailbox_resource_id
shared_mailbox_email
shared_mailbox_name
shared_mailbox_description
shared_mailbox_created_at
shared_mailbox_updated_at
shared_mailbox_count
resource_type
roles
actor_id
user_nickname
user_email
user_full_name
user_first_name
user_last_name
user_middle_name
user_department_id
user_position
user_gender
user_birthday
user_main_phone
comment
```

---

## Описание ключевых колонок

```text
shared_mailbox_resource_id
```

Технический ID общего ящика в Яндекс 360.

```text
shared_mailbox_email
```

Email общего ящика. Самое удобное поле для поиска ящика в GUI панели администратора.

```text
shared_mailbox_name
```

Название общего ящика.

```text
shared_mailbox_description
```

Описание общего ящика.

```text
shared_mailbox_created_at
```

Дата создания общего ящика.

```text
shared_mailbox_updated_at
```

Дата последнего обновления общего ящика.

```text
shared_mailbox_count
```

Количество сотрудников, имеющих доступ к общему ящику, согласно списку общих ящиков.

```text
resource_type
```

Тип ресурса. Скрипт сохраняет только:

```text
shared
```

```text
roles
```

Роли сотрудника по отношению к общему ящику.

```text
actor_id
```

ID сотрудника. Используется как `actorId` в методе получения доступных сотруднику ящиков.

```text
user_nickname
```

Логин сотрудника.

```text
user_email
```

Email сотрудника.

```text
user_full_name
```

ФИО сотрудника.

```text
user_department_id
```

ID подразделения сотрудника.

```text
user_position
```

Должность сотрудника.

```text
comment
```

Технический комментарий. Например, ошибка получения карточки общего ящика или ошибка запроса ресурсов пользователя.

---

## Пример строки CSV

```csv
shared_mailbox_resource_id;shared_mailbox_email;shared_mailbox_name;shared_mailbox_description;shared_mailbox_created_at;shared_mailbox_updated_at;shared_mailbox_count;resource_type;roles;actor_id;user_nickname;user_email;user_full_name
1130000121212;admins@domain.ru;Отдел администрирования;;2025-08-01T08:07:01.081Z;2025-08-01T08:07:00.576Z;3;shared;shared_mailbox_owner;11300000342312;ivanov_ii;ivanov_ii@domain.ru;Иванов Иван Тестович
```

---

## Дополнительный CSV-отчет

Файл:

```text
y360_shared_mailboxes_without_matched_users.csv
```

Содержит общие ящики, которые есть в списке общих ящиков, но по обходу пользователей не удалось найти совпадающих доступов.

Колонки:

```text
shared_mailbox_resource_id
shared_mailbox_email
shared_mailbox_name
shared_mailbox_description
shared_mailbox_created_at
shared_mailbox_updated_at
shared_mailbox_count
comment
```

Возможное значение комментария:

```text
NO_MATCHED_USERS_FOUND_BY_USER_RESOURCES_SCAN
```

---

## Роли доступа

В отчете могут встречаться следующие роли:

```text
shared_mailbox_owner
```

Полные права на общий ящик.

```text
shared_mailbox_sender
```

Право отправлять письма от имени общего ящика.

```text
shared_mailbox_half_sender
```

Ограниченная отправка писем в почтовых программах.

```text
shared_mailbox_imap_admin
```

Управление ящиком в IMAP-клиенте.

Если у пользователя несколько ролей, они записываются через запятую:

```text
shared_mailbox_owner,shared_mailbox_sender
```

---

## Производительность

Скрипт делает один запрос на каждого сотрудника:

```http
GET /admin/v1/org/{orgId}/mailboxes/resources/{actorId}
```

Поэтому количество запросов примерно такое:

```text
страницы пользователей + список общих ящиков + карточки общих ящиков + количество сотрудников
```

Пример для организации с 10 000 сотрудников и 100 общими ящиками:

```text
10 запросов на пользователей при perPage=1000
1 запрос на список общих ящиков
100 запросов на карточки общих ящиков
10 000 запросов на ресурсы сотрудников
```

Для больших организаций рекомендуется:

```bash
export REQUEST_DELAY_SECONDS="1.0"
export MAX_RETRIES="8"
export MAX_BACKOFF_SECONDS="120"
```

---

## Безопасность

Не храните OAuth-токены в коде.

Неправильно:

```python
TOKEN = "real_oauth_token"
```

Правильно:

```bash
export Y360_TOKEN="y0_example_token_do_not_commit"
```

Перед публикацией репозитория проверьте, что токены не попали в:

```text
README.md
.env
исходный код
логи
историю команд
CSV-файлы
```

---

## Рекомендуемый `.gitignore`

```gitignore
.venv/
__pycache__/
*.pyc
.env
*.csv
.DS_Store
```

---

## Типовые ошибки

### 401 Unauthorized

Возможные причины:

* токен не передан;
* токен неверный;
* токен истек;
* токен был отозван;
* используется не тот OAuth-токен.

Проверьте:

```bash
echo "${Y360_ORG_ID}"
echo "${Y360_TOKEN}"
```

---

### 403 Forbidden

Возможные причины:

* у токена нет нужных прав;
* приложение не получило нужные OAuth scopes;
* пользователь, от имени которого получен токен, не имеет нужных прав;
* организация недоступна для данного токена.

---

### 404 Not Found

Возможные причины:

* неверный `orgId`;
* неверный `resourceId`;
* общий ящик был удален;
* сотрудник был удален;
* `actorId` не относится к этой организации.

---

### 429 Too Many Requests

API ограничил частоту запросов.

Увеличьте задержку:

```bash
export REQUEST_DELAY_SECONDS="1.0"
export MAX_RETRIES="8"
export MAX_BACKOFF_SECONDS="120"
```

Затем повторите запуск.

---

### USER_RESOURCES_REQUEST_ERROR

Скрипт не смог получить список ящиков, доступных конкретному сотруднику.

Причина будет видна в консоли по HTTP-статусу и тексту ответа API.

---

### SHARED_MAILBOX_DETAILS_REQUEST_ERROR

Скрипт не смог получить карточку общего ящика по `resourceId`.

Такой общий ящик все равно попадет в отчет, но поля `email`, `name`, `description`, `createdAt`, `updatedAt` могут быть пустыми.

---

## Рекомендуемый порядок запуска

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install requests

export Y360_ORG_ID="8269182"
export Y360_TOKEN="y0_example_token_do_not_commit"

export REQUEST_DELAY_SECONDS="1.0"
export MAX_RETRIES="8"
export BACKOFF_FACTOR="2"
export MAX_BACKOFF_SECONDS="120"

python3 y360_shared_mailboxes_access.py
```

---

## Назначение

Скрипт полезен для:

* аудита доступов к общим ящикам;
* проверки избыточных прав;
* подготовки отчета для ИБ;
* инвентаризации общих почтовых ящиков;
* сверки данных API с GUI панели администратора;
* подготовки к миграции или внедрению Яндекс 360;
* регулярного контроля прав доступа.

---

## Ограничения

Скрипт только читает данные.

Он не:

* создает общие ящики;
* удаляет общие ящики;
* меняет права доступа;
* меняет сотрудников;
* меняет настройки почты.

---

## Лицензия

MIT

```

Документационная база: метод `MailboxService_ListResources` возвращает общие и делегированные ящики, доступные сотруднику, включая `resourceId`, `type` и `roles`; для сотрудников используется `actorId`; роли включают `shared_mailbox_owner`, `shared_mailbox_sender`, `shared_mailbox_half_sender` и `shared_mailbox_imap_admin`. :contentReference[oaicite:1]{index=1} Метод списка сотрудников Яндекс 360 нужен для получения `id`, `nickname`, `email` и ФИО пользователя; именно `id` сотрудника используется дальше как `actorId`. 
```

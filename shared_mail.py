#!/usr/bin/env python3
import csv
import os
import sys
import time
import random
from typing import Any, Dict, List, Optional, Set

import requests


ORG_ID = os.getenv("Y360_ORG_ID")
TOKEN = os.getenv("Y360_TOKEN")

REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "0.5"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "6"))
BACKOFF_FACTOR = float(os.getenv("BACKOFF_FACTOR", "2"))
MAX_BACKOFF_SECONDS = float(os.getenv("MAX_BACKOFF_SECONDS", "60"))

API360_BASE_URL = "https://api360.yandex.net"

USERS_URL_TEMPLATE = f"{API360_BASE_URL}/directory/v1/org/{{org_id}}/users"
SHARED_MAILBOXES_URL_TEMPLATE = f"{API360_BASE_URL}/admin/v1/org/{{org_id}}/mailboxes/shared"
SHARED_MAILBOX_DETAILS_URL_TEMPLATE = f"{API360_BASE_URL}/admin/v1/org/{{org_id}}/mailboxes/shared/{{resource_id}}"
USER_RESOURCES_URL_TEMPLATE = f"{API360_BASE_URL}/admin/v1/org/{{org_id}}/mailboxes/resources/{{actor_id}}"

OUTPUT_CSV = "y360_shared_mailboxes_access.csv"
UNMATCHED_CSV = "y360_shared_mailboxes_without_matched_users.csv"

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def require_env() -> None:
    missing = []

    if not ORG_ID:
        missing.append("Y360_ORG_ID")

    if not TOKEN:
        missing.append("Y360_TOKEN")

    if missing:
        print("Не заданы переменные окружения:", ", ".join(missing))
        print()
        print("Пример:")
        print('export Y360_ORG_ID="8269182"')
        print('export Y360_TOKEN="ваш_oauth_токен"')
        sys.exit(1)


def headers() -> Dict[str, str]:
    return {
        "Authorization": f"OAuth {TOKEN}",
        "Accept": "application/json",
    }


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None

    try:
        seconds = float(value)
        if seconds >= 0:
            return seconds
    except ValueError:
        return None

    return None


def calculate_backoff_seconds(attempt: int, response: Optional[requests.Response]) -> float:
    if response is not None:
        retry_after = parse_retry_after(response.headers.get("Retry-After"))
        if retry_after is not None:
            return min(retry_after, MAX_BACKOFF_SECONDS)

    base_delay = BACKOFF_FACTOR ** attempt
    jitter = random.uniform(0, 0.5)

    return min(base_delay + jitter, MAX_BACKOFF_SECONDS)


def request_get(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    last_response: Optional[requests.Response] = None
    last_error: Optional[Exception] = None

    for attempt in range(MAX_RETRIES + 1):
        if REQUEST_DELAY_SECONDS > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        try:
            response = requests.get(
                url,
                headers=headers(),
                params=params or {},
                timeout=60,
            )

            last_response = response

            if response.status_code < 400:
                if not response.text.strip():
                    return {}
                return response.json()

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                wait_seconds = calculate_backoff_seconds(attempt, response)
                print(
                    f"Временная ошибка API: HTTP {response.status_code}. "
                    f"Повтор через {wait_seconds:.1f} сек. "
                    f"Попытка {attempt + 1}/{MAX_RETRIES}."
                )
                time.sleep(wait_seconds)
                continue

            print()
            print("Ошибка запроса")
            print("URL:", response.url)
            print("HTTP status:", response.status_code)
            print("Response:", response.text)
            response.raise_for_status()

        except requests.Timeout as error:
            last_error = error

            if attempt < MAX_RETRIES:
                wait_seconds = calculate_backoff_seconds(attempt, None)
                print(
                    f"Timeout запроса. Повтор через {wait_seconds:.1f} сек. "
                    f"Попытка {attempt + 1}/{MAX_RETRIES}."
                )
                time.sleep(wait_seconds)
                continue

            raise

        except requests.ConnectionError as error:
            last_error = error

            if attempt < MAX_RETRIES:
                wait_seconds = calculate_backoff_seconds(attempt, None)
                print(
                    f"Сетевая ошибка. Повтор через {wait_seconds:.1f} сек. "
                    f"Попытка {attempt + 1}/{MAX_RETRIES}."
                )
                time.sleep(wait_seconds)
                continue

            raise

    if last_response is not None:
        print()
        print("Запрос не выполнен после всех повторов")
        print("URL:", last_response.url)
        print("HTTP status:", last_response.status_code)
        print("Response:", last_response.text)
        last_response.raise_for_status()

    if last_error is not None:
        raise last_error

    raise RuntimeError("Неизвестная ошибка request_get")


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def get_name_part(user: Dict[str, Any], key: str) -> str:
    name = user.get("name", {})

    if not isinstance(name, dict):
        return ""

    return safe_str(name.get(key, ""))


def build_full_name(user: Dict[str, Any]) -> str:
    last = get_name_part(user, "last")
    first = get_name_part(user, "first")
    middle = get_name_part(user, "middle")

    return " ".join(part for part in [last, first, middle] if part).strip()


def get_contact_value(user: Dict[str, Any], contact_type: str, main_only: bool = True) -> str:
    contacts = user.get("contacts", [])

    if not isinstance(contacts, list):
        return ""

    for contact in contacts:
        if not isinstance(contact, dict):
            continue

        if contact.get("type") != contact_type:
            continue

        if main_only and not contact.get("main", False):
            continue

        return safe_str(contact.get("value", ""))

    return ""


def get_all_users() -> List[Dict[str, Any]]:
    users_url = USERS_URL_TEMPLATE.format(org_id=ORG_ID)

    all_users: List[Dict[str, Any]] = []
    page = 1
    per_page = 1000

    while True:
        data = request_get(
            users_url,
            params={
                "page": page,
                "perPage": per_page,
            },
        )

        users = data.get("users", [])
        total = int(data.get("total", 0) or 0)
        pages = int(data.get("pages", 0) or 0)

        if not isinstance(users, list):
            users = []

        all_users.extend(users)

        print(f"Пользователи: получено {len(all_users)} из {total}, страница {page} из {pages}")

        if not users:
            break

        if pages > 0 and page >= pages:
            break

        if total > 0 and len(all_users) >= total:
            break

        page += 1

    return all_users


def get_shared_mailboxes() -> List[Dict[str, Any]]:
    shared_url = SHARED_MAILBOXES_URL_TEMPLATE.format(org_id=ORG_ID)

    data = request_get(shared_url)
    resources = data.get("resources", [])

    if not isinstance(resources, list):
        resources = []

    print(f"Общие ящики: найдено {len(resources)}")

    return resources


def get_shared_mailbox_details(resource_id: str) -> Dict[str, Any]:
    details_url = SHARED_MAILBOX_DETAILS_URL_TEMPLATE.format(
        org_id=ORG_ID,
        resource_id=resource_id,
    )

    data = request_get(details_url)

    if not isinstance(data, dict):
        return {}

    return data


def enrich_shared_mailboxes_with_details(shared_mailboxes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    total = len(shared_mailboxes)

    for index, mailbox in enumerate(shared_mailboxes, start=1):
        resource_id = safe_str(mailbox.get("resourceId", "")).strip()

        if not resource_id:
            enriched.append(mailbox)
            continue

        print(f"[{index}/{total}] Получаю карточку общего ящика: resourceId={resource_id}")

        try:
            details = get_shared_mailbox_details(resource_id)
        except requests.HTTPError as error:
            print(f"Не удалось получить карточку общего ящика resourceId={resource_id}: {error}")
            details = {
                "id": resource_id,
                "email": "",
                "name": "",
                "description": "",
                "createdAt": "",
                "updatedAt": "",
                "details_error": "SHARED_MAILBOX_DETAILS_REQUEST_ERROR",
            }

        merged = {
            **mailbox,
            "id": safe_str(details.get("id", resource_id)),
            "email": safe_str(details.get("email", "")),
            "name": safe_str(details.get("name", "")),
            "description": safe_str(details.get("description", "")),
            "createdAt": safe_str(details.get("createdAt", "")),
            "updatedAt": safe_str(details.get("updatedAt", "")),
            "details_error": safe_str(details.get("details_error", "")),
        }

        enriched.append(merged)

    return enriched


def get_user_mailbox_resources(actor_id: str) -> List[Dict[str, Any]]:
    user_resources_url = USER_RESOURCES_URL_TEMPLATE.format(
        org_id=ORG_ID,
        actor_id=actor_id,
    )

    data = request_get(user_resources_url)
    resources = data.get("resources", [])

    if not isinstance(resources, list):
        resources = []

    return resources


def roles_to_string(roles: Any) -> str:
    if isinstance(roles, list):
        return ",".join(safe_str(role) for role in roles)

    return safe_str(roles)


def build_shared_mailboxes_index(shared_mailboxes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}

    for mailbox in shared_mailboxes:
        resource_id = safe_str(mailbox.get("resourceId", "")).strip()

        if not resource_id:
            resource_id = safe_str(mailbox.get("id", "")).strip()

        if not resource_id:
            continue

        index[resource_id] = mailbox

    return index


def make_user_error_row(user: Dict[str, Any], actor_id: str, comment: str) -> Dict[str, Any]:
    return {
        "shared_mailbox_resource_id": "",
        "shared_mailbox_email": "",
        "shared_mailbox_name": "",
        "shared_mailbox_description": "",
        "shared_mailbox_created_at": "",
        "shared_mailbox_updated_at": "",
        "shared_mailbox_count": "",
        "resource_type": "ERROR",
        "roles": "",
        "actor_id": actor_id,
        "user_nickname": safe_str(user.get("nickname", "")),
        "user_email": safe_str(user.get("email", "")),
        "user_full_name": build_full_name(user),
        "user_first_name": get_name_part(user, "first"),
        "user_last_name": get_name_part(user, "last"),
        "user_middle_name": get_name_part(user, "middle"),
        "user_department_id": safe_str(user.get("departmentId", "")),
        "user_position": safe_str(user.get("position", "")),
        "user_gender": safe_str(user.get("gender", "")),
        "user_birthday": safe_str(user.get("birthday", "")),
        "user_main_phone": get_contact_value(user, "phone", main_only=True),
        "comment": comment,
    }


def build_rows(
    users: List[Dict[str, Any]],
    shared_mailboxes_by_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    shared_mailbox_ids: Set[str] = set(shared_mailboxes_by_id.keys())

    total_users = len(users)

    for index, user in enumerate(users, start=1):
        actor_id = safe_str(user.get("id", "")).strip()

        if not actor_id:
            print(f"[{index}/{total_users}] Пропускаю пользователя без id")
            continue

        nickname = safe_str(user.get("nickname", ""))
        email = safe_str(user.get("email", ""))

        print(f"[{index}/{total_users}] Проверяю доступы: {email or nickname or actor_id}")

        try:
            resources = get_user_mailbox_resources(actor_id)
        except requests.HTTPError as error:
            print(f"Не удалось получить ресурсы для actorId={actor_id}: {error}")
            rows.append(make_user_error_row(user, actor_id, "USER_RESOURCES_REQUEST_ERROR"))
            continue

        for resource in resources:
            resource_id = safe_str(resource.get("resourceId", "")).strip()
            resource_type = safe_str(resource.get("type", "")).strip()

            if resource_type != "shared":
                continue

            if resource_id not in shared_mailbox_ids:
                continue

            shared_mailbox = shared_mailboxes_by_id.get(resource_id, {})

            details_error = safe_str(shared_mailbox.get("details_error", ""))

            rows.append(
                {
                    "shared_mailbox_resource_id": resource_id,
                    "shared_mailbox_email": safe_str(shared_mailbox.get("email", "")),
                    "shared_mailbox_name": safe_str(shared_mailbox.get("name", "")),
                    "shared_mailbox_description": safe_str(shared_mailbox.get("description", "")),
                    "shared_mailbox_created_at": safe_str(shared_mailbox.get("createdAt", "")),
                    "shared_mailbox_updated_at": safe_str(shared_mailbox.get("updatedAt", "")),
                    "shared_mailbox_count": safe_str(shared_mailbox.get("count", "")),
                    "resource_type": resource_type,
                    "roles": roles_to_string(resource.get("roles", [])),
                    "actor_id": actor_id,
                    "user_nickname": nickname,
                    "user_email": email,
                    "user_full_name": build_full_name(user),
                    "user_first_name": get_name_part(user, "first"),
                    "user_last_name": get_name_part(user, "last"),
                    "user_middle_name": get_name_part(user, "middle"),
                    "user_department_id": safe_str(user.get("departmentId", "")),
                    "user_position": safe_str(user.get("position", "")),
                    "user_gender": safe_str(user.get("gender", "")),
                    "user_birthday": safe_str(user.get("birthday", "")),
                    "user_main_phone": get_contact_value(user, "phone", main_only=True),
                    "comment": details_error,
                }
            )

    return rows


def get_csv_fieldnames() -> List[str]:
    return [
        "shared_mailbox_resource_id",
        "shared_mailbox_email",
        "shared_mailbox_name",
        "shared_mailbox_description",
        "shared_mailbox_created_at",
        "shared_mailbox_updated_at",
        "shared_mailbox_count",
        "resource_type",
        "roles",
        "actor_id",
        "user_nickname",
        "user_email",
        "user_full_name",
        "user_first_name",
        "user_last_name",
        "user_middle_name",
        "user_department_id",
        "user_position",
        "user_gender",
        "user_birthday",
        "user_main_phone",
        "comment",
    ]


def write_csv(rows: List[Dict[str, Any]]) -> None:
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=get_csv_fieldnames(), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def write_unmatched_shared_mailboxes_csv(
    rows: List[Dict[str, Any]],
    shared_mailboxes: List[Dict[str, Any]],
) -> None:
    matched_ids = {
        safe_str(row.get("shared_mailbox_resource_id", "")).strip()
        for row in rows
        if safe_str(row.get("shared_mailbox_resource_id", "")).strip()
    }

    fieldnames = [
        "shared_mailbox_resource_id",
        "shared_mailbox_email",
        "shared_mailbox_name",
        "shared_mailbox_description",
        "shared_mailbox_created_at",
        "shared_mailbox_updated_at",
        "shared_mailbox_count",
        "comment",
    ]

    with open(UNMATCHED_CSV, "w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()

        for mailbox in shared_mailboxes:
            resource_id = safe_str(mailbox.get("resourceId", "")).strip()

            if not resource_id:
                resource_id = safe_str(mailbox.get("id", "")).strip()

            if not resource_id:
                continue

            if resource_id in matched_ids:
                continue

            details_error = safe_str(mailbox.get("details_error", ""))

            writer.writerow(
                {
                    "shared_mailbox_resource_id": resource_id,
                    "shared_mailbox_email": safe_str(mailbox.get("email", "")),
                    "shared_mailbox_name": safe_str(mailbox.get("name", "")),
                    "shared_mailbox_description": safe_str(mailbox.get("description", "")),
                    "shared_mailbox_created_at": safe_str(mailbox.get("createdAt", "")),
                    "shared_mailbox_updated_at": safe_str(mailbox.get("updatedAt", "")),
                    "shared_mailbox_count": safe_str(mailbox.get("count", "")),
                    "comment": details_error or "NO_MATCHED_USERS_FOUND_BY_USER_RESOURCES_SCAN",
                }
            )


def main() -> None:
    require_env()

    print("Настройки:")
    print(f"Y360_ORG_ID={ORG_ID}")
    print(f"REQUEST_DELAY_SECONDS={REQUEST_DELAY_SECONDS}")
    print(f"MAX_RETRIES={MAX_RETRIES}")
    print(f"BACKOFF_FACTOR={BACKOFF_FACTOR}")
    print(f"MAX_BACKOFF_SECONDS={MAX_BACKOFF_SECONDS}")
    print()

    print("Шаг 1. Получаю список сотрудников организации...")
    users = get_all_users()
    print(f"Всего сотрудников получено: {len(users)}")
    print()

    print("Шаг 2. Получаю список общих ящиков организации...")
    shared_mailboxes_raw = get_shared_mailboxes()
    print()

    print("Шаг 3. Получаю email/name/description по каждому общему ящику...")
    shared_mailboxes = enrich_shared_mailboxes_with_details(shared_mailboxes_raw)
    shared_mailboxes_by_id = build_shared_mailboxes_index(shared_mailboxes)
    print(f"Всего общих ящиков в индексе: {len(shared_mailboxes_by_id)}")
    print()

    print("Шаг 4. Проверяю доступные ящики по каждому сотруднику...")
    rows = build_rows(users, shared_mailboxes_by_id)
    print()

    print("Шаг 5. Сохраняю CSV...")
    write_csv(rows)
    write_unmatched_shared_mailboxes_csv(rows, shared_mailboxes)

    print()
    print(f"Готово. Основной отчет: {OUTPUT_CSV}")
    print(f"Дополнительный отчет: {UNMATCHED_CSV}")
    print(f"Строк в основном отчете без учета заголовка: {len(rows)}")


if __name__ == "__main__":
    main()
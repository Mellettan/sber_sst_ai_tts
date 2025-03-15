import uuid

import requests
from loguru import logger


@logger.catch
def get_token(auth_token, scope) -> dict:
    """
    Выполняет POST-запрос к эндпоинту, который выдает токен.

    Параметры:
    - auth_token (str): токен авторизации, необходимый для запроса.
    - область (str): область действия запроса API. По умолчанию — «SALUTE_SPEECH_PERS».

    Возвращает:
    - ответ API, где токен и срок его "годности".
    """
    # Создадим идентификатор UUID (36 знаков)
    rq_uid = str(uuid.uuid4())

    # API URL
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

    # Заголовки
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": rq_uid,
        "Authorization": f"Basic {auth_token}",
    }

    # Тело запроса
    payload = {"scope": scope}

    response = requests.post(url, headers=headers, data=payload, verify=False)
    return response.json()

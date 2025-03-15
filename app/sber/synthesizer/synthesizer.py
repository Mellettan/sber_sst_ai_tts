import requests
from loguru import logger

from app.sber.sql.get_tokens_from_db import get_token_from_db


@logger.catch
def synthesize_speech(text, format="wav16", voice="Bys_24000") -> bytes:
    url = "https://smartspeech.sber.ru/rest/v1/text:synthesize"
    headers = {
        "Authorization": f"Bearer {get_token_from_db('salute_speech').get('token')}",
        "Content-Type": "application/text",
    }
    params = {"format": format, "voice": voice}
    response = requests.post(
        url, headers=headers, params=params, data=text.encode(), verify=False
    )

    if response.status_code == 200:
        return response.content
    else:
        logger.error(f"Ошибка синтеза: {response.status_code} - {response.json()}")

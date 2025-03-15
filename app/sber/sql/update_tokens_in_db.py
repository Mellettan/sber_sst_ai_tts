# Функция для обновления токенов в базе данных
import time
import os

import urllib3
from dotenv import load_dotenv
import sqlite3

from loguru import logger

from app.sber.get_token import get_token

load_dotenv()

SALUTE_SPEECH_API_KEY = os.getenv("SALUTE_SPEECH_API_KEY")
GIGACHAT_API_KEY = os.getenv("GIGACHAT_API_KEY")

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)  # Игнорируем предупреждение об отсутствии проверки сертификата SSL


@logger.catch
def update_tokens_if_needed():
    # Подключаемся к базе данных
    db_path = os.path.join(os.path.dirname(__file__), "..", "sber.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Токены, которые нужно проверить
    tokens_to_check = ["salute_speech", "giga_chat"]

    for token_name in tokens_to_check:
        # Проверяем, существует ли токен в таблице
        cursor.execute("SELECT expires_at FROM tokens WHERE name = ?", (token_name,))
        row = cursor.fetchone()

        current_time = int(time.time())  # Текущее время в секундах
        expires_at = row[0] if row else None

        # Если токена нет или срок действия истекает менее чем через минуту
        if not row or (expires_at // 1000 - current_time < 60):
            logger.info(f"Токен {token_name} отсутствует или истекает. Обновление...")

            # Получаем новый токен
            scope = (
                "SALUTE_SPEECH_PERS"
                if token_name == "salute_speech"
                else "GIGACHAT_API_PERS"
            )
            auth_token = (
                SALUTE_SPEECH_API_KEY
                if token_name == "salute_speech"
                else GIGACHAT_API_KEY
            )
            token_data = get_token(auth_token, scope)

            if "access_token" in token_data and "expires_at" in token_data:
                new_token = token_data["access_token"]
                new_expires_at = token_data["expires_at"]

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO tokens (name, token, expires_at)
                    VALUES (?, ?, ?)
                """,
                    (token_name, new_token, new_expires_at),
                )

                logger.info(f"Токен {token_name} успешно обновлен.")
            else:
                logger.error(f"Не удалось получить токен {token_name}: {token_data}")

    conn.commit()
    conn.close()

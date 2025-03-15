import os
import sqlite3

from loguru import logger


@logger.catch
def get_token_from_db(token_name):
    """
    Получает конкретный токен из таблицы tokens по его имени.

    Параметры:
    - token_name (str): Имя токена (например, 'salute_speech').

    Возвращает:
    - Словарь с данными о токене или None, если токен не найден.
    """
    db_path = os.path.join(os.path.dirname(__file__), "..", "sber.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Выполняем запрос для получения конкретного токена
    cursor.execute(
        "SELECT name, token, expires_at FROM tokens WHERE name = ?", (token_name,)
    )
    row = cursor.fetchone()

    conn.close()

    if row:
        return {"name": row[0], "token": row[1], "expires_at": row[2]}
    return None  # Если токен не найден

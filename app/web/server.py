import json
import os
from multiprocessing import Process
import redis

from fastapi import FastAPI, WebSocket
from loguru import logger
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from app.sber.sql.get_tokens_from_db import get_token_from_db
from app.sber.transcriber.transcriber import recognize
from app.sber.sql.update_tokens_in_db import update_tokens_if_needed
from app.sber.ai_agent.ai_agent import initialize_ai_agent, analyze_text
from app.sber.synthesizer.synthesizer import synthesize_speech

app = FastAPI()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

r = redis.StrictRedis(host="redis")


@app.websocket("/ws/recognize/")
async def websocket_recognize(websocket: WebSocket):
    update_tokens_if_needed()
    r.flushdb()  # noqa - no await
    await websocket.accept()
    logger.info("WebSocket connection established.")

    conversation = initialize_ai_agent(get_token_from_db("giga_chat").get("token"))
    last_transcription_text = None

    while True:
        if last_transcription_text == "":
            break  # Прерываем цикл, если последнее распознавание пустое

        # Запускаем gRPC-обработчик в отдельном процессе
        recognition_process = Process(target=recognize)
        recognition_process.start()
        r.delete("recognition_done")  # noqa - no await

        try:
            while recognition_process.is_alive():
                audio_data = await websocket.receive_bytes()
                logger.debug(
                    f"Received audio chunk from WebSocket: {len(audio_data)} bytes"
                )
                r.lpush("audio_chunks", audio_data)  # noqa - no await!

                transcription: bytes = r.rpop("transcriptions")  # noqa - r.rpop returns bytes
                if transcription or transcription == b"":
                    last_transcription_text = transcription.decode("utf-8")
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "transcription",
                                "status": "streaming",
                                "text": last_transcription_text,
                            }
                        )
                    )
                    logger.debug(
                        f"Sent transcription to client: {last_transcription_text}"
                    )

            if r.get("recognition_done") == b"1" and last_transcription_text:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "transcription",
                            "status": "final",
                            "text": last_transcription_text,
                        }
                    )
                )
                logger.success(
                    "Recognition process completed, starting text analysis..."
                )
                analyzed_text = analyze_text(last_transcription_text, conversation)
                await websocket.send_text(
                    json.dumps({"type": "response", "text": analyzed_text})
                )
                audio_response = synthesize_speech(analyzed_text)
                await websocket.send_bytes(audio_response)
                logger.info("Synthesized audio sent to client.")

                # Ожидаем подтверждения от клиента о завершении воспроизведения
                logger.info("Waiting for client to finish audio playback...")
                while True:
                    message = await websocket.receive()
                    if (
                        "text" in message
                        and message["text"] == "audio_playback_finished"
                    ):
                        logger.info(
                            "Client finished audio playback, resuming recognition cycle."
                        )
                        break
                    elif "bytes" in message:
                        logger.warning(
                            "Received unexpected audio data during playback wait, ignoring..."
                        )
                        continue  # Игнорируем бинарные данные, если они приходят
                    else:
                        logger.warning(
                            f"Received unexpected message: {message}, continuing to wait..."
                        )

        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            break
        finally:
            if recognition_process.is_alive():
                recognition_process.terminate()
                logger.info("Recognition process terminated.")

    await websocket.close()  # noqa - this code is reachable only if an exception occurs
    logger.info("WebSocket connection closed.")


@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>STT-AI-TTS</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            button { padding: 10px 20px; font-size: 18px; cursor: pointer; }
        </style>
    </head>
    <body>
        <h1>Нажми!</h1>
        <p>Нажмите кнопку, чтобы перейти к интерфейсу голосового ассистента.</p>
        <button onclick="location.href='/static/index.html'">Перейти</button>
    </body>
    </html>
    """

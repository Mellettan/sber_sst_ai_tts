import itertools
import os
from typing import Generator

import redis

from loguru import logger
import grpc  # noqa (poetry add grpcio)

from app.sber.sql.get_tokens_from_db import get_token_from_db
from app.sber.transcriber import recognition_pb2, recognition_pb2_grpc

SAMPLE_RATE = 16000
output_file = "output.pcm"
current_file = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
cert_path = os.path.join(project_root, "rtr_ca.pem")
SALUTE_SPEECH_TOKEN = get_token_from_db("salute_speech").get("token")

ENCODING_PCM = "pcm"

ENCODINGS_MAP = {
    ENCODING_PCM: recognition_pb2.RecognitionOptions.AudioEncoding.PCM_S16LE,
    "opus": recognition_pb2.RecognitionOptions.AudioEncoding.OPUS,
    "mp3": recognition_pb2.RecognitionOptions.AudioEncoding.MP3,
    "flac": recognition_pb2.RecognitionOptions.AudioEncoding.FLAC,
    "alaw": recognition_pb2.RecognitionOptions.AudioEncoding.ALAW,
    "mulaw": recognition_pb2.RecognitionOptions.AudioEncoding.MULAW,
    "g729": recognition_pb2.RecognitionOptions.AudioEncoding.G729,
}


# TODO: Определение конца предложения на основе тишины. (SILERO_VAD)
# TODO: SpeakerSeparationOptions.enable - добавить определение голосов
# TODO: Нейронки для определения конца фразы (https://www.perplexity.ai/search/ia-sobiraius-sobrat-golosovogo-JCO9hxAnRGKGIeTtT3f9LA)
# TODO: RAG (https://habr.com/ru/articles/779526/)
# TODO: Нейронка для определения - к чему обращаться и где искать


class Arguments:
    NOT_RECOGNITION_OPTIONS = {
        "host",
        "token",
        "file",
        "normalized_result",
        "emotions_result",
        "metadata",
        "ca",
    }
    DURATIONS = {"no_speech_timeout", "max_speech_timeout", "eou_timeout"}
    REPEATED = {"words", "insight_models"}
    HINTS_PREFIX = "hints_"
    SPEAKER_SEPARATION_PREFIX = "speaker_separation_options_"
    NORMALIZATION_PREFIX = "normalization_options_"
    OPTIONAL_BOOL_FIELDS = {
        "enable_multi_utterance",
        "enable_partial_results",
        "enable_vad",
        "custom_ws_flow_control",
        "enable_long_utterances",
    }

    def __init__(self):
        super().__setattr__("recognition_options", recognition_pb2.RecognitionOptions())

    def __setattr__(self, key, value):
        if key in self.NOT_RECOGNITION_OPTIONS:
            super().__setattr__(key, value)
        elif key.startswith(self.HINTS_PREFIX):
            key = key[len(self.HINTS_PREFIX) :]
            self._set_option(self.recognition_options.hints, key, value)
        elif key.startswith(self.SPEAKER_SEPARATION_PREFIX):
            key = key[len(self.SPEAKER_SEPARATION_PREFIX) :]
            self._set_option(
                self.recognition_options.speaker_separation_options, key, value
            )
        elif key.startswith(self.NORMALIZATION_PREFIX):
            key = key[len(self.NORMALIZATION_PREFIX) :]
            self._set_option(
                self.recognition_options.normalization_options,
                key,
                value,
                is_optional_bool=True,
            )
        else:
            self._set_option(
                self.recognition_options, key, value, key in self.OPTIONAL_BOOL_FIELDS
            )

    def _set_option(self, obj, key, value, is_optional_bool=False):
        if key in self.DURATIONS:
            getattr(obj, key).FromJsonString(value)
        elif key in self.REPEATED:
            if value:
                getattr(obj, key).extend(value)
        elif is_optional_bool:
            getattr(obj, key).enable = value
        else:
            setattr(obj, key, value)


r = redis.StrictRedis(host="redis")


def generate_audio_chunks_from_redis() -> Generator[recognition_pb2.RecognitionRequest, None, None]:
    """Генератор, который читает аудиоданные из Redis."""
    logger.info("Starting to read audio chunks from Redis...")
    while True:
        chunk = r.brpop(["audio_chunks"], timeout=5)  # Ожидаем данные с тайм-аутом
        if chunk is None:
            logger.debug("No audio chunks available, waiting...")
            continue
        _, audio_data = chunk  # Извлекаем данные (игнорируем ключ)
        logger.debug(f"Received chunk from Redis: {len(audio_data)} bytes")
        yield recognition_pb2.RecognitionRequest(audio_chunk=audio_data)


def recognize() -> None:
    args = Arguments()
    args.host = "smartspeech.sber.ru"
    args.ca = cert_path
    args.token = SALUTE_SPEECH_TOKEN
    args.audio_encoding = ENCODINGS_MAP[ENCODING_PCM]
    args.channels_count = 1  # Количество каналов
    args.enable_partial_results = True
    #  args.enable_multi_utterance = True
    args.enable_vad = True  # TODO: Что это?
    args.metadata = []
    args.sample_rate = SAMPLE_RATE  # Частота дискретизации
    args.language = "ru-RU"  # Язык
    args.no_speech_timeout = "4s"  # Таймаут без речи
    args.max_speech_timeout = "20s"  # Максимальный таймаут речи

    ssl_cred = grpc.ssl_channel_credentials(
        root_certificates=open(args.ca, "rb").read() if args.ca else None,
    )
    token_cred = grpc.access_token_call_credentials(args.token)

    channel = grpc.secure_channel(
        args.host, grpc.composite_channel_credentials(ssl_cred, token_cred)
    )

    stub = recognition_pb2_grpc.SmartSpeechStub(channel)

    metadata_pairs = [
        (args.metadata[i], args.metadata[i + 1])
        for i in range(0, len(args.metadata), 2)
    ]

    con = stub.Recognize(
        itertools.chain(
            (recognition_pb2.RecognitionRequest(options=args.recognition_options),),
            generate_audio_chunks_from_redis(),
        ),
        metadata=metadata_pairs,
    )

    try:
        logger.info("Starting recognition...")
        for resp in con:
            if resp.HasField("transcription"):
                transcription = resp.transcription
                normalized_text = transcription.results[0].normalized_text
                logger.info(
                    f"Transcription (eou={transcription.eou}): {normalized_text}"
                )
                # Сохраняем результат в Redis для отправки клиенту
                r.lpush("transcriptions", normalized_text if normalized_text else "")
            else:
                logger.warning(f"Non-transcription response: {resp}")

    except grpc.RpcError as e:
        logger.error(f"gRPC error: {e.code()}, details: {e.details()}")
    except Exception as e:
        logger.error(f"Error: {str(e)}")
    finally:
        channel.close()
        logger.info("gRPC recognition finished.")
        r.set("recognition_done", "1")

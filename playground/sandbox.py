import argparse
import itertools
import sys
import time
import wave
from pprint import pprint

import pyaudio
from loguru import logger
import grpc
import sounddevice

import recognition_pb2
import recognition_pb2_grpc
from app.sber.sql.get_tokens_from_db import get_token_from_db
from app.sber.sql.update_tokens_in_db import update_tokens_if_needed

CHUNK_SIZE = 1024 * 2  # размер в байтах
SAMPLE_RATE = 16000
output_file = "output.pcm"

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


def generate_audio_chunks_from_mic(sample_rate, chunk_size=CHUNK_SIZE):
    # Инициализация PyAudio
    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=pyaudio.paInt16,  # 16-битный PCM
        channels=1,  # Количество каналов
        rate=sample_rate,  # Частота дискретизации
        input=True,  # Входной поток
        frames_per_buffer=chunk_size,
    )

    logger.debug("Starting microphone input...")
    try:
        while True:
            data = stream.read(chunk_size, exception_on_overflow=True)
            logger.debug(f"Received chunk: {repr(data)[:20]}...")
            yield recognition_pb2.RecognitionRequest(audio_chunk=data)
    finally:
        # Завершение потока
        stream.stop_stream()
        stream.close()
        audio.terminate()


def recognize(args):
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

    logger.debug("Starting recognition...")
    con = stub.Recognize(
        itertools.chain(
            (recognition_pb2.RecognitionRequest(options=args.recognition_options),),
            generate_audio_chunks_from_mic(SAMPLE_RATE),
        ),
        metadata=metadata_pairs,
    )

    try:
        logger.info("Starting recognition...")
        sys.stdout.flush()
        for resp in con:
            if resp.HasField("transcription"):
                transcription = resp.transcription
                logger.info(
                    f"Received transcription (eou={transcription.eou}, eou_reason={transcription.eou_reason}):"
                )
                logger.info(transcription.results[0].normalized_text)
                sys.stdout.flush()
            else:
                logger.warning("Received non-transcription response:", resp)
                sys.stdout.flush()

    except grpc.RpcError as err:
        logger.error(
            "RPC error: code = {}, details = {}".format(err.code(), err.details())
        )
    except Exception as exc:
        logger.error("Exception:", exc)
    else:
        logger.info("Recognition has finished")
    finally:
        channel.close()


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


def main():
    update_tokens_if_needed()
    input_device_info = sounddevice.query_devices(kind="input")
    logger.info("Starting...")
    logger.info(f"Input devices: {input_device_info}")
    args = Arguments()
    args.host = "smartspeech.sber.ru"
    args.ca = r"C:\rtr_ca.pem"
    args.token = get_token_from_db("salute_speech").get("token")
    args.audio_encoding = ENCODINGS_MAP[ENCODING_PCM]
    args.channels_count = 1  # Количество каналов
    args.enable_partial_results = True
    #   args.enable_multi_utterance = True
    args.enable_vad = True  # TODO: Что это?
    args.metadata = []
    args.sample_rate = SAMPLE_RATE  # Частота дискретизации
    args.language = "ru-RU"  # Язык
    args.no_speech_timeout = "7s"  # Таймаут без речи
    args.max_speech_timeout = "20s"  # Максимальный таймаут речи

    recognize(args)


if __name__ == "__main__":
    main()

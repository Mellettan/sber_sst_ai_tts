import argparse
import itertools
import sys
import time
from pprint import pprint

import grpc

import recognition_pb2
import recognition_pb2_grpc

CHUNK_SIZE = 2048
SLEEP_TIME = 0.1

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


def try_printing_request_id(md):
    for m in md:
        if m.key == "x-request-id":
            print("RequestID:", m.value)


def generate_audio_chunks(path, chunk_size=CHUNK_SIZE, sleep_time=SLEEP_TIME):
    with open(path, "rb") as f:
        for data in iter(lambda: f.read(chunk_size), b""):
            yield recognition_pb2.RecognitionRequest(audio_chunk=data)
            time.sleep(sleep_time)


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

    con = stub.Recognize(
        itertools.chain(
            (recognition_pb2.RecognitionRequest(options=args.recognition_options),),
            generate_audio_chunks(args.file),
        ),
        metadata=metadata_pairs,
    )

    try:
        print("Starting recognition...")
        sys.stdout.flush()  # Принудительный сброс буфера вывода
        for resp in con:
            if resp.HasField("transcription"):
                transcription = resp.transcription
                print(f"Received transcription (eou={transcription.eou}):")
                pprint(transcription, indent=2)
                sys.stdout.flush()  # Сбрасываем буфер после каждого вывода
            else:
                print("Received non-transcription response:", resp)
                sys.stdout.flush()

    except grpc.RpcError as err:
        print("RPC error: code = {}, details = {}".format(err.code(), err.details()))
    except Exception as exc:
        print("Exception:", exc)
    else:
        print("Recognition has finished")
    finally:
        try_printing_request_id(con.initial_metadata())
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
    args = Arguments()
    args.host = "smartspeech.sber.ru"
    args.ca = r"C:\rtr_ca.pem"
    args.token = r"eyJjdHkiOiJqd3QiLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.HEcbu5zQiWoXQ5j55_fnWwsescXBCYFzq7qJuXBUX58qLlbxVXh2fX6Ze6z49e75heEBCNFdxLG_V6dgE94oSgfv1FTYi6HXsCz64VVxPhOE0mv3SqeLQIU_wLiPj1wJkJ0C38zeyEN8ZdyRJSVffTzcA94tYO4Bcn5myHijEhPiEk9S3epg3I6GR7w54aAg_aMGE4slZqg9J85Ku96JWS7YBMQRn6GpRqxs5IJIeKGrTFmaXAJGDrico7Q6h6JtCkoPPRHYJsmT7k-4DvzJucti2US5e4CChLrT3ItbPHAVwgPWPH96hn17EN5ZkXEnUSZg5e2CjCa2uMg7Eac5Fg.V46pxQ766rSaR0hBY3gc1Q.tfjRhAKzcHGFBAnJdtE-8YPAX_J3k4AlYuW9NmvsIOPWnTj1GFiQRomRKjWtAnQT_ejHM1al2_VbzD2tfks9F9ydMPPpHuzH-WaV4GAUK24Oda1uUZyprWu_vtWqADz04DQ3P3jVJtyV9q_DcQaT2-WmmB_yJBO_1qifGpZbag3LYIZObkH0hu3S5RxuqCWGkE5KZ5QmLy6BCGjh0HcnMpIlh_A0AM9GdSt_ZY8H8uXgJPcFUmFu1DBwxiFQgSWQ_HQSqVyssw0HnVpZHsXtF13AfrCkz6sCfXuonQiYC21hvdloytmOEBgLLjeXYHmPUd15H82Hfgt-SekqRxGK1c3LWQwo4K2kZcvR0ewZ2u1bZAG0Z_m1cU2PytNiInOveoYiGlvDW2_ZT4PDOdOEcsSV8RbpqocI9k238pYOCODPmgjXMYe3Owy0mv3M9loDAwxC5Ufazd6yWSG8TGWP7vL71zSwYe9IHd4eXujFh0aZbYdNAV_OLm9bAt9V0Ig-V25MFadXtVrAS2dv0Bu3aCZ9NvU1ZsD3K7L8MxSVY74OIytLRQJulUBY2medizhi7ees9BRsJ0JbZQMo1wl0QoEzl_3ohjK_5RlvehrdkOsBvuB83pv3F2RtwwM68TwdfFjy1JoTinnBhDzjIqx6OI_2AhMxGKI4zt_m-x0Tg5EH0ySZW44MDVjRUPQSZUdN_tEzWNYuAUF4uHySvcm0fOaODzqks9DxpvVb2Becgxk.dXETJirr4e7zMvX8ndqxdQwc7V-krNYWl4DHEVP8Yk0"
    args.file = r"D:\PyCharm Community Edition 2023.2.1\Projects\vocode_main\playground\output.pcm"
    args.audio_encoding = ENCODINGS_MAP[ENCODING_PCM]
    args.channels_count = 1  # Количество каналов
    args.enable_partial_results = True
    args.metadata = []
    args.sample_rate = 16000  # Частота дискретизации
    args.language = "ru-RU"  # Язык
    args.no_speech_timeout = "7s"  # Таймаут без речи
    args.max_speech_timeout = "20s"  # Максимальный таймаут речи

    recognize(args)


if __name__ == "__main__":
    main()

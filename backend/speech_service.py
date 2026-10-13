import base64
import os
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from openai import OpenAI


MAX_AUDIO_BYTES = 6 * 1024 * 1024
MAX_REQUESTS_PER_MINUTE = 6
ALLOWED_AUDIO_TYPES = {
    "audio/aac",
    "audio/flac",
    "audio/m4a",
    "audio/mp3",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/opus",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
}

_requests_by_ip: dict[str, deque[float]] = defaultdict(deque)
_request_lock = Lock()


def normalize_audio_type(content_type: str | None) -> str:
    return str(content_type or "").split(";", 1)[0].strip().lower()


def allow_speech_request(client_ip: str) -> bool:
    now = monotonic()
    cutoff = now - 60
    key = client_ip or "unknown"
    with _request_lock:
        bucket = _requests_by_ip[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= MAX_REQUESTS_PER_MINUTE:
            return False
        bucket.append(now)
        return True


def transcribe_audio(audio: bytes, content_type: str) -> str:
    mime_type = normalize_audio_type(content_type)
    if mime_type not in ALLOWED_AUDIO_TYPES:
        raise ValueError("unsupported audio type")
    if not audio:
        raise ValueError("empty audio")
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("audio too large")

    api_key = os.getenv(
        "SPEECH_OPENAI_API_KEY",
        os.getenv("CHAT_OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", "")),
    ).strip()
    if not api_key:
        raise RuntimeError("speech service is not configured")

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv(
            "SPEECH_OPENAI_BASE_URL",
            os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ),
        timeout=float(os.getenv("SPEECH_OPENAI_TIMEOUT_SECONDS", "45")),
        max_retries=0,
    )
    encoded = base64.b64encode(audio).decode("ascii")
    data_uri = f"data:{mime_type};base64,{encoded}"
    completion = client.chat.completions.create(
        model=os.getenv("SPEECH_OPENAI_MODEL", "qwen3-asr-flash"),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_uri},
                    }
                ],
            },
        ],
        extra_body={"asr_options": {"language": "zh", "enable_itn": True}},
    )
    text = str(completion.choices[0].message.content or "").strip()
    if not text:
        raise ValueError("speech was not recognized")
    return text

import atexit
from typing import Tuple

from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler

from functools import lru_cache

from src.config import LANGFUSE_PUBLIC_KEY ,LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL


@lru_cache(maxsize=1)
def _init_langfuse_singleton(
    public_key: str,
    secret_key: str,
    host: str,
    flush_at: int,
    flush_interval: float,
):
    Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
        flush_at=flush_at,
        flush_interval=flush_interval,
    )
    return get_client()


def init_langfuse(
    public_key: str = LANGFUSE_PUBLIC_KEY,
    secret_key: str = LANGFUSE_SECRET_KEY,
    host: str = LANGFUSE_BASE_URL,
    auto_flush: bool = True,
    flush_at: int = 1,
    flush_interval: float = 1,
) -> Tuple[CallbackHandler, object]:

    client = _init_langfuse_singleton(
        public_key,
        secret_key,
        host,
        flush_at,
        flush_interval,
    )

    if auto_flush:
        atexit.register(client.flush)

    handler = CallbackHandler()
    return handler, client

import logging
from collections.abc import Iterator

import openai
from openai import OpenAI

from ..ports import CapabilityUnavailable, CompletionGateway

log = logging.getLogger("helpdesk.gateway")


class GatewayClient(CompletionGateway):
    """Implementa o port falando com o AI Gateway (LiteLLM) no formato Chat Completions,
    com a chave do próprio gateway. Único componente da aplicação que chama o gateway."""

    def __init__(self, base_url: str, api_key: str, timeout_s: float):
        # Sem retry no SDK: retry e fallback são do gateway, e retries em camadas se multiplicam.
        # O timeout é o teto da aplicação para a chamada inteira, com fallbacks incluídos.
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=0)

    def complete(self, capability: str, prompt: str, max_tokens: int | None = None) -> str:
        try:
            response = self._client.chat.completions.create(**self._request(capability, prompt, max_tokens))
        except openai.APIError as error:
            raise self._unavailable(capability, error) from error
        log.info("capability=%s served_by=%s", capability, response.model)
        return response.choices[0].message.content

    def stream(self, capability: str, prompt: str, max_tokens: int | None = None) -> Iterator[str]:
        try:
            chunks = self._client.chat.completions.create(**self._request(capability, prompt, max_tokens),
                                                          stream=True)
            for chunk in chunks:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except openai.APIError as error:
            # Vale para a falha antes do primeiro trecho e para a falha no meio do stream,
            # que o gateway repassa como um evento de erro e o SDK levanta aqui.
            raise self._unavailable(capability, error) from error

    @staticmethod
    def _request(capability: str, prompt: str, max_tokens: int | None) -> dict:
        request = {"model": capability, "messages": [{"role": "user", "content": prompt}]}
        if max_tokens:
            request["max_tokens"] = max_tokens
        return request

    @staticmethod
    def _unavailable(capability: str, error: openai.APIError) -> CapabilityUnavailable:
        if isinstance(error, openai.APITimeoutError):
            reason = "o gateway não respondeu dentro do prazo"
        elif isinstance(error, openai.APIStatusError):
            reason = f"o gateway recusou ou falhou (HTTP {error.status_code})"
        else:
            reason = "a geração foi interrompida"
        log.warning("capability=%s unavailable: %s (%s)", capability, reason, error)
        return CapabilityUnavailable(capability, reason)

from openai import OpenAI

from ..ports import CompletionGateway


class GatewayClient(CompletionGateway):
    """Implementa o port falando com o AI Gateway (LiteLLM) no formato Chat Completions,
    com a chave do próprio gateway."""

    def __init__(self, base_url: str, api_key: str, timeout_s: float):
        # Sem retry no SDK: retry e fallback são do gateway, e retries em camadas se multiplicam.
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=0)

    def complete(self, capability: str, prompt: str, max_tokens: int | None = None) -> str:
        extra = {"max_tokens": max_tokens} if max_tokens else {}
        response = self._client.chat.completions.create(
            model=capability,
            messages=[{"role": "user", "content": prompt}],
            **extra,
        )
        return response.choices[0].message.content

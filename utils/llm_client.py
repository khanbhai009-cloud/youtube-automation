import os
import time


class LLMClient:
    def __init__(self):
        self._groq = None
        self._cerebras = None
        self.groq_model = "llama-3.3-70b-versatile"
        self.cerebras_model = "llama-3.3-70b"

    def _get_groq(self):
        if self._groq is None:
            from groq import Groq
            self._groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
        return self._groq

    def _get_cerebras(self):
        if self._cerebras is None:
            from cerebras.cloud.sdk import Cerebras
            self._cerebras = Cerebras(api_key=os.getenv("CEREBRAS_API_KEY"))
        return self._cerebras

    def _call_groq(self, messages: list, max_tokens: int, temperature: float) -> str:
        resp = self._get_groq().chat.completions.create(
            model=self.groq_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content

    def _call_cerebras(self, messages: list, max_tokens: int) -> str:
        resp = self._get_cerebras().chat.completions.create(
            model=self.cerebras_model,
            messages=messages,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content

    def complete(
        self,
        messages: list,
        max_tokens: int = 3000,
        temperature: float = 0.85,
        task_type: str = "creative",
    ) -> str:
        """
        Send a completion request with task-based model routing.

        task_type='creative'  → Groq first, Cerebras on failure
        task_type='logical'   → Cerebras first, Groq on failure
        """
        if task_type == "logical":
            try:
                print("[LLM] Trying Cerebras (logical task)...")
                return self._call_cerebras(messages, max_tokens)
            except Exception as e:
                print(f"[LLM] Cerebras failed: {e}. Switching to Groq...")
                time.sleep(1)
                try:
                    return self._call_groq(messages, max_tokens, temperature)
                except Exception as e2:
                    raise RuntimeError(f"Both LLMs failed — Cerebras: {e} | Groq: {e2}")
        else:
            try:
                print("[LLM] Trying Groq (creative task)...")
                return self._call_groq(messages, max_tokens, temperature)
            except Exception as e:
                print(f"[LLM] Groq failed: {e}. Switching to Cerebras...")
                time.sleep(1)
                try:
                    return self._call_cerebras(messages, max_tokens)
                except Exception as e2:
                    raise RuntimeError(f"Both LLMs failed — Groq: {e} | Cerebras: {e2}")

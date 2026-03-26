import os
import time
from groq import Groq
from cerebras.cloud.sdk import Cerebras

class LLMClient:
    def __init__(self):
        self.groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.cerebras = Cerebras(api_key=os.getenv("CEREBRAS_API_KEY"))
        self.groq_model = "llama-3.3-70b-versatile"
        self.cerebras_model = "llama-3.3-70b"

    def complete(self, messages: list, max_tokens: int = 3000, temperature: float = 0.85) -> str:
        try:
            print("[LLM] Trying Groq...")
            resp = self.groq.chat.completions.create(
                model=self.groq_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"[LLM] Groq failed: {e}. Switching to Cerebras...")
            time.sleep(1)
            try:
                resp = self.cerebras.chat.completions.create(
                    model=self.cerebras_model,
                    messages=messages,
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content
            except Exception as e2:
                raise RuntimeError(f"Both LLMs failed — Groq: {e} | Cerebras: {e2}")

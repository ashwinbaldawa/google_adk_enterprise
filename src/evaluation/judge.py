"""
LLM Judge abstraction.

Currently uses Ollama locally. Swap to Vertex AI Eval SDK or Gemini
by implementing a new judge class with the same interface.
"""

import logging
import os
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger(__name__)


class BaseJudge(ABC):
    """Abstract judge interface for evaluation."""

    @abstractmethod
    def evaluate(self, prompt: str) -> str:
        """Send prompt to judge LLM and return response text."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...


class OllamaJudge(BaseJudge):
    """Judge using local Ollama instance."""

    def __init__(
        self,
        model: str = None,
        host: str = None,
        timeout: int = 120,
    ):
        self._model = model or os.getenv("JUDGE_MODEL", "llama3.2")
        self._host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model

    def evaluate(self, prompt: str) -> str:
        try:
            resp = requests.post(
                f"{self._host}/api/generate",
                json={"model": self._model, "prompt": prompt, "stream": False},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except Exception as e:
            logger.error("Ollama judge call failed: %s", e)
            return ""


def parse_judge_response(response: str) -> tuple[str, float, str]:
    """
    Parse structured judge response.

    Expected format:
        LABEL: <label>
        SCORE: <0.0-1.0>
        REASON: <explanation>
    """
    label = "unknown"
    score = 0.0
    reason = response

    for line in response.split("\n"):
        line = line.strip()
        upper = line.upper()
        if upper.startswith("LABEL:"):
            label = line.split(":", 1)[1].strip().lower()
        elif upper.startswith("SCORE:"):
            try:
                score = float(line.split(":", 1)[1].strip())
                score = max(0.0, min(1.0, score))
            except ValueError:
                pass
        elif upper.startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()

    return label, score, reason

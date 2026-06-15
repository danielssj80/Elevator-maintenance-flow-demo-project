from typing import Any

import boto3
from botocore.config import Config

from app.core.config import settings


class BedrockClient:
    def __init__(self, boto_client: Any = None, model_id: str | None = None) -> None:
        self._model_id = model_id or settings.bedrock_model_id
        timeout = settings.briefing_timeout_seconds
        self._client = boto_client or boto3.client(
            "bedrock-runtime",
            region_name=settings.bedrock_region,
            config=Config(
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={"max_attempts": 1},
            ),
        )

    def generate(self, system_prompt: str, user_message: str) -> str:
        response = self._client.converse(
            modelId=self._model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"maxTokens": 450, "temperature": 0.3},
        )
        return response["output"]["message"]["content"][0]["text"]

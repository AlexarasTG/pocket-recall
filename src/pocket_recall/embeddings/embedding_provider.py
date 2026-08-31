"""Turn text into vectors with the local FastEmbed model."""

import json
import os
from importlib.metadata import version

import numpy as np

from pocket_recall.config import MemoryConfig
from pocket_recall.embeddings import model_specification
from pocket_recall.errors import EmbeddingError


class EmbeddingProvider:
    """Load a fixed model revision and produce normalized, 384-number vectors."""

    @staticmethod
    def specification() -> str:
        return json.dumps(
            {
                "provider": "fastembed",
                "provider_version": version("fastembed"),
                "runtime_version": version("onnxruntime"),
                "model": model_specification.MODEL_NAME,
                "repository": model_specification.MODEL_REPOSITORY,
                "revision": model_specification.MODEL_REVISION,
                "dimensions": model_specification.DIMENSIONS,
                "input_format_version": 1,
                "query_instruction": model_specification.QUERY_INSTRUCTION,
                "vector_format": "normalized-float32-le",
            },
            sort_keys=True,
        )

    def __init__(self, config: MemoryConfig, *, allow_download: bool = False) -> None:
        try:
            # The runtime's API opt-out happens too late to prevent import-time telemetry.
            os.environ["ORT_DISABLE_TELEMETRY"] = "1"
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            import onnxruntime

            onnxruntime.disable_telemetry_events()
            from fastembed import TextEmbedding
            from huggingface_hub import snapshot_download

            config.model_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            model_path = snapshot_download(
                repo_id=model_specification.MODEL_REPOSITORY,
                revision=model_specification.MODEL_REVISION,
                cache_dir=str(config.model_directory),
                local_files_only=not allow_download,
                allow_patterns=["*.json", "vocab.txt", "model_optimized.onnx"],
            )
            self.model = TextEmbedding(
                model_name=model_specification.MODEL_NAME,
                specific_model_path=model_path,
                cache_dir=str(config.model_directory),
                local_files_only=True,
                threads=config.embedding_threads,
                providers=["CPUExecutionProvider"],
            )
            # Count the complete input and reject overflow instead of silently losing text.
            self.model.model.tokenizer.no_truncation()
        except Exception as error:
            raise EmbeddingError(f"Could not load the local model; run memory maintenance init: {error}") from error

    def embed(self, text: str) -> bytes:
        try:
            token_count = self.model.token_count(text)
        except Exception as error:
            raise EmbeddingError(f"Could not tokenize the embedding input: {error}") from error
        if token_count > model_specification.TOKEN_LIMIT:
            raise EmbeddingError(
                f"Embedding input has {token_count} tokens; the model limit is {model_specification.TOKEN_LIMIT}. "
                "Shorten the query or the memory's title, aliases, and body."
            )
        try:
            vector = np.asarray(next(self.model.embed([text], batch_size=1, parallel=None)), dtype="<f4")
        except Exception as error:
            raise EmbeddingError(f"The local model could not embed the text: {error}") from error
        if vector.shape != (model_specification.DIMENSIONS,) or not np.isfinite(vector).all():
            raise EmbeddingError("The local model returned an invalid vector")
        length = float(np.linalg.norm(vector))
        if length == 0:
            raise EmbeddingError("The local model returned a zero-length vector")
        return (vector / length).astype("<f4").tobytes()

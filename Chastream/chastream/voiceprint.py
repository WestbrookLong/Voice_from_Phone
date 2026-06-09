from __future__ import annotations

import secrets
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from .config import configure_local_caches
from .models import SpeakerCollection, SpeakerMatch, VoiceElement
from .storage import ProfileRepository


CAMPP_MODEL_ID = "iic/speech_campplus_sv_zh_en_16k-common_advanced"


def normalize_embedding(value) -> np.ndarray:
    embedding = np.asarray(value, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(embedding))
    if norm <= 1e-8:
        raise RuntimeError("Speaker model returned an empty embedding.")
    return embedding / norm


def cosine_similarity(left, right) -> float:
    return float(np.dot(normalize_embedding(left), normalize_embedding(right)))


class CampPlusEmbeddingProvider:
    def __init__(self, model_id: str = CAMPP_MODEL_ID) -> None:
        configure_local_caches()
        self.model_id = model_id
        self._pipeline = None
        self._lock = threading.RLock()

    def available(self) -> tuple[bool, str]:
        try:
            import addict  # noqa: F401
            import modelscope  # noqa: F401
            import torch  # noqa: F401
        except Exception as exc:
            return False, str(exc)
        return True, ""

    def _get_pipeline(self):
        with self._lock:
            if self._pipeline is None:
                ok, message = self.available()
                if not ok:
                    raise RuntimeError(f"CAM++ dependencies are incomplete: {message}")
                from modelscope.pipelines import pipeline

                self._pipeline = pipeline(
                    task="speaker-verification",
                    model=self.model_id,
                    model_revision="v1.0.0",
                )
            return self._pipeline

    def extract(self, audio_path: Path) -> np.ndarray:
        with self._lock:
            result = self._get_pipeline()([str(audio_path), str(audio_path)], output_emb=True)
        embeddings = result.get("embs")
        if embeddings is None or len(embeddings) < 1:
            raise RuntimeError("CAM++ did not return an embedding.")
        return normalize_embedding(embeddings[0])


class VoiceprintService:
    def __init__(
        self,
        provider: CampPlusEmbeddingProvider | None = None,
        repository: ProfileRepository | None = None,
    ) -> None:
        self.provider = provider or CampPlusEmbeddingProvider()
        self.repository = repository or ProfileRepository()

    def build_element(
        self,
        name: str,
        sample_paths: list[Path],
        progress: Callable[[int, int], None] | None = None,
    ) -> VoiceElement:
        if not name.strip():
            raise ValueError("Speaker name is required.")
        if not sample_paths:
            raise ValueError("At least one voice sample is required.")
        embeddings = []
        for index, path in enumerate(sample_paths, start=1):
            embeddings.append(self.provider.extract(path))
            if progress:
                progress(index, len(sample_paths))
        centroid = normalize_embedding(np.mean(np.stack(embeddings), axis=0))
        return VoiceElement(
            id=f"element-{secrets.token_hex(5)}",
            name=name.strip(),
            model_id=self.provider.model_id,
            sample_paths=[str(path) for path in sample_paths],
            embeddings=[item.tolist() for item in embeddings],
            centroid=centroid.tolist(),
        )

    def match(
        self,
        embedding,
        collections: list[SpeakerCollection],
        *,
        threshold: float,
        required_margin: float,
    ) -> SpeakerMatch:
        collection_scores = []
        for collection in collections:
            element_scores = sorted(
                (
                    (cosine_similarity(embedding, element.centroid), element)
                    for element in collection.elements
                    if not element.hidden and element.centroid
                ),
                key=lambda item: item[0],
                reverse=True,
            )
            if not element_scores:
                continue
            best_element_score, best_element = element_scores[0]
            collection_scores.append(
                {
                    "collection": collection,
                    "score": best_element_score,
                    "best_element": best_element,
                    "elements": [
                        {
                            "elementId": element.id,
                            "elementName": element.name,
                            "score": score,
                        }
                        for score, element in element_scores
                    ],
                }
            )
        collection_scores.sort(key=lambda item: item["score"], reverse=True)
        if not collection_scores:
            return SpeakerMatch(None, "未识别发言人", 0.0, 0.0, 0.0, False, "unknown")
        best = collection_scores[0]
        second = collection_scores[1] if len(collection_scores) > 1 else None
        best_score = float(best["score"])
        best_collection = best["collection"]
        best_element = best["best_element"]
        second_score = float(second["score"]) if second else -1.0
        second_collection = second["collection"] if second else None
        second_element = second["best_element"] if second else None
        margin = best_score - second_score
        accepted = best_score >= threshold and margin >= required_margin
        confidence = "high" if accepted and best_score >= threshold + 0.12 else "medium" if accepted else "low"
        return SpeakerMatch(
            profile_id=best_collection.id if accepted else None,
            display_name=best_collection.name if accepted else "未识别发言人",
            score=best_score,
            second_score=second_score,
            margin=margin,
            accepted=accepted,
            confidence=confidence,
            best_candidate_name=best_collection.name,
            second_candidate_name=second_collection.name if second_collection else "",
            best_element_id=best_element.id,
            best_element_name=best_element.name,
            second_element_id=second_element.id if second_element else "",
            second_element_name=second_element.name if second_element else "",
            collection_scores=[
                {
                    "collectionId": item["collection"].id,
                    "collectionName": item["collection"].name,
                    "score": item["score"],
                    "bestElementId": item["best_element"].id,
                    "bestElementName": item["best_element"].name,
                    "elements": item["elements"],
                }
                for item in collection_scores
            ],
        )

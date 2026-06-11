from __future__ import annotations

import threading
from pathlib import Path

from .audio import slice_wav, speech_quality
from .config import configure_local_caches
from .voiceprint import CampPlusEmbeddingProvider, cosine_similarity


SCL_MODEL_ID = "damo/speech_campplus-transformer_scl_zh-cn_16k-common"


class SpeakerChangeLocator:
    def __init__(self, embedding_provider: CampPlusEmbeddingProvider) -> None:
        configure_local_caches()
        self.embedding_provider = embedding_provider
        self._pipeline = None
        self._lock = threading.RLock()

    def _get_pipeline(self):
        with self._lock:
            if self._pipeline is None:
                from modelscope.pipelines import pipeline

                self._pipeline = pipeline(
                    task="speaker-diarization",
                    model=SCL_MODEL_ID,
                    model_revision="v1.0.0",
                )
            return self._pipeline

    def locate(self, path: Path, left_embedding, right_embedding) -> float | None:
        result = self._get_pipeline()(
            str(path),
            embds=[left_embedding, right_embedding],
            output_res=True,
        )
        if isinstance(result, tuple) and len(result) >= 2:
            change_seconds = result[1]
        elif isinstance(result, dict):
            change_seconds = result.get("change_point") or result.get("change_seconds")
        else:
            change_seconds = None
        return float(change_seconds) if change_seconds is not None else None


class SentenceChangeRefiner:
    """Uses SCL only inside one timestamped punctuation unit."""

    def __init__(
        self,
        embedding_provider: CampPlusEmbeddingProvider,
        *,
        minimum_side_ms: int = 800,
        edge_window_ms: int = 1600,
        change_probe_threshold: float = 0.24,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.minimum_side_ms = minimum_side_ms
        self.edge_window_ms = edge_window_ms
        self.change_probe_threshold = change_probe_threshold
        self.locator = SpeakerChangeLocator(embedding_provider)

    def locate(
        self,
        audio_path: Path,
        start_ms: int,
        end_ms: int,
        output_dir: Path,
        token: str,
        *,
        force_probe: bool = False,
    ) -> tuple[int | None, dict]:
        duration_ms = end_ms - start_ms
        record = {
            "startMs": start_ms,
            "endMs": end_ms,
            "durationMs": duration_ms,
            "accepted": False,
            "forcedByAmbiguousMatch": force_probe,
        }
        if duration_ms < self.minimum_side_ms * 2:
            record["reason"] = "unit_too_short"
            return None, record

        output_dir.mkdir(parents=True, exist_ok=True)
        unit_path = slice_wav(
            audio_path,
            output_dir / f"{token}.wav",
            start_ms,
            end_ms,
            padding_ms=0,
        )
        edge_ms = min(self.edge_window_ms, max(self.minimum_side_ms, duration_ms // 3))
        left_path = slice_wav(
            audio_path,
            output_dir / f"{token}-left.wav",
            start_ms,
            min(end_ms, start_ms + edge_ms),
            padding_ms=0,
        )
        right_path = slice_wav(
            audio_path,
            output_dir / f"{token}-right.wav",
            max(start_ms, end_ms - edge_ms),
            end_ms,
            padding_ms=0,
        )
        if not speech_quality(left_path)["usable"] or not speech_quality(right_path)["usable"]:
            record["reason"] = "edge_audio_not_usable"
            return None, record

        left_embedding = self.embedding_provider.extract(left_path)
        right_embedding = self.embedding_provider.extract(right_path)
        edge_similarity = cosine_similarity(left_embedding, right_embedding)
        record["edgeSimilarity"] = edge_similarity
        if edge_similarity >= self.change_probe_threshold and not force_probe:
            record["reason"] = "same_speaker_edges"
            return None, record

        local_change = self.locator.locate(unit_path, left_embedding, right_embedding)
        if local_change is None:
            record["reason"] = "scl_no_change"
            return None, record
        change_ms = start_ms + int(local_change * 1000)
        record["candidateMs"] = change_ms
        if (
            change_ms - start_ms < self.minimum_side_ms
            or end_ms - change_ms < self.minimum_side_ms
        ):
            record["reason"] = "candidate_near_unit_edge"
            return None, record

        record["accepted"] = True
        record["reason"] = "candidate"
        return change_ms, record

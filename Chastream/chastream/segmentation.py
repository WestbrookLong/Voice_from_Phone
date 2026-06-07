from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from .audio import read_wav_mono, speech_quality, write_wav_mono
from .config import configure_local_caches
from .models import AudioSegment
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
        pipeline = self._get_pipeline()
        result = pipeline(
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


class SpeakerTimelineSegmenter:
    """Finds acoustic speaker changes without using ASR speaker labels."""

    def __init__(
        self,
        embedding_provider: CampPlusEmbeddingProvider,
        *,
        minimum_segment_ms: int = 1200,
        window_ms: int = 7000,
        stride_ms: int = 3500,
        edge_window_ms: int = 1800,
        change_probe_threshold: float = 0.24,
        merge_distance_ms: int = 800,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.minimum_segment_ms = minimum_segment_ms
        self.window_ms = max(window_ms, minimum_segment_ms * 2 + 800)
        self.stride_ms = max(1000, min(stride_ms, self.window_ms))
        self.edge_window_ms = edge_window_ms
        self.change_probe_threshold = change_probe_threshold
        self.merge_distance_ms = merge_distance_ms
        self.locator = SpeakerChangeLocator(embedding_provider)

    def detect(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        enable_scl: bool,
    ) -> tuple[list[int], list[dict]]:
        if not enable_scl:
            return [], []
        samples, sample_rate = read_wav_mono(audio_path)
        duration_ms = int(len(samples) * 1000 / sample_rate)
        if duration_ms < self.minimum_segment_ms * 2:
            return [], []
        output_dir.mkdir(parents=True, exist_ok=True)
        candidates: list[int] = []
        diagnostics: list[dict] = []

        for index, start_ms in enumerate(self._window_starts(duration_ms), start=1):
            end_ms = min(duration_ms, start_ms + self.window_ms)
            if end_ms - start_ms < self.minimum_segment_ms * 2:
                continue
            token = f"probe-{index:04d}"
            window_path = self._write_range(
                samples, sample_rate, output_dir / f"{token}.wav", start_ms, end_ms
            )
            left_path = self._write_range(
                samples,
                sample_rate,
                output_dir / f"{token}-left.wav",
                start_ms,
                min(end_ms, start_ms + self.edge_window_ms),
            )
            right_path = self._write_range(
                samples,
                sample_rate,
                output_dir / f"{token}-right.wav",
                max(start_ms, end_ms - self.edge_window_ms),
                end_ms,
            )
            record = {"windowStartMs": start_ms, "windowEndMs": end_ms, "accepted": False}
            if not speech_quality(left_path)["usable"] or not speech_quality(right_path)["usable"]:
                record["reason"] = "edge_audio_not_usable"
                diagnostics.append(record)
                continue
            left_embedding = self.embedding_provider.extract(left_path)
            right_embedding = self.embedding_provider.extract(right_path)
            edge_similarity = cosine_similarity(left_embedding, right_embedding)
            record["edgeSimilarity"] = edge_similarity
            if edge_similarity >= self.change_probe_threshold:
                record["reason"] = "same_speaker_edges"
                diagnostics.append(record)
                continue
            local_change = self.locator.locate(window_path, left_embedding, right_embedding)
            if local_change is None:
                record["reason"] = "scl_no_change"
                diagnostics.append(record)
                continue
            change_ms = start_ms + int(local_change * 1000)
            record["candidateMs"] = change_ms
            if (
                change_ms - start_ms < self.minimum_segment_ms
                or end_ms - change_ms < self.minimum_segment_ms
            ):
                record["reason"] = "candidate_near_window_edge"
                diagnostics.append(record)
                continue
            record["accepted"] = True
            record["reason"] = "candidate"
            diagnostics.append(record)
            candidates.append(change_ms)

        return self.merge_candidates(candidates), diagnostics

    def build_segments(
        self,
        audio_path: Path,
        change_points: list[int],
        output_dir: Path,
    ) -> list[AudioSegment]:
        samples, sample_rate = read_wav_mono(audio_path)
        duration_ms = int(len(samples) * 1000 / sample_rate)
        boundaries = [0, *sorted(point for point in change_points if 0 < point < duration_ms), duration_ms]
        output_dir.mkdir(parents=True, exist_ok=True)
        segments = []
        for index, (start_ms, end_ms) in enumerate(zip(boundaries, boundaries[1:]), start=1):
            path = self._write_range(
                samples,
                sample_rate,
                output_dir / f"speaker-interval-{index:04d}.wav",
                start_ms,
                end_ms,
            )
            segments.append(
                AudioSegment(
                    id=f"speaker-interval-{index}",
                    start_ms=start_ms,
                    end_ms=end_ms,
                    audio_path=str(path),
                    change_point_before=index > 1,
                )
            )
        return segments

    def _window_starts(self, duration_ms: int) -> list[int]:
        if duration_ms <= self.window_ms:
            return [0]
        starts = list(range(0, max(1, duration_ms - self.window_ms + 1), self.stride_ms))
        final_start = max(0, duration_ms - self.window_ms)
        if not starts or starts[-1] != final_start:
            starts.append(final_start)
        return starts

    def merge_candidates(self, candidates: list[int]) -> list[int]:
        if not candidates:
            return []
        groups: list[list[int]] = [[value] for value in sorted(candidates)]
        merged_groups: list[list[int]] = []
        for group in groups:
            if merged_groups and group[0] - merged_groups[-1][-1] <= self.merge_distance_ms:
                merged_groups[-1].extend(group)
            else:
                merged_groups.append(group)
        return [int(np.median(group)) for group in merged_groups]

    @staticmethod
    def _write_range(
        samples: np.ndarray,
        sample_rate: int,
        target: Path,
        start_ms: int,
        end_ms: int,
    ) -> Path:
        start = max(0, int(start_ms * sample_rate / 1000))
        end = min(len(samples), int(end_ms * sample_rate / 1000))
        write_wav_mono(target, samples[start:end], sample_rate)
        return target

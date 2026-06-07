from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .audio import FsmnVadProcessor, read_wav_mono, slice_wav, speech_quality
from .models import AudioSegment, ResolvedUtterance, SpeakerMatch, TimedWord, VoiceProfile
from .segmentation import SpeakerTimelineSegmenter
from .voiceprint import VoiceprintService, cosine_similarity


UNKNOWN_SPEAKER = "未识别发言人"


class DialogueResolver:
    def __init__(
        self,
        voiceprints: VoiceprintService,
        *,
        threshold: float,
        margin: float,
        minimum_speech_ms: int,
        scl_window_ms: int = 7000,
        scl_stride_ms: int = 3500,
    ) -> None:
        self.voiceprints = voiceprints
        self.threshold = threshold
        self.margin = margin
        self.minimum_speech_ms = minimum_speech_ms
        self.segmenter = SpeakerTimelineSegmenter(
            voiceprints.provider,
            minimum_segment_ms=minimum_speech_ms,
            window_ms=scl_window_ms,
            stride_ms=scl_stride_ms,
        )
        self.vad = FsmnVadProcessor()

    def resolve(
        self,
        audio_path: Path,
        words: list[TimedWord],
        profiles: list[VoiceProfile],
        segments_dir: Path,
        *,
        enable_scl: bool,
    ) -> tuple[list[int], list[AudioSegment], list[ResolvedUtterance], list[dict]]:
        if not profiles:
            raise RuntimeError("请先注册至少一个声纹档案。")
        probe_dir = segments_dir / "scl-probes"
        raw_points, scl_diagnostics = self.segmenter.detect(
            audio_path,
            probe_dir,
            enable_scl=enable_scl,
        )
        change_points, validation = self._validate_change_points(
            audio_path,
            raw_points,
            profiles,
            segments_dir / "change-validation",
        )
        segments = self.segmenter.build_segments(audio_path, change_points, segments_dir / "intervals")
        match_records = [self._match_segment(segment, profiles) for segment in segments]
        self._smooth_unknown_matches(match_records)
        resolved = self._assign_words(words, match_records)
        diagnostics = [
            {
                "sclWindows": scl_diagnostics,
                "rawChangePoints": raw_points,
                "validatedChangePoints": change_points,
                "changeValidation": validation,
            },
            *[
                {
                    "segmentId": record["segment"].id,
                    "quality": record["quality"],
                    "speechRanges": record["speechRanges"],
                    "embeddingAudioPath": record["embeddingAudioPath"],
                    "match": asdict(record["match"]),
                    "smoothed": record.get("smoothed", False),
                }
                for record in match_records
            ],
        ]
        return change_points, segments, self._merge_adjacent(resolved), diagnostics

    def _validate_change_points(
        self,
        audio_path: Path,
        candidates: list[int],
        profiles: list[VoiceProfile],
        output_dir: Path,
    ) -> tuple[list[int], list[dict]]:
        output_dir.mkdir(parents=True, exist_ok=True)
        samples, sample_rate = read_wav_mono(audio_path)
        duration_ms = int(len(samples) * 1000 / sample_rate)
        accepted = []
        diagnostics = []
        for index, point in enumerate(candidates, start=1):
            left = AudioSegment(
                id=f"change-{index}-left",
                start_ms=max(0, point - 2200),
                end_ms=max(0, point - 150),
                audio_path="",
            )
            right = AudioSegment(
                id=f"change-{index}-right",
                start_ms=point + 150,
                end_ms=min(duration_ms, point + 2200),
                audio_path="",
            )
            point_dir = output_dir / f"point-{index}"
            point_dir.mkdir(parents=True, exist_ok=True)
            left_path = slice_wav(
                audio_path,
                point_dir / "left.wav",
                left.start_ms,
                left.end_ms,
                padding_ms=0,
            )
            right_path = slice_wav(
                audio_path,
                point_dir / "right.wav",
                right.start_ms,
                right.end_ms,
                padding_ms=0,
            )
            record = {"pointMs": point, "accepted": False}
            if left.end_ms - left.start_ms < 800 or right.end_ms - right.start_ms < 800:
                record["reason"] = "validation_slice_too_short"
                diagnostics.append(record)
                continue
            left_match, left_embedding = self._match_path(left_path, profiles)
            right_match, right_embedding = self._match_path(right_path, profiles)
            record["leftMatch"] = asdict(left_match)
            record["rightMatch"] = asdict(right_match)
            if left_embedding is None or right_embedding is None:
                record["reason"] = "validation_audio_not_usable"
            elif left_match.accepted and right_match.accepted:
                if left_match.profile_id != right_match.profile_id:
                    record["accepted"] = True
                    record["reason"] = "different_registered_speakers"
                else:
                    record["reason"] = "same_registered_speaker"
            else:
                similarity = cosine_similarity(left_embedding, right_embedding)
                record["embeddingSimilarity"] = similarity
                record["accepted"] = similarity < self.segmenter.change_probe_threshold
                record["reason"] = "embedding_change" if record["accepted"] else "similar_embeddings"
            if record["accepted"]:
                accepted.append(point)
            diagnostics.append(record)
        return accepted, diagnostics

    def _match_segment(self, segment: AudioSegment, profiles: list[VoiceProfile]) -> dict:
        source_path = Path(segment.audio_path)
        match, embedding, quality, speech_ranges, embedding_path = self._match_path_details(
            source_path,
            profiles,
        )
        return {
            "segment": segment,
            "match": match,
            "embedding": embedding,
            "quality": quality,
            "speechRanges": speech_ranges,
            "embeddingAudioPath": str(embedding_path),
        }

    def _match_path(
        self,
        path: Path,
        profiles: list[VoiceProfile],
    ) -> tuple[SpeakerMatch, object | None]:
        match, embedding, _, _, _ = self._match_path_details(path, profiles)
        return match, embedding

    def _match_path_details(
        self,
        path: Path,
        profiles: list[VoiceProfile],
    ) -> tuple[SpeakerMatch, object | None, dict, list[list[int]], Path]:
        clean_path = path.with_name(f"{path.stem}.speech.wav")
        try:
            embedding_path, speech_ranges = self.vad.clean(path, clean_path)
        except Exception:
            embedding_path, speech_ranges = path, []
        quality = speech_quality(embedding_path)
        if not quality["usable"]:
            return self._unknown_match(), None, quality, speech_ranges, embedding_path
        embedding = self.voiceprints.provider.extract(embedding_path)
        match = self.voiceprints.match(
            embedding,
            profiles,
            threshold=self.threshold,
            required_margin=self.margin,
        )
        return match, embedding, quality, speech_ranges, embedding_path

    @staticmethod
    def _smooth_unknown_matches(records: list[dict]) -> None:
        for index in range(1, len(records) - 1):
            current = records[index]
            if current["match"].accepted:
                continue
            left = records[index - 1]["match"]
            right = records[index + 1]["match"]
            if left.accepted and right.accepted and left.profile_id == right.profile_id:
                current["match"] = SpeakerMatch(
                    profile_id=left.profile_id,
                    display_name=left.display_name,
                    score=max(left.score, right.score),
                    second_score=max(left.second_score, right.second_score),
                    margin=min(left.margin, right.margin),
                    accepted=True,
                    confidence="inferred",
                )
                current["smoothed"] = True

    def _assign_words(self, words: list[TimedWord], records: list[dict]) -> list[ResolvedUtterance]:
        grouped: dict[str, list[TimedWord]] = {record["segment"].id: [] for record in records}
        for word in words:
            midpoint = (word.start_ms + word.end_ms) // 2
            record = self._record_for_time(records, midpoint)
            if record:
                grouped[record["segment"].id].append(word)

        resolved = []
        for record in records:
            segment: AudioSegment = record["segment"]
            assigned = grouped[segment.id]
            if not assigned:
                continue
            match: SpeakerMatch = record["match"]
            segment.text = join_timed_words(assigned)
            resolved.append(
                ResolvedUtterance(
                    id=segment.id,
                    canonical_speaker_id=match.profile_id,
                    display_name=match.display_name,
                    start_ms=assigned[0].start_ms,
                    end_ms=assigned[-1].end_ms,
                    text=segment.text,
                    score=match.score,
                    confidence=match.confidence,
                )
            )
        return resolved

    @staticmethod
    def _record_for_time(records: list[dict], timestamp_ms: int) -> dict | None:
        for record in records:
            segment: AudioSegment = record["segment"]
            if segment.start_ms <= timestamp_ms < segment.end_ms:
                return record
        return records[-1] if records and timestamp_ms == records[-1]["segment"].end_ms else None

    @staticmethod
    def _merge_adjacent(items: list[ResolvedUtterance]) -> list[ResolvedUtterance]:
        merged: list[ResolvedUtterance] = []
        for item in items:
            previous = merged[-1] if merged else None
            same_identity = (
                previous is not None
                and previous.canonical_speaker_id == item.canonical_speaker_id
                and previous.display_name == item.display_name
                and item.start_ms - previous.end_ms <= 1200
            )
            if same_identity:
                previous.end_ms = item.end_ms
                previous.text = join_text(previous.text, item.text)
                previous.score = max(previous.score, item.score)
                if previous.confidence not in {"high", "inferred"}:
                    previous.confidence = item.confidence
            else:
                merged.append(item)
        return merged

    @staticmethod
    def _unknown_match() -> SpeakerMatch:
        return SpeakerMatch(None, UNKNOWN_SPEAKER, 0.0, 0.0, 0.0, False, "unknown")


def join_timed_words(words: list[TimedWord]) -> str:
    value = ""
    for word in words:
        value = join_text(value, f"{word.text}{word.punctuation}")
    return value.strip()


def join_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    needs_space = left[-1].isascii() and right[0].isascii() and left[-1].isalnum() and right[0].isalnum()
    return f"{left}{' ' if needs_space else ''}{right}"


def dialogue_to_markdown(items: list[ResolvedUtterance]) -> str:
    lines = ["# 对话记录"]
    for item in items:
        start = _format_time(item.start_ms)
        end = _format_time(item.end_ms)
        lines.extend(["", f"**[{start} - {end}] {item.display_name}**", "", item.text])
    return "\n".join(lines).strip()


def _format_time(milliseconds: int) -> str:
    total = max(0, milliseconds // 1000)
    return f"{total // 60:02d}:{total % 60:02d}"

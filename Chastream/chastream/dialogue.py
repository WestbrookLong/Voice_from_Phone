from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .audio import FsmnVadProcessor, slice_wav, speech_quality
from .models import AudioSegment, ResolvedUtterance, SpeakerMatch, TimedWord, VoiceProfile
from .segmentation import SentenceChangeRefiner
from .voiceprint import VoiceprintService


UNKNOWN_SPEAKER = "未识别发言人"
DISPLAY_BOUNDARIES = frozenset("，,。！？!?；;")


@dataclass
class PunctuationUnit:
    id: str
    start_ms: int
    end_ms: int
    words: list[TimedWord]
    scl_split: bool = False

    @property
    def text(self) -> str:
        return join_timed_words(self.words)


class DialogueResolver:
    def __init__(
        self,
        voiceprints: VoiceprintService,
        *,
        threshold: float,
        margin: float,
        minimum_speech_ms: int,
        scl_trigger_threshold: float = 0.24,
    ) -> None:
        self.voiceprints = voiceprints
        self.threshold = threshold
        self.margin = margin
        self.minimum_speech_ms = minimum_speech_ms
        self.refiner = SentenceChangeRefiner(
            voiceprints.provider,
            minimum_side_ms=max(800, minimum_speech_ms // 2),
            change_probe_threshold=scl_trigger_threshold,
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

        base_units = build_punctuation_units(words)
        units: list[PunctuationUnit] = []
        change_points: list[int] = []
        scl_diagnostics: list[dict] = []
        for unit in base_units:
            refined, points, diagnostics = self._refine_unit(
                audio_path,
                unit,
                segments_dir / "scl-refinement",
                enable_scl=enable_scl,
                depth=0,
            )
            units.extend(refined)
            change_points.extend(points)
            scl_diagnostics.extend(diagnostics)

        records = [
            self._match_unit(audio_path, unit, profiles, segments_dir / "sentence-units")
            for unit in units
        ]
        self._smooth_unknown_matches(records)
        segments = [record["segment"] for record in records]
        resolved = [self._to_resolved(record) for record in records]
        diagnostics = [
            {
                "strategy": "punctuation_units_with_sentence_internal_scl",
                "baseUnitCount": len(base_units),
                "finalUnitCount": len(units),
                "changePoints": sorted(change_points),
                "sclRefinement": scl_diagnostics,
            },
            *[
                {
                    "segmentId": record["segment"].id,
                    "startMs": record["segment"].start_ms,
                    "endMs": record["segment"].end_ms,
                    "text": record["segment"].text,
                    "quality": record["quality"],
                    "speechRanges": record["speechRanges"],
                    "embeddingAudioPath": record["embeddingAudioPath"],
                    "match": asdict(record["match"]),
                    "smoothed": record.get("smoothed", False),
                }
                for record in records
            ],
        ]
        return sorted(change_points), segments, resolved, diagnostics

    def _refine_unit(
        self,
        audio_path: Path,
        unit: PunctuationUnit,
        output_dir: Path,
        *,
        enable_scl: bool,
        depth: int,
    ) -> tuple[list[PunctuationUnit], list[int], list[dict]]:
        if not enable_scl or depth >= 2 or len(unit.words) < 2:
            return [unit], [], []
        candidate, diagnostic = self.refiner.locate(
            audio_path,
            unit.start_ms,
            unit.end_ms,
            output_dir,
            f"{unit.id}-depth-{depth}",
        )
        diagnostic["unitId"] = unit.id
        if candidate is None:
            return [unit], [], [diagnostic]

        boundary_index, aligned_ms = nearest_word_boundary(unit.words, candidate)
        diagnostic["alignedMs"] = aligned_ms
        diagnostic["boundaryWordIndex"] = boundary_index
        if boundary_index <= 0 or boundary_index >= len(unit.words):
            diagnostic["accepted"] = False
            diagnostic["reason"] = "no_valid_word_boundary"
            return [unit], [], [diagnostic]

        left_words = unit.words[:boundary_index]
        right_words = unit.words[boundary_index:]
        left = PunctuationUnit(
            id=f"{unit.id}-a",
            start_ms=left_words[0].start_ms,
            end_ms=left_words[-1].end_ms,
            words=left_words,
            scl_split=True,
        )
        right = PunctuationUnit(
            id=f"{unit.id}-b",
            start_ms=right_words[0].start_ms,
            end_ms=right_words[-1].end_ms,
            words=right_words,
            scl_split=True,
        )
        if (
            left.end_ms - left.start_ms < self.refiner.minimum_side_ms
            or right.end_ms - right.start_ms < self.refiner.minimum_side_ms
        ):
            diagnostic["accepted"] = False
            diagnostic["reason"] = "aligned_word_side_too_short"
            return [unit], [], [diagnostic]

        left_units, left_points, left_diagnostics = self._refine_unit(
            audio_path,
            left,
            output_dir,
            enable_scl=enable_scl,
            depth=depth + 1,
        )
        right_units, right_points, right_diagnostics = self._refine_unit(
            audio_path,
            right,
            output_dir,
            enable_scl=enable_scl,
            depth=depth + 1,
        )
        return (
            [*left_units, *right_units],
            [aligned_ms, *left_points, *right_points],
            [diagnostic, *left_diagnostics, *right_diagnostics],
        )

    def _match_unit(
        self,
        audio_path: Path,
        unit: PunctuationUnit,
        profiles: list[VoiceProfile],
        output_dir: Path,
    ) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        source_path = slice_wav(
            audio_path,
            output_dir / f"{unit.id}.wav",
            unit.start_ms,
            unit.end_ms,
            padding_ms=80,
        )
        clean_path = source_path.with_name(f"{source_path.stem}.speech.wav")
        try:
            embedding_path, speech_ranges = self.vad.clean(source_path, clean_path)
        except Exception:
            embedding_path, speech_ranges = source_path, []
        quality = speech_quality(embedding_path)
        match = self._unknown_match()
        if quality["usable"]:
            embedding = self.voiceprints.provider.extract(embedding_path)
            match = self.voiceprints.match(
                embedding,
                profiles,
                threshold=self.threshold,
                required_margin=self.margin,
            )
        segment = AudioSegment(
            id=unit.id,
            start_ms=unit.start_ms,
            end_ms=unit.end_ms,
            audio_path=str(source_path),
            text=unit.text,
            change_point_before=unit.scl_split,
        )
        return {
            "segment": segment,
            "match": match,
            "quality": quality,
            "speechRanges": speech_ranges,
            "embeddingAudioPath": str(embedding_path),
        }

    @staticmethod
    def _smooth_unknown_matches(records: list[dict]) -> None:
        for index in range(1, len(records) - 1):
            current = records[index]
            if current["match"].accepted:
                continue
            left = records[index - 1]["match"]
            right = records[index + 1]["match"]
            if left.accepted and right.accepted and left.profile_id == right.profile_id:
                direct: SpeakerMatch = current["match"]
                current["match"] = SpeakerMatch(
                    profile_id=left.profile_id,
                    display_name=left.display_name,
                    score=direct.score,
                    second_score=direct.second_score,
                    margin=direct.margin,
                    accepted=True,
                    confidence="inferred",
                    best_candidate_name=direct.best_candidate_name,
                    second_candidate_name=direct.second_candidate_name,
                )
                current["smoothed"] = True

    @staticmethod
    def _to_resolved(record: dict) -> ResolvedUtterance:
        segment: AudioSegment = record["segment"]
        match: SpeakerMatch = record["match"]
        return ResolvedUtterance(
            id=segment.id,
            canonical_speaker_id=match.profile_id,
            display_name=match.display_name,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            text=segment.text,
            score=match.score,
            second_score=match.second_score,
            margin=match.margin,
            confidence=match.confidence,
            best_candidate_name=match.best_candidate_name,
            second_candidate_name=match.second_candidate_name,
        )

    @staticmethod
    def _unknown_match() -> SpeakerMatch:
        return SpeakerMatch(None, UNKNOWN_SPEAKER, 0.0, 0.0, 0.0, False, "unknown")


def build_punctuation_units(words: list[TimedWord]) -> list[PunctuationUnit]:
    units: list[PunctuationUnit] = []
    current: list[TimedWord] = []
    current_sentence_id = ""
    for word in words:
        if current and current_sentence_id and word.sentence_id != current_sentence_id:
            units.append(_make_unit(len(units) + 1, current))
            current = []
        current.append(word)
        current_sentence_id = word.sentence_id
        if _is_display_boundary(word):
            units.append(_make_unit(len(units) + 1, current))
            current = []
            current_sentence_id = ""
    if current:
        units.append(_make_unit(len(units) + 1, current))
    return units


def nearest_word_boundary(words: list[TimedWord], target_ms: int) -> tuple[int, int]:
    candidates = []
    for index in range(1, len(words)):
        boundary_ms = (words[index - 1].end_ms + words[index].start_ms) // 2
        candidates.append((abs(boundary_ms - target_ms), index, boundary_ms))
    if not candidates:
        return 0, target_ms
    _, index, boundary_ms = min(candidates)
    return index, boundary_ms


def _make_unit(index: int, words: list[TimedWord]) -> PunctuationUnit:
    return PunctuationUnit(
        id=f"sentence-unit-{index}",
        start_ms=words[0].start_ms,
        end_ms=words[-1].end_ms,
        words=list(words),
    )


def _is_display_boundary(word: TimedWord) -> bool:
    punctuation = f"{word.punctuation}{word.text[-1:]}"
    return any(mark in DISPLAY_BOUNDARIES for mark in punctuation)


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
    lines = ["# 对话记录", ""]
    for item in items:
        start = _format_time(item.start_ms)
        end = _format_time(item.end_ms)
        lines.append(f"- `[{start} - {end}]` **{item.display_name}**：{item.text}")
    return "\n".join(lines).strip()


def _format_time(milliseconds: int) -> str:
    total_seconds, millis = divmod(max(0, milliseconds), 1000)
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}.{millis:03d}"

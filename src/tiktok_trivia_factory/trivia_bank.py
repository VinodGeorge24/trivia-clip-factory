from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class BankQuestion:
    question: str
    choices: tuple[tuple[str, str], ...]
    correct_label: str
    answer: str


@dataclass(frozen=True)
class BankTopic:
    heading: str
    number: str
    category: str
    title: str
    questions: tuple[BankQuestion, ...]
    source_path: Path
    source_start: int
    source_end: int
    source_text: str


DEFAULT_BANK_PATHS = (
    Path("var/trivia-rewrite"),
    Path("trivia-questions.txt"),
    Path("triviaquestions.txt"),
)
USED_BANK_FILENAME = "used-trivia-bank.txt"


class TriviaBankError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConsumedBankTopic:
    heading: str
    source_path: Path
    used_path: Path


def find_matching_bank_topic(prompt: str, bank_path: Path | None = None) -> BankTopic | None:
    prompt_tokens = _topic_tokens(prompt)
    if not prompt_tokens:
        return None

    best_topic: BankTopic | None = None
    best_score = 0.0
    for topic in load_bank_topics(bank_path):
        score = _match_score(prompt_tokens, topic)
        if score > best_score:
            best_score = score
            best_topic = topic

    return best_topic if best_score >= 0.42 else None


def load_bank_topics(bank_path: Path | None = None) -> list[BankTopic]:
    paths = _candidate_paths(bank_path)
    topics: list[BankTopic] = []
    for path in paths:
        if path.is_dir():
            for file_path in sorted(path.glob("batch_*.txt")):
                topics.extend(_parse_bank_file(file_path))
        elif path.is_file():
            topics.extend(_parse_bank_file(path))
    return topics


def consume_bank_topic(topic: BankTopic, job_id: str, prompt: str) -> ConsumedBankTopic:
    """Move a selected bank topic out of the source bank and into the used log."""
    source_path = topic.source_path
    used_path = _used_bank_path(source_path)
    current_text = source_path.read_text(encoding="utf-8")
    if current_text[topic.source_start : topic.source_end].strip() != topic.source_text.strip():
        topic = _find_topic_in_file(source_path, topic.heading)

    used_path.parent.mkdir(parents=True, exist_ok=True)
    _append_used_topic(used_path, topic, job_id, prompt)
    _remove_topic_from_source(source_path, topic)
    return ConsumedBankTopic(heading=topic.heading, source_path=source_path, used_path=used_path)


def consume_bank_topic_from_script(script_json: str, job_id: str, prompt: str) -> ConsumedBankTopic | None:
    payload = json.loads(script_json)
    if payload.get("provider") != "local_trivia_bank":
        return None
    script_prompt = payload.get("prompt")
    resolved_prompt = prompt.strip() or (script_prompt if isinstance(script_prompt, str) else "")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return None
    heading = metadata.get("trivia_bank_heading")
    source = metadata.get("trivia_bank_source")
    if not isinstance(heading, str) or not isinstance(source, str):
        return None
    topic = _find_topic_in_file(Path(source), heading)
    return consume_bank_topic(topic, job_id=job_id, prompt=resolved_prompt)


def _candidate_paths(bank_path: Path | None) -> list[Path]:
    if bank_path is not None:
        return [bank_path.expanduser().resolve()]

    return [path.resolve() for path in DEFAULT_BANK_PATHS]


def _parse_bank_file(path: Path) -> list[BankTopic]:
    raw_text = path.read_text(encoding="utf-8")
    offset = 1 if raw_text.startswith("\ufeff") else 0
    text = raw_text[offset:]
    used_headings = _load_used_headings(_used_bank_path(path))
    matches = list(re.finditer(r"^(\d{3})\. \[([^\]\n]+)\]\s*$", text, flags=re.MULTILINE))
    topics: list[BankTopic] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(0).strip()
        if heading in used_headings:
            continue
        block = text[match.end() : end].strip()
        questions = _parse_questions(block)
        if not questions:
            continue
        category, title = _split_heading(match.group(2))
        topics.append(
            BankTopic(
                heading=heading,
                number=match.group(1),
                category=category,
                title=title,
                questions=tuple(questions),
                source_path=path,
                source_start=match.start() + offset,
                source_end=end + offset,
                source_text=text[match.start() : end].strip(),
            )
        )
    return topics


def _find_topic_in_file(path: Path, heading: str) -> BankTopic:
    for topic in _parse_bank_file_including_used(path):
        if topic.heading == heading:
            return topic
    raise TriviaBankError(f"Could not find bank topic to consume: {heading} in {path}")


def _parse_bank_file_including_used(path: Path) -> list[BankTopic]:
    raw_text = path.read_text(encoding="utf-8")
    offset = 1 if raw_text.startswith("\ufeff") else 0
    text = raw_text[offset:]
    matches = list(re.finditer(r"^(\d{3})\. \[([^\]\n]+)\]\s*$", text, flags=re.MULTILINE))
    topics: list[BankTopic] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end() : end].strip()
        questions = _parse_questions(block)
        if not questions:
            continue
        category, title = _split_heading(match.group(2))
        topics.append(
            BankTopic(
                heading=match.group(0).strip(),
                number=match.group(1),
                category=category,
                title=title,
                questions=tuple(questions),
                source_path=path,
                source_start=match.start() + offset,
                source_end=end + offset,
                source_text=text[match.start() : end].strip(),
            )
        )
    return topics


def _used_bank_path(source_path: Path) -> Path:
    return source_path.parent / USED_BANK_FILENAME


def _load_used_headings(used_path: Path) -> set[str]:
    if not used_path.exists():
        return set()
    text = used_path.read_text(encoding="utf-8").lstrip("\ufeff")
    return {
        match.group(0).strip()
        for match in re.finditer(r"^(\d{3})\. \[([^\]\n]+)\]\s*$", text, flags=re.MULTILINE)
    }


def _append_used_topic(used_path: Path, topic: BankTopic, job_id: str, prompt: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = used_path.read_text(encoding="utf-8") if used_path.exists() else ""
    prefix = "\n\n" if existing.strip() else ""
    entry = (
        f"{prefix}# Used at: {timestamp}\n"
        f"# Job: {job_id}\n"
        f"# Prompt: {prompt.strip()}\n"
        f"# Source: {topic.source_path}\n"
        f"{topic.source_text.strip()}\n"
    )
    used_path.write_text(existing.rstrip() + entry, encoding="utf-8")


def _remove_topic_from_source(source_path: Path, topic: BankTopic) -> None:
    text = source_path.read_text(encoding="utf-8")
    updated = text[: topic.source_start].rstrip() + "\n\n" + text[topic.source_end :].lstrip()
    source_path.write_text(updated.strip() + "\n", encoding="utf-8")


def _parse_questions(block: str) -> list[BankQuestion]:
    raw_questions = [part.strip() for part in re.split(r"(?m)^Question:\s*$", block)[1:]]
    questions: list[BankQuestion] = []
    for raw_question in raw_questions:
        lines = [line.rstrip() for line in raw_question.splitlines() if line.strip()]
        option_start = next((i for i, line in enumerate(lines) if re.match(r"^[ABC]\. ", line)), None)
        if option_start is None:
            continue
        question_text = " ".join(lines[:option_start]).strip()
        options = tuple(
            (match.group(1), match.group(2).strip())
            for line in lines
            if (match := re.match(r"^([ABC])\. (.+)$", line))
        )
        answer_match = next(
            (re.match(r"^Answer: ([ABC])\. (.+)$", line) for line in lines if line.startswith("Answer: ")),
            None,
        )
        if not question_text or len(options) != 3 or answer_match is None:
            continue
        correct_label = answer_match.group(1)
        answer = answer_match.group(2).strip()
        option_map = dict(options)
        if option_map.get(correct_label) != answer:
            continue
        questions.append(
            BankQuestion(
                question=question_text,
                choices=options,
                correct_label=correct_label,
                answer=answer,
            )
        )
    return questions


def _split_heading(value: str) -> tuple[str, str]:
    if " - " not in value:
        return "Trivia", value.strip()
    category, title = value.split(" - ", 1)
    return category.strip(), title.strip()


def _match_score(prompt_tokens: set[str], topic: BankTopic) -> float:
    title_tokens = _topic_tokens(topic.title)
    category_tokens = _topic_tokens(topic.category)
    heading_tokens = _topic_tokens(topic.heading)
    searchable_tokens = title_tokens | category_tokens | heading_tokens
    if not searchable_tokens:
        return 0.0
    prompt_eras = _era_tokens(prompt_tokens)
    topic_eras = _era_tokens(searchable_tokens)
    if prompt_eras and topic_eras and prompt_eras.isdisjoint(topic_eras):
        return 0.0
    weak_tokens = {"basketball", "men", "mens", "nba", "ncaa", "sports", "women", "womens"}
    if not ((prompt_tokens & searchable_tokens) - weak_tokens):
        return 0.0

    title_overlap = len(prompt_tokens & title_tokens) / max(1, len(title_tokens))
    prompt_coverage = len(prompt_tokens & searchable_tokens) / max(1, len(prompt_tokens))
    return (title_overlap * 0.62) + (prompt_coverage * 0.38)


def _topic_tokens(value: str) -> set[str]:
    stopwords = {
        "a",
        "about",
        "all",
        "and",
        "for",
        "history",
        "make",
        "me",
        "of",
        "on",
        "please",
        "questions",
        "quiz",
        "sports",
        "the",
        "trivia",
        "video",
        "with",
    }
    normalized = _normalized_topic(value)
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) > 1 and token not in stopwords
    }


def _era_tokens(tokens: set[str]) -> set[str]:
    return {token for token in tokens if re.fullmatch(r"(?:18|19|20)\d0s|(?:18|19|20)\d{2}", token)}


def _normalized_topic(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("&", " and ")).strip()

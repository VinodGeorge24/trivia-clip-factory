from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from html import unescape
from urllib.parse import unquote
from urllib.request import Request, urlopen

from .models import SourceCitationDraft


DEFAULT_DURATION_SECONDS = 45
DEFAULT_QUESTION_COUNT = 10
PROVIDER = "local_seed"
RESEARCH_WIKIPEDIA_PROVIDER = "research_wikipedia"
RESEARCH_OPENTDB_PROVIDER = "research_opentdb"
RESEARCH_CODEX_WEB_PROVIDER = "codex_web_search"
RESEARCH_GEMINI_WEB_PROVIDER = "gemini_web_search"
DEFAULT_FORMAT = "qa"
SUPPORTED_FORMATS = ("qa", "multiple_choice", "true_false", "fill_in_blank", "guess_image")
FetchJson = Callable[[str], dict[str, object]]


class UnsupportedTopicError(RuntimeError):
    pass


@dataclass(frozen=True)
class TriviaFact:
    question: str
    answer: str
    explanation: str
    difficulty: str
    answer_type: str


@dataclass(frozen=True)
class TopicPack:
    topic_key: str
    title: str
    hook: str
    caption_template: str
    hashtags: tuple[str, ...]
    citation_label: str
    citation_reference: str
    facts: tuple[TriviaFact, ...]
    distractor_bank: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class GeneratedScript:
    script_json: str
    provider: str
    confidence: float
    citations: list[SourceCitationDraft]


@dataclass(frozen=True)
class ResearchTriviaFact:
    question: str
    answer: str
    explanation: str
    difficulty: str
    answer_type: str
    distractors: tuple[str, ...]
    citation_label: str
    confidence: float


@dataclass(frozen=True)
class ResearchScriptDraft:
    provider: str
    topic: str
    hook: str
    caption_template: str
    hashtags: tuple[str, ...]
    source_type: str
    citation_label: str
    citation_reference: str
    confidence: float
    facts: tuple[ResearchTriviaFact, ...]


TOPIC_PACKS: dict[str, TopicPack] = {
    "fifa_world_cup": TopicPack(
        topic_key="fifa_world_cup",
        title="FIFA World Cup",
        hook="Think you know World Cup history? Ten quick questions. Keep score.",
        caption_template="World Cup trivia challenge: {count} questions. How many did you get right?",
        hashtags=("#trivia", "#worldcup", "#football", "#soccer", "#quiz"),
        citation_label="curated_fifa_world_cup_seed_v1",
        citation_reference="Local curated seed pack: FIFA World Cup historical facts v1",
        facts=(
            TriviaFact(
                "Which country hosted the first FIFA World Cup in 1930?",
                "Uruguay",
                "Uruguay hosted the first tournament and also won it.",
                "easy",
                "country",
            ),
            TriviaFact(
                "What trophy was awarded before the current FIFA World Cup Trophy?",
                "The Jules Rimet Trophy",
                "The original trophy was named after FIFA president Jules Rimet.",
                "medium",
                "award",
            ),
            TriviaFact(
                "Which country won the famous 1950 Maracanazo match against Brazil?",
                "Uruguay",
                "Uruguay beat Brazil in Rio de Janeiro in the decisive 1950 final-round match.",
                "medium",
                "country",
            ),
            TriviaFact(
                "Which tournament was the first FIFA World Cup held in Africa?",
                "South Africa 2010",
                "South Africa hosted the first World Cup on the African continent.",
                "easy",
                "tournament",
            ),
            TriviaFact(
                "Which two countries co-hosted the 2002 FIFA World Cup?",
                "South Korea and Japan",
                "The 2002 tournament was the first World Cup co-hosted by two nations.",
                "easy",
                "country_pair",
            ),
            TriviaFact(
                "What award goes to the top goalscorer at a FIFA World Cup?",
                "The Golden Boot",
                "The Golden Boot is awarded to the tournament's leading goalscorer.",
                "easy",
                "award",
            ),
            TriviaFact(
                "Diego Maradona's 'Hand of God' goal came against which country?",
                "England",
                "Maradona scored the famous goal for Argentina against England in 1986.",
                "medium",
                "country",
            ),
            TriviaFact(
                "Which country hosted the first FIFA Women's World Cup in 1991?",
                "China",
                "The first Women's World Cup was staged in China in 1991.",
                "medium",
                "country",
            ),
            TriviaFact(
                "What year introduced the current FIFA World Cup Trophy?",
                "1974",
                "The current trophy replaced the Jules Rimet Trophy starting with the 1974 tournament.",
                "hard",
                "year",
            ),
            TriviaFact(
                "What does a penalty shootout decide in knockout World Cup matches?",
                "The winner after a tied match remains level after extra time",
                "A shootout is used when a knockout match is still tied after extra time.",
                "easy",
                "rule",
            ),
        ),
        distractor_bank={
            "country": ("Brazil", "Argentina", "Italy", "Germany", "France", "England", "Spain", "Netherlands", "United States", "Sweden"),
            "award": ("The Golden Ball", "The Golden Glove", "The Best Young Player Award", "The Silver Boot", "The Fair Play Trophy"),
            "tournament": ("Brazil 2014", "Germany 2006", "Russia 2018", "France 1998", "Qatar 2022"),
            "country_pair": ("China and Russia", "USA and Canada", "Spain and Portugal", "Mexico and Brazil", "France and Germany"),
            "year": ("1966", "1970", "1982", "1990", "2002"),
            "rule": ("The team with more corners", "The group ranking before extra time", "The team with fewer yellow cards", "The team listed first on the bracket"),
        },
    ),
    "led_zeppelin": TopicPack(
        topic_key="led_zeppelin",
        title="Led Zeppelin",
        hook="Only real classic rock fans are getting all ten of these.",
        caption_template="Led Zeppelin trivia: {count} questions. Drop your score.",
        hashtags=("#trivia", "#ledzeppelin", "#classicrock", "#rockmusic", "#quiz"),
        citation_label="curated_led_zeppelin_seed_v1",
        citation_reference="Local curated seed pack: Led Zeppelin historical facts v1",
        facts=(
            TriviaFact("Who was Led Zeppelin's lead singer?", "Robert Plant", "Plant's vocals became one of the band's defining sounds.", "easy", "person"),
            TriviaFact("Who played guitar in Led Zeppelin?", "Jimmy Page", "Jimmy Page formed the band after the Yardbirds era.", "easy", "person"),
            TriviaFact("Who was Led Zeppelin's drummer?", "John Bonham", "Bonham is widely known for his powerful rock drumming.", "easy", "person"),
            TriviaFact("Who played bass and keyboards for Led Zeppelin?", "John Paul Jones", "Jones handled bass, keyboards, and orchestral arrangements.", "medium", "person"),
            TriviaFact("In what year did Led Zeppelin form?", "1968", "The band formed in London in 1968.", "medium", "year"),
            TriviaFact("Which album includes 'Stairway to Heaven'?", "Led Zeppelin IV", "The track appears on the band's untitled fourth album.", "easy", "album"),
            TriviaFact("What was Led Zeppelin's debut album called?", "Led Zeppelin", "Their first album used the band name as its title.", "easy", "album"),
            TriviaFact("Which member's death led to Led Zeppelin disbanding?", "John Bonham", "The band ended after Bonham died in 1980.", "medium", "person"),
            TriviaFact("What record label did Led Zeppelin launch in the 1970s?", "Swan Song Records", "The band founded Swan Song as its own label.", "hard", "record_label"),
            TriviaFact("Which blues-influenced song opens Led Zeppelin II?", "Whole Lotta Love", "The song became one of the band's signature tracks.", "medium", "song"),
        ),
        distractor_bank={
            "person": ("Robert Plant", "Jimmy Page", "John Bonham", "John Paul Jones", "Roger Daltrey", "Eric Clapton", "Keith Moon", "Brian Jones"),
            "year": ("1965", "1967", "1969", "1971", "1973"),
            "album": ("Led Zeppelin", "Led Zeppelin II", "Led Zeppelin IV", "Houses of the Holy", "Physical Graffiti", "Presence"),
            "record_label": ("Atlantic Records", "Apple Records", "Rolling Stones Records", "Island Records", "Harvest Records"),
            "song": ("Black Dog", "Immigrant Song", "Kashmir", "Dazed and Confused", "Rock and Roll"),
        },
    ),
    "grade_science": TopicPack(
        topic_key="grade_science",
        title="Grade School Science",
        hook="Are you smarter than a grade-school science quiz? Ten questions.",
        caption_template="Grade school science trivia: {count} questions. How many were too easy?",
        hashtags=("#trivia", "#science", "#quiz", "#learnontiktok", "#generalknowledge"),
        citation_label="curated_grade_science_seed_v1",
        citation_reference="Local curated seed pack: grade-school science facts v1",
        facts=(
            TriviaFact("What planet is known as the Red Planet?", "Mars", "Iron-rich dust gives Mars its reddish color.", "easy", "planet"),
            TriviaFact("What gas do plants take in during photosynthesis?", "Carbon dioxide", "Plants use carbon dioxide, water, and light to make sugar.", "easy", "gas"),
            TriviaFact("What is the center of an atom called?", "The nucleus", "The nucleus contains protons and neutrons.", "easy", "structure"),
            TriviaFact("What force pulls objects toward Earth?", "Gravity", "Gravity attracts objects with mass toward each other.", "easy", "force"),
            TriviaFact("What process turns liquid water into water vapor?", "Evaporation", "Evaporation happens when liquid molecules escape into gas.", "easy", "process"),
            TriviaFact("What organ pumps blood through the body?", "The heart", "The heart circulates blood through blood vessels.", "easy", "organ"),
            TriviaFact("What is H2O better known as?", "Water", "Each water molecule has two hydrogen atoms and one oxygen atom.", "easy", "substance"),
            TriviaFact("What simple machine is a ramp?", "An inclined plane", "A ramp reduces the force needed to move something upward.", "medium", "simple_machine"),
            TriviaFact("What part of a plant absorbs most water from soil?", "The roots", "Roots anchor the plant and absorb water and minerals.", "easy", "plant_part"),
            TriviaFact("What is the freezing point of water in Celsius?", "0 degrees Celsius", "Pure water freezes at 0 degrees Celsius under standard pressure.", "medium", "temperature"),
        ),
        distractor_bank={
            "planet": ("Venus", "Jupiter", "Mercury", "Saturn", "Neptune"),
            "gas": ("Oxygen", "Nitrogen", "Hydrogen", "Helium", "Methane"),
            "structure": ("The electron cloud", "The cell wall", "The membrane", "The cytoplasm", "The orbit"),
            "force": ("Magnetism", "Friction", "Air resistance", "Tension", "Buoyancy"),
            "process": ("Condensation", "Freezing", "Melting", "Precipitation", "Sublimation"),
            "organ": ("The lungs", "The liver", "The brain", "The stomach", "The kidneys"),
            "substance": ("Salt", "Oxygen", "Carbon dioxide", "Sugar", "Helium"),
            "simple_machine": ("A pulley", "A lever", "A wheel and axle", "A screw", "A wedge"),
            "plant_part": ("The petals", "The stem", "The leaves", "The seeds", "The fruit"),
            "temperature": ("100 degrees Celsius", "32 degrees Celsius", "-10 degrees Celsius", "50 degrees Celsius", "212 degrees Celsius"),
        },
    ),
}


def generate_script(
    prompt: str,
    question_count: int | None = None,
    duration_seconds: int | None = None,
    fetch_json: FetchJson | None = None,
) -> GeneratedScript:
    try:
        pack = _select_topic_pack(prompt)
    except UnsupportedTopicError:
        return _generate_research_script(prompt, question_count, duration_seconds, fetch_json)

    requested_count = question_count or _parse_question_count(prompt) or DEFAULT_QUESTION_COUNT
    count = max(1, min(requested_count, len(pack.facts)))
    duration = duration_seconds or DEFAULT_DURATION_SECONDS

    questions = []
    for index, fact in enumerate(pack.facts[:count], start=1):
        question_id = f"q{index:02d}"
        choices, correct_choice_label = _build_choices(fact, pack, index)
        questions.append(
            {
                "id": question_id,
                "format": DEFAULT_FORMAT,
                "question": fact.question,
                "answer": fact.answer,
                "answer_type": fact.answer_type,
                "choices": choices,
                "correct_choice_label": correct_choice_label,
                "explanation": fact.explanation,
                "difficulty": fact.difficulty,
                "confidence": 0.72,
                "citation_labels": [pack.citation_label],
                "on_screen_text": fact.question,
                "voiceover": f"Question {index}. {fact.question} Answer: {fact.answer}. {fact.explanation}",
            }
        )

    payload = {
        "schema_version": 1,
        "provider": PROVIDER,
        "generation_mode": "local_seed",
        "format": DEFAULT_FORMAT,
        "supported_formats": list(SUPPORTED_FORMATS),
        "topic": pack.title,
        "prompt": prompt.strip(),
        "target_duration_seconds": duration,
        "hook": pack.hook,
        "questions": questions,
        "caption": pack.caption_template.format(count=count),
        "hashtags": list(pack.hashtags),
        "metadata": {
            "question_count": count,
            "needs_external_research": False,
            "suitability_notes": "Local seed script. Review facts before publishing.",
        },
    }
    citation = SourceCitationDraft(
        label=pack.citation_label,
        source_type="curated_seed",
        reference=pack.citation_reference,
        confidence=0.72,
    )
    return GeneratedScript(
        script_json=json.dumps(payload, indent=2, sort_keys=True),
        provider=PROVIDER,
        confidence=0.72,
        citations=[citation],
    )


def _generate_research_script(
    prompt: str,
    question_count: int | None,
    duration_seconds: int | None,
    fetch_json: FetchJson | None,
) -> GeneratedScript:
    if not _supports_research_prompt(prompt):
        raise UnsupportedTopicError(
            "No local seed pack or free research provider supports this topic yet."
        )

    requested_count = question_count or _parse_question_count(prompt) or DEFAULT_QUESTION_COUNT
    duration = duration_seconds or DEFAULT_DURATION_SECONDS
    fetcher = fetch_json or _default_fetch_json
    provider_errors: list[str] = []

    for provider in (_research_from_wikipedia, _research_from_opentdb):
        try:
            draft = provider(prompt, requested_count, fetcher)
        except UnsupportedTopicError as error:
            provider_errors.append(str(error))
            continue
        return _research_draft_to_generated_script(
            draft=draft,
            prompt=prompt,
            requested_count=requested_count,
            duration=duration,
        )

    detail = "; ".join(provider_errors) if provider_errors else "no provider returned usable facts"
    raise UnsupportedTopicError(f"No free research provider could generate this topic yet. Tried: {detail}")


def _research_draft_to_generated_script(
    draft: ResearchScriptDraft,
    prompt: str,
    requested_count: int,
    duration: int,
) -> GeneratedScript:
    count = max(1, min(requested_count, len(draft.facts)))
    questions = []
    for index, fact in enumerate(draft.facts[:count], start=1):
        choices, correct_choice_label = _build_research_choices(fact, index)
        questions.append(
            {
                "id": f"q{index:02d}",
                "format": DEFAULT_FORMAT,
                "question": fact.question,
                "answer": fact.answer,
                "answer_type": fact.answer_type,
                "choices": choices,
                "correct_choice_label": correct_choice_label,
                "explanation": fact.explanation,
                "difficulty": fact.difficulty,
                "confidence": fact.confidence,
                "citation_labels": [fact.citation_label],
                "on_screen_text": fact.question,
                "voiceover": f"Question {index}. {fact.question} Answer: {fact.answer}. {fact.explanation}",
            }
        )

    payload = {
        "schema_version": 1,
        "provider": draft.provider,
        "generation_mode": "free_research",
        "format": DEFAULT_FORMAT,
        "supported_formats": list(SUPPORTED_FORMATS),
        "topic": draft.topic,
        "prompt": prompt.strip(),
        "target_duration_seconds": duration,
        "hook": draft.hook,
        "questions": questions,
        "caption": draft.caption_template.format(count=count),
        "hashtags": list(draft.hashtags),
        "metadata": {
            "question_count": count,
            "needs_external_research": True,
            "research_provider": draft.provider,
            "provider_chain": [
                PROVIDER,
                RESEARCH_WIKIPEDIA_PROVIDER,
                RESEARCH_OPENTDB_PROVIDER,
                RESEARCH_CODEX_WEB_PROVIDER,
                RESEARCH_GEMINI_WEB_PROVIDER,
            ],
            "suitability_notes": "Free research-backed script. Review facts and source citations before publishing.",
        },
    }
    citation = SourceCitationDraft(
        label=draft.citation_label,
        source_type=draft.source_type,
        reference=draft.citation_reference,
        confidence=draft.confidence,
    )
    return GeneratedScript(
        script_json=json.dumps(payload, indent=2, sort_keys=True),
        provider=draft.provider,
        confidence=draft.confidence,
        citations=[citation],
    )


def _research_from_wikipedia(prompt: str, requested_count: int, fetch_json: FetchJson) -> ResearchScriptDraft:
    if "nba finals" not in prompt.lower():
        raise UnsupportedTopicError("Wikimedia provider currently supports NBA Finals prompts only")

    summary_url = "https://en.wikipedia.org/api/rest_v1/page/summary/NBA_Finals"
    extract_url = (
        "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1"
        "&titles=NBA_Finals&format=json&redirects=1"
    )
    summary_payload = fetch_json(summary_url)
    extract_payload = fetch_json(extract_url)
    summary = str(summary_payload.get("extract", "")).strip()
    extract = _extract_wikipedia_text(extract_payload)
    evidence = f"{summary}\n{extract}".strip()
    if not evidence:
        raise UnsupportedTopicError("Wikimedia provider returned no NBA Finals text")

    citation_label = "wikimedia_nba_finals_v1"
    facts = _nba_finals_facts_from_evidence(evidence, citation_label)
    if not facts:
        raise UnsupportedTopicError("Wikimedia provider returned NBA Finals text but no supported facts")
    return ResearchScriptDraft(
        provider=RESEARCH_WIKIPEDIA_PROVIDER,
        topic="NBA Finals",
        hook="Think you know NBA Finals history? Keep score through this quick challenge.",
        caption_template="NBA Finals trivia challenge: {count} questions. Drop your score.",
        hashtags=("#trivia", "#nba", "#nbafinals", "#basketball", "#quiz"),
        source_type="wikimedia_api",
        citation_label=citation_label,
        citation_reference=f"{summary_url} and {extract_url}",
        confidence=0.68,
        facts=tuple(facts[: max(1, requested_count)]),
    )


def _research_from_opentdb(prompt: str, requested_count: int, fetch_json: FetchJson) -> ResearchScriptDraft:
    normalized = prompt.lower()
    if not any(term in normalized for term in ("nba", "basketball", "sports")):
        raise UnsupportedTopicError("Open Trivia DB fallback currently supports sports prompts only")

    amount = max(1, min(requested_count, 10))
    url = f"https://opentdb.com/api.php?amount={amount}&category=21&type=multiple&encode=url3986"
    payload = fetch_json(url)
    if int(payload.get("response_code", 1)) != 0:
        raise UnsupportedTopicError("Open Trivia DB returned no usable sports questions")
    raw_results = payload.get("results", [])
    if not isinstance(raw_results, list) or not raw_results:
        raise UnsupportedTopicError("Open Trivia DB returned an empty result set")

    citation_label = "opentdb_sports_v1"
    facts: list[ResearchTriviaFact] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        question = _decode_trivia_text(item.get("question", ""))
        answer = _decode_trivia_text(item.get("correct_answer", ""))
        incorrect = item.get("incorrect_answers", [])
        distractors = tuple(_decode_trivia_text(value) for value in incorrect if value)
        if not question or not answer or len(distractors) < 2:
            continue
        facts.append(
            ResearchTriviaFact(
                question=question,
                answer=answer,
                explanation="This question came from the Open Trivia DB sports category.",
                difficulty=str(item.get("difficulty", "medium")),
                answer_type="sports_answer",
                distractors=distractors[:2],
                citation_label=citation_label,
                confidence=0.55,
            )
        )
    if not facts:
        raise UnsupportedTopicError("Open Trivia DB results did not include enough multiple-choice data")
    return ResearchScriptDraft(
        provider=RESEARCH_OPENTDB_PROVIDER,
        topic="Sports Trivia",
        hook="Quick sports trivia round. Keep score as you go.",
        caption_template="Sports trivia challenge: {count} questions. Drop your score.",
        hashtags=("#trivia", "#sports", "#basketball", "#quiz"),
        source_type="opentdb_api",
        citation_label=citation_label,
        citation_reference=url,
        confidence=0.55,
        facts=tuple(facts),
    )


def _extract_wikipedia_text(payload: dict[str, object]) -> str:
    query = payload.get("query")
    if not isinstance(query, dict):
        return ""
    pages = query.get("pages")
    if not isinstance(pages, dict):
        return ""
    extracts: list[str] = []
    for page in pages.values():
        if isinstance(page, dict):
            extract = page.get("extract")
            if isinstance(extract, str) and extract.strip():
                extracts.append(extract.strip())
    return "\n".join(extracts)


def _nba_finals_facts_from_evidence(evidence: str, citation_label: str) -> list[ResearchTriviaFact]:
    normalized = evidence.lower()
    facts: list[ResearchTriviaFact] = []
    if "national basketball association" in normalized or "(nba)" in normalized:
        facts.append(
            ResearchTriviaFact(
                question="The NBA Finals is the championship series of which league?",
                answer="The National Basketball Association",
                explanation="The NBA Finals is the championship series for the National Basketball Association.",
                difficulty="easy",
                answer_type="league",
                distractors=("The WNBA", "NCAA Division I"),
                citation_label=citation_label,
                confidence=0.68,
            )
        )
    if "eastern" in normalized and "western" in normalized and "conference" in normalized:
        facts.append(
            ResearchTriviaFact(
                question="Which two conference champions meet in the NBA Finals?",
                answer="The Eastern and Western Conference champions",
                explanation="The NBA Finals is contested by the Eastern Conference champion and the Western Conference champion.",
                difficulty="easy",
                answer_type="conference_pair",
                distractors=("The Atlantic and Pacific Division champions", "The top two regular-season teams"),
                citation_label=citation_label,
                confidence=0.66,
            )
        )
    if "larry o'brien" in normalized or "larry obrien" in normalized:
        facts.append(
            ResearchTriviaFact(
                question="What trophy is awarded to the NBA Finals champion?",
                answer="The Larry O'Brien Championship Trophy",
                explanation="The NBA Finals winner receives the Larry O'Brien Championship Trophy.",
                difficulty="medium",
                answer_type="award",
                distractors=("The Bill Russell Trophy", "The Naismith Trophy"),
                citation_label=citation_label,
                confidence=0.66,
            )
        )
    if "most valuable player" in normalized or "finals mvp" in normalized:
        facts.append(
            ResearchTriviaFact(
                question="What award recognizes the top player of the NBA Finals?",
                answer="The NBA Finals Most Valuable Player Award",
                explanation="The NBA Finals MVP award recognizes the standout player of the championship series.",
                difficulty="easy",
                answer_type="award",
                distractors=("The Defensive Player of the Year Award", "The Rookie of the Year Award"),
                citation_label=citation_label,
                confidence=0.64,
            )
        )
    if "best-of-seven" in normalized or "best of seven" in normalized:
        facts.append(
            ResearchTriviaFact(
                question="What playoff format does the NBA Finals use?",
                answer="A best-of-seven series",
                explanation="The NBA Finals is played as a best-of-seven championship series.",
                difficulty="easy",
                answer_type="format",
                distractors=("A single championship game", "A best-of-three series"),
                citation_label=citation_label,
                confidence=0.64,
            )
        )
    if "baa finals" in normalized:
        facts.append(
            ResearchTriviaFact(
                question="What was the NBA Finals initially known as?",
                answer="The BAA Finals",
                explanation="The championship series was initially known as the BAA Finals before the NBA era.",
                difficulty="hard",
                answer_type="name",
                distractors=("The ABA Finals", "The NBL Championship"),
                citation_label=citation_label,
                confidence=0.6,
            )
        )
    return facts


def _build_research_choices(fact: ResearchTriviaFact, index: int) -> tuple[list[dict[str, object]], str]:
    labels = ("A", "B", "C")
    correct_slot = (index - 1) % len(labels)
    distractors = [value for value in fact.distractors if value.casefold() != fact.answer.casefold()]
    if len(distractors) < 2:
        raise UnsupportedTopicError(f"Not enough distractors for research answer: {fact.answer}")
    option_texts = distractors[:2]
    option_texts.insert(correct_slot, fact.answer)
    choices = [
        {
            "label": label,
            "text": text,
            "is_correct": label_index == correct_slot,
        }
        for label_index, (label, text) in enumerate(zip(labels, option_texts, strict=True))
    ]
    return choices, labels[correct_slot]


def _supports_research_prompt(prompt: str) -> bool:
    normalized = prompt.lower()
    return "nba finals" in normalized or "basketball" in normalized or "nba" in normalized


def _decode_trivia_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return unescape(unquote(value)).strip()


def _default_fetch_json(url: str) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "tiktok-trivia-factory/0.1 local-research",
        },
    )
    with urlopen(request, timeout=8) as response:
        raw = response.read().decode("utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise UnsupportedTopicError(f"Research provider returned non-object JSON: {url}")
    return payload


def _select_topic_pack(prompt: str) -> TopicPack:
    normalized = prompt.lower()
    if "world cup" in normalized or "fifa" in normalized:
        return TOPIC_PACKS["fifa_world_cup"]
    if "led zeppelin" in normalized:
        return TOPIC_PACKS["led_zeppelin"]
    if "science" in normalized or "5th grader" in normalized or "sixth grade" in normalized or "6th grade" in normalized:
        return TOPIC_PACKS["grade_science"]
    raise UnsupportedTopicError(
        "No local seed pack supports this topic yet. Add a supported topic or wait for the research provider phase."
    )


def _parse_question_count(prompt: str) -> int | None:
    match = re.search(r"\b(\d{1,2})\s+(?:trivia\s+)?questions?\b", prompt.lower())
    if match is None:
        return None
    return int(match.group(1))


def _build_choices(fact: TriviaFact, pack: TopicPack, index: int) -> tuple[list[dict[str, object]], str]:
    labels = ("A", "B", "C")
    correct_slot = (index - 1) % len(labels)
    option_texts = _select_distractors(fact, pack, count=2)
    option_texts.insert(correct_slot, fact.answer)
    choices = [
        {
            "label": label,
            "text": text,
            "is_correct": label_index == correct_slot,
        }
        for label_index, (label, text) in enumerate(zip(labels, option_texts, strict=True))
    ]
    return choices, labels[correct_slot]


def _select_distractors(fact: TriviaFact, pack: TopicPack, count: int) -> list[str]:
    candidates = [
        candidate
        for candidate in pack.distractor_bank.get(fact.answer_type, ())
        if candidate.strip().casefold() != fact.answer.strip().casefold()
    ]
    if len(candidates) < count:
        candidates.extend(
            other_fact.answer
            for other_fact in pack.facts
            if other_fact.answer_type == fact.answer_type
            and other_fact.answer.strip().casefold() != fact.answer.strip().casefold()
        )
    unique_candidates = _unique_preserving_order(candidates)
    if len(unique_candidates) < count:
        raise UnsupportedTopicError(
            f"Not enough {fact.answer_type} distractors available for answer: {fact.answer}"
        )
    offset = (len(fact.question) + len(fact.answer)) % len(unique_candidates)
    rotated = unique_candidates[offset:] + unique_candidates[:offset]
    return rotated[:count]


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = value.strip().casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(value)
    return unique

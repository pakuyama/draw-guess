"""게임 규칙: 방, 플레이어, 정답 판정, 점수.

이 파일은 Flask나 Socket.IO를 모릅니다. (AGENTS.md 참고)
지금은 뼈대만 있으며, docs/tasks.md 순서대로 채워 나갑니다.
"""
from __future__ import annotations

import json
import random
import string
from dataclasses import dataclass, field
from pathlib import Path

MAX_PLAYERS = 8
TURN_SECONDS = 80
TOTAL_ROUNDS = 3
WORDS_PATH = Path(__file__).parent / "data" / "words.json"


@dataclass
class Player:
    """방에 들어온 한 사람."""

    player_id: str
    nickname: str
    sid: str = ""
    score: int = 0
    guessed: bool = False
    connected: bool = True


@dataclass
class Room:
    """게임 방 하나의 상태."""

    code: str
    host_id: str
    players: list[Player] = field(default_factory=list)
    state: str = "waiting"  # waiting | choosing | drawing | turn_end | game_end
    round: int = 1
    drawer_index: int = 0
    word: str | None = None
    word_choices: list[str] = field(default_factory=list)
    strokes: list[dict] = field(default_factory=list)
    turn_started_at: float = 0.0

    def add_player(self, player: Player) -> None:
        """플레이어를 추가한다. 가득 차면 ValueError."""
        if len(self.players) >= MAX_PLAYERS:
            raise ValueError("방이 가득 찼어요.")
        self.players.append(player)


rooms: dict[str, Room] = {}


def make_room_code() -> str:
    """겹치지 않는 6자리 방 코드를 만든다."""
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in rooms:
            return code


def load_words() -> dict[str, list[str]]:
    """제시어 사전을 읽는다."""
    return json.loads(WORDS_PATH.read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    """정답 비교용: 띄어쓰기 제거, 소문자."""
    return text.replace(" ", "").strip().lower()


def is_correct(guess: str, answer: str) -> bool:
    """채팅 내용이 정답인지 판정한다."""
    return normalize(guess) == normalize(answer)


def guess_score(seconds_left: float, first: bool) -> int:
    """맞힌 사람 점수: 남은 시간 비례(20~100) + 첫 정답 보너스 20."""
    score = max(20, round(100 * seconds_left / TURN_SECONDS))
    return score + (20 if first else 0)


def drawer_score(correct_count: int) -> int:
    """출제자 점수: 맞힌 사람 1명당 25점."""
    return 25 * correct_count

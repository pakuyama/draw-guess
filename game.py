"""게임 규칙: 방, 플레이어, 정답 판정, 점수.

이 파일은 Flask나 Socket.IO를 모릅니다. (AGENTS.md 참고)
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

MAX_PLAYERS = 8
MIN_PLAYERS = 2
TURN_SECONDS = 80
TOTAL_ROUNDS = 3
WORDS_PATH = Path(__file__).parent / "data" / "words.json"
NICKNAME_MAX = 10

# 방 코드에 쓰는 글자. 헷갈리는 0/O, 1/I/L은 뺀다.
CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6


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

    def is_full(self) -> bool:
        """정원(8명)이 찼는지."""
        return len(self.players) >= MAX_PLAYERS

    def find_player(self, player_id: str) -> Player | None:
        """player_id로 플레이어를 찾는다. 없으면 None."""
        for player in self.players:
            if player.player_id == player_id:
                return player
        return None

    def add_player(self, player: Player) -> None:
        """플레이어를 추가한다. 가득 찼거나 이미 있는 player_id면 ValueError."""
        if self.is_full():
            raise ValueError(f"방이 가득 찼어요. ({MAX_PLAYERS}/{MAX_PLAYERS})")
        if self.find_player(player.player_id):
            raise ValueError("이미 이 방에 들어와 있어요. 다른 창이나 탭을 확인해 주세요.")
        self.players.append(player)

    def can_start(self) -> bool:
        """대기 중이고 2명 이상이면 시작할 수 있다."""
        return self.state == "waiting" and len(self.players) >= MIN_PLAYERS

    def public_state(self) -> dict:
        """모든 참가자에게 보내도 되는 방 정보. 제시어(word)는 넣지 않는다."""
        return {
            "code": self.code,
            "host_id": self.host_id,
            "state": self.state,
            "round": self.round,
            "players": [
                {
                    "player_id": p.player_id,
                    "nickname": p.nickname,
                    "score": p.score,
                    "guessed": p.guessed,
                    "connected": p.connected,
                }
                for p in self.players
            ],
        }


rooms: dict[str, Room] = {}


def make_room_code() -> str:
    """겹치지 않는 6자리 방 코드를 만든다."""
    while True:
        code = "".join(random.choices(CODE_CHARS, k=CODE_LENGTH))
        if code not in rooms:
            return code


def clean_nickname(nickname: str) -> str:
    """닉네임 앞뒤 공백을 지우고 10자로 자른다. 비어 있으면 ValueError."""
    name = (nickname or "").strip()[:NICKNAME_MAX]
    if not name:
        raise ValueError("닉네임을 입력해 주세요.")
    return name


def normalize_code(code: str) -> str:
    """사용자가 입력한 방 코드를 대문자로 바꾸고 공백을 지운다."""
    return (code or "").replace(" ", "").strip().upper()


def check_player_id(player_id: str) -> str:
    """브라우저가 보낸 player_id가 비어 있지 않은지 확인한다."""
    if not player_id:
        raise ValueError("접속 정보가 없어요. 새로고침해 주세요.")
    return player_id


def create_room(player_id: str, nickname: str) -> Room:
    """새 방을 만들고 만든 사람을 방장으로 넣는다."""
    host = Player(player_id=check_player_id(player_id), nickname=clean_nickname(nickname))
    room = Room(code=make_room_code(), host_id=player_id)
    room.add_player(host)
    rooms[room.code] = room
    return room


def get_room(code: str) -> Room | None:
    """방 코드로 방을 찾는다. 없으면 None."""
    return rooms.get(normalize_code(code))


def join_room(code: str, player_id: str, nickname: str) -> tuple[Room, Player]:
    """방 코드로 방에 들어간다. 실패하면 이유를 담은 ValueError."""
    nickname = clean_nickname(nickname)
    if len(normalize_code(code)) != CODE_LENGTH:
        raise ValueError("방 코드 6자리를 입력해 주세요.")
    room = get_room(code)
    if room is None:
        raise ValueError("없는 방 코드예요.")
    if room.state != "waiting":
        raise ValueError("이미 게임이 진행 중이에요.")
    player = Player(player_id=check_player_id(player_id), nickname=nickname)
    room.add_player(player)
    return room, player


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

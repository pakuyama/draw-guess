"""게임 규칙: 방, 플레이어, 정답 판정, 점수.

이 파일은 Flask나 Socket.IO를 모릅니다. (AGENTS.md 참고)
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

MAX_PLAYERS = 8
MIN_PLAYERS = 2
TURN_SECONDS = 80
TOTAL_ROUNDS = 3
CHOOSE_SECONDS = 10  # 제시어 고르는 시간. 넘으면 자동 선택
HINT_SECONDS = 40  # 그리기 시작 후 이만큼 지나면 첫 글자 초성 공개
TURN_END_SECONDS = 5  # 정답 공개 화면을 보여 주는 시간
CHAT_MAX = 50
RECONNECT_SECONDS = 30  # 연결이 끊겨도 이 시간 안에 돌아오면 자리·점수 유지
WORDS_PATH = Path(__file__).parent / "data" / "words.json"
NICKNAME_MAX = 10

# 방 코드에 쓰는 글자. 헷갈리는 0/O, 1/I/L은 뺀다.
CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6

# 그림 데이터 한도 (design.md 6장 "스트로크 전송")
MAX_PART_POINTS = 200  # 한 번(약 40ms)에 보낼 수 있는 점 수
MAX_TURN_POINTS = 20000  # 한 턴 동안 그릴 수 있는 점 수
MIN_WIDTH = 0.002
MAX_WIDTH = 0.08

# 그리기 도구 (design.md 6장 "그리기 도구"). 화면(static/canvas.js)과 같은 값을 쓴다.
PALETTE = ["#222222", "#e53935", "#fb8c00", "#fdd835", "#43a047", "#1e88e5", "#8e24aa", "#6d4c41"]
ERASER_COLOR = "#ffffff"
WIDTHS = [0.006, 0.012, 0.024]
ERASER_WIDTH = 0.04


@dataclass
class Player:
    """방에 들어온 한 사람."""

    player_id: str
    nickname: str
    sid: str = ""
    score: int = 0
    guessed: bool = False
    connected: bool = True
    first_guesses: int = 0  # 첫 정답 횟수 (동점일 때 순위 기준)
    disconnected_at: float = 0.0  # 연결이 끊긴 시각 (connected가 False일 때)


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
    deadline: float = 0.0  # 지금 단계(고르기·그리기·정답 공개)가 끝나는 시각
    hint_stage: int = 0  # 0: 글자 수, 1: 첫 글자 초성까지
    guess_order: list[str] = field(default_factory=list)  # 이번 턴에 맞힌 순서
    turn_points: dict[str, int] = field(default_factory=dict)  # 이번 턴에 얻은 점수
    used_words: set[str] = field(default_factory=set)
    ranking: list[dict] = field(default_factory=list)

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

    @property
    def drawer_id(self) -> str | None:
        """이번 턴 출제자의 player_id. 게임 중이 아니면 None."""
        if self.state not in ("choosing", "drawing") or not self.players:
            return None
        return self.players[self.drawer_index % len(self.players)].player_id

    def can_draw(self, player_id: str) -> bool:
        """그림을 그릴 수 있는 사람인지: 그리는 단계의 출제자만."""
        return self.state == "drawing" and self.drawer_id == player_id

    def add_stroke_part(self, player_id: str, data: dict) -> dict:
        """출제자가 보낸 선 조각을 검사해 저장하고, 다른 사람에게 보낼 조각을 돌려준다.

        같은 id면 앞 조각에 점을 이어 붙이고, 새 id면 새 선을 시작한다.
        그릴 수 없는 사람이거나 데이터가 이상하면 ValueError.
        """
        if not self.can_draw(player_id):
            raise ValueError("지금은 그릴 수 없어요.")
        part = clean_stroke_part(data)
        used = sum(len(s["points"]) for s in self.strokes)
        if used + len(part["points"]) > MAX_TURN_POINTS:
            raise ValueError("이번 턴에 그릴 수 있는 양을 넘었어요.")

        last = self.strokes[-1] if self.strokes else None
        if last and last["id"] == part["id"]:
            last["points"].extend(part["points"])
        else:
            self.strokes.append({**part, "points": list(part["points"])})
        return part

    def undo_stroke(self, player_id: str, stroke_id: str) -> str:
        """출제자가 마지막 선을 되돌린다. 지운 선 id를 돌려준다. 없으면 ValueError."""
        if not self.can_draw(player_id):
            raise ValueError("지금은 그릴 수 없어요.")
        if not self.strokes or self.strokes[-1]["id"] != stroke_id:
            raise ValueError("되돌릴 선이 없어요.")
        self.strokes.pop()
        return stroke_id

    def clear_strokes(self, player_id: str) -> None:
        """출제자가 그림을 모두 지운다."""
        if not self.can_draw(player_id):
            raise ValueError("지금은 그릴 수 없어요.")
        self.strokes.clear()

    # ---------- 게임 진행 (T12~T15) ----------

    def drawer(self) -> Player | None:
        """이번 턴 출제자."""
        did = self.drawer_id
        return self.find_player(did) if did else None

    def guessers(self) -> list[Player]:
        """이번 턴에 맞혀야 하는 사람들 (출제자 제외, 접속 중)."""
        return [p for p in self.players if p.player_id != self.drawer_id and p.connected]

    def seconds_left(self, now: float) -> int:
        """지금 단계의 남은 초."""
        return max(0, int(round(self.deadline - now)))

    def start_game(self, player_id: str, now: float, words: dict[str, list[str]]) -> list[Out]:
        """방장이 게임을 시작한다."""
        if player_id != self.host_id:
            raise ValueError("방장만 시작할 수 있어요.")
        if self.state != "waiting":
            raise ValueError("이미 게임이 진행 중이에요.")
        if len(self.players) < MIN_PLAYERS:
            raise ValueError(f"{MIN_PLAYERS}명 이상 모여야 시작할 수 있어요.")
        for p in self.players:
            p.score = 0
            p.first_guesses = 0
            p.guessed = False
        self.round = 1
        self.drawer_index = 0
        self.ranking = []
        self.used_words = set()
        return [Out("game_started", {"total_rounds": TOTAL_ROUNDS})] + self._start_turn(now, words)

    def _start_turn(self, now: float, words: dict[str, list[str]]) -> list[Out]:
        """새 턴: 출제자에게 제시어 3개를 보여 준다."""
        self.state = "choosing"
        self.word = None
        self.strokes = []
        self.guess_order = []
        self.turn_points = {}
        self.hint_stage = 0
        for p in self.players:
            p.guessed = False
        self.word_choices = pick_word_choices(words, self.used_words)
        self.deadline = now + CHOOSE_SECONDS
        drawer = self.drawer()
        if drawer is None:
            return self._end_game()
        return [
            Out("turn_choosing", {"drawer_id": drawer.player_id, "nickname": drawer.nickname,
                                  "round": self.round, "seconds": CHOOSE_SECONDS}),
            Out("word_choices", {"choices": list(self.word_choices), "seconds": CHOOSE_SECONDS},
                to=[drawer.player_id]),
            Out.state(),
        ]

    def choose_word(self, player_id: str, word: str, now: float) -> list[Out]:
        """출제자가 제시어를 고른다."""
        if self.state != "choosing" or player_id != self.drawer_id:
            raise ValueError("지금은 제시어를 고를 수 없어요.")
        if word not in self.word_choices:
            raise ValueError("보기에 없는 제시어예요.")
        return self._begin_drawing(word, now)

    def _begin_drawing(self, word: str, now: float) -> list[Out]:
        self.state = "drawing"
        self.word = word
        self.used_words.add(word)
        self.word_choices = []
        self.turn_started_at = now
        self.deadline = now + TURN_SECONDS
        return [
            Out("turn_start", self.turn_info(now)),
            Out("your_word", {"word": word}, to=[self.drawer_id]),
            Out.state(),
        ]

    def turn_info(self, now: float) -> dict:
        """모두에게 보내는 이번 턴 정보 (정답은 빼고 힌트만)."""
        drawer = self.drawer()
        return {
            "drawer_id": drawer.player_id if drawer else None,
            "nickname": drawer.nickname if drawer else "",
            "round": self.round,
            "length": len(self.word or ""),
            "hint": make_hint(self.word or "", self.hint_stage),
            "seconds": self.seconds_left(now),
        }

    def chat(self, player_id: str, text: str, now: float) -> list[Out]:
        """채팅 한 줄. 그리는 중이면 정답 판정도 한다."""
        player = self.find_player(player_id)
        text = clean_chat(text)
        if player is None or not text:
            return []
        message = {"player_id": player_id, "nickname": player.nickname, "text": text}

        if self.state == "choosing" and player_id == self.drawer_id:
            # 고르는 중인 출제자가 보기 단어를 미리 말하지 못하게 한다
            if any(normalize(w) in normalize(text) for w in self.word_choices):
                return [Out("notice", {"text": "제시어 보기는 채팅으로 말할 수 없어요."}, to=[player_id])]
            return [Out("chat", message)]

        if self.state != "drawing":
            return [Out("chat", message)]

        if now >= self.deadline:
            # 시간이 끝난 뒤 도착한 말은 판정하지 않고 턴을 끝낸다 (다음 타이머 확인 전이라도)
            return self._end_turn(now, "time_up")

        if player_id == self.drawer_id:
            if normalize(self.word) in normalize(text):
                return [Out("notice", {"text": "정답이 들어간 메시지는 보낼 수 없어요."}, to=[player_id])]
            return [Out("chat", message)]

        if player.guessed:
            # 이미 맞힌 사람의 말은 출제자와 맞힌 사람끼리만 본다 (정답 힌트 방지)
            insiders = [self.drawer_id] + self.guess_order
            return [Out("chat", {**message, "insider": True}, to=insiders)]

        if is_correct(text, self.word):
            return self._correct(player, now)

        if normalize(self.word) in normalize(text):
            # "정답 코끼리?"처럼 정답이 들어 있지만 딱 맞지 않은 말: 다른 사람에게 정답이 보이지 않게 본인에게만
            return [
                Out("chat", message, to=[player_id]),
                Out("notice", {"text": "정답 단어만 입력해야 맞힌 것으로 쳐요."}, to=[player_id]),
            ]

        if is_close(text, self.word):
            return [
                Out("chat", message, to=[player_id]),
                Out("notice", {"text": "거의 맞았어요!"}, to=[player_id]),
            ]
        return [Out("chat", message)]

    def _correct(self, player: Player, now: float) -> list[Out]:
        first = not self.guess_order
        points = guess_score(self.deadline - now, first)
        player.guessed = True
        player.score += points
        if first:
            player.first_guesses += 1
        self.guess_order.append(player.player_id)
        self.turn_points[player.player_id] = points
        outs = [
            Out("correct", {"player_id": player.player_id, "nickname": player.nickname, "points": points}),
            Out.state(),
        ]
        if all(p.guessed for p in self.guessers()):
            outs += self._end_turn(now, "all_correct")
        return outs

    # ---------- 연결 끊김 · 나가기 (T20~T21) ----------

    def disconnect(self, player_id: str, now: float) -> list[Out]:
        """연결이 끊겼다. 30초 동안 자리를 남겨 둔다."""
        player = self.find_player(player_id)
        if player is None or not player.connected:
            return []
        player.connected = False
        player.disconnected_at = now
        outs = [Out.state()]
        # 남은 사람이 모두 이미 맞혔다면 기다릴 필요가 없다
        if self.state == "drawing" and player_id != self.drawer_id and self.guessers() \
                and all(p.guessed for p in self.guessers()):
            outs += self._end_turn(now, "all_correct")
        return outs

    def reconnect(self, player: Player, sid: str) -> list[Out]:
        """같은 player_id로 다시 들어왔다. 자리와 점수를 그대로 돌려준다."""
        player.sid = sid
        player.connected = True
        player.disconnected_at = 0.0
        return [Out.state()]

    def remove_player(self, player_id: str, now: float, words: dict[str, list[str]]) -> list[Out]:
        """방에서 내보낸다 (나가기 버튼, 또는 30초 동안 돌아오지 않음)."""
        player = self.find_player(player_id)
        if player is None:
            return []
        outs: list[Out] = []
        index = self.players.index(player)
        was_drawer = player_id == self.drawer_id

        # 그리던 사람이 나가면 이번 턴은 바로 끝낸다
        if was_drawer and self.state in ("choosing", "drawing"):
            if self.state == "choosing":
                self.word = None
            outs += self._end_turn(now, "drawer_left")

        self.players.remove(player)
        if index <= self.drawer_index and self.state != "waiting":
            # 지금·이전 출제자가 빠지면 순서가 한 칸씩 당겨진다
            self.drawer_index -= 1
        outs.append(Out("left", {"player_id": player_id, "nickname": player.nickname}))

        if not self.players:
            rooms.pop(self.code, None)
            return []
        if self.host_id == player_id:
            connected = [p for p in self.players if p.connected]
            self.host_id = (connected or self.players)[0].player_id
            outs.append(Out("notice", {"text": "방장이 나가서 방장이 바뀌었어요."}))

        if self.state not in ("waiting", "game_end") and len(self.players) < MIN_PLAYERS:
            outs.append(Out("notice", {"text": "남은 사람이 부족해서 게임을 끝냈어요."}))
            return outs + self._end_game()
        if self.state == "drawing" and self.guessers() and all(p.guessed for p in self.guessers()):
            outs += self._end_turn(now, "all_correct")
        return outs + [Out.state()]

    def tick(self, now: float, words: dict[str, list[str]]) -> list[Out]:
        """시간이 흐르며 생기는 일: 오래 끊긴 사람 내보내기, 자동 선택, 힌트, 시간 초과, 다음 턴."""
        outs: list[Out] = []
        for p in list(self.players):
            if not p.connected and now - p.disconnected_at >= RECONNECT_SECONDS:
                outs += self.remove_player(p.player_id, now, words)
        if self.code not in rooms:
            return outs
        return outs + self._tick_turn(now, words)

    def _tick_turn(self, now: float, words: dict[str, list[str]]) -> list[Out]:
        if self.state == "choosing" and now >= self.deadline:
            return self._begin_drawing(random.choice(self.word_choices), now)
        if self.state == "drawing":
            if now >= self.deadline:
                return self._end_turn(now, "time_up")
            if self.hint_stage == 0 and now - self.turn_started_at >= HINT_SECONDS:
                self.hint_stage = 1
                return [Out("hint", {"hint": make_hint(self.word, 1)})]
        if self.state == "turn_end" and now >= self.deadline:
            return self._next_turn(now, words)
        return []

    def _end_turn(self, now: float, reason: str) -> list[Out]:
        """턴 끝: 출제자 점수를 더하고 정답을 공개한다."""
        drawer = self.drawer()
        if drawer and reason != "drawer_left":
            gained = drawer_score(len(self.guess_order))
            drawer.score += gained
            self.turn_points[drawer.player_id] = gained
        word = self.word
        self.state = "turn_end"
        self.deadline = now + TURN_END_SECONDS
        scores = [
            {"player_id": p.player_id, "nickname": p.nickname, "points": self.turn_points.get(p.player_id, 0)}
            for p in sorted(self.players, key=lambda p: -self.turn_points.get(p.player_id, 0))
        ]
        nxt = self._peek_next_drawer()
        return [
            Out("turn_end", {"word": word, "reason": reason, "scores": scores, "seconds": TURN_END_SECONDS,
                             "next_drawer": nxt.nickname if nxt else None}),
            Out.state(),
        ]

    def _peek_next_drawer(self) -> Player | None:
        """다음 턴 출제자. 이번이 마지막 턴이면 None."""
        index, rnd = self.drawer_index + 1, self.round
        if index >= len(self.players):
            index, rnd = 0, rnd + 1
        if rnd > TOTAL_ROUNDS or not self.players:
            return None
        return self.players[index]

    def _next_turn(self, now: float, words: dict[str, list[str]]) -> list[Out]:
        """다음 출제자로. 모두 한 번씩 그렸으면 다음 라운드, 마지막 라운드면 게임 끝."""
        self.drawer_index += 1
        if self.drawer_index >= len(self.players):
            self.drawer_index = 0
            self.round += 1
        if self.round > TOTAL_ROUNDS:
            return self._end_game()
        return self._start_turn(now, words)

    def _end_game(self) -> list[Out]:
        self.state = "game_end"
        self.word = None
        self.ranking = make_ranking(self.players)
        return [Out("game_end", {"ranking": self.ranking}), Out.state()]

    def back_to_lobby(self) -> list[Out]:
        """게임이 끝난 뒤 [다시 하기]: 같은 사람들과 대기실로."""
        if self.state != "game_end":
            raise ValueError("게임이 끝난 뒤에만 돌아갈 수 있어요.")
        self.state = "waiting"
        self.round = 1
        self.drawer_index = 0
        self.strokes = []
        for p in self.players:
            p.score = 0
            p.first_guesses = 0
            p.guessed = False
        return [Out("lobby", {}), Out.state()]

    def private_outs(self, player_id: str, now: float) -> list[Out]:
        """다시 연결한 사람에게 보낼 지금 상황 (출제자에게는 제시어 포함)."""
        outs = []
        if self.state == "choosing":
            drawer = self.drawer()
            outs.append(Out("turn_choosing", {"drawer_id": drawer.player_id, "nickname": drawer.nickname,
                                              "round": self.round, "seconds": self.seconds_left(now)},
                            to=[player_id]))
            if player_id == self.drawer_id:
                outs.append(Out("word_choices", {"choices": list(self.word_choices),
                                                 "seconds": self.seconds_left(now)}, to=[player_id]))
        elif self.state == "drawing":
            outs.append(Out("turn_start", self.turn_info(now), to=[player_id]))
            if player_id == self.drawer_id:
                outs.append(Out("your_word", {"word": self.word}, to=[player_id]))
        elif self.state == "game_end":
            outs.append(Out("game_end", {"ranking": self.ranking}, to=[player_id]))
        return outs

    def public_state(self, now: float | None = None) -> dict:
        """모든 참가자에게 보내도 되는 방 정보. 제시어(word)는 넣지 않는다."""
        now = time.time() if now is None else now
        return {
            "code": self.code,
            "host_id": self.host_id,
            "drawer_id": self.drawer_id,
            "state": self.state,
            "round": self.round,
            "total_rounds": TOTAL_ROUNDS,
            "seconds": self.seconds_left(now) if self.state != "waiting" else 0,
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


@dataclass
class Out:
    """app.py가 보낼 메시지 하나. to가 None이면 방 전체, 아니면 그 player_id들에게만."""

    event: str
    data: dict = field(default_factory=dict)
    to: list[str] | None = None

    @staticmethod
    def state() -> "Out":
        """방 정보(room_state)를 방 전체에 다시 보내라는 표시."""
        return Out("room_state")


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


def join_room(code: str, player_id: str, nickname: str, rejoin: bool = False) -> tuple[Room, Player]:
    """방 코드로 방에 들어간다. 실패하면 이유를 담은 ValueError.

    이미 이 방에 있는 player_id라면 다시 연결한 것으로 보고 같은 Player를 돌려준다
    (연결이 끊겨 있었거나, 새로고침처럼 rejoin=True로 온 경우). 게임 중이어도 된다.
    """
    nickname = clean_nickname(nickname)
    if len(normalize_code(code)) != CODE_LENGTH:
        raise ValueError("방 코드 6자리를 입력해 주세요.")
    room = get_room(code)
    if room is None:
        raise ValueError("없는 방 코드예요.")
    existing = room.find_player(player_id) if player_id else None
    if existing and (rejoin or not existing.connected):
        return room, existing
    if existing:
        raise ValueError("이미 이 방에 들어와 있어요. 다른 창이나 탭을 확인해 주세요.")
    if room.state != "waiting":
        raise ValueError("이미 게임이 진행 중이에요.")
    player = Player(player_id=check_player_id(player_id), nickname=nickname)
    room.add_player(player)
    return room, player


def find_by_sid(sid: str) -> tuple[Room, Player] | tuple[None, None]:
    """소켓 연결 ID로 방과 플레이어를 찾는다."""
    for room in rooms.values():
        for player in room.players:
            if player.sid == sid:
                return room, player
    return None, None


def clean_stroke_part(data: dict) -> dict:
    """브라우저가 보낸 선 조각을 검사하고 정리한다. 이상하면 ValueError."""
    if not isinstance(data, dict):
        raise ValueError("잘못된 그림 데이터예요.")
    stroke_id = data.get("id")
    color = data.get("color")
    width = data.get("width")
    points = data.get("points")

    if not isinstance(stroke_id, str) or not 1 <= len(stroke_id) <= 40:
        raise ValueError("잘못된 선 번호예요.")
    if not isinstance(color, str) or color.lower() not in PALETTE + [ERASER_COLOR]:
        raise ValueError("잘못된 색이에요.")
    if not isinstance(width, (int, float)) or not MIN_WIDTH <= width <= MAX_WIDTH:
        raise ValueError("잘못된 굵기예요.")
    if not isinstance(points, list) or not 1 <= len(points) <= MAX_PART_POINTS:
        raise ValueError("잘못된 점 목록이에요.")

    cleaned = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("잘못된 점이에요.")
        x, y = point
        if not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in (x, y)):
            raise ValueError("점이 캔버스 밖에 있어요.")
        cleaned.append([round(float(x), 4), round(float(y), 4)])

    return {"id": stroke_id, "color": color.lower(), "width": round(float(width), 4), "points": cleaned}


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


# ---------- 게임 규칙 도우미 ----------

CHOSUNG = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"


def chosung(char: str) -> str:
    """한글 한 글자의 초성. 한글이 아니면 그대로."""
    code = ord(char) - 0xAC00
    if 0 <= code < 11172:
        return CHOSUNG[code // 588]
    return char


def make_hint(word: str, stage: int) -> str:
    """힌트: 0단계는 글자 수만 (_ _ _), 1단계는 첫 글자 초성 (ㄱ _ _)."""
    if not word:
        return ""
    marks = ["_"] * len(word)
    if stage >= 1:
        marks[0] = chosung(word[0])
    return " ".join(marks)


def clean_chat(text) -> str:
    """채팅: 앞뒤 공백 제거, 줄바꿈 제거, 50자까지."""
    if not isinstance(text, str):
        return ""
    return " ".join(text.split())[:CHAT_MAX]


def is_close(guess: str, answer: str) -> bool:
    """정답과 한 글자만 다른지 (바꾸기·넣기·빼기 한 번). 두 글자 이상 단어만."""
    a, b = normalize(guess), normalize(answer)
    if a == b or len(b) < 2 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def pick_word_choices(words: dict[str, list[str]], used: set[str]) -> list[str]:
    """쉬움·보통·어려움에서 하나씩, 이번 게임에 나온 적 없는 단어로 고른다."""
    choices = []
    for level in ("easy", "normal", "hard"):
        pool = [w for w in words.get(level, []) if w not in used and w not in choices]
        if not pool:
            pool = [w for w in words.get(level, []) if w not in choices]
        if pool:
            choices.append(random.choice(pool))
    return choices


def make_ranking(players: list[Player]) -> list[dict]:
    """최종 순위: 점수 높은 순, 같으면 첫 정답 횟수 많은 순. 둘 다 같으면 같은 등수."""
    ordered = sorted(players, key=lambda p: (-p.score, -p.first_guesses))
    ranking = []
    for i, p in enumerate(ordered):
        prev = ordered[i - 1] if i else None
        same = prev and (prev.score, prev.first_guesses) == (p.score, p.first_guesses)
        rank = ranking[-1]["rank"] if same else i + 1
        ranking.append({"rank": rank, "player_id": p.player_id, "nickname": p.nickname,
                        "score": p.score, "first_guesses": p.first_guesses})
    return ranking


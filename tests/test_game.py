"""game.py 단위 테스트. 실행: python -m pytest"""
import pytest

import game


@pytest.fixture(autouse=True)
def clear_rooms():
    """테스트마다 방 목록을 비운다."""
    game.rooms.clear()
    yield
    game.rooms.clear()


def test_room_code_format():
    code = game.make_room_code()
    assert len(code) == 6
    assert all(ch in game.CODE_CHARS for ch in code)


def test_room_code_has_no_confusing_chars():
    for ch in "0O1IL":
        assert ch not in game.CODE_CHARS


def test_room_codes_do_not_repeat():
    codes = {game.create_room(f"p{i}", f"사람{i}").code for i in range(200)}
    assert len(codes) == 200


def test_create_room_makes_host():
    room = game.create_room("p1", "  윤하  ")
    assert room.host_id == "p1"
    assert room.state == "waiting"
    assert [p.nickname for p in room.players] == ["윤하"]
    assert game.get_room(room.code) is room


def test_get_room_ignores_case_and_spaces():
    room = game.create_room("p1", "윤하")
    assert game.get_room(" " + room.code.lower() + " ") is room
    assert game.get_room("ZZZZZZ") is None


def test_nickname_rules():
    assert game.clean_nickname("가나다라마바사아자차카") == "가나다라마바사아자차"
    with pytest.raises(ValueError):
        game.clean_nickname("   ")


def test_room_full_at_eight():
    room = game.create_room("p0", "방장")
    for i in range(1, game.MAX_PLAYERS):
        room.add_player(game.Player(player_id=f"p{i}", nickname=f"사람{i}"))
    assert room.is_full()
    with pytest.raises(ValueError):
        room.add_player(game.Player(player_id="p9", nickname="늦은사람"))


def test_same_player_cannot_join_twice():
    room = game.create_room("p1", "윤하")
    with pytest.raises(ValueError):
        room.add_player(game.Player(player_id="p1", nickname="윤하"))


def test_can_start_needs_two_players():
    room = game.create_room("p1", "윤하")
    assert not room.can_start()
    room.add_player(game.Player(player_id="p2", nickname="민수"))
    assert room.can_start()


def test_public_state_hides_word():
    room = game.create_room("p1", "윤하")
    room.word = "고양이"
    state = room.public_state()
    assert "word" not in state
    assert "고양이" not in str(state)
    assert state["players"][0]["nickname"] == "윤하"


def test_words_file_loads():
    words = game.load_words()
    assert set(words) == {"easy", "normal", "hard"}
    assert sum(len(v) for v in words.values()) >= 100


def test_join_room_adds_player():
    room = game.create_room("p1", "윤하")
    joined, player = game.join_room(room.code.lower(), "p2", " 민수 ")
    assert joined is room
    assert player.nickname == "민수"
    assert [p.player_id for p in room.players] == ["p1", "p2"]


def test_join_room_errors():
    room = game.create_room("p1", "윤하")
    with pytest.raises(ValueError, match="없는 방 코드"):
        game.join_room("ZZZZZZ", "p2", "민수")
    with pytest.raises(ValueError, match="닉네임"):
        game.join_room(room.code, "p2", "  ")
    with pytest.raises(ValueError, match="접속 정보"):
        game.join_room(room.code, "", "민수")


def test_join_room_error_messages_in_order():
    """design.md 3장의 입장 오류 메시지 순서."""
    room = game.create_room("p1", "윤하")
    cases = [
        (("", "p2", " "), "닉네임을 입력해 주세요."),
        (("AB12", "p2", "민수"), "방 코드 6자리를 입력해 주세요."),
        (("ZZZZZZ", "p2", "민수"), "없는 방 코드예요."),
        ((room.code, "p1", "윤하"), "이미 이 방에 들어와 있어요. 다른 창이나 탭을 확인해 주세요."),
    ]
    for args, message in cases:
        with pytest.raises(ValueError) as err:
            game.join_room(*args)
        assert str(err.value) == message


def test_join_room_full_message():
    room = game.create_room("p0", "방장")
    for i in range(1, 8):
        game.join_room(room.code, f"p{i}", f"사람{i}")
    with pytest.raises(ValueError) as err:
        game.join_room(room.code, "p8", "아홉째")
    assert str(err.value) == "방이 가득 찼어요. (8/8)"
    assert len(room.players) == 8


def test_cannot_join_game_in_progress():
    room = game.create_room("p1", "윤하")
    room.state = "drawing"
    with pytest.raises(ValueError, match="이미 게임이 진행 중"):
        game.join_room(room.code, "p2", "민수")


def drawing_room():
    """윤하가 출제자로 그리는 중인 방."""
    room = game.create_room("p1", "윤하")
    game.join_room(room.code, "p2", "민수")
    room.state = "drawing"
    room.drawer_index = 0
    return room


def part(stroke_id="a-1", points=None, color="#222222", width=0.012):
    return {"id": stroke_id, "color": color, "width": width, "points": [[0.1, 0.2]] if points is None else points}


def test_only_drawer_can_draw():
    room = drawing_room()
    assert room.drawer_id == "p1"
    assert room.can_draw("p1")
    assert not room.can_draw("p2")
    room.state = "waiting"
    assert room.drawer_id is None
    assert not room.can_draw("p1")


def test_stroke_parts_join_by_id():
    room = drawing_room()
    room.add_stroke_part("p1", part("a-1", [[0.1, 0.1], [0.2, 0.2]]))
    room.add_stroke_part("p1", part("a-1", [[0.3, 0.3]]))
    room.add_stroke_part("p1", part("a-2", [[0.5, 0.5]]))
    assert [s["id"] for s in room.strokes] == ["a-1", "a-2"]
    assert room.strokes[0]["points"] == [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]


def test_non_drawer_stroke_rejected():
    room = drawing_room()
    with pytest.raises(ValueError):
        room.add_stroke_part("p2", part())
    assert room.strokes == []


@pytest.mark.parametrize(
    "bad",
    [
        part(points=[[1.5, 0.2]]),
        part(points=[[0.1]]),
        part(points=[]),
        part(points=[[0.1, 0.1]] * (game.MAX_PART_POINTS + 1)),
        part(color="red"),
        part(color="#12345"),
        part(width=0.5),
        part(stroke_id=""),
        {"id": "a-1"},
        "not a dict",
    ],
)
def test_bad_stroke_data_rejected(bad):
    room = drawing_room()
    with pytest.raises(ValueError):
        room.add_stroke_part("p1", bad)


def test_stroke_points_rounded():
    cleaned = game.clean_stroke_part(part(points=[[0.123456, 1]], color="#E53935"))
    assert cleaned["points"] == [[0.1235, 1.0]]
    assert cleaned["color"] == "#e53935"


def test_only_palette_and_eraser_colors():
    for color in game.PALETTE + [game.ERASER_COLOR]:
        game.clean_stroke_part(part(color=color))
    with pytest.raises(ValueError):
        game.clean_stroke_part(part(color="#123456"))


def test_undo_and_clear():
    room = drawing_room()
    room.add_stroke_part("p1", part("a-1"))
    room.add_stroke_part("p1", part("a-2"))
    with pytest.raises(ValueError):
        room.undo_stroke("p1", "a-1")  # 마지막 선만 되돌릴 수 있다
    with pytest.raises(ValueError):
        room.undo_stroke("p2", "a-2")  # 출제자만
    assert room.undo_stroke("p1", "a-2") == "a-2"
    assert [s["id"] for s in room.strokes] == ["a-1"]
    with pytest.raises(ValueError):
        room.clear_strokes("p2")
    room.clear_strokes("p1")
    assert room.strokes == []


def test_turn_point_limit():
    room = drawing_room()
    chunk = [[0.5, 0.5]] * game.MAX_PART_POINTS
    for i in range(game.MAX_TURN_POINTS // game.MAX_PART_POINTS):
        room.add_stroke_part("p1", part(f"s-{i}", chunk))
    with pytest.raises(ValueError):
        room.add_stroke_part("p1", part("s-last", [[0.5, 0.5]]))


def test_public_state_has_drawer_but_not_word():
    room = drawing_room()
    room.word = "고양이"
    state = room.public_state()
    assert state["drawer_id"] == "p1"
    assert "고양이" not in str(state)


# ---------- 게임 진행 (T12~T16) ----------

WORDS = {"easy": ["사과", "토끼"], "normal": ["등대", "기린"], "hard": ["열기구", "오로라"]}


def events_of(outs, name):
    return [o for o in outs if o.event == name]


def started_room(n=3, now=1000.0):
    """n명이 들어와 게임을 시작한 방. 첫 출제자는 p0."""
    room = game.create_room("p0", "사람0")
    for i in range(1, n):
        game.join_room(room.code, f"p{i}", f"사람{i}")
    outs = room.start_game("p0", now, WORDS)
    return room, outs


def test_start_game_rules():
    room = game.create_room("p0", "방장")
    with pytest.raises(ValueError, match="2명 이상"):
        room.start_game("p0", 0, WORDS)
    game.join_room(room.code, "p1", "민수")
    with pytest.raises(ValueError, match="방장만"):
        room.start_game("p1", 0, WORDS)
    outs = room.start_game("p0", 0, WORDS)
    assert room.state == "choosing" and room.round == 1 and room.drawer_id == "p0"
    choices = events_of(outs, "word_choices")[0]
    assert choices.to == ["p0"]  # 제시어 보기는 출제자에게만
    assert len(choices.data["choices"]) == 3
    assert set(choices.data["choices"]) <= {w for ws in WORDS.values() for w in ws}
    with pytest.raises(ValueError, match="이미 게임이 진행 중"):
        room.start_game("p0", 0, WORDS)


def test_choose_word_only_drawer_and_only_choices():
    room, _ = started_room()
    with pytest.raises(ValueError):
        room.choose_word("p1", room.word_choices[0], 1001)
    with pytest.raises(ValueError):
        room.choose_word("p0", "없는단어", 1001)
    word = room.word_choices[1]
    outs = room.choose_word("p0", word, 1001)
    assert room.state == "drawing" and room.word == word
    start = events_of(outs, "turn_start")[0]
    assert start.to is None and word not in str(start.data)  # 모두에게는 정답 없이
    assert start.data["length"] == len(word)
    assert events_of(outs, "your_word")[0].to == ["p0"]


def test_auto_choose_after_10_seconds():
    room, _ = started_room(now=1000)
    assert room.tick(1009, WORDS) == []
    outs = room.tick(1010, WORDS)
    assert room.state == "drawing" and room.word in WORDS["easy"] + WORDS["normal"] + WORDS["hard"]
    assert events_of(outs, "turn_start")


def drawing(n=3, word="열기구", now=1000.0):
    room, _ = started_room(n, now)
    room.word_choices = [word]
    room.choose_word("p0", word, now)
    return room


def test_chat_and_correct_answer_hidden():
    room = drawing()
    outs = room.chat("p1", "풍선?", 1005)
    assert events_of(outs, "chat")[0].data["text"] == "풍선?"
    outs = room.chat("p1", " 열 기구 ", 1020)  # 띄어쓰기 무시
    assert not events_of(outs, "chat")  # 정답은 채팅으로 보이지 않는다
    correct = events_of(outs, "correct")[0].data
    assert correct["player_id"] == "p1" and "열기구" not in str(correct)
    assert room.find_player("p1").guessed


def test_scores_first_bonus_and_drawer():
    room = drawing(n=3, now=1000)
    room.chat("p1", "열기구", 1020)  # 60초 남음: 75점 + 첫 정답 20
    room.chat("p2", "열기구", 1060)  # 20초 남음: 25점
    p0, p1, p2 = (room.find_player(f"p{i}") for i in range(3))
    assert p1.score == 95 and p1.first_guesses == 1
    assert p2.score == 25
    assert room.state == "turn_end"  # 모두 맞히면 바로 턴 끝
    assert p0.score == 50  # 출제자: 2명 x 25점


def test_minimum_score_20():
    room = drawing(n=2, now=1000)
    room.chat("p1", "열기구", 1079.9)
    assert room.find_player("p1").score == 20 + 20


def test_close_answer_only_to_self():
    room = drawing(word="열기구")
    outs = room.chat("p1", "열기수", 1005)
    assert all(o.to == ["p1"] for o in outs)
    assert events_of(outs, "notice")[0].data["text"] == "거의 맞았어요!"


def test_drawer_cannot_say_answer():
    room = drawing(word="열기구")
    outs = room.chat("p0", "이건 열기구야", 1005)
    assert events_of(outs, "notice")[0].to == ["p0"]
    assert not events_of(outs, "chat")


def test_guessed_players_chat_only_with_insiders():
    room = drawing(n=3)
    room.chat("p1", "열기구", 1005)
    outs = room.chat("p1", "쉬웠다", 1006)
    assert set(events_of(outs, "chat")[0].to) == {"p0", "p1"}
    score = room.find_player("p1").score
    outs = room.chat("p1", "열기구", 1007)  # 다시 말해도 점수 없음
    assert not events_of(outs, "correct") and room.find_player("p1").score == score


def test_hint_after_40_seconds_and_time_up():
    room = drawing(word="열기구", now=1000)
    assert room.turn_info(1000)["hint"] == "_ _ _"
    assert room.tick(1039, WORDS) == []
    outs = room.tick(1040, WORDS)
    assert events_of(outs, "hint")[0].data["hint"] == "ㅇ _ _"
    outs = room.tick(1080, WORDS)
    end = events_of(outs, "turn_end")[0].data
    assert end["word"] == "열기구" and end["reason"] == "time_up"
    assert room.find_player("p0").score == 0  # 아무도 못 맞히면 출제자 0점


def test_full_game_three_rounds():
    """3명이 3라운드: 턴 9번 뒤 게임 끝, 출제 순서 p0 p1 p2 반복."""
    words = game.load_words()
    room = game.create_room("p0", "사람0")
    for i in (1, 2):
        game.join_room(room.code, f"p{i}", f"사람{i}")
    room.start_game("p0", 0, words)
    now, drawers = 0.0, []
    while room.state != "game_end":
        assert room.state == "choosing"
        drawers.append(room.drawer_id)
        now += 1
        room.choose_word(room.drawer_id, room.word_choices[0], now)
        for p in room.guessers():
            room.chat(p.player_id, room.word, now + 10)
        assert room.state == "turn_end"
        now += 20
        room.tick(now, words)
    assert drawers == ["p0", "p1", "p2"] * 3
    assert len(room.used_words) == 9  # 한 게임에서 같은 단어가 다시 나오지 않는다(단어가 충분할 때)
    assert room.ranking[0]["rank"] == 1


def test_ranking_ties():
    a = game.Player("a", "가", score=100, first_guesses=1)
    b = game.Player("b", "나", score=100, first_guesses=2)
    c = game.Player("c", "다", score=100, first_guesses=1)
    d = game.Player("d", "라", score=50)
    ranking = game.make_ranking([a, b, c, d])
    assert [(r["player_id"], r["rank"]) for r in ranking] == [("b", 1), ("a", 2), ("c", 2), ("d", 4)]


def test_back_to_lobby_resets():
    room, _ = started_room(n=2, now=0)
    with pytest.raises(ValueError):
        room.back_to_lobby()
    room._end_game()
    room.back_to_lobby()
    assert room.state == "waiting" and all(p.score == 0 for p in room.players)


def test_helpers():
    assert game.chosung("가") == "ㄱ" and game.chosung("힣") == "ㅎ" and game.chosung("A") == "A"
    assert game.is_close("고양이", "고양미") and game.is_close("고양", "고양이")
    assert not game.is_close("고양이", "고양이") and not game.is_close("개", "새")
    assert game.clean_chat("  안녕\n하세요  ") == "안녕 하세요"
    assert len(game.clean_chat("가" * 80)) == game.CHAT_MAX


def test_turn_end_names_next_drawer():
    room = drawing(n=2, now=1000)
    outs = room.tick(1080, WORDS)
    assert events_of(outs, "turn_end")[0].data["next_drawer"] == "사람1"
    room.round, room.drawer_index = game.TOTAL_ROUNDS, 1
    assert room._peek_next_drawer() is None


# ---------- 연결 끊김 · 나가기 (T20~T21) ----------


def test_disconnect_keeps_seat_for_30_seconds():
    room = drawing(n=3, now=1000)
    room.chat("p1", "열기구", 1010)
    score = room.find_player("p1").score
    room.disconnect("p1", 1020)
    assert not room.find_player("p1").connected
    room.tick(1049, WORDS)
    assert room.find_player("p1") is not None  # 29초: 아직 자리 있음
    again, player = game.join_room(room.code, "p1", "사람1")  # 게임 중이어도 돌아올 수 있다
    room.reconnect(player, "new-sid")
    assert player.connected and player.score == score and player.sid == "new-sid"


def test_removed_after_30_seconds():
    room = drawing(n=3, now=1000)
    room.disconnect("p2", 1010)
    outs = room.tick(1040, WORDS)
    assert room.find_player("p2") is None
    assert events_of(outs, "left")[0].data["nickname"] == "사람2"


def test_rejoin_flag_takes_over_connected_seat():
    room = game.create_room("p1", "윤하")
    with pytest.raises(ValueError, match="이미 이 방에"):
        game.join_room(room.code, "p1", "윤하")
    _, player = game.join_room(room.code, "p1", "윤하", rejoin=True)  # 새로고침
    assert player is room.players[0]


def test_host_leaves_next_becomes_host():
    room = game.create_room("p0", "방장")
    game.join_room(room.code, "p1", "민수")
    game.join_room(room.code, "p2", "지영")
    room.disconnect("p1", 0)
    room.remove_player("p0", 0, WORDS)
    assert room.host_id == "p2"  # 연결된 사람 중 첫 번째


def test_drawer_leaves_turn_moves_on():
    room = drawing(n=3, now=1000)  # 출제자 p0
    outs = room.remove_player("p0", 1010, WORDS)
    end = events_of(outs, "turn_end")[0].data
    assert end["reason"] == "drawer_left" and end["next_drawer"] == "사람1"
    room.tick(1010 + game.TURN_END_SECONDS, WORDS)
    assert room.state == "choosing" and room.drawer_id == "p1"


def test_non_drawer_leaving_keeps_order():
    room = drawing(n=4, now=1000)
    room.chat("p1", "열기구", 1001)
    room.chat("p2", "열기구", 1002)
    room.remove_player("p3", 1003, WORDS)  # 남은 사람이 모두 맞혔으니 턴 끝
    assert room.state == "turn_end"
    room.tick(1003 + game.TURN_END_SECONDS, WORDS)
    assert room.drawer_id == "p1"


def test_earlier_player_leaving_does_not_skip_anyone():
    room = drawing(n=3, now=1000)
    room.tick(1080, WORDS)  # p0 턴 끝
    room.tick(1085, WORDS)  # p1 차례
    assert room.drawer_id == "p1"
    room.remove_player("p0", 1086, WORDS)  # 이미 그린 p0이 나가도
    assert room.drawer_id == "p1"  # 지금 출제자는 그대로


def test_too_few_players_ends_game():
    room = drawing(n=2, now=1000)
    outs = room.remove_player("p1", 1010, WORDS)
    assert room.state == "game_end" and events_of(outs, "game_end")


def test_last_player_leaving_deletes_room():
    room = game.create_room("p0", "혼자")
    room.remove_player("p0", 0, WORDS)
    assert game.get_room(room.code) is None


def test_everyone_left_guessed_ends_turn_on_disconnect():
    room = drawing(n=3, now=1000)
    room.chat("p1", "열기구", 1001)
    outs = room.disconnect("p2", 1002)
    assert room.state == "turn_end" and events_of(outs, "turn_end")


def test_second_tab_mid_game_gets_duplicate_message():
    room = drawing(n=2)
    with pytest.raises(ValueError, match="이미 이 방에"):
        game.join_room(room.code, "p1", "사람1")


def test_word_list_meets_r7():
    """R7: 제시어 500개 이상, 난이도 3단계, 중복·띄어쓰기 없음, 1~6글자."""
    words = game.load_words()
    all_words = [w for level in ("easy", "normal", "hard") for w in words[level]]
    assert len(all_words) >= 500
    assert len(set(all_words)) == len(all_words)
    assert all(1 <= len(w) <= 6 and " " not in w for w in all_words)



# ---------- 코드 검토에서 찾은 문제 (2026-10-21) ----------


@pytest.mark.parametrize("text", ["열기구!!", "정답 열기구?", "열기구 맞죠"])
def test_guess_containing_answer_not_shown_to_others(text):
    room = drawing(n=3, word="열기구")
    outs = room.chat("p1", text, 1005)
    assert all(o.to == ["p1"] for o in outs)
    assert not room.find_player("p1").guessed


def test_drawer_cannot_leak_choices_while_choosing():
    room, _ = started_room()
    outs = room.chat("p0", "보기는 " + room.word_choices[2], 1001)
    assert events_of(outs, "notice")[0].to == ["p0"] and not events_of(outs, "chat")
    assert events_of(room.chat("p0", "고르는 중", 1001), "chat")


def test_guess_after_deadline_does_not_score():
    room = drawing(n=3, word="열기구", now=1000)
    outs = room.chat("p1", "열기구", 1080.1)
    assert room.state == "turn_end" and events_of(outs, "turn_end")[0].data["reason"] == "time_up"
    assert room.find_player("p1").score == 0

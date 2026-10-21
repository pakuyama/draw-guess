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

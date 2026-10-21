"""app.py 실시간 이벤트 테스트. 브라우저 대신 Socket.IO 테스트 클라이언트를 쓴다."""
import time

import pytest

import app as server
import game


@pytest.fixture(autouse=True)
def clear_rooms():
    server.app.config["TESTING"] = True  # 테스트에서는 타이머를 켜지 않고 run_tick()을 직접 부른다
    game.rooms.clear()
    yield
    game.rooms.clear()


def connect():
    return server.socketio.test_client(server.app)


def events(client, name):
    """받은 메시지 중 이름이 name인 것들의 데이터 목록."""
    return [m["args"][0] for m in client.get_received() if m["name"] == name]


def test_home_page():
    res = server.app.test_client().get("/")
    assert res.status_code == 200


def test_health_check():
    res = server.app.test_client().get("/healthz")
    assert res.status_code == 200 and res.get_json()["ok"] is True


def test_create_room_sends_code_and_state():
    host = connect()
    host.emit("create_room", {"player_id": "p1", "nickname": "윤하"})
    received = host.get_received()
    names = [m["name"] for m in received]
    assert names == ["room_created", "room_state"]
    code = received[0]["args"][0]["code"]
    state = received[1]["args"][0]
    assert state["code"] == code
    assert state["host_id"] == "p1"


def test_two_players_see_each_other():
    """M1 확인: 두 사람이 같은 방에 들어가 서로 이름이 보인다."""
    host = connect()
    host.emit("create_room", {"player_id": "p1", "nickname": "윤하"})
    code = events(host, "room_created")[0]["code"]

    guest = connect()
    guest.emit("join_room", {"code": code, "player_id": "p2", "nickname": "민수"})

    guest_state = events(guest, "room_state")[-1]
    host_state = events(host, "room_state")[-1]
    for state in (guest_state, host_state):
        assert [p["nickname"] for p in state["players"]] == ["윤하", "민수"]


def test_other_rooms_do_not_receive_state():
    a = connect()
    a.emit("create_room", {"player_id": "a1", "nickname": "가"})
    code_a = events(a, "room_created")[0]["code"]
    b = connect()
    b.emit("create_room", {"player_id": "b1", "nickname": "나"})
    b.get_received()

    c = connect()
    c.emit("join_room", {"code": code_a, "player_id": "a2", "nickname": "다"})
    assert events(b, "room_state") == []


def test_join_wrong_code_sends_error():
    guest = connect()
    guest.emit("join_room", {"code": "ZZZZZZ", "player_id": "p2", "nickname": "민수"})
    assert events(guest, "error") == [{"message": "없는 방 코드예요."}]


def test_create_room_without_nickname_sends_error():
    host = connect()
    host.emit("create_room", {"player_id": "p1", "nickname": ""})
    assert events(host, "error") == [{"message": "닉네임을 입력해 주세요."}]


def test_ninth_player_gets_full_message_and_others_unchanged():
    host = connect()
    host.emit("create_room", {"player_id": "p0", "nickname": "방장"})
    code = events(host, "room_created")[0]["code"]
    for i in range(1, 8):
        connect().emit("join_room", {"code": code, "player_id": f"p{i}", "nickname": f"사람{i}"})
    host.get_received()

    ninth = connect()
    ninth.emit("join_room", {"code": code, "player_id": "p8", "nickname": "아홉째"})
    assert events(ninth, "error") == [{"message": "방이 가득 찼어요. (8/8)"}]
    assert events(ninth, "room_state") == []
    assert events(host, "room_state") == []  # 실패한 입장은 방 사람들에게 알리지 않는다


def drawing_setup():
    """윤하(출제자)와 민수가 그리는 중인 방."""
    host = connect()
    host.emit("create_room", {"player_id": "p1", "nickname": "윤하"})
    code = events(host, "room_created")[0]["code"]
    guest = connect()
    guest.emit("join_room", {"code": code, "player_id": "p2", "nickname": "민수"})
    room = game.get_room(code)
    room.state = "drawing"
    room.drawer_index = 0
    host.get_received()
    guest.get_received()
    return host, guest, room


def test_stroke_is_relayed_to_others_only():
    host, guest, room = drawing_setup()
    data = {"id": "a-1", "color": "#222222", "width": 0.012, "points": [[0.1, 0.1], [0.2, 0.2]]}
    host.emit("stroke", data)
    assert events(guest, "stroke") == [data]
    assert events(host, "stroke") == []  # 그린 사람에게는 다시 보내지 않는다
    assert room.strokes[0]["points"] == [[0.1, 0.1], [0.2, 0.2]]


def test_stroke_from_non_drawer_is_ignored():
    host, guest, room = drawing_setup()
    guest.emit("stroke", {"id": "b-1", "color": "#222222", "width": 0.012, "points": [[0.5, 0.5]]})
    assert events(host, "stroke") == []
    assert room.strokes == []


def test_bad_stroke_is_ignored():
    host, guest, room = drawing_setup()
    host.emit("stroke", {"id": "a-1", "color": "#222222", "width": 0.012, "points": [[9, 9]]})
    assert events(guest, "stroke") == []
    assert events(host, "error") == []


def test_undo_and_clear_are_relayed():
    host, guest, room = drawing_setup()
    for sid in ("a-1", "a-2"):
        host.emit("stroke", {"id": sid, "color": "#222222", "width": 0.012, "points": [[0.1, 0.1]]})
    guest.get_received()
    host.emit("undo", {"id": "a-2"})
    assert events(guest, "undo") == [{"id": "a-2"}]
    guest.emit("clear")  # 출제자가 아니면 무시
    assert events(host, "clear") == []
    host.emit("clear")
    assert events(guest, "clear") == [{}]
    assert room.strokes == []


def test_sync_sends_current_drawing():
    """T11: 다시 맞추기를 요청하면 지금까지 그린 그림 전체를 받는다."""
    host, guest, room = drawing_setup()
    host.emit("stroke", {"id": "a-1", "color": "#222222", "width": 0.012, "points": [[0.1, 0.1], [0.2, 0.2]]})
    host.emit("stroke", {"id": "a-1", "color": "#222222", "width": 0.012, "points": [[0.3, 0.3]]})
    host.emit("stroke", {"id": "a-2", "color": "#e53935", "width": 0.024, "points": [[0.5, 0.5]]})
    guest.get_received()
    guest.emit("sync")
    received = events(guest, "strokes")
    assert len(received) == 1
    strokes = received[0]["strokes"]
    assert [s["id"] for s in strokes] == ["a-1", "a-2"]
    assert strokes[0]["points"] == [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]


def test_sync_from_unknown_socket_is_ignored():
    stranger = connect()
    stranger.emit("sync")
    assert stranger.get_received() == []


# ---------- 게임 진행 이벤트 (T12~T15) ----------


def lobby_with(n):
    """방장 + (n-1)명이 대기실에 있는 상태. 클라이언트 목록과 방 코드."""
    clients = [connect()]
    clients[0].emit("create_room", {"player_id": "p0", "nickname": "사람0"})
    code = events(clients[0], "room_created")[0]["code"]
    for i in range(1, n):
        c = connect()
        c.emit("join_room", {"code": code, "player_id": f"p{i}", "nickname": f"사람{i}"})
        clients.append(c)
    for c in clients:
        c.get_received()
    return clients, game.get_room(code)


def test_start_game_by_host_only():
    (host, guest), room = lobby_with(2)
    guest.emit("start_game")
    assert events(guest, "error") == [{"message": "방장만 시작할 수 있어요."}]
    host.emit("start_game")
    host_names = [m["name"] for m in host.get_received()]
    guest_got = guest.get_received()
    assert "word_choices" in host_names
    assert "word_choices" not in [m["name"] for m in guest_got]  # 보기는 출제자만
    assert "turn_choosing" in [m["name"] for m in guest_got]
    assert room.state == "choosing"


def test_play_one_turn_over_sockets():
    (host, guest), room = lobby_with(2)
    host.emit("start_game")
    choices = events(host, "word_choices")[0]["choices"]
    guest.get_received()
    host.emit("choose_word", {"word": choices[0]})
    assert events(host, "your_word") == [{"word": choices[0]}]
    start = events(guest, "turn_start")[0]
    assert choices[0] not in str(start)

    guest.emit("chat", {"text": "아무말"})
    assert events(host, "chat")[0]["text"] == "아무말"
    guest.emit("chat", {"text": choices[0]})
    host_msgs = host.get_received()
    assert [m["name"] for m in host_msgs if m["name"] in ("correct", "turn_end")] == ["correct", "turn_end"]
    turn_end = [m["args"][0] for m in host_msgs if m["name"] == "turn_end"][0]
    assert turn_end["word"] == choices[0]


def test_timer_moves_game_forward():
    (host, guest), room = lobby_with(2)
    host.emit("start_game")
    t0 = time.time()
    server.run_tick(t0 + game.CHOOSE_SECONDS + 1)  # 고르지 않으면 자동 선택
    assert room.state == "drawing"
    assert events(host, "your_word")
    server.run_tick(room.turn_started_at + game.HINT_SECONDS + 0.1)
    assert events(guest, "hint")
    server.run_tick(room.deadline + 0.1)  # 시간 초과
    assert room.state == "turn_end"
    server.run_tick(room.deadline + 0.1)  # 5초 뒤 다음 출제자
    assert room.state == "choosing" and room.drawer_id == "p1"


def test_back_to_lobby_after_game_end():
    (host, guest), room = lobby_with(2)
    host.emit("start_game")
    room._end_game()
    guest.emit("back_to_lobby")
    assert events(host, "lobby") == [{}]
    assert room.state == "waiting"


# ---------- 연결 끊김 · 나가기 (T20~T21) ----------


def test_reconnect_after_refresh_restores_game():
    (host, guest), room = lobby_with(2)
    host.emit("start_game")
    word = room.word_choices[0]
    host.emit("choose_word", {"word": word})
    host.emit("stroke", {"id": "a-1", "color": "#222222", "width": 0.012, "points": [[0.1, 0.1]]})
    host.disconnect()  # 새로고침: 연결이 끊김
    assert not room.find_player("p0").connected
    host2 = connect()
    host2.emit("join_room", {"code": room.code, "player_id": "p0", "nickname": "사람0", "rejoin": True})
    names = [m["name"] for m in host2.get_received()]
    assert {"room_joined", "room_state", "turn_start", "your_word", "strokes"} <= set(names)
    assert room.find_player("p0").connected and room.state == "drawing"


def test_leave_room_removes_and_passes_host():
    (host, guest), room = lobby_with(2)
    host.emit("leave_room")
    assert events(host, "left_room") == [{}]
    assert [p.player_id for p in room.players] == ["p1"]
    assert room.host_id == "p1"
    state = events(guest, "room_state")[-1]
    assert state["host_id"] == "p1"


def test_disconnected_player_removed_by_timer():
    (host, guest), room = lobby_with(2)
    guest.disconnect()
    server.run_tick(time.time() + game.RECONNECT_SECONDS + 1)
    assert [p.player_id for p in room.players] == ["p0"]
    assert events(host, "left")[0]["nickname"] == "사람1"



def test_old_tab_is_told_when_replaced():
    (host, guest), room = lobby_with(2)
    copy = connect()
    copy.emit("join_room", {"code": room.code, "player_id": "p1", "nickname": "사람1", "rejoin": True})
    assert events(guest, "replaced") == [{}]
    assert room.find_player("p1").sid != ""

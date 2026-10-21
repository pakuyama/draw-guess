"""app.py 실시간 이벤트 테스트. 브라우저 대신 Socket.IO 테스트 클라이언트를 쓴다."""
import pytest

import app as server
import game


@pytest.fixture(autouse=True)
def clear_rooms():
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

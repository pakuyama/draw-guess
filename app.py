"""웹 서버: 화면 제공과 실시간 이벤트 연결.

게임 규칙은 game.py에 두고, 여기서는 받고 → 호출하고 → 보내기만 합니다.
game.py가 돌려주는 Out 목록을 deliver()가 알맞은 사람에게 보냅니다.
"""
import functools
import threading
import time

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

import game

app = Flask(__name__)
socketio = SocketIO(app)

WORDS = game.load_words()
TICK_SECONDS = 0.25  # 타이머 확인 간격

# 여러 사람의 이벤트와 타이머가 동시에 방 상태를 바꾸지 않도록 한 번에 하나씩 처리한다
lock = threading.RLock()
ticker_started = False


def locked(handler):
    """이벤트 처리 중에는 다른 이벤트·타이머가 방 상태를 바꾸지 못하게 한다."""

    @functools.wraps(handler)
    def wrapper(*args, **kwargs):
        with lock:
            return handler(*args, **kwargs)

    return wrapper


@app.route("/")
def index():
    """게임 화면(한 페이지)을 보여준다."""
    return render_template("index.html")


# ---------- 보내기 ----------


def send_room_state(room: game.Room) -> None:
    """방 안의 모든 사람에게 최신 방 정보를 보낸다."""
    socketio.emit("room_state", room.public_state(), to=room.code)


def send_strokes(room: game.Room, sid: str) -> None:
    """지금까지 그린 선 전체를 한 사람에게 보낸다. (늦게 들어오거나 다시 연결했을 때)"""
    socketio.emit("strokes", {"strokes": room.strokes}, to=sid)


def deliver(room: game.Room, outs: list) -> None:
    """game.py가 만든 메시지를 보낸다. to가 없으면 방 전체, 있으면 그 사람들에게만."""
    for out in outs:
        if out.event == "room_state":
            send_room_state(room)
            continue
        if out.to is None:
            socketio.emit(out.event, out.data, to=room.code)
            continue
        for player_id in dict.fromkeys(out.to):  # 같은 사람에게 두 번 보내지 않게
            player = room.find_player(player_id)
            if player and player.sid and player.connected:
                socketio.emit(out.event, out.data, to=player.sid)


# ---------- 타이머 ----------


def run_tick(now: float | None = None) -> None:
    """모든 방의 시간 흐름(자동 선택, 힌트, 시간 초과, 다음 턴)을 한 번 처리한다."""
    now = time.time() if now is None else now
    with lock:
        for room in list(game.rooms.values()):
            deliver(room, room.tick(now, WORDS))


def ticker() -> None:
    """서버가 켜져 있는 동안 계속 시간을 확인한다. (브라우저 타이머는 표시용)

    한 번 오류가 나도 타이머가 멈추면 모든 방이 멈추므로, 오류는 기록만 하고 계속 돈다.
    """
    while True:
        socketio.sleep(TICK_SECONDS)
        try:
            run_tick()
        except Exception:  # noqa: BLE001 - 어떤 오류든 타이머는 살려 둔다
            app.logger.exception("타이머 처리 중 오류")


@socketio.on("connect")
def on_connect():
    """첫 접속 때 타이머를 한 번만 켠다. 테스트에서는 run_tick()을 직접 부른다."""
    global ticker_started
    with lock:
        if not ticker_started and not app.config.get("TESTING"):
            ticker_started = True
            socketio.start_background_task(ticker)


# ---------- 방 만들기 · 참가 ----------


def send_error(message: str) -> None:
    emit("error", {"message": message})


def current() -> tuple:
    """이 소켓 연결의 방과 플레이어."""
    return game.find_by_sid(request.sid)


@socketio.on("sync")
@locked
def on_sync(_data=None):
    """화면을 다시 맞추고 싶을 때: 방 정보, 지금 턴 상황, 그림을 보낸다."""
    room, player = current()
    if room is None:
        return
    emit("room_state", room.public_state())
    deliver(room, room.private_outs(player.player_id, time.time()))
    send_strokes(room, request.sid)


@socketio.on("create_room")
@locked
def on_create_room(data):
    """방 만들기: 만든 사람을 방장으로 넣고 방 정보를 보낸다."""
    data = data or {}
    try:
        room = game.create_room(data.get("player_id", ""), data.get("nickname", ""))
    except ValueError as err:
        send_error(str(err))
        return
    room.players[0].sid = request.sid
    join_room(room.code)
    emit("room_created", {"code": room.code, "player_id": room.host_id})
    send_room_state(room)


@socketio.on("join_room")
@locked
def on_join_room(data):
    """방 참가: 방 코드로 들어가고 방 전체에 새 참가자 목록을 보낸다."""
    data = data or {}
    try:
        room, player = game.join_room(
            data.get("code", ""), data.get("player_id", ""), data.get("nickname", ""),
            rejoin=bool(data.get("rejoin")),
        )
    except ValueError as err:
        send_error(str(err))
        return
    old_sid = player.sid
    if old_sid and old_sid != request.sid:
        # 새로고침 등으로 같은 사람이 새 연결로 왔다: 예전 연결은 방에서 빼고, 아직 열려 있으면 알린다
        socketio.emit("replaced", {}, to=old_sid)
        leave_room(room.code, sid=old_sid)
    room.reconnect(player, request.sid)
    join_room(room.code)
    emit("room_joined", {"code": room.code, "player_id": player.player_id})
    send_room_state(room)
    deliver(room, room.private_outs(player.player_id, time.time()))
    if room.strokes:
        send_strokes(room, request.sid)


# ---------- 게임 진행 ----------


@socketio.on("start_game")
@locked
def on_start_game(_data=None):
    """방장이 게임을 시작한다."""
    room, player = current()
    if room is None:
        return
    try:
        outs = room.start_game(player.player_id, time.time(), WORDS)
    except ValueError as err:
        send_error(str(err))
        return
    deliver(room, outs)


@socketio.on("choose_word")
@locked
def on_choose_word(data):
    """출제자가 제시어를 고른다."""
    room, player = current()
    if room is None or not isinstance(data, dict):
        return
    try:
        outs = room.choose_word(player.player_id, data.get("word"), time.time())
    except ValueError:
        return
    deliver(room, outs)


@socketio.on("chat")
@locked
def on_chat(data):
    """채팅과 정답 판정."""
    room, player = current()
    if room is None or not isinstance(data, dict):
        return
    deliver(room, room.chat(player.player_id, data.get("text"), time.time()))


@socketio.on("back_to_lobby")
@locked
def on_back_to_lobby(_data=None):
    """게임이 끝난 뒤 [다시 하기]."""
    room, _player = current()
    if room is None:
        return
    try:
        outs = room.back_to_lobby()
    except ValueError:
        return
    deliver(room, outs)


# ---------- 그림 ----------


@socketio.on("stroke")
@locked
def on_stroke(data):
    """출제자가 그린 선 조각을 방의 다른 사람에게 전달한다. 이상한 데이터는 조용히 버린다."""
    room, player = current()
    if room is None:
        return
    try:
        part = room.add_stroke_part(player.player_id, data)
    except ValueError:
        return
    emit("stroke", part, to=room.code, include_self=False)


@socketio.on("undo")
@locked
def on_undo(data):
    """출제자의 되돌리기를 다른 사람에게 전달한다."""
    room, player = current()
    if room is None or not isinstance(data, dict):
        return
    try:
        stroke_id = room.undo_stroke(player.player_id, data.get("id"))
    except ValueError:
        return
    emit("undo", {"id": stroke_id}, to=room.code, include_self=False)


@socketio.on("clear")
@locked
def on_clear(_data=None):
    """출제자의 전체 지우기를 다른 사람에게 전달한다."""
    room, player = current()
    if room is None:
        return
    try:
        room.clear_strokes(player.player_id)
    except ValueError:
        return
    emit("clear", {}, to=room.code, include_self=False)


# ---------- 연결 끊김 · 나가기 (T20~T21) ----------


@socketio.on("disconnect")
@locked
def on_disconnect(*_args):
    """연결이 끊기면 30초 동안 자리를 남겨 둔다. 그 안에 돌아오면 그대로 이어서 한다."""
    room, player = current()
    if room is None:
        return
    deliver(room, room.disconnect(player.player_id, time.time()))


@socketio.on("leave_room")
@locked
def on_leave_room(_data=None):
    """[나가기]: 바로 방에서 뺀다. 방장·출제자였다면 넘기거나 턴을 끝낸다."""
    room, player = current()
    if room is None:
        return
    player.sid = ""  # 이 연결로는 더 이상 이 방 메시지를 받지 않는다
    leave_room(room.code)
    outs = room.remove_player(player.player_id, time.time(), WORDS)
    if game.get_room(room.code):
        deliver(room, outs)
    emit("left_room", {})


if __name__ == "__main__":
    # 개발용 실행. allow_unsafe_werkzeug: 터미널이 아닌 곳(IDE 실행 버튼 등)에서도 켜지도록 허용
    # 실제 배포(T26)에서는 gunicorn 등 운영용 서버를 사용한다.
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)

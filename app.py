"""웹 서버: 화면 제공과 실시간 이벤트 연결.

게임 규칙은 game.py에 두고, 여기서는 받고 → 호출하고 → 보내기만 합니다.
"""
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

import game

app = Flask(__name__)
socketio = SocketIO(app)


@app.route("/")
def index():
    """게임 화면(한 페이지)을 보여준다."""
    return render_template("index.html")


def send_room_state(room: game.Room) -> None:
    """방 안의 모든 사람에게 최신 방 정보를 보낸다."""
    socketio.emit("room_state", room.public_state(), to=room.code)


@socketio.on("create_room")
def on_create_room(data):
    """방 만들기: 만든 사람을 방장으로 넣고 방 정보를 보낸다."""
    data = data or {}
    try:
        room = game.create_room(data.get("player_id", ""), data.get("nickname", ""))
    except ValueError as err:
        emit("error", {"message": str(err)})
        return
    room.players[0].sid = request.sid
    join_room(room.code)
    emit("room_created", {"code": room.code, "player_id": room.host_id})
    send_room_state(room)


@socketio.on("join_room")
def on_join_room(data):
    """방 참가: 방 코드로 들어가고 방 전체에 새 참가자 목록을 보낸다."""
    data = data or {}
    try:
        room, player = game.join_room(
            data.get("code", ""), data.get("player_id", ""), data.get("nickname", "")
        )
    except ValueError as err:
        emit("error", {"message": str(err)})
        return
    player.sid = request.sid
    join_room(room.code)
    emit("room_joined", {"code": room.code, "player_id": player.player_id})
    send_room_state(room)


# TODO T9: stroke / undo / clear
# TODO T12~T15: start_game / choose_word / chat / 타이머
# TODO T20~T21: disconnect / 재접속 / 방장 넘기기


if __name__ == "__main__":
    # 개발용 실행. allow_unsafe_werkzeug: 터미널이 아닌 곳(IDE 실행 버튼 등)에서도 켜지도록 허용
    # 실제 배포(T26)에서는 gunicorn 등 운영용 서버를 사용한다.
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)

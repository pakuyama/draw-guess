"""웹 서버: 화면 제공과 실시간 이벤트 연결.

게임 규칙은 game.py에 두고, 여기서는 받고 → 호출하고 → 보내기만 합니다.
지금은 뼈대만 있으며, docs/tasks.md 순서대로 채워 나갑니다.
"""
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room

import game

app = Flask(__name__)
socketio = SocketIO(app)


@app.route("/")
def index():
    """게임 화면(한 페이지)을 보여준다."""
    return render_template("index.html")


@socketio.on("create_room")
def on_create_room(data):
    """방 만들기 (T5에서 완성)."""
    code = game.make_room_code()
    host = game.Player(player_id=data["player_id"], nickname=data["nickname"])
    room = game.Room(code=code, host_id=host.player_id)
    room.add_player(host)
    game.rooms[code] = room
    join_room(code)
    emit("room_created", {"code": code})


# TODO T5: join_room / room_state
# TODO T9: stroke / undo / clear
# TODO T12~T15: start_game / choose_word / chat / 타이머


if __name__ == "__main__":
    # 개발용 실행. allow_unsafe_werkzeug: 터미널이 아닌 곳(IDE 실행 버튼 등)에서도 켜지도록 허용
    # 실제 배포(T26)에서는 gunicorn 등 운영용 서버를 사용한다.
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)

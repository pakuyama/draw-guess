"""그림 전달 지연 측정 (T25).

가짜 플레이어 여러 명이 실제 서버에 접속해 방을 만들고 게임을 시작한 뒤,
출제자가 40ms마다 선 조각을 보내고 나머지가 받기까지 걸린 시간을 잰다.
모든 가짜 플레이어가 이 컴퓨터 한 대에서 돌기 때문에 시계가 같아 지연을 바로 비교할 수 있다.

준비:  pip install "python-socketio[client]" websocket-client
실행:  python tools/latency_check.py                      (내 PC: http://localhost:5000)
       python tools/latency_check.py https://배포주소 8 10  (주소, 인원, 측정 초)
"""
import statistics
import sys
import threading
import time
import uuid

import socketio

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000"
PLAYERS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
SECONDS = float(sys.argv[3]) if len(sys.argv) > 3 else 8
GOAL_MS = 200  # requirements.md 6장

delays: list[float] = []
lock = threading.Lock()


def new_client(name: str, inbox: dict) -> socketio.Client:
    client = socketio.Client()

    @client.on("*")
    def any_event(event, data=None):
        inbox.setdefault(event, []).append(data)

    @client.on("stroke")
    def on_stroke(part):
        sent_us = int(part["id"].split("-")[1])
        with lock:
            delays.append(time.time() * 1000 - sent_us / 1000)

    client.connect(URL, transports=["websocket"])
    client.name = name
    return client


def wait_for(inbox: dict, event: str, timeout: float = 5.0):
    end = time.time() + timeout
    while time.time() < end:
        if inbox.get(event):
            return inbox[event][-1]
        time.sleep(0.02)
    raise SystemExit(f"'{event}' 응답이 없어요. 서버 주소({URL})를 확인해 주세요.")


def main() -> None:
    run = uuid.uuid4().hex[:6]
    host_inbox: dict = {}
    host = new_client("측정방장", host_inbox)
    host.emit("create_room", {"player_id": f"lat-{run}-0", "nickname": "측정방장"})
    code = wait_for(host_inbox, "room_created")["code"]

    others = []
    for i in range(1, PLAYERS):
        inbox: dict = {}
        c = new_client(f"측정{i}", inbox)
        c.emit("join_room", {"code": code, "player_id": f"lat-{run}-{i}", "nickname": f"측정{i}"})
        wait_for(inbox, "room_joined")
        others.append(c)

    host.emit("start_game")
    choices = wait_for(host_inbox, "word_choices")["choices"]
    host.emit("choose_word", {"word": choices[0]})
    wait_for(host_inbox, "your_word")

    print(f"{URL} · {PLAYERS}명 · {SECONDS:.0f}초 측정 중...")
    sent = 0
    start = time.time()
    while time.time() - start < SECONDS:
        stamp = int(time.time() * 1e6)
        host.emit("stroke", {"id": f"m-{stamp}", "color": "#222222", "width": 0.012,
                             "points": [[0.5, 0.5]] * 10})
        sent += 1
        time.sleep(0.04)
    time.sleep(1)

    for c in [host] + others:
        c.emit("leave_room")
    time.sleep(0.5)  # 나가기가 처리된 뒤 연결을 끊어 빈 방을 남기지 않는다
    for c in [host] + others:
        c.disconnect()

    expected = sent * (PLAYERS - 1)
    if not delays:
        raise SystemExit("받은 선이 없어요.")
    d = sorted(delays)
    p95 = d[int(len(d) * 0.95) - 1]
    print(f"보낸 조각 {sent}개, 받은 횟수 {len(d)}/{expected} (빠짐 {expected - len(d)})")
    print(f"지연  중간값 {statistics.median(d):.0f}ms · 95% {p95:.0f}ms · 최대 {d[-1]:.0f}ms")
    print("결과:", "목표(200ms 이하) 통과" if p95 <= GOAL_MS else "목표(200ms) 넘음 — 서버 위치·사양 확인 필요")


if __name__ == "__main__":
    main()

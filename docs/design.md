# 설계 — 어떤 구조로 만들까

## 1. 기술 선택

| 영역 | 선택 | 이유 |
| --- | --- | --- |
| 서버 | Python + Flask | 배우기 쉽고 코드가 짧음 |
| 실시간 통신 | Flask-SocketIO (WebSocket) | 방(room) 기능이 내장되어 있음 |
| 화면 | HTML + CSS + JavaScript, HTML5 Canvas | 설치 없이 브라우저에서 동작 |
| 브라우저 통신 | Socket.IO 클라이언트 4.7.5 (cdnjs에서 불러옴) | 서버(python-socketio 5.x)와 맞는 버전 |
| 데이터 | 서버 메모리 + `data/words.json` | MVP는 DB 없이 충분 |
| 배포 | Render 또는 Fly.io | 무료/저가로 WebSocket 지원 |

## 2. 파일 역할

```text
app.py            서버 시작, 화면(/) 제공, Socket.IO 이벤트 받기 → game.py 호출 → 결과 보내기
game.py           Room, Player 클래스와 게임 규칙 (Flask를 모름)
data/words.json   {"easy": [...], "normal": [...], "hard": [...]}
templates/index.html  메인·대기실·게임·결과 화면 (한 페이지에서 전환)
static/main.js    화면 전환, 소켓 연결, 채팅
static/canvas.js  그리기, 스트로크 전송·재생
static/style.css  화면 디자인
tests/test_game.py  game.py 단위 테스트
```

원칙: **규칙은 game.py, 통신은 app.py, 화면은 static/** 으로 나눈다.

## 3. 데이터 구조 (game.py)

```python
Player:
    sid: str          # 소켓 연결 ID (재접속 시 바뀜)
    player_id: str    # 브라우저에 저장하는 고정 ID (재접속 확인용)
    nickname: str
    score: int
    guessed: bool     # 이번 턴에 맞혔는지
    connected: bool

Room:
    code: str              # 6자리 방 코드
    host_id: str
    players: list[Player]  # 입장 순서 = 출제 순서
    state: str             # "waiting" | "choosing" | "drawing" | "turn_end" | "game_end"
    round: int             # 1~3
    drawer_index: int
    word: str | None       # 현재 제시어 (서버만 앎)
    word_choices: list[str]
    strokes: list[dict]    # 이번 턴에 그린 선 (늦게 온 사람용)
    turn_started_at: float
```

방 목록은 `rooms: dict[str, Room]` 으로 서버 메모리에 둔다.

- **방 코드:** 6자리, 헷갈리는 0/O, 1/I/L을 뺀 31개 글자(`A~Z`, `2~9`)로 만든다. 입력할 때는 대소문자·공백을 무시한다.
- **닉네임:** 앞뒤 공백 제거, 최대 10자, 비어 있으면 거절.
- **`join_room(code, player_id, nickname)`:** 방 찾기 + 닉네임 정리 + 입장을 한 번에 한다. 실패하면 사용자에게 보여 줄 문장을 담은 ValueError.
- **입장 오류 메시지:** 검사 순서대로 아래 문장을 `error` 이벤트로 보내고, 메인 화면 아래에 빨간 글씨로 보여 준다.
  1. 닉네임이 비었을 때: "닉네임을 입력해 주세요."
  2. 방 코드가 6자리가 아닐 때: "방 코드 6자리를 입력해 주세요."
  3. 없는 방일 때: "없는 방 코드예요."
  4. 대기 중이 아닐 때: "이미 게임이 진행 중이에요."
  5. 8명이 찼을 때: "방이 가득 찼어요. (8/8)"
  6. 같은 브라우저(player_id)가 또 들어올 때: "이미 이 방에 들어와 있어요. 다른 창이나 탭을 확인해 주세요."
- **`Room.public_state()`:** 모두에게 보내는 방 정보(코드·방장·출제자·상태·라운드·플레이어 목록). 제시어는 넣지 않는다.

## 4. 게임 상태 흐름

```text
waiting ──(방장 시작)──▶ choosing ──(제시어 선택/10초)──▶ drawing
   ▲                                                       │
   │                                     (모두 정답 / 80초) ▼
game_end ◀──(3라운드 끝)── turn_end ──(5초 후 다음 출제자)──▶ choosing
```

## 5. 실시간 이벤트 목록

| 방향 | 이벤트 | 데이터 | 설명 |
| --- | --- | --- | --- |
| 브라우저→서버 | `create_room` | nickname, player_id | 방 만들기 |
| 브라우저→서버 | `join_room` | code, nickname, player_id | 방 참가·재접속 |
| 브라우저→서버 | `start_game` | – | 방장만 가능 |
| 브라우저→서버 | `choose_word` | word | 출제자만 가능 |
| 브라우저→서버 | `stroke` | points, color, width | 출제자만, 30~50ms 묶음 |
| 브라우저→서버 | `undo` / `clear` | – | 출제자만 |
| 브라우저→서버 | `chat` | text | 정답 판정 대상 |
| 서버→본인 | `room_created` / `room_joined` | code, player_id | 방 만들기·참가 성공 응답 |
| 서버→본인 | `error` | message | 실패 이유 (예: "없는 방 코드예요.") |
| 서버→브라우저 | `room_state` | 플레이어·점수·상태 | 변화가 있을 때마다 방 전체에 |
| 서버→출제자 | `word_choices` | 제시어 3개 | 출제자에게만 |
| 서버→브라우저 | `turn_start` | drawer, 글자 수, 남은 시간 | |
| 서버→브라우저 | `stroke` / `undo` / `clear` | | 출제자 외 모두에게 |
| 서버→브라우저 | `hint` | 예: "ㄱ _ _" | |
| 서버→브라우저 | `chat` / `correct` | 닉네임, 내용 / 맞힌 사람 | 정답 내용은 숨김 |
| 서버→브라우저 | `turn_end` | 정답, 이번 턴 점수 | |
| 서버→브라우저 | `game_end` | 최종 순위 | |

## 6. 주요 규칙 구현

- **정답 판정:** `normalize(text) = text.replace(" ", "").strip().lower()` 로 비교.
  정답과 한 글자 차이면 본인에게만 "거의 맞았어요!" 표시, 다른 사람에게는 메시지를 숨김.
- **점수:** `max(20, round(100 * 남은시간 / 제한시간))` + 첫 정답 +20, 출제자 +25 × 맞힌 인원
- **타이머:** 서버에서 `socketio.start_background_task`로 1초마다 확인. 브라우저 타이머는 표시용.
- **캔버스 좌표:** 점 좌표를 캔버스 크기 대비 0~1 비율로 보내고 저장한다. PC·모바일처럼 화면 크기가 달라도 같은 그림이 보인다.
- **스트로크 형식:** 선 하나 = `{"color": "#222222", "width": 0.012, "points": [[x, y], ...]}`. 좌표와 굵기(`width`)는 캔버스 한 변 대비 0~1 비율, 소수 넷째 자리까지. 0.002보다 가까운 점은 버린다. 점 하나짜리 선은 점으로 그린다.
- **그림판(`static/canvas.js`의 `DrawingBoard`):** Pointer Events로 마우스·터치·펜을 한 번에 처리한다. 한 번에 한 손가락만 받고, 캔버스 밖으로 나가면 가장자리 좌표로 붙인다. 화면 배율(devicePixelRatio)만큼 실제 픽셀을 잡고, 크기가 바뀌면 저장된 선으로 다시 그린다. 선을 다 그리면 `onStroke(stroke)`를 부른다. `enabled`가 false면 그릴 수 없다(출제자만 true).
- **스트로크 전송:** 출제자 브라우저는 선마다 id(`임의6자-순번`)를 붙이고, 40ms마다 새로 생긴 점만 묶어 `stroke`로 보낸다(한 번에 최대 200점). 서버는 `Room.add_stroke_part`로 검사한 뒤 같은 id면 앞 선에 이어 붙이고, 새 id면 새 선으로 `strokes`에 저장한 다음 출제자를 뺀 방 사람들에게 그대로 전달한다. 받는 쪽은 `DrawingBoard.applyPart`로 같은 방식으로 이어 그린다.
- **그림 데이터 검사:** 그리는 단계(`drawing`)의 출제자만 보낼 수 있다. 색은 `#RRGGBB`, 굵기 0.002~0.08, 좌표 0~1, 조각당 200점, 한 턴 20000점까지. 어긋나면 오류 메시지 없이 버린다(정상 화면에서는 생기지 않는 경우).
- **WebSocket:** 개발 서버에서 WebSocket을 쓰려면 `simple-websocket` 패키지가 필요하다. 없으면 느린 HTTP 폴링으로 동작한다.
- **초대 링크:** `/?room=ABC123` 형식. 열면 메인 화면의 방 코드 칸이 미리 채워진다.
- **재접속:** 브라우저 `localStorage`에 `player_id` 저장. 끊기면 `connected=False`, 30초 후 제거.

## 7. 화면 구성

화면별 와이어프레임은 [wireframes.md](wireframes.md)를 참고한다.

- **메인:** 닉네임 입력, [방 만들기], 방 코드 입력 + [참가]
- **대기실:** 참가자 목록, 방 코드·링크 복사, [게임 시작] (방장)
- **게임:** 위쪽 타이머·힌트 / 왼쪽 점수판 / 가운데 캔버스 / 오른쪽 채팅 / 아래쪽 그리기 도구
- **결과:** 1~3위 시상대, 전체 점수, [다시 하기] [나가기]
- 모바일: 캔버스 위, 채팅 아래로 세로 배치

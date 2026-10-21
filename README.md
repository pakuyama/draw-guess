# 그려봐! (Draw & Guess)

여러 명이 웹 브라우저에서 함께 즐기는 실시간 그림 맞히기 게임입니다.
한 명이 제시어를 그리면 나머지 사람들이 채팅으로 정답을 맞힙니다.

- 인원: 한 방에 2~8명
- 플랫폼: PC·모바일 웹 브라우저 (설치 필요 없음)
- 기술: Python (Flask + Flask-SocketIO), HTML5 Canvas

## 폴더 구조

```text
draw-guess/
├─ README.md              # 실행과 사용 방법
├─ AGENTS.md              # 지원 도구(AI 코딩 도우미)의 작업 지침
├─ requirements.txt       # 파이썬 패키지 목록
├─ app.py                 # 웹 서버, 화면 연결, 실시간 이벤트
├─ game.py                # 방·턴·정답 판정·점수 (게임 규칙)
├─ data/words.json        # 제시어 사전
├─ templates/index.html   # 게임 화면
├─ static/                # 화면용 JS·CSS
└─ docs/
   ├─ requirements.md     # 무엇이 되어야 하나
   ├─ design.md           # 어떤 구조로 만들까
   ├─ tasks.md            # 어떤 순서로 구현할까
   └─ progress.md         # 지금 어디까지 했나
```

## 실행 방법

Python 3.10 이상이 필요합니다.

```bash
# 1. 가상환경 만들기 (처음 한 번)
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 서버 실행
python app.py
```

브라우저에서 `http://localhost:5000` 에 접속합니다.
같은 와이파이의 다른 기기에서는 `http://<내 PC의 IP>:5000` 으로 접속할 수 있습니다.

## 사용 방법

1. 닉네임을 입력하고 **방 만들기**를 누릅니다.
2. 화면의 **방 코드(6자리)** 또는 초대 링크를 친구에게 보냅니다.
3. 친구는 닉네임과 방 코드를 입력해 **참가**합니다.
4. 모두 모이면 방장이 **게임 시작**을 누릅니다.
5. 출제자는 제시어를 골라 그림을 그리고, 나머지는 채팅으로 정답을 입력합니다.
6. 3라운드가 끝나면 최종 순위가 나옵니다.

## 문서

- [요구사항](docs/requirements.md): 게임이 무엇을 해야 하는지
- [설계](docs/design.md): 파일 구조, 데이터, 통신 방식
- [와이어프레임](docs/wireframes.md): 화면 4개 배치
- [작업 순서](docs/tasks.md): 단계별 구현 계획과 일정
- [진행 상황](docs/progress.md): 지금 어디까지 했는지

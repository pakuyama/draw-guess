# AGENTS.md — 지원 도구 작업 지침

이 문서는 Claude, Copilot 같은 AI 코딩 도우미가 이 프로젝트에서 작업할 때 따를 규칙입니다.

## 작업 전에 읽을 것

1. `docs/requirements.md`: 무엇을 만들어야 하는지
2. `docs/design.md`: 파일 역할과 데이터 구조
3. `docs/tasks.md`: 지금 할 작업
4. `docs/progress.md`: 지금까지 한 작업

## 작업 원칙

- **한 번에 작업 하나만** 합니다. `docs/tasks.md`에서 체크되지 않은 가장 앞의 작업부터 진행합니다.
- 작업을 마치면 `docs/tasks.md`에 체크하고 `docs/progress.md`에 날짜와 한 일을 기록합니다.
- 요구사항에 없는 기능을 임의로 추가하지 않습니다. 필요해 보이면 `progress.md`의 '제안' 항목에 적습니다.
- 설계를 바꿔야 하면 코드보다 `docs/design.md`를 먼저 고칩니다.

## 파일별 규칙

- `game.py`: 게임 규칙만 담습니다. Flask나 Socket.IO를 import하지 않습니다. (테스트하기 쉽게)
- `app.py`: 화면 연결과 실시간 이벤트만 담당합니다. 점수 계산 같은 규칙은 `game.py`를 호출합니다.
- `data/words.json`: 형식(`easy`/`normal`/`hard` 목록)을 바꾸지 않습니다.
- 정답 판정과 점수 계산은 **반드시 서버(game.py)** 에서 합니다. 브라우저에 정답을 보내지 않습니다. (출제자 제외)

## 코드 스타일

- Python 3.10 이상, PEP 8, 함수와 변수 이름은 영어 `snake_case`
- 주석과 화면에 보이는 글자는 한국어
- 함수에는 짧은 docstring을 답니다.
- 새 패키지를 추가하면 `requirements.txt`에도 적습니다.

## 확인 방법

- 작업 후 `python app.py`로 실행해 브라우저 창 2개로 직접 확인합니다.
- `game.py`를 고쳤다면 `python -m pytest`를 실행합니다. (테스트는 `tests/` 폴더)

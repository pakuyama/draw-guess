// 게임 화면과 결과 화면 (wireframes.md 3~4장, design.md 5장 이벤트 목록)
// main.js의 socket, playerId, currentCode, $, showScreen 을 함께 쓴다.

const game = {
  state: null, // 마지막 room_state
  deadline: 0, // 지금 단계가 끝나는 시각 (브라우저 시계, 표시용)
  word: null, // 내가 출제자일 때만 아는 제시어
  hint: "",
  guessed: false,
};

const board = new DrawingBoard($("board"));
board.enabled = false;
const tools = buildToolbar($("tools"), board);
tools.hidden = true;
linkBoardToSocket(board, socket);

function isDrawer() {
  return game.state && game.state.drawer_id === playerId;
}

function setDeadline(seconds) {
  game.deadline = Date.now() + seconds * 1000;
  if (typeof renderTimer === "function") renderTimer();
}

// ---------- 방 정보 ----------

socket.on("room_state", (state) => {
  if (state.code !== currentCode) return;
  const prev = game.state;
  game.state = state;
  if (!prev || prev.state !== state.state) setDeadline(state.seconds);

  const me = state.players.find((p) => p.player_id === playerId);
  game.guessed = Boolean(me && me.guessed);

  board.enabled = state.state === "drawing" && isDrawer();
  tools.hidden = !board.enabled;
  $("round-label").textContent = `라운드 ${state.round}/${state.total_rounds}`;
  renderScoreboard(state);
  renderTop();
  renderChatInput();
});

function renderScoreboard(state) {
  const list = $("scoreboard");
  list.replaceChildren();
  const sorted = [...state.players].sort((a, b) => b.score - a.score);
  sorted.forEach((p, i) => {
    const li = document.createElement("li");
    li.className = "score-row";
    if (p.player_id === playerId) li.classList.add("me");
    if (!p.connected) li.classList.add("away");

    const rank = document.createElement("span");
    rank.className = "score-rank";
    rank.textContent = i + 1;

    const name = document.createElement("span");
    name.className = "score-name";
    name.textContent = p.nickname;

    const tag = document.createElement("span");
    tag.className = "tag";
    if (p.player_id === state.drawer_id) tag.textContent = "그림";
    else if (p.guessed) tag.textContent = "정답";
    else tag.hidden = true;

    const score = document.createElement("span");
    score.className = "score-points";
    score.textContent = p.score;

    li.append(rank, name, tag, score);
    list.appendChild(li);
  });
}

// ---------- 위쪽 줄: 힌트·제시어·타이머 ----------

function renderTop() {
  const hint = $("hint");
  const st = game.state && game.state.state;
  const set = (label, value) => {
    hint.replaceChildren();
    if (!value) return;
    const v = document.createElement("span");
    v.className = "hint-value";
    v.textContent = value;
    hint.append(label, v);
  };
  if (st === "drawing" && isDrawer() && game.word) set("제시어 ", game.word);
  else if (st === "drawing") set("힌트 ", game.hint);
  else set("", "");
}

function renderTimer() {
  const left = Math.max(0, Math.ceil((game.deadline - Date.now()) / 1000));
  const st = game.state && game.state.state;
  const timer = $("timer");
  timer.textContent = st === "drawing" || st === "choosing" ? `남은 시간 ${left}` : "";
  timer.classList.toggle("urgent", st === "drawing" && left <= 10);
  const counter = document.querySelector("[data-countdown]");
  if (counter) counter.textContent = left;
}
setInterval(renderTimer, 250);

// ---------- 가운데 안내 창 ----------

function showOverlay(build) {
  const box = $("overlay");
  box.replaceChildren();
  build(box);
  box.hidden = false;
  renderTimer();
}

function hideOverlay() {
  $("overlay").hidden = true;
}

function line(parent, text, className) {
  const el = document.createElement("p");
  el.textContent = text;
  if (className) el.className = className;
  parent.appendChild(el);
  return el;
}

socket.on("turn_choosing", (data) => {
  board.clear();
  game.word = null;
  game.hint = "";
  setDeadline(data.seconds);
  if (data.drawer_id === playerId) return; // 출제자는 word_choices 로 보기를 받는다
  showOverlay((box) => line(box, `${data.nickname}님이 제시어를 고르고 있어요...`, "overlay-title"));
  renderTop();
});

socket.on("word_choices", (data) => {
  setDeadline(data.seconds);
  showOverlay((box) => {
    const title = line(box, "그릴 제시어를 골라 주세요 ", "overlay-title");
    const sec = document.createElement("span");
    sec.dataset.countdown = "";
    title.append("(", sec, "초)");
    const row = document.createElement("div");
    row.className = "choices";
    data.choices.forEach((word) => {
      const b = document.createElement("button");
      b.className = "btn";
      b.textContent = word;
      b.addEventListener("click", () => socket.emit("choose_word", { word }));
      row.appendChild(b);
    });
    box.appendChild(row);
  });
  renderTimer();
});

socket.on("turn_start", (data) => {
  hideOverlay();
  game.hint = data.hint;
  setDeadline(data.seconds);
  renderTop();
  addSystem(`${data.nickname}님이 그리기 시작했어요. (${data.length}글자)`);
  playSound("start");
});

socket.on("your_word", (data) => {
  game.word = data.word;
  renderTop();
});

socket.on("hint", (data) => {
  game.hint = data.hint;
  renderTop();
  addSystem(`힌트: ${data.hint}`);
});

socket.on("correct", (data) => {
  addSystem(`${data.nickname}님이 정답을 맞혔어요! (+${data.points})`, "correct");
  playSound(data.player_id === playerId ? "correct" : "other");
});

socket.on("turn_end", (data) => {
  board.enabled = false;
  tools.hidden = true;
  setDeadline(data.seconds);
  const left = data.reason === "drawer_left";
  if (data.word) addSystem(`정답은 "${data.word}"였어요.`);
  showOverlay((box) => {
    if (left) line(box, "출제자가 나갔어요", "overlay-title");
    if (data.word) line(box, `정답은 "${data.word}"`, left ? "overlay-sub" : "overlay-title");
    const scores = document.createElement("div");
    scores.className = "turn-scores";
    data.scores.forEach((s) => {
      const span = document.createElement("span");
      span.textContent = `${s.nickname} ${s.points > 0 ? "+" + s.points : "0"}`;
      scores.appendChild(span);
    });
    box.appendChild(scores);
    if (data.next_drawer) {
      const next = line(box, `다음 출제자: ${data.next_drawer} (`, "overlay-sub");
      const sec = document.createElement("span");
      sec.dataset.countdown = "";
      next.append(sec, "초 후)");
    }
  });
});

// ---------- 채팅 ----------

function addChatLine(build, className) {
  const log = $("chat-log");
  const li = document.createElement("li");
  if (className) li.className = className;
  build(li);
  log.appendChild(li);
  while (log.children.length > 100) log.firstChild.remove();
  log.scrollTop = log.scrollHeight;
}

function addSystem(text, className) {
  addChatLine((li) => (li.textContent = text), "system " + (className || ""));
}

socket.on("chat", (msg) => {
  addChatLine((li) => {
    const who = document.createElement("strong");
    who.textContent = msg.nickname + ": ";
    li.append(who, msg.text); // 글자로만 넣는다 (HTML 실행 방지)
  }, msg.insider ? "insider" : "");
});

socket.on("notice", (data) => addSystem(data.text, "notice"));
socket.on("left", (data) => addSystem(`${data.nickname}님이 나갔어요.`));

function renderChatInput() {
  const input = $("chat-input");
  const st = game.state && game.state.state;
  if (st === "drawing" && game.guessed) {
    input.disabled = true;
    input.placeholder = "정답을 맞혔어요! 기다려 주세요";
  } else {
    input.disabled = false;
    input.placeholder = st === "drawing" && isDrawer() ? "채팅 (정답은 말할 수 없어요)" : "정답을 입력하세요";
  }
}

$("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("chat-input");
  const text = input.value.trim();
  if (!text) return;
  socket.emit("chat", { text });
  input.value = "";
});

// ---------- 결과 화면 ----------

socket.on("game_end", (data) => {
  hideOverlay();
  board.clear();
  renderResult(data.ranking);
  playSound("end");
});

function renderResult(ranking) {
  const podium = $("podium");
  podium.replaceChildren();
  // 2위 - 1위 - 3위 순서로 놓는다
  const top = ranking.slice(0, 3);
  [top[1], top[0], top[2]].forEach((r) => {
    if (!r) return;
    const col = document.createElement("div");
    col.className = `podium-col place-${Math.min(r.rank, 3)}`;
    const name = document.createElement("div");
    name.className = "podium-name";
    name.textContent = r.nickname;
    const block = document.createElement("div");
    block.className = "podium-block";
    const rank = document.createElement("strong");
    rank.textContent = `${r.rank}위`;
    const score = document.createElement("span");
    score.textContent = `${r.score}점`;
    block.append(rank, score);
    col.append(name, block);
    podium.appendChild(col);
  });

  const rest = $("rank-rest");
  rest.replaceChildren();
  ranking.slice(3).forEach((r) => {
    const li = document.createElement("li");
    li.textContent = `${r.rank}위  ${r.nickname}  ${r.score}점`;
    rest.appendChild(li);
  });
}

$("btn-again").addEventListener("click", () => socket.emit("back_to_lobby", {}));
$("btn-exit").addEventListener("click", leaveRoom);

socket.on("lobby", () => {
  hideOverlay();
  board.clear();
  $("chat-log").replaceChildren();
});

// ---------- 효과음 (T19) ----------
// 소리 파일 없이 브라우저에서 짧은 음을 만들어 낸다 (Web Audio).

const sound = {
  ctx: null,
  on: loadValue("dg_sound") !== "off",
};

function audio() {
  if (!sound.ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    sound.ctx = new AC();
  }
  if (sound.ctx.state === "suspended") sound.ctx.resume();
  return sound.ctx;
}

// 음 하나: 주파수(Hz), 시작(초 뒤), 길이(초), 크기
function tone(freq, start, length, volume = 0.15, type = "sine") {
  const ctx = audio();
  if (!ctx) return;
  const t = ctx.currentTime + start;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0, t);
  gain.gain.linearRampToValueAtTime(volume, t + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.001, t + length);
  osc.connect(gain).connect(ctx.destination);
  osc.start(t);
  osc.stop(t + length + 0.02);
}

const SOUNDS = {
  correct: () => { tone(660, 0, 0.12); tone(990, 0.1, 0.2); }, // 내가 맞혔을 때
  other: () => tone(880, 0, 0.1, 0.08), // 다른 사람이 맞혔을 때
  start: () => { tone(523, 0, 0.12, 0.1); tone(784, 0.12, 0.18, 0.1); }, // 그리기 시작
  tick: () => tone(1200, 0, 0.05, 0.06, "square"), // 마지막 5초
  end: () => { tone(523, 0, 0.15); tone(659, 0.15, 0.15); tone(784, 0.3, 0.3); }, // 게임 끝
};

function playSound(name) {
  if (!sound.on || !SOUNDS[name]) return;
  try {
    SOUNDS[name]();
  } catch (e) {
    // 소리가 안 나도 게임은 계속한다
  }
}

function renderSoundButton() {
  const b = $("btn-sound");
  b.textContent = sound.on ? "소리 켜짐" : "소리 꺼짐";
  b.setAttribute("aria-pressed", String(sound.on));
}

$("btn-sound").addEventListener("click", () => {
  sound.on = !sound.on;
  saveValue("dg_sound", sound.on ? "on" : "off");
  renderSoundButton();
  if (sound.on) playSound("other");
});
renderSoundButton();

// 마지막 5초 째깍 소리: 초가 바뀔 때 한 번씩
let lastTick = null;
setInterval(() => {
  const st = game.state && game.state.state;
  const left = Math.ceil((game.deadline - Date.now()) / 1000);
  if (st === "drawing" && left <= 5 && left >= 1 && left !== lastTick) {
    lastTick = left;
    playSound("tick");
  }
}, 100);

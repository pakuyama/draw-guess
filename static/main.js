// 화면 전환, 소켓 연결, 메인·대기실 화면 (design.md 2장, wireframes.md 1~2장)

const MAX_PLAYERS = 8;
const MIN_PLAYERS = 2;

const $ = (id) => document.getElementById(id);

// ---------- 브라우저에 저장하는 값 (재접속 확인용 player_id, 마지막 닉네임) ----------

function loadValue(key) {
  try {
    return localStorage.getItem(key);
  } catch (e) {
    return null;
  }
}

function saveValue(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (e) {
    // 저장이 막힌 브라우저(시크릿 창 등)에서는 저장 없이 진행
  }
}

function makeId() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return "p-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

let playerId = loadValue("dg_player_id");
if (!playerId) {
  playerId = makeId();
  saveValue("dg_player_id", playerId);
}

// ---------- 화면 전환 ----------

function showScreen(name) {
  document.querySelectorAll(".screen").forEach((el) => {
    el.hidden = el.id !== "screen-" + name;
  });
}

function showError(message) {
  const box = $("main-error");
  box.textContent = message;
  box.hidden = !message;
}

// ---------- 메인 화면 ----------

const nicknameInput = $("nickname");
const codeInput = $("room-code");

nicknameInput.value = loadValue("dg_nickname") || "";

// 초대 링크(/?room=ABC123)로 들어오면 방 코드를 미리 채운다
const invitedCode = new URLSearchParams(location.search).get("room");
if (invitedCode) codeInput.value = invitedCode.toUpperCase().slice(0, 6);

function nickname() {
  return nicknameInput.value.trim();
}

function roomCode() {
  return codeInput.value.replace(/\s/g, "").toUpperCase();
}

function updateMainButtons() {
  const hasName = nickname().length > 0;
  $("btn-create").disabled = !hasName;
  $("btn-join").disabled = !hasName || roomCode().length !== 6;
}

nicknameInput.addEventListener("input", () => {
  showError("");
  updateMainButtons();
});

codeInput.addEventListener("input", () => {
  codeInput.value = codeInput.value.toUpperCase();
  showError("");
  updateMainButtons();
});

codeInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !$("btn-join").disabled) $("btn-join").click();
});

nicknameInput.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  if (roomCode().length === 6 && !$("btn-join").disabled) $("btn-join").click();
  else if (!$("btn-create").disabled) $("btn-create").click();
});

updateMainButtons();

// ---------- 소켓 ----------

const socket = io();
let currentCode = null;

$("btn-create").addEventListener("click", () => {
  saveValue("dg_nickname", nickname());
  socket.emit("create_room", { player_id: playerId, nickname: nickname() });
});

$("btn-join").addEventListener("click", () => {
  saveValue("dg_nickname", nickname());
  socket.emit("join_room", { code: roomCode(), player_id: playerId, nickname: nickname() });
});

function enterLobby(code) {
  currentCode = code;
  $("lobby-code").textContent = code;
  history.replaceState(null, "", "/?room=" + code);
  showScreen("lobby");
}

socket.on("room_created", (data) => enterLobby(data.code));
socket.on("room_joined", (data) => enterLobby(data.code));

socket.on("error", (data) => {
  showScreen("main");
  showError(data.message);
});

socket.on("disconnect", () => {
  if (currentCode) $("lobby-status").textContent = "서버와 연결이 끊겼어요. 새로고침해 주세요.";
});

// ---------- 대기실 ----------

socket.on("room_state", (state) => {
  if (state.code !== currentCode) return;
  renderPlayers(state);
  renderStart(state);
});

function renderPlayers(state) {
  const list = $("player-list");
  list.replaceChildren();

  state.players.forEach((p) => {
    const li = document.createElement("li");
    li.className = "player";
    if (p.player_id === playerId) li.classList.add("me");

    const name = document.createElement("span");
    name.textContent = p.nickname; // textContent로 넣어 닉네임 속 HTML이 실행되지 않게 한다
    li.appendChild(name);

    if (p.player_id === state.host_id) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = "방장";
      li.appendChild(tag);
    }
    list.appendChild(li);
  });

  for (let i = state.players.length; i < MAX_PLAYERS; i++) {
    const li = document.createElement("li");
    li.className = "player empty";
    li.textContent = "빈 자리";
    list.appendChild(li);
  }

  $("player-count").textContent = `(${state.players.length}/${MAX_PLAYERS})`;
}

function renderStart(state) {
  const isHost = state.host_id === playerId;
  const enough = state.players.length >= MIN_PLAYERS;
  const startBtn = $("btn-start");

  startBtn.hidden = !isHost;
  startBtn.disabled = !enough;

  if (isHost) {
    $("lobby-status").textContent = enough ? "" : `${MIN_PLAYERS}명 이상 모이면 시작할 수 있어요`;
  } else {
    $("lobby-status").textContent = "방장이 시작하기를 기다리는 중...";
  }
}

// 게임 시작은 T12에서 서버와 연결한다
$("btn-start").addEventListener("click", () => {
  socket.emit("start_game", {});
});

$("btn-leave").addEventListener("click", () => {
  // 방에서 나가는 처리(목록에서 빼기, 방장 넘기기)는 T21에서 서버에 추가한다
  location.href = "/";
});

// ---------- 복사 ----------

function copyText(text, doneMessage) {
  const note = $("copy-note");
  const done = () => {
    note.textContent = doneMessage;
    setTimeout(() => (note.textContent = ""), 2000);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
  } else {
    fallbackCopy(text, done);
  }
}

// http://내 PC IP:5000 처럼 보안 연결이 아닌 주소에서도 복사되게 하는 방법
function fallbackCopy(text, done) {
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  try {
    document.execCommand("copy");
    done();
  } catch (e) {
    $("copy-note").textContent = text;
  }
  area.remove();
}

$("btn-copy-code").addEventListener("click", () => copyText(currentCode, "방 코드를 복사했어요"));
$("btn-copy-link").addEventListener("click", () =>
  copyText(`${location.origin}/?room=${currentCode}`, "초대 링크를 복사했어요")
);

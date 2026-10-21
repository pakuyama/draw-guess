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

// ---------- 다시 연결 (T20) ----------
// 들어간 방을 이 탭(sessionStorage)에 기억해 두고, 새로고침하거나 연결이 잠깐 끊겼다가
// 다시 붙으면 자동으로 같은 자리로 돌아간다. 다른 탭에는 기억이 없으므로 중복 입장은 여전히 막힌다.

let rejoining = false;

function loadSession() {
  try {
    return JSON.parse(sessionStorage.getItem("dg_session") || "null");
  } catch (e) {
    return null;
  }
}

function saveSession(code) {
  try {
    sessionStorage.setItem("dg_session", JSON.stringify({ code, nickname: nickname() }));
  } catch (e) {
    // 저장이 막히면 새로고침 때 다시 연결되지 않을 뿐 게임은 된다
  }
}

function clearSession() {
  try {
    sessionStorage.removeItem("dg_session");
  } catch (e) {}
}

function showBanner(text) {
  const banner = $("conn-banner");
  banner.textContent = text;
  banner.hidden = !text;
}

socket.on("connect", () => {
  const session = loadSession();
  const code = currentCode || (session && session.code);
  if (!code || !session) return;
  // 초대 링크로 다른 방에 들어온 경우에는 예전 방으로 돌아가지 않는다
  if (!currentCode && invitedCode && invitedCode.toUpperCase() !== code) return;
  rejoining = true;
  showBanner("다시 연결하는 중...");
  socket.emit("join_room", { code, player_id: playerId, nickname: session.nickname, rejoin: true });
});

socket.on("disconnect", () => {
  if (currentCode) showBanner("연결이 끊겼어요. 다시 연결하는 중...");
});

$("btn-create").addEventListener("click", () => {
  saveValue("dg_nickname", nickname());
  socket.emit("create_room", { player_id: playerId, nickname: nickname() });
});

$("btn-join").addEventListener("click", () => {
  saveValue("dg_nickname", nickname());
  socket.emit("join_room", { code: roomCode(), player_id: playerId, nickname: nickname() });
});

function enterLobby(code) {
  rejoining = false;
  showBanner("");
  if (code !== currentCode || !loadSession()) saveSession(code);
  currentCode = code;
  $("lobby-code").textContent = code;
  history.replaceState(null, "", "/?room=" + code);
  showScreen("lobby");
}

socket.on("room_created", (data) => enterLobby(data.code));
socket.on("room_joined", (data) => enterLobby(data.code));

socket.on("error", (data) => {
  if (rejoining) {
    // 방이 없어졌거나 30초가 지나 자리가 없어졌다
    rejoining = false;
    currentCode = null;
    clearSession();
    showBanner("");
    showScreen("main");
    showError("방에 다시 들어가지 못했어요. 방이 끝났거나 자리가 없어졌어요.");
    return;
  }
  if (currentCode) {
    // 방 안에서 생긴 오류(예: 시작 조건)는 대기실 안내 줄에 보여 준다
    $("lobby-status").textContent = data.message;
    return;
  }
  showScreen("main");
  showError(data.message);
});


// ---------- 대기실 ----------

socket.on("room_state", (state) => {
  if (state.code !== currentCode) return;
  renderPlayers(state);
  renderStart(state);
  // 방 상태에 맞는 화면으로 바꾼다 (게임 화면 내용은 game.js가 그린다)
  if (state.state === "waiting") showScreen("lobby");
  else if (state.state === "game_end") showScreen("result");
  else showScreen("game");
});

function renderPlayers(state) {
  const list = $("player-list");
  list.replaceChildren();

  state.players.forEach((p) => {
    const li = document.createElement("li");
    li.className = "player";
    if (p.player_id === playerId) li.classList.add("me");
    if (!p.connected) li.classList.add("away");

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

$("btn-start").addEventListener("click", () => {
  socket.emit("start_game", {});
});

// [나가기]: 서버에서 자리를 빼고(방장·출제자면 넘김) 첫 화면으로 간다
function leaveRoom() {
  clearSession();
  currentCode = null;
  socket.emit("leave_room", {});
  setTimeout(() => (location.href = "/"), 600); // 응답이 없어도 이동
}

socket.on("left_room", () => (location.href = "/"));

// 같은 자리로 다른 창(탭 복제 등)이 들어오면 이 창은 멈춘다
socket.on("replaced", () => {
  currentCode = null;
  showBanner("");
  showScreen("main");
  showError("다른 창에서 같은 자리로 들어왔어요. 이 창은 닫아 주세요.");
});
$("btn-leave").addEventListener("click", leaveRoom);

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

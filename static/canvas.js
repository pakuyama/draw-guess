// 그림판: 마우스·터치·펜으로 그리기 (design.md 6장 "캔버스 좌표", "스트로크 형식")
//
// 선 하나(스트로크)는 아래 형식으로 저장한다. 좌표와 굵기는 캔버스 크기 대비 0~1 비율이라
// PC와 휴대폰처럼 화면 크기가 달라도 같은 그림이 된다.
//   { id: "k3x9-1", color: "#222222", width: 0.012, points: [[x, y], [x, y], ...] }
//
// 사용법:
//   const board = new DrawingBoard(canvasElement, { onStroke: (stroke) => { ... } });
//   board.enabled = true;          // 출제자만 true
//   board.applyPart(part);         // 다른 사람이 보낸 선 조각 그리기
//   board.clear();                 // 전체 지우기
//   linkBoardToSocket(board, socket);  // 그리는 선을 서버로 보내고, 받은 선을 그린다 (T9)
//   buildToolbar(container, board);    // 색·굵기·지우개·되돌리기·전체 지우기 버튼 (T10)

// 그리기 도구. 서버(game.PALETTE, game.WIDTHS)와 같은 값을 쓴다.
const PALETTE = [
  ["#222222", "검정"],
  ["#e53935", "빨강"],
  ["#fb8c00", "주황"],
  ["#fdd835", "노랑"],
  ["#43a047", "초록"],
  ["#1e88e5", "파랑"],
  ["#8e24aa", "보라"],
  ["#6d4c41", "갈색"],
];
const WIDTHS = [
  [0.006, "가늘게"],
  [0.012, "보통"],
  [0.024, "굵게"],
];
const ERASER_COLOR = "#ffffff";
const ERASER_WIDTH = 0.04;

const DEFAULT_COLOR = PALETTE[0][0];
const DEFAULT_WIDTH = WIDTHS[1][0]; // 캔버스 너비의 1.2%
const MIN_GAP = 0.002; // 이보다 가까운 점은 버려서 데이터를 줄인다
const BACKGROUND = "#ffffff";
const SEND_INTERVAL = 40; // ms. 이 간격으로 새 점을 묶어 보낸다 (design.md: 30~50ms)
const MAX_PART_POINTS = 200; // 서버 한도(game.MAX_PART_POINTS)와 맞춘다

// 선 번호: 브라우저마다 겹치지 않게 임의 앞부분 + 순번
const STROKE_PREFIX = Math.random().toString(36).slice(2, 8);
let strokeCount = 0;

class DrawingBoard {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onStroke = options.onStroke || null;
    this.onUndo = null; // 내가 되돌렸을 때 (서버로 알리기)
    this.onClear = null; // 내가 전체 지웠을 때 (서버로 알리기)

    this.enabled = true;
    this.color = DEFAULT_COLOR;
    this.width = DEFAULT_WIDTH;
    this.eraser = false; // 지우개: 흰색 굵은 선으로 덮는다

    this.strokes = []; // 완성된 선 목록
    this.current = null; // 지금 그리는 선
    this.pointerId = null; // 한 번에 손가락·마우스 하나만 받는다
    this.outbox = []; // 아직 서버로 다 보내지 않은 내 선: { stroke, sent }

    this._bindEvents();
    this._watchSize();
  }

  // ---------- 좌표 변환 ----------

  _toRatio(event) {
    const rect = this.canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;
    return [clamp(x), clamp(y)];
  }

  _size() {
    return this.canvas.width; // 정사각형이므로 너비 = 높이
  }

  // ---------- 입력 ----------

  _bindEvents() {
    const c = this.canvas;
    c.addEventListener("pointerdown", (e) => this._start(e));
    c.addEventListener("pointermove", (e) => this._move(e));
    c.addEventListener("pointerup", (e) => this._end(e));
    c.addEventListener("pointercancel", (e) => this._end(e));
    c.addEventListener("lostpointercapture", (e) => this._end(e));
    // 길게 누를 때 메뉴가 뜨지 않게 한다
    c.addEventListener("contextmenu", (e) => e.preventDefault());
  }

  _start(event) {
    if (!this.enabled || this.pointerId !== null) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    event.preventDefault();

    this.pointerId = event.pointerId;
    try {
      this.canvas.setPointerCapture(event.pointerId);
    } catch (e) {
      // 일부 브라우저는 캡처를 지원하지 않는다. 캡처 없이도 그리기는 된다.
    }

    strokeCount += 1;
    this.current = {
      id: `${STROKE_PREFIX}-${strokeCount}`,
      color: this.eraser ? ERASER_COLOR : this.color,
      width: this.eraser ? ERASER_WIDTH : this.width,
      points: [this._toRatio(event)],
    };
    this.outbox.push({ stroke: this.current, sent: 0 });
    this._drawDot(this.current);
  }

  _move(event) {
    if (event.pointerId !== this.pointerId || !this.current) return;
    event.preventDefault();

    // 빠르게 움직일 때 브라우저가 합쳐 둔 중간 점까지 받아서 선이 끊기지 않게 한다
    const events = event.getCoalescedEvents ? event.getCoalescedEvents() : [event];
    for (const e of events.length ? events : [event]) {
      const point = this._toRatio(e);
      const points = this.current.points;
      const last = points[points.length - 1];
      if (distance(last, point) < MIN_GAP) continue;
      points.push(point);
      this._drawSegment(this.current, last, point);
    }
  }

  _end(event) {
    if (event.pointerId !== this.pointerId || !this.current) return;
    const stroke = this.current;
    this.current = null;
    this.pointerId = null;

    this.strokes.push(stroke);
    if (this.onStroke) this.onStroke(stroke);
  }

  // ---------- 그리기 ----------

  _style(stroke) {
    const ctx = this.ctx;
    ctx.strokeStyle = stroke.color;
    ctx.fillStyle = stroke.color;
    ctx.lineWidth = Math.max(1, stroke.width * this._size());
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
  }

  _drawDot(stroke) {
    const [x, y] = stroke.points[0];
    const size = this._size();
    this._style(stroke);
    this.ctx.beginPath();
    this.ctx.arc(x * size, y * size, this.ctx.lineWidth / 2, 0, Math.PI * 2);
    this.ctx.fill();
  }

  _drawSegment(stroke, from, to) {
    const size = this._size();
    this._style(stroke);
    this.ctx.beginPath();
    this.ctx.moveTo(from[0] * size, from[1] * size);
    this.ctx.lineTo(to[0] * size, to[1] * size);
    this.ctx.stroke();
  }

  _drawStroke(stroke) {
    if (!stroke.points || stroke.points.length === 0) return;
    if (stroke.points.length === 1) {
      this._drawDot(stroke);
      return;
    }
    // 한 경로로 그려서 굵은 선의 이음새가 보이지 않게 한다
    const size = this._size();
    this._style(stroke);
    this.ctx.beginPath();
    this.ctx.moveTo(stroke.points[0][0] * size, stroke.points[0][1] * size);
    for (let i = 1; i < stroke.points.length; i++) {
      this.ctx.lineTo(stroke.points[i][0] * size, stroke.points[i][1] * size);
    }
    this.ctx.stroke();
  }

  _paintBackground() {
    this.ctx.fillStyle = BACKGROUND;
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
  }

  /** 저장된 선을 처음부터 다시 그린다. (크기가 바뀌었을 때) */
  redraw() {
    this._paintBackground();
    for (const stroke of this.strokes) this._drawStroke(stroke);
    if (this.current) this._drawStroke(this.current);
  }

  /** 다른 사람이 보낸 선 조각을 그린다. 같은 id면 이어 그리고, 새 id면 새 선을 시작한다. */
  applyPart(part) {
    const last = this.strokes[this.strokes.length - 1];
    if (last && last.id === part.id) {
      let prev = last.points[last.points.length - 1];
      for (const point of part.points) {
        last.points.push(point);
        this._drawSegment(last, prev, point);
        prev = point;
      }
      return;
    }
    const stroke = { id: part.id, color: part.color, width: part.width, points: [...part.points] };
    this.strokes.push(stroke);
    this._drawStroke(stroke);
  }

  /** 아직 안 보낸 내 점들을 조각으로 꺼낸다. 다 보낸 선은 outbox에서 뺀다. */
  takeParts() {
    const parts = [];
    for (const item of this.outbox) {
      const { stroke } = item;
      while (item.sent < stroke.points.length) {
        const points = stroke.points.slice(item.sent, item.sent + MAX_PART_POINTS);
        parts.push({ id: stroke.id, color: stroke.color, width: stroke.width, points });
        item.sent += points.length;
      }
    }
    this.outbox = this.outbox.filter((item) => item.stroke === this.current);
    return parts;
  }

  /** 선 목록 전체를 받아 처음부터 다시 그린다. (늦게 들어왔거나 다시 연결했을 때) */
  load(strokes) {
    this.strokes = strokes.map((s) => ({ ...s, points: s.points.map((p) => [p[0], p[1]]) }));
    this.current = null;
    this.pointerId = null;
    this.outbox = [];
    this.redraw();
  }

  /** 내가 그린 마지막 선을 되돌린다. (출제자) */
  undo() {
    if (!this.enabled || this.current || this.strokes.length === 0) return null;
    const stroke = this.strokes.pop();
    this.redraw();
    if (this.onUndo) this.onUndo(stroke.id);
    return stroke.id;
  }

  /** 다른 사람이 되돌린 선을 지운다. */
  applyUndo(strokeId) {
    const last = this.strokes[this.strokes.length - 1];
    if (last && last.id === strokeId) {
      this.strokes.pop();
      this.redraw();
    }
  }

  /** 내가 전체 지우기를 눌렀을 때. (출제자) */
  clearAll() {
    if (!this.enabled) return;
    this.clear();
    if (this.onClear) this.onClear();
  }

  /** 모든 선을 지운다. (화면만. 새 턴이나 받은 지우기에 쓴다) */
  clear() {
    this.strokes = [];
    this.current = null;
    this.pointerId = null;
    this.outbox = [];
    this._paintBackground();
  }

  // ---------- 크기 ----------

  _watchSize() {
    const fit = () => {
      // 화면에 보이는 크기 x 화면 배율(레티나 등)만큼 실제 픽셀을 잡아 선이 흐리지 않게 한다
      const cssSize = this.canvas.getBoundingClientRect().width;
      const pixels = Math.round(cssSize * (window.devicePixelRatio || 1));
      if (pixels > 0 && (pixels !== this.canvas.width || pixels !== this.canvas.height)) {
        this.canvas.width = pixels;
        this.canvas.height = pixels;
        this.redraw();
      }
    };
    if (window.ResizeObserver) new ResizeObserver(fit).observe(this.canvas);
    else window.addEventListener("resize", fit);
    fit();
    this.redraw(); // 처음 한 번 흰 배경을 칠한다
  }
}

function clamp(value) {
  return Math.min(1, Math.max(0, Math.round(value * 10000) / 10000));
}

function distance(a, b) {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/**
 * 그림판과 소켓을 잇는다.
 * - 내가 그린 점은 SEND_INTERVAL마다 묶어서 "stroke"로 보낸다.
 * - 서버가 보낸 "stroke" 조각은 그림판에 그린다.
 */
function linkBoardToSocket(board, socket) {
  const timer = setInterval(() => {
    if (!socket.connected) return;
    for (const part of board.takeParts()) socket.emit("stroke", part);
  }, SEND_INTERVAL);
  const flush = () => {
    for (const part of board.takeParts()) socket.emit("stroke", part);
  };
  board.onUndo = (id) => {
    flush();
    socket.emit("undo", { id });
  };
  board.onClear = () => socket.emit("clear", {});
  socket.on("stroke", (part) => board.applyPart(part));
  socket.on("undo", (data) => board.applyUndo(data.id));
  socket.on("clear", () => board.clear());
  socket.on("strokes", (data) => board.load(data.strokes));
  return () => clearInterval(timer);
}

/**
 * 그리기 도구 막대를 만든다: 색 8가지, 굵기 3단계, 지우개, 되돌리기, 전체 지우기.
 * 출제자가 아닐 때는 toolbar.hidden = true 로 숨긴다.
 */
function buildToolbar(container, board) {
  container.replaceChildren();
  container.classList.add("toolbar");

  const group = (label) => {
    const el = document.createElement("div");
    el.className = "tool-group";
    el.setAttribute("role", "group");
    el.setAttribute("aria-label", label);
    container.appendChild(el);
    return el;
  };
  const button = (parent, label, className, onClick) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tool " + className;
    b.setAttribute("aria-label", label);
    b.title = label;
    b.addEventListener("click", onClick);
    parent.appendChild(b);
    return b;
  };

  const colors = group("색");
  const colorButtons = PALETTE.map(([color, name]) => {
    const b = button(colors, name, "swatch", () => {
      board.color = color;
      board.eraser = false;
      refresh();
    });
    b.style.setProperty("--swatch", color);
    b.dataset.color = color;
    return b;
  });

  const widths = group("굵기");
  const widthButtons = WIDTHS.map(([width, name], i) => {
    const b = button(widths, name, "width", () => {
      board.width = width;
      refresh();
    });
    b.dataset.width = width;
    b.style.setProperty("--dot", `${6 + i * 6}px`);
    return b;
  });

  const actions = group("편집");
  const eraser = button(actions, "지우개", "text", () => {
    board.eraser = !board.eraser;
    refresh();
  });
  eraser.textContent = "지우개";
  const undo = button(actions, "되돌리기", "text", () => board.undo());
  undo.textContent = "되돌리기";
  const clear = button(actions, "전체 지우기", "text", () => board.clearAll());
  clear.textContent = "전체 지우기";

  function refresh() {
    colorButtons.forEach((b) => b.setAttribute("aria-pressed", String(!board.eraser && b.dataset.color === board.color)));
    widthButtons.forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.width) === board.width)));
    eraser.setAttribute("aria-pressed", String(board.eraser));
  }
  refresh();
  return container;
}

"use strict";

// ---------- 공통 도구 ----------
const $ = (sel, el = document) => el.querySelector(sel);

/** DOM 요소 만들기. 문자열은 textContent로만 넣어서 서버 응답이 HTML로 해석되지 않는다. */
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    throw new Error("서버에 연결하지 못했어요. 서버가 켜져 있는지 확인해 주세요.");
  }
  let body = null;
  try { body = await res.json(); } catch (e) { /* 본문이 없을 수 있다 */ }
  if (!res.ok) {
    const d = body && body.detail;
    throw new Error(typeof d === "string" ? d : "요청 값이 올바르지 않아요.");
  }
  return body;
}

/** 2026-11-19T14:03:44+09:00 -> 2026-11-19 14:03 */
function fmtTime(iso) { return (iso || "").replace("T", " ").slice(0, 16); }

function showNotice(el, text, kind = "") {
  el.className = "notice " + kind;
  el.textContent = text;
  el.hidden = !text;
}

// ---------- 탭 ----------
const views = { chat: $("#view-chat"), plans: $("#view-plans"), logs: $("#view-logs") };
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    for (const [name, el] of Object.entries(views)) el.hidden = name !== btn.dataset.tab;
    if (btn.dataset.tab === "plans") loadPlans();
    if (btn.dataset.tab === "logs") loadLogs();
  });
});

// ---------- API 키 안내 ----------
async function loadHealth() {
  const box = $("#health");
  try {
    const hl = await api("/api/health");
    if (hl.missing_guide.length) {
      box.replaceChildren(h("p", {}, "⚠ 설정이 필요한 항목이 있어요."),
        h("ul", {}, hl.missing_guide.map((g) => h("li", {}, g))),
        h("p", {}, ".env를 고친 뒤 서버를 다시 시작해 주세요."));
      box.hidden = false;
    } else {
      box.hidden = true;
    }
  } catch (e) {
    showNotice(box, e.message, "error");
  }
}

// ---------- 실행 과정 표시 (F3019) ----------
const STEP_LABEL = {
  analyze: "요청 분석", plan: "계획 수립", work: "Tool 조회", judge: "제약 판단",
  replan: "재계획", places: "주변 장소 조회", respond: "응답 작성", save: "계획 저장",
};
const TOOL_LABEL = { get_wave_forecast: "파고 예보", get_beach_weather: "해변 날씨", search_places: "주변 장소" };
const GRADE_CLASS = { "적합": "ok", "주의": "warn", "부적합": "bad", "판정 불가": "bad" };

function argsSummary(tool, a = {}) {
  if (tool === "get_wave_forecast") return `${a.region} · ${a.date}${a.end_time ? " · ~" + a.end_time : ""}`;
  if (tool === "get_beach_weather") return `${(a.spot_ids || []).length}곳 · ${a.date}`;
  if (tool === "search_places") return `${a.category}`;
  return "";
}

function stepDetail(step, p) {
  if (step === "analyze") return `의도 ${p.intent || "-"}${p.reason ? " — " + p.reason : ""}`;
  if (step === "plan") return `${p.region}${p.region_assumed ? " (지역을 말하지 않아 기본값)" : ""}`;
  if (step === "work") return `${p.calls}개 호출${p.fatal ? " · 치명 오류로 중단" : ""}`;
  if (step === "judge") return `${p.region}: 후보 ${p.candidates}곳 / 제외 ${p.excluded}곳`;
  if (step === "save") return p.saved ? "저장됨" : "저장 못 함";
  return "";
}

/** 이벤트 목록을 실행 순서대로 보여 준다. 재계획이 일어난 지점은 구분선과 색으로 나눈다. */
function renderTrace(events) {
  const list = h("ol", { class: "trace" });
  let phase = 0;
  let lastReq = null;
  const add = (cls, ...kids) => list.append(h("li", { class: `row ${cls} phase-${phase % 4}` }, ...kids));

  for (const e of events) {
    const p = e.payload || {};
    if (e.type === "tool_request") { lastReq = p; continue; }
    if (e.type === "replan") {
      phase += 1;
      list.append(h("li", { class: "divider" },
        `↻ 재계획 ${p.count}회 — ${p.next_region} 확인 (${p.reason})`));
    } else if (e.type === "tool_response") {
      const ok = p.ok;
      const args = lastReq && lastReq.tool === p.tool && !p.cached ? lastReq.args : null;
      add(ok ? "tool" : "tool fail",
        h("span", { class: "name" }, TOOL_LABEL[p.tool] || p.tool),
        args && h("span", { class: "meta" }, argsSummary(p.tool, args)),
        h("span", { class: "badge " + (ok ? "ok" : "bad") }, ok ? "성공" : "실패"),
        p.cached ? h("span", { class: "badge" }, "이미 받은 결과 재사용")
                 : h("span", { class: "meta" }, `${p.elapsed_ms}ms${p.attempt > 1 ? " · 재시도" : ""}`),
        !ok && p.error && h("span", { class: "meta" }, `${p.error.code}: ${p.error.message}`));
    } else if (e.type === "judge_result") {
      add("judge", h("span", { class: "name" }, "판정"),
        h("span", { class: "spotchips" }, (p.spots || []).map((s) =>
          h("span", { class: "badge " + (GRADE_CLASS[s.grade] || "") },
            `${s.name || s.spot_id} ${s.grade}`))));
    } else if (e.type === "step_end") {
      if (p.step === "replan" || p.step === "judge") continue; // 아래 행들이 더 자세히 보여 준다
      add("step", h("span", { class: "name" }, STEP_LABEL[p.step] || p.step),
        h("span", { class: "meta" }, `${p.elapsed_ms}ms`),
        h("span", { class: "meta" }, stepDetail(p.step, p)));
    } else if (e.type === "plan_saved") {
      add("step", h("span", { class: "name" }, "계획 저장"), h("span", { class: "meta" }, `#${p.plan_id}`));
    } else if (e.type === "error") {
      add("error", h("span", { class: "name" }, "오류"), h("span", { class: "meta" }, `${p.step || ""} ${p.error || ""}`));
    }
  }
  return list;
}

// ---------- 대화 화면 ----------
const messagesEl = $("#messages");
const inputEl = $("#chat-input");
const sendBtn = $("#chat-send");
let sessionId = null;
let busy = false;

const EXAMPLES = [
  "토요일 오전에 양양에서 초보가 탈 만한 곳 찾아줘, 오후 2시 전엔 나와야 해",
  "내일 부산에서 초보가 탈 수 있는 곳 알려줘. 근처 서핑샵도 알려줘",
];
$("#examples").append(...EXAMPLES.map((t) => h("button", { class: "chip", type: "button", onclick: () => send(t) }, t)));

function scrollDown() { window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }); }

function addUser(text) {
  const empty = $("#chat-empty");
  if (empty) empty.remove();
  messagesEl.append(h("div", { class: "msg user" }, h("div", { class: "bubble" }, text)));
}

function addPending() {
  const hints = ["요청을 분석하는 중", "파고와 날씨를 조회하는 중", "조건에 맞는지 판단하는 중"];
  const label = h("span", { class: "dots" }, hints[0]);
  const el = h("div", { class: "msg bot pending" }, h("div", { class: "bubble" }, label));
  messagesEl.append(el);
  let i = 0;
  const timer = setInterval(() => { i = Math.min(i + 1, hints.length - 1); label.firstChild.textContent = hints[i]; }, 3500);
  return { remove() { clearInterval(timer); el.remove(); } };
}

function keyNotice(err) {
  if (!err) return null;
  if (err.code === "MISSING_KEY" || err.code === "AUTH_ERROR") {
    return h("div", { class: "notice error" },
      h("p", {}, "API 키 설정을 확인해 주세요."),
      h("ul", {}, h("li", {}, err.message), h("li", {}, "프로젝트 폴더의 .env 파일에 키를 넣고 서버를 다시 시작하세요.")));
  }
  return h("div", { class: "notice error" }, h("p", {}, `처리 중 문제가 생겼어요 (${err.code}).`));
}

function addBot(r) {
  const steps = r.events.filter((e) => e.type === "step_end").length;
  const trace = r.events.length
    ? h("details", { class: "trace-box", open: true },
        h("summary", {}, `실행 과정 · ${steps}단계 · Tool ${r.tool_log.length}회 · 재계획 ${r.replan_count}회`),
        renderTrace(r.events))
    : null;
  messagesEl.append(h("div", { class: "msg bot" }, h("div", { class: "bubble" }, r.answer), keyNotice(r.error), trace));
}

async function send(text) {
  text = (text || "").trim();
  if (!text || busy) return;
  busy = true;
  sendBtn.disabled = true;
  inputEl.value = "";
  addUser(text);
  const pending = addPending();
  scrollDown();
  try {
    const r = await api("/api/chat", { method: "POST", body: { session_id: sessionId, message: text } });
    sessionId = r.session_id;
    pending.remove();
    addBot(r);
  } catch (e) {
    pending.remove();
    messagesEl.append(h("div", { class: "msg bot" }, h("div", { class: "notice error" }, e.message)));
  } finally {
    busy = false;
    sendBtn.disabled = false;
    inputEl.focus();
    scrollDown();
  }
}

$("#chat-form").addEventListener("submit", (ev) => { ev.preventDefault(); send(inputEl.value); });
$("#chat-new").addEventListener("click", () => {
  if (busy) return;
  sessionId = null;
  messagesEl.replaceChildren(h("div", { class: "empty", id: "chat-empty" }, h("p", {}, "새 대화를 시작했어요. 날짜와 지역, 서핑 경험 수준을 알려 주세요.")));
});

// ---------- 계획 관리 화면 (F3018) ----------
const plansMsg = $("#plans-msg");

function overlapIds(plans) {
  const ids = new Set();
  for (const a of plans) for (const b of plans) {
    if (a.id < b.id && a.date === b.date && a.start_time < b.end_time && a.end_time > b.start_time) {
      ids.add(a.id); ids.add(b.id);
    }
  }
  return ids;
}

async function loadPlans() {
  const box = $("#plans-list");
  try {
    const plans = await api("/api/plans");
    if (!plans.length) {
      box.replaceChildren(h("div", { class: "empty-list" }, "저장한 계획이 없어요. 대화 화면에서 추천을 받고 \"1번 저장해줘\"라고 해 보세요."));
      return;
    }
    const overlaps = overlapIds(plans);
    box.replaceChildren(...plans.map((p) => planCard(p, overlaps.has(p.id))));
  } catch (e) {
    showNotice(plansMsg, e.message, "error");
  }
}

function planCard(p, overlapping) {
  const card = h("div", { class: "card" + (overlapping ? " overlap" : "") });
  const view = () => {
    card.replaceChildren(
      h("div", { class: "card-top" },
        h("span", { class: "card-title" }, `${p.spot_name}`),
        h("span", {}, `${p.date} ${p.start_time}~${p.end_time}`,
          overlapping ? h("span", { class: "badge warn", style: "margin-left:8px" }, "시간 겹침") : null)),
      p.note && h("div", { class: "card-meta" }, p.note),
      h("div", { class: "card-meta" }, `저장 ${fmtTime(p.created_at)}${p.updated_at ? " · 수정 " + fmtTime(p.updated_at) : ""}`),
      h("div", { class: "card-actions" },
        h("button", { class: "ghost", onclick: edit }, "수정"),
        h("button", { class: "ghost danger", onclick: remove }, "삭제")));
  };
  const edit = () => {
    const date = h("input", { type: "date", value: p.date });
    const start = h("input", { type: "time", value: p.start_time });
    const end = h("input", { type: "time", value: p.end_time });
    const note = h("input", { type: "text", value: p.note || "", maxlength: 300 });
    const err = h("div", { class: "notice error", hidden: true });
    const save = async () => {
      const body = {};
      if (date.value !== p.date) body.date = date.value;
      if (start.value !== p.start_time) body.start_time = start.value;
      if (end.value !== p.end_time) body.end_time = end.value;
      if (note.value !== (p.note || "")) body.note = note.value;
      if (!Object.keys(body).length) { view(); return; }
      try {
        const r = await api(`/api/plans/${p.id}`, { method: "PATCH", body });
        if (r.overlaps.length) {
          showNotice(plansMsg, `수정했어요. 같은 날 시간이 겹치는 계획이 있어요: ${r.overlaps.map((o) => `${o.spot_name} ${o.start_time}~${o.end_time}`).join(", ")}`, "warn");
        } else {
          showNotice(plansMsg, "수정했어요.", "ok");
        }
        loadPlans();
      } catch (e) { showNotice(err, e.message, "error"); }
    };
    card.replaceChildren(
      h("div", { class: "card-title" }, `${p.spot_name} 수정`),
      h("div", { class: "form-grid" },
        h("label", {}, "날짜", date), h("label", {}, "시작", start), h("label", {}, "종료", end), h("label", {}, "메모", note)),
      err,
      h("div", { class: "card-actions" }, h("button", { class: "ghost", onclick: save }, "저장"), h("button", { class: "ghost", onclick: view }, "취소")));
  };
  const remove = async () => {
    if (!confirm(`${p.spot_name} ${p.date} 계획을 삭제할까요?`)) return;
    try {
      await api(`/api/plans/${p.id}`, { method: "DELETE" });
      showNotice(plansMsg, "삭제했어요.", "ok");
      loadPlans();
    } catch (e) { showNotice(plansMsg, e.message, "error"); }
  };
  view();
  return card;
}
$("#plans-refresh").addEventListener("click", loadPlans);

// ---------- 실행 로그 화면 ----------
const logsMsg = $("#logs-msg");
const detailEl = $("#log-detail");

async function loadLogs() {
  const box = $("#logs-list");
  detailEl.hidden = true;
  try {
    const sessions = await api("/api/logs");
    if (!sessions.length) {
      box.replaceChildren(h("div", { class: "empty-list" }, "저장된 실행 로그가 없어요."));
      return;
    }
    box.replaceChildren(...sessions.map((s) => h("div", { class: "card" },
      h("div", { class: "card-top" },
        h("span", { class: "card-title" }, s.session_id),
        h("span", { class: "card-meta" }, fmtTime(s.started_at))),
      h("div", { class: "card-meta" }, `이벤트 ${s.event_count}개 · 재계획 ${s.replan_count || 0}회 · 오류 ${s.error_count || 0}건`),
      h("div", { class: "card-actions" },
        h("button", { class: "ghost", onclick: () => showLog(s.session_id) }, "보기"),
        h("button", { class: "ghost danger", onclick: () => removeLog(s.session_id) }, "삭제")))));
  } catch (e) {
    showNotice(logsMsg, e.message, "error");
  }
}

async function showLog(id) {
  try {
    const d = await api(`/api/logs/${encodeURIComponent(id)}`);
    detailEl.replaceChildren(h("h2", {}, `세션 ${id}`), renderTrace(d.events),
      h("details", {}, h("summary", { class: "card-meta" }, "원본 이벤트 (JSON)"),
        h("pre", { class: "raw" }, JSON.stringify(d.events, null, 2))));
    detailEl.hidden = false;
    detailEl.scrollIntoView({ behavior: "smooth" });
  } catch (e) { showNotice(logsMsg, e.message, "error"); }
}

async function removeLog(id) {
  if (!confirm(`세션 ${id}의 실행 로그를 삭제할까요?`)) return;
  try {
    await api(`/api/logs/${encodeURIComponent(id)}`, { method: "DELETE" });
    showNotice(logsMsg, "삭제했어요.", "ok");
    loadLogs();
  } catch (e) { showNotice(logsMsg, e.message, "error"); }
}
$("#logs-refresh").addEventListener("click", loadLogs);

loadHealth();
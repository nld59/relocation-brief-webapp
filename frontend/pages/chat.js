
import React, { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import Layout from "../components/Layout";
import { ALL_TAGS } from "../components/tags";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

const INITIAL_ASSISTANT_TEXT = `Hi! I'm your relocation broker. We'll build your brief in a few questions, then you can keep asking.

Currently available city: Brussels (more cities coming soon). Click Brussels to start.`;

const INITIAL_STATE = {
  city: "",
  householdType: "",
  childrenCount: 0,
  childrenAges: [],
  mode: "buy",
  bedrooms: "2",
  propertyType: "apartment",
  budgetMin: null,
  budgetMax: null,
  priorities: [],
  includeWorkCommute: false,
  workTransport: "public_transport",
  workMinutes: 35,
  workAddress: "",
  includeSchoolCommute: false,
  schoolTransport: "walk",
  schoolMinutes: 10,
  qualityMode: "fast",
};

function clampInt(v, min, max) {
  const n = parseInt(String(v), 10);
  if (Number.isNaN(n)) return null;
  return Math.max(min, Math.min(max, n));
}

function tagLabel(id) {
  const t = ALL_TAGS.find((x) => x.id === id);
  return t ? t.title : id;
}

function parseRange(text) {
  // supports: "2500-3600", "2500 to 3600", "2.5k-3.6k", "2 500 - 3 600"
  const t = String(text || "").toLowerCase().replace(/€/g, "").replace(/eur/g, "");
  const norm = t.replace(/,/g, ".").replace(/\s+/g, " ").trim();

  const kMul = (s) => {
    if (!s) return null;
    let x = s.trim();
    let mul = 1;
    if (x.endsWith("k")) {
      mul = 1000;
      x = x.slice(0, -1);
    }
    const n = parseFloat(x);
    if (Number.isNaN(n)) return null;
    return Math.round(n * mul);
  };

  // find tokens like 2500, 3.6k
  const tokens = norm.match(/(\d+(?:\.\d+)?k?)/g) || [];
  if (tokens.length < 2) return { min: null, max: null };
  let a = kMul(tokens[0]);
  let b = kMul(tokens[1]);
  if (a == null || b == null) return { min: null, max: null };
  if (b < a) [a, b] = [b, a];
  return { min: a, max: b };
}

export default function ChatPage() {
  const router = useRouter();
  const [sessionId] = useState(() => "chat_" + uid());
  const [messages, setMessages] = useState(() => [
    { role: "assistant", text: INITIAL_ASSISTANT_TEXT },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const [state, setState] = useState(INITIAL_STATE);
  const [step, setStep] = useState("city"); // city -> household -> kids? -> housing -> bedrooms -> propertyType -> budget -> top3 -> extras -> work -> workDetails? -> school -> schoolDetails? -> generate -> clarify -> qa
  const [mode, setMode] = useState("onboarding"); // onboarding | clarify | qa
  const [tagTop, setTagTop] = useState([]); // top3 storage

  const [briefId, setBriefId] = useState("");
  const [clarifying, setClarifying] = useState([]);
  const [clarAnswers, setClarAnswers] = useState({});

  // history snapshots for Back
  const [history, setHistory] = useState([]);

  const bottomRef = useRef(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy, step, mode, briefId, clarifying.length]);

  const canSend = input.trim().length > 0 && !busy;

  function push(role, text) {
    setMessages((prev) => [...prev, { role, text }]);
  }

  function snapshot() {
    // capture minimal rollback info
    setHistory((h) => [
      ...h,
      {
        step,
        mode,
        state,
        tagTop,
        briefId,
        clarifying,
        clarAnswers,
        messagesLen: messages.length,
      },
    ]);
  }

  function goBack() {
    setHistory((h) => {
      if (!h.length) return h;
      const last = h[h.length - 1];
      setStep(last.step);
      setMode(last.mode);
      setState(last.state);
      setTagTop(last.tagTop);
      setBriefId(last.briefId);
      setClarifying(last.clarifying);
      setClarAnswers(last.clarAnswers);
      setMessages((prev) => prev.slice(0, last.messagesLen));
      return h.slice(0, -1);
    });
  }

  function clearChat() {
    setHistory([]);
    setMode("onboarding");
    setStep("city");
    setTagTop([]);
    setBriefId("");
    setClarifying([]);
    setClarAnswers({});
    setState(INITIAL_STATE);
    setMessages([{ role: "assistant", text: INITIAL_ASSISTANT_TEXT }]);
    setInput("");
  }

  async function callDraft(payload) {
    const res = await fetch(`${API}/brief/draft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = data?.detail || `Request failed (${res.status})`;
      throw new Error(err);
    }
    return data;
  }

  async function callFinal(brief_id, clarifying_answers) {
    const res = await fetch(`${API}/brief/final`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brief_id, clarifying_answers }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = data?.detail || `Request failed (${res.status})`;
      throw new Error(err);
    }
    return data;
  }

  async function callQA(brief_id, question) {
    const res = await fetch(`${API}/brief/qa`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brief_id, question, mode: "report_only" }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = data?.detail || `Request failed (${res.status})`;
      throw new Error(err);
    }
    return data;
  }

  async function generateBrief() {
    setBusy(true);
    try {
      push("assistant", "Got it. Generating your brief…");
      const payload = { ...state };
      const data = await callDraft(payload);
      setBriefId(data.brief_id);

      const qs = data.clarifying_questions || [];
      if (qs.length > 0) {
        setClarifying(qs);
        setClarAnswers({});
        setMode("clarify");
        setStep("clarify");
        push("assistant", "Quick clarifications so I can be accurate:");
      } else {
        setMode("qa");
        setStep("qa");
        push(
          "assistant",
          "Your brief is ready. You can download the PDF below. Ask me anything about your report."
        );
      }
    } catch (e) {
      push("assistant", `I couldn't generate the brief: ${e.message}`);
      setStep("generate");
    } finally {
      setBusy(false);
    }
  }

  async function finalizeWithClarifications() {
    setBusy(true);
    try {
      const missing = (clarifying || []).filter(
        (q) => clarAnswers[q.id] === undefined || clarAnswers[q.id] === ""
      );
      if (missing.length) {
        push("assistant", "Please answer all clarification questions above first.");
        return;
      }
      push("assistant", "Thanks — updating your brief…");
      const data = await callFinal(briefId, clarAnswers);
      const qs = data.clarifying_questions || [];
      if (qs.length > 0) {
        setClarifying(qs);
        setClarAnswers({});
        setMode("clarify");
        setStep("clarify");
        push("assistant", "One more quick thing:");
      } else {
        setClarifying([]);
        setMode("qa");
        setStep("qa");
        push(
          "assistant",
          "All set. Your brief is ready. You can download the PDF below. Ask me anything about your report."
        );
      }
    } catch (e) {
      push("assistant", `I couldn't finalize the brief: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  function askNext(nextStep, assistantText) {
    if (assistantText) push("assistant", assistantText);
    setStep(nextStep);
  }

  function onSend() {
    if (!canSend) return;
    const text = input.trim();
    setInput("");
    push("user", text);

    // Q&A mode (stay on same page)
    if (mode === "qa") {
      if (!briefId) {
        push("assistant", "I don't have a report yet. Type “generate” when ready.");
        return;
      }
      setBusy(true);
      (async () => {
        try {
          const data = await callQA(briefId, text);
          push("assistant", data.answer || "Sorry, I couldn't answer that.");
        } catch (e) {
          push("assistant", `Q&A failed: ${e.message}`);
        } finally {
          setBusy(false);
        }
      })();
      return;
    }

    // Onboarding / clarify uses deterministic steps
    if (step === "city") {
      // city is fixed to Brussels - user can type or click button; any input proceeds
      snapshot();
      setState((s) => ({ ...s, city: "Brussels" }));
      askNext(
        "household",
        "Great. How many people are relocating?\n\nChoose one: Solo / Couple / Family"
      );
      return;
    }

    if (step === "household") {
      const low = text.toLowerCase();
      snapshot();
      if (low.includes("solo") || low === "1") {
        setState((s) => ({
          ...s,
          householdType: "solo",
          childrenCount: 0,
          childrenAges: [],
        }));
        askNext("housing", "Got it. Rent or buy? (rent / buy)");
        return;
      }
      if (low.includes("couple") || low === "2") {
        setState((s) => ({
          ...s,
          householdType: "couple",
          childrenCount: 0,
          childrenAges: [],
        }));
        askNext("housing", "Got it. Rent or buy? (rent / buy)");
        return;
      }
      if (low.includes("family")) {
        setState((s) => ({ ...s, householdType: "family" }));
        askNext(
          "kids",
          'How many children, and what are their ages?\n\nExample: "2 kids, ages 3 and 7"'
        );
        return;
      }
      push("assistant", "Please reply with: Solo / Couple / Family");
      // revert snapshot? no, we didn't change anything meaningful
      return;
    }

    if (step === "kids") {
      const nums = (text.match(/\d+/g) || [])
        .map((n) => parseInt(n, 10))
        .filter((n) => !Number.isNaN(n));
      const count = nums.length ? nums[0] : null;
      const ages = nums.length > 1 ? nums.slice(1, 6) : [];
      if (count === null) {
        push(
          "assistant",
          'Please include the number of children. Example: "2 kids, ages 3 and 7".'
        );
        return;
      }
      snapshot();
      setState((s) => ({ ...s, childrenCount: count, childrenAges: ages }));
      askNext("housing", "Thanks. Rent or buy? (rent / buy)");
      return;
    }

    if (step === "housing") {
      const low = text.toLowerCase();
      if (!low.includes("rent") && !low.includes("buy") && !low.includes("purchase")) {
        push("assistant", "Please reply: rent or buy");
        return;
      }
      snapshot();
      setState((s) => ({ ...s, mode: low.includes("rent") ? "rent" : "buy" }));
      askNext("bedrooms", "How many rooms/bedrooms do you need?\n\nChoose: studio / 1 / 2 / 3");
      return;
    }

    if (step === "bedrooms") {
      const low = text.toLowerCase().trim();
      const allowed = new Set(["studio", "1", "2", "3"]);
      if (!allowed.has(low)) {
        push("assistant", "Please choose one: studio / 1 / 2 / 3");
        return;
      }
      snapshot();
      setState((s) => ({ ...s, bedrooms: low }));
      askNext("propertyType", "Apartment or house? (apartment / house / not sure)");
      return;
    }

    if (step === "propertyType") {
      const low = text.toLowerCase();
      let val = "";
      if (low.includes("apartment")) val = "apartment";
      else if (low.includes("house")) val = "house";
      else if (low.includes("not") || low.includes("sure")) val = "not_sure";
      if (!val) {
        push("assistant", "Please reply: apartment / house / not sure");
        return;
      }
      snapshot();
      setState((s) => ({ ...s, propertyType: val }));
      askNext(
        "budget",
        "What is your budget range?\n\nExamples:\n- 2000-3000\n- 2.5k to 3.6k\n(We interpret based on rent/buy.)"
      );
      return;
    }

    if (step === "budget") {
      const { min, max } = parseRange(text);
      if (min == null || max == null) {
        push("assistant", 'Please give a range with two numbers, e.g., "2000-3000" or "2.5k-3.6k".');
        return;
      }
      snapshot();
      setState((s) => ({ ...s, budgetMin: min, budgetMax: max }));
      setTagTop([]);
      const intro = `Now pick your TOP 3 priorities (reply with 3 numbers):\n`;
      const list = ALL_TAGS.slice(0, 12).map((t, i) => `${i + 1}. ${t.title}`).join("\n");
      askNext("top3", `${intro}${list}\n\n(We will add more options right after.)`);
      return;
    }

    if (step === "top3") {
      const nums = (text.match(/\d+/g) || [])
        .map((n) => parseInt(n, 10))
        .filter((n) => n >= 1 && n <= ALL_TAGS.length);
      const uniq = [...new Set(nums)].slice(0, 3);
      if (uniq.length < 3) {
        push("assistant", 'Please reply with 3 numbers (e.g., "1 5 9").');
        return;
      }
      snapshot();
      const picked = uniq.map((n) => ALL_TAGS[n - 1].id);
      setTagTop(picked);
      setState((s) => ({ ...s, priorities: picked }));
      const allList = ALL_TAGS.map((t, i) => `${i + 1}. ${t.title}`).join("\n");
      askNext(
        "extras",
        `Great. Add up to 4 more priorities (optional). Reply with numbers, or type "skip".\n\n${allList}`
      );
      return;
    }

    if (step === "extras") {
      const low = text.toLowerCase().trim();
      if (low === "skip" || low === "no" || low === "none") {
        askNext("work", "Do you want to optimize for commute to work? (yes/no)");
        return;
      }
      const nums = (text.match(/\d+/g) || [])
        .map((n) => parseInt(n, 10))
        .filter((n) => n >= 1 && n <= ALL_TAGS.length);
      const uniq = [...new Set(nums)].slice(0, 4);
      snapshot();
      const extra = uniq
        .map((n) => ALL_TAGS[n - 1].id)
        .filter((id) => !tagTop.includes(id));
      const combined = [...tagTop, ...extra].slice(0, 7);
      setState((s) => ({ ...s, priorities: combined }));
      askNext("work", "Do you want to optimize for commute to work? (yes/no)");
      return;
    }

    if (step === "work") {
      const low = text.toLowerCase();
      if (!low.startsWith("y") && !low.startsWith("n")) {
        push("assistant", "Please reply: yes or no");
        return;
      }
      snapshot();
      if (low.startsWith("y")) {
        setState((s) => ({ ...s, includeWorkCommute: true }));
        askNext(
          "workDetails",
          'Ok. How will you commute (public_transport / car / bike) and what is your max minutes?\nExample: "public_transport 35"\nYou can also add destination like "Wavre".'
        );
      } else {
        setState((s) => ({ ...s, includeWorkCommute: false, workAddress: "" }));
        askNext("school", "Do you want to optimize for commute to school? (yes/no)");
      }
      return;
    }

    if (step === "workDetails") {
      const low = text.toLowerCase();
      let transport = "public_transport";
      if (low.includes("car")) transport = "car";
      else if (low.includes("bike")) transport = "bike";
      const nums = (text.match(/\d+/g) || [])
        .map((n) => parseInt(n, 10))
        .filter((n) => !Number.isNaN(n));
      const minutes = nums.length ? clampInt(nums[0], 5, 120) : null;
      if (minutes === null) {
        push("assistant", 'Please include max minutes. Example: "public_transport 35".');
        return;
      }
      // naive destination capture: keep the last 1-2 tokens if not numeric/keyword
      let addr = "";
      const toks = text.split(/\s+/).filter(Boolean);
      if (toks.length) {
        const last = toks[toks.length - 1];
        if (!/^\d+$/.test(last) && last.length > 2) {
          addr = toks.slice(-2).join(" ");
        }
      }
      snapshot();
      setState((s) => ({
        ...s,
        workTransport: transport,
        workMinutes: minutes,
        workAddress: addr || s.workAddress,
      }));
      askNext("school", "Do you want to optimize for commute to school? (yes/no)");
      return;
    }

    if (step === "school") {
      const low = text.toLowerCase();
      if (!low.startsWith("y") && !low.startsWith("n")) {
        push("assistant", "Please reply: yes or no");
        return;
      }
      snapshot();
      if (low.startsWith("y")) {
        setState((s) => ({ ...s, includeSchoolCommute: true }));
        askNext(
          "schoolDetails",
          'Ok. How will you commute to school (walk / public_transport / car) and max minutes?\nExample: "walk 10"'
        );
      } else {
        setState((s) => ({ ...s, includeSchoolCommute: false }));
        askNext("generate", 'Perfect. I have enough to generate your brief. Type "generate".');
      }
      return;
    }

    if (step === "schoolDetails") {
      const low = text.toLowerCase();
      let transport = "walk";
      if (low.includes("car")) transport = "car";
      else if (low.includes("public")) transport = "public_transport";
      const nums = (text.match(/\d+/g) || [])
        .map((n) => parseInt(n, 10))
        .filter((n) => !Number.isNaN(n));
      const minutes = nums.length ? clampInt(nums[0], 5, 120) : null;
      if (minutes === null) {
        push("assistant", 'Please include minutes. Example: "walk 10".');
        return;
      }
      snapshot();
      setState((s) => ({ ...s, schoolTransport: transport, schoolMinutes: minutes }));
      askNext("generate", 'Perfect. I have enough to generate your brief. Type "generate".');
      return;
    }

    if (step === "generate") {
      if (text.toLowerCase().includes("gen")) {
        snapshot();
        generateBrief();
      } else {
        push("assistant", 'Type "generate" when you are ready.');
      }
      return;
    }

    if (mode === "clarify") {
      push("assistant", "Please use the clarification UI above.");
      return;
    }
  }

  const selectedTags = useMemo(
    () => (state.priorities || []).map(tagLabel).join(", "),
    [state.priorities]
  );

  return (
    <Layout>
      <div className="container">
        <div className="card" style={{ maxWidth: 900 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
            <h1 className="h1" style={{ marginBottom: 6 }}>
              Chat with a broker
            </h1>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <button className="btn" type="button" onClick={goBack} disabled={!history.length || busy}>
                Back
              </button>
              <button className="btn" type="button" onClick={clearChat} disabled={busy}>
                Clear chat
              </button>
              <Link href="/chat" className="linkBtn">
                Home
              </Link>
            </div>
          </div>

          <p className="p" style={{ marginTop: 0 }}>
            One conversation. I’ll ask a few questions, generate your PDF brief, then you can keep asking.
          </p>

          {step === "city" && (
            <div style={{ marginBottom: 12, display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button
                className="btn"
                type="button"
                onClick={() => {
                  // auto-set Brussels and move on (as if user answered)
                  snapshot();
                  setState((s) => ({ ...s, city: "Brussels" }));
                  push("user", "Brussels");
                  askNext("household", "Great. How many people are relocating?\n\nChoose one: Solo / Couple / Family");
                }}
                disabled={busy}
              >
                Brussels
              </button>
              <div style={{ color: "var(--muted)", fontSize: 12, alignSelf: "center" }}>
                More cities coming soon.
              </div>
            </div>
          )}

          <div
            style={{
              border: "1px solid var(--stroke)",
              borderRadius: 16,
              padding: 12,
              height: 520,
              overflowY: "auto",
              background: "rgba(0,0,0,0.12)",
            }}
          >
            {messages.map((m, idx) => (
              <div
                key={idx}
                style={{
                  display: "flex",
                  justifyContent: m.role === "user" ? "flex-end" : "flex-start",
                  margin: "8px 0",
                }}
              >
                <div
                  style={{
                    maxWidth: "78%",
                    padding: "10px 12px",
                    borderRadius: 14,
                    whiteSpace: "pre-wrap",
                    border: "1px solid var(--stroke)",
                    background: m.role === "user" ? "rgba(47,102,255,0.20)" : "rgba(255,255,255,0.06)",
                  }}
                >
                  {m.text}
                </div>
              </div>
            ))}

            {mode === "clarify" && clarifying.length > 0 && (
              <div
                style={{
                  marginTop: 10,
                  padding: 10,
                  borderRadius: 12,
                  border: "1px solid var(--stroke)",
                  background: "rgba(255,255,255,0.04)",
                }}
              >
                <div style={{ fontWeight: 700, marginBottom: 8 }}>Clarifying questions</div>
                {clarifying.map((q) => (
                  <div key={q.id} style={{ marginBottom: 10 }}>
                    <div style={{ marginBottom: 6 }}>{q.question}</div>

                    {q.type === "single_choice" &&
                      (q.options || []).map((opt) => (
                        <label key={String(opt.value)} style={{ display: "block", margin: "4px 0" }}>
                          <input
                            type="radio"
                            name={q.id}
                            value={opt.value}
                            checked={String(clarAnswers[q.id] || "") === String(opt.value)}
                            onChange={() => setClarAnswers((a) => ({ ...a, [q.id]: opt.value }))}
                          />{" "}
                          {opt.label}
                        </label>
                      ))}

                    {q.type !== "single_choice" && (
                      <input
                        className="input"
                        placeholder="Type your answer"
                        value={clarAnswers[q.id] || ""}
                        onChange={(e) => setClarAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                      />
                    )}
                  </div>
                ))}
                <button className="btn" disabled={busy} onClick={finalizeWithClarifications}>
                  Apply clarifications
                </button>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          <div className="row" style={{ marginTop: 12 }}>
            <input
              className="input"
              placeholder={busy ? "Working…" : mode === "qa" ? "Ask about your report…" : "Type your message…"}
              value={input}
              disabled={busy}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onSend();
              }}
            />
            <button className="btn" disabled={!canSend} onClick={onSend}>
              Send
            </button>
          </div>

          <div style={{ marginTop: 10, color: "var(--muted)", fontSize: 13 }}>
            <div>
              <b>Current inputs:</b> {state.city || "—"} · {state.mode} · budget {state.budgetMin ?? "—"}–{state.budgetMax ?? "—"} ·
              priorities: {selectedTags || "—"}
            </div>
          </div>

          {briefId && (
            <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
              <a
                className="btn"
                href={`${API}/brief/download?brief_id=${briefId}&format=pdf`}
                target="_blank"
                rel="noreferrer"
              >
                Download PDF
              </a>
              <a className="btn" href={`${API}/brief/download?brief_id=${briefId}&format=md`} target="_blank" rel="noreferrer">
                Download MD
              </a>
              <a className="btn" href={`${API}/brief/download?brief_id=${briefId}&format=norm`} target="_blank" rel="noreferrer">
                Download norm.json
              </a>
            </div>
          )}

          <div style={{ marginTop: 12, color: "var(--muted)", fontSize: 12 }}>
            {mode === "qa"
              ? "Q&A mode: answers are based on your report."
              : "Tip: You can use Back/Clear if you made a mistake."}
          </div>
        </div>
      </div>
    </Layout>
  );
}

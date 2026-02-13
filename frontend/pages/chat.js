
import React, { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import Layout from "../components/Layout";
import { ALL_TAGS } from "../components/tags";
import { extractTagsFromText } from "../components/tag_extractor";

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
  // Robust budget parsing.
  // Supports:
  //  - "2500-3600", "2500 to 3600", "2 500 - 3 600"
  //  - "2.5k-3.6k", "700k - 1.2m", "700k-1.2mln", "€700k to €1,2 mln"
  const raw = String(text || "")
    .toLowerCase()
    .replace(/€/g, "")
    .replace(/eur/g, "")
    .replace(/\s+/g, " ")
    .trim();

  // Normalize separators: "1,2" -> "1.2" (decimals) and "1 200 000" -> "1200000"
  const norm = raw
    .replace(/(\d),(\d)/g, "$1.$2")
    .replace(/(?<=\d)\s+(?=\d{3}\b)/g, "") // remove thousand spaces
    .trim();

  const parseToken = (tok) => {
    if (!tok) return null;
    let t = tok.trim();
    // token pattern: number + optional suffix
    const m = t.match(/^(\d+(?:\.\d+)?)(k|m|mln|million)?$/);
    if (!m) return null;
    const num = parseFloat(m[1]);
    if (Number.isNaN(num)) return null;
    const suf = m[2] || "";
    let mul = 1;
    if (suf === "k") mul = 1000;
    if (suf === "m" || suf === "mln" || suf === "million") mul = 1000000;
    return Math.round(num * mul);
  };

  // Extract tokens like: 2500, 3.6k, 1.2m, 1.2mln
  const tokens = norm.match(/\d+(?:\.\d+)?(?:mln|million|k|m)?/g) || [];
  if (tokens.length < 2) return { min: null, max: null };

  // Heuristic: take the first 2 "value" tokens that successfully parse.
  // (This avoids the classic "1.2mln" -> ["1", "2", "mln"] bug.)
  const vals = [];
  for (const tok of tokens) {
    const v = parseToken(tok);
    if (v != null) vals.push(v);
    if (vals.length >= 2) break;
  }
  if (vals.length < 2) return { min: null, max: null };

  let [a, b] = vals;
  if (b < a) [a, b] = [b, a];
  return { min: a, max: b };
}

function budgetExamples(mode) {
  if (mode === "rent") {
    return "Examples:\n- 2000-3000\n- 2.5k to 3.6k\n(monthly rent)";
  }
  return "Examples:\n- 500k-800k\n- 700k to 1.2m\n(purchase budget)";
}

function formatBudget(min, max, mode) {
  if (min == null || max == null) return "—";
  const fmt = (v) => {
    if (mode === "buy" && v >= 1000000) {
      return `${(v / 1000000).toFixed(v % 1000000 === 0 ? 0 : 1)}m`;
    }
    if (mode === "buy" && v >= 1000) {
      return `${Math.round(v / 1000)}k`;
    }
    return String(v);
  };
  return `${fmt(min)}–${fmt(max)}`;
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
  const [step, setStep] = useState("city"); // city -> household -> kids? -> housing -> bedrooms -> propertyType -> budget -> priorities_freeform -> priorities_confirm -> priorities_edit -> work -> workDetails? -> school -> schoolDetails? -> generate -> clarify -> qa
  const [mode, setMode] = useState("onboarding"); // onboarding | clarify | qa
  const [tagTop, setTagTop] = useState([]); // top3 storage
  const [priorityDraft, setPriorityDraft] = useState({ top3: [], also: [], selected: [] });
  const [editSelected, setEditSelected] = useState([]);

  const [briefId, setBriefId] = useState("");
  const [clarifying, setClarifying] = useState([]);
  const [clarAnswers, setClarAnswers] = useState({});

  // QA controls
  const [qaMode, setQaMode] = useState("report_only"); // report_only | verified

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

  
  function applyPrioritiesFromSelection(selected, top3) {
    const sel = (selected || []).slice(0, 7);
    const top = (top3 || []).slice(0, 3);

    const finalTop = top.length ? top : sel.slice(0, 3);
    const rest = sel.filter((id) => !finalTop.includes(id));
    return [...finalTop, ...rest].slice(0, 7);
  }

  function confirmPriorityProposal() {
    snapshot();
    const priorities = applyPrioritiesFromSelection(priorityDraft.selected, priorityDraft.top3);
    setState((s) => ({ ...s, priorities }));
    askNext("work", "Do you want to optimize for commute to work? (yes/no)");
  }

  function openPriorityEditor() {
    snapshot();
    setEditSelected(priorityDraft.selected || []);
    setTagTop(priorityDraft.top3 || []);
    setStep("priorities_edit");
    push("assistant", "Sure — adjust your priorities below, then press “Confirm priorities”.");
  }

  function toggleEditSelected(id) {
    setEditSelected((prev) => {
      const exists = prev.includes(id);
      let next = exists ? prev.filter((x) => x !== id) : [...prev, id];
      if (next.length > 7) next = next.slice(0, 7);
      // keep top3 consistent
      setTagTop((tprev) => tprev.filter((x) => next.includes(x)).slice(0, 3));
      return next;
    });
  }

  function toggleTop3(id) {
    setTagTop((prev) => {
      const exists = prev.includes(id);
      if (exists) return prev.filter((x) => x !== id);
      if (prev.length >= 3) return prev; // limit
      return [...prev, id];
    });
  }

  function confirmEditedPriorities() {
    snapshot();
    const priorities = applyPrioritiesFromSelection(editSelected, tagTop);
    setState((s) => ({ ...s, priorities }));
    askNext("work", "Do you want to optimize for commute to work? (yes/no)");
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

  async function callQA(brief_id, question, modeOverride) {
    const res = await fetch(`${API}/brief/qa`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brief_id, question, mode: modeOverride || qaMode }),
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
          // If verified fails (missing key / blocked domains), suggest fallback.
          const msg = String(e.message || "");
          if (qaMode === "verified") {
            push(
              "assistant",
              `Verified lookup failed: ${msg}. You can switch Verified off to answer strictly from the report.`
            );
          } else {
            push("assistant", `Q&A failed: ${msg}`);
          }
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
        `What is your budget range?\n\n${budgetExamples(state.mode)}\n\nTip: You can type formats like “700k-1.2m” or “2.5k-3.6k”.`
      );
      return;
    }

    if (step === "budget") {
      const { min, max } = parseRange(text);
      if (min == null || max == null) {
        push(
          "assistant",
          'Please give a range with two values, e.g., "2000-3000", "2.5k-3.6k" (rent) or "700k-1.2m" (buy).'
        );
        return;
      }
      snapshot();
      setState((s) => ({ ...s, budgetMin: min, budgetMax: max }));
      setTagTop([]);
      setPriorityDraft({ top3: [], also: [], selected: [] });
      setEditSelected([]);
      askNext(
        "priorities_freeform",
        `Now describe in your own words what matters most.

Examples:
- “Green and quiet, family-friendly, good schools, but still close to the center.”
- “Vibrant cafés and culture, international vibe, easy commute to EU Quarter.”`
      );
      return;
    }

    if (step === "priorities_freeform") {
      // Convert user freeform text into tags
      snapshot();
      const res = extractTagsFromText(text, ALL_TAGS);
      const selected = [...res.top3, ...res.also].slice(0, 7);

      if (!selected.length) {
        push(
          "assistant",
          "I couldn't confidently map that to our priorities. No worries — please pick from the list below."
        );
        setPriorityDraft({ top3: [], also: [], selected: [] });
        setEditSelected([]);
        setTagTop([]);
        setStep("priorities_edit");
        return;
      }

      setPriorityDraft({ top3: res.top3, also: res.also, selected });
      setEditSelected(selected);
      setTagTop(res.top3);

      const topLabels = res.top3.map((id) => ALL_TAGS.find((t) => t.id === id)?.title || id);
      const alsoLabels = res.also.map((id) => ALL_TAGS.find((t) => t.id === id)?.title || id);

      let msg = `I understood your priorities like this:\n\nTop priorities: ${topLabels.join(
        ", "
      )}`;
      if (alsoLabels.length) msg += `\nAlso: ${alsoLabels.join(", ")}`;
      msg += `\n\nConfirm? (Yes / Edit)`;

      askNext("priorities_confirm", msg);
      return;
    }

    if (step === "priorities_confirm") {
      const low = text.toLowerCase().trim();
      if (low.startsWith("y")) {
        snapshot();
        const selected = (priorityDraft.selected || []).slice(0, 7);
        const top3 = (priorityDraft.top3 || []).slice(0, 3);
        const finalTop = top3.length ? top3 : selected.slice(0, 3);
        const rest = selected.filter((id) => !finalTop.includes(id));
        const priorities = [...finalTop, ...rest].slice(0, 7);

        setState((s) => ({ ...s, priorities }));
        askNext("work", "Do you want to optimize for commute to work? (yes/no)");
        return;
      }
      if (low.startsWith("e")) {
        snapshot();
        setEditSelected(priorityDraft.selected || []);
        setTagTop(priorityDraft.top3 || []);
        setStep("priorities_edit");
        push(
          "assistant",
          "Sure — adjust your priorities below, then press “Confirm priorities”."
        );
        return;
      }
      push('assistant', 'Please reply "Yes" to confirm or "Edit" to adjust.');
      return;
    }

    if (step === "priorities_edit") {
      // In edit step we rely on UI controls. As a fallback, user can type:
      // - "confirm" to apply current selection
      // - "skip" to proceed with current selection (or empty)
      const low = text.toLowerCase().trim();
      if (low.includes("confirm") || low.includes("done") || low.startsWith("ok")) {
        // apply selection
        snapshot();
        const selected = (editSelected || []).slice(0, 7);
        const top3 = (tagTop || []).slice(0, 3);
        const finalTop = top3.length ? top3 : selected.slice(0, 3);
        const rest = selected.filter((id) => !finalTop.includes(id));
        const priorities = [...finalTop, ...rest].slice(0, 7);
        setState((s) => ({ ...s, priorities }));
        askNext("work", "Do you want to optimize for commute to work? (yes/no)");
        return;
      }
      if (low === "skip") {
        snapshot();
        const selected = (editSelected || []).slice(0, 7);
        const top3 = (tagTop || []).slice(0, 3);
        const finalTop = top3.length ? top3 : selected.slice(0, 3);
        const rest = selected.filter((id) => !finalTop.includes(id));
        const priorities = [...finalTop, ...rest].slice(0, 7);
        setState((s) => ({ ...s, priorities }));
        askNext("work", "Do you want to optimize for commute to work? (yes/no)");
        return;
      }
      push(
        "assistant",
        'Use the checklist to edit priorities, then click “Confirm priorities”. (Or type "confirm".)'
      );
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

          {step === "priorities_confirm" && (
            <div style={{ marginTop: 12, display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button className="btn" type="button" disabled={busy} onClick={confirmPriorityProposal}>
                Yes, looks right
              </button>
              <button className="btn" type="button" disabled={busy} onClick={openPriorityEditor}>
                Edit priorities
              </button>
            </div>
          )}

          {step === "priorities_edit" && (
            <div
              style={{
                marginTop: 12,
                padding: 12,
                borderRadius: 16,
                border: "1px solid var(--stroke)",
                background: "rgba(255,255,255,0.04)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                <div style={{ fontWeight: 700 }}>
                  Edit priorities (selected {editSelected.length}/7 · top {tagTop.length}/3)
                </div>
                <button
                  className="btn"
                  type="button"
                  disabled={busy || editSelected.length === 0}
                  onClick={confirmEditedPriorities}
                >
                  Confirm priorities
                </button>
              </div>

              <div style={{ marginTop: 10, maxHeight: 220, overflowY: "auto", paddingRight: 6 }}>
                {ALL_TAGS.map((t) => {
                  const checked = editSelected.includes(t.id);
                  const isTop = tagTop.includes(t.id);
                  return (
                    <div
                      key={t.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 12,
                        padding: "6px 4px",
                        borderBottom: "1px solid rgba(255,255,255,0.06)",
                      }}
                    >
                      <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleEditSelected(t.id)}
                          disabled={busy}
                        />
                        <span>{t.title}</span>
                      </label>

                      <button
                        type="button"
                        className="btn"
                        style={{
                          padding: "6px 10px",
                          opacity: checked ? 1 : 0.4,
                          pointerEvents: checked ? "auto" : "none",
                        }}
                        onClick={() => toggleTop3(t.id)}
                        disabled={busy || !checked}
                        title="Mark/unmark as Top-3"
                      >
                        {isTop ? "Top ✓" : "Make Top"}
                      </button>
                    </div>
                  );
                })}
              </div>

              <div style={{ marginTop: 10, color: "var(--muted)", fontSize: 12 }}>
                Tip: Select up to 7 priorities. Mark up to 3 as “Top”. If you don’t mark Top, we’ll use the first selected.
              </div>
            </div>
          )}

          {mode === "qa" && briefId && (
            <div style={{ marginTop: 10 }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                {[
                  "Why is the #1 commune first?",
                  "Compare #1 vs #2 communes",
                  "Why not Uccle for my case?",
                  "Summarize my top communes in 3 bullets",
                  "What should I watch out for when viewing apartments?",
                ].map((q) => (
                  <button
                    key={q}
                    type="button"
                    className="btn"
                    style={{ padding: "6px 10px", fontSize: 12, opacity: busy ? 0.6 : 1 }}
                    disabled={busy}
                    onClick={() => {
                      setInput(q);
                      setTimeout(() => onSend(), 0);
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>

              <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 10 }}>
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={qaMode === "verified"}
                    onChange={(e) => setQaMode(e.target.checked ? "verified" : "report_only")}
                    disabled={busy}
                  />
                  <span>
                    <b>Verified</b> (official sources)
                  </span>
                </label>
                <span style={{ color: "var(--muted)", fontSize: 12 }}>
                  {qaMode === "verified"
                    ? "Uses an allowlist of official domains and returns citations."
                    : "Answers strictly from your report."}
                </span>
              </div>
            </div>
          )}

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
              <b>Current inputs:</b> {state.city || "—"} · {state.mode} · budget {formatBudget(state.budgetMin, state.budgetMax, state.mode)}{state.mode === "rent" ? " €/mo" : ""} ·
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

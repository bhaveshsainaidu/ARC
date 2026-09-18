import json
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock

import numpy as np


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR            = get_base_dir()
MEMORY_PATH         = BASE_DIR / "memory" / "long_term.json"
SEMANTIC_PATH       = BASE_DIR / "memory" / "semantic_store.json"
SEMANTIC_STORE_PATH = SEMANTIC_PATH
EPISODES_PATH       = BASE_DIR / "memory" / "episodes.json"
PENDING_TASKS_PATH  = BASE_DIR / "memory" / "pending_tasks.json"
_lock               = Lock()
_episodes_lock      = Lock()
_tasks_lock         = Lock()
MAX_VALUE_LENGTH    = 380

# ── Why there are two very different numbers here ────────────────────────────
#
# There used to be one: MEMORY_MAX_CHARS = 2200, applied to the whole store. It
# was a *storage* limit, and it existed only because the entire memory was
# pasted into the system prompt on every connect — so growing the memory grew
# every single request. When it filled, _trim_to_limit() deleted the oldest
# entries and printed one line to a console nobody reads. A memory described as
# "deeply remembers projects, preferences and personal context" was in practice
# two pages long, and quietly forgot your sister's name after a few weeks.
#
# Storage and prompt budget are now separate concerns:
#
#   MEMORY_MAX_CHARS  — a runaway guard, not a feature limit. Nothing normal
#                       reaches it; a bug writing in a loop does.
#   PROMPT_CORE_CHARS — what actually rides in the system prompt every session.
#                       Smaller than the old whole-memory dump, so sessions
#                       start *faster* than before, not slower.
#
# Everything above the core stays on disk and is fetched on demand by the
# recall_memory tool — see search_memory() and format_memory_for_prompt().
MEMORY_MAX_CHARS  = 200_000
PROMPT_CORE_CHARS = 900
PROMPT_INDEX_CHARS = 420
# Most entries any one category may contribute to the core block, so a person
# with forty stored preferences still gets their sister into the prompt.
PROMPT_MAX_PER_CATEGORY = 6

def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }

def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()
    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data:
                        data[key] = {}
                return data
            return _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()

def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


# Set by main.py so a trim can reach the activity log. Deleting something a
# person told you and mentioning it only on stdout is how a memory loses trust.
_trim_notifier = None


def set_trim_notifier(fn) -> None:
    """Register a callable(str) that surfaces trims to the user."""
    global _trim_notifier
    _trim_notifier = fn


def _trim_to_limit(memory: dict) -> dict:
    if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
        return memory
    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))
    dropped = []
    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        dropped.append(f"{cat}/{key}")
        print(f"[Memory] 🗑️  Trimmed {cat}/{key}")
    if dropped and _trim_notifier:
        try:
            _trim_notifier(
                f"SYS: Memory full — forgot {len(dropped)} oldest entries "
                f"({', '.join(dropped[:3])}{'…' if len(dropped) > 3 else ''})"
            )
        except Exception:
            pass
    return memory

def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    memory = _trim_to_limit(memory)
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            new_val  = _truncate_value(str(value["value"] if isinstance(value, dict) else value))
            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True
    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return memory

def _entry_value(entry) -> str:
    """Accept both the {'value': ..., 'updated': ...} shape and a bare string,
    because early versions of the store wrote plain strings."""
    if isinstance(entry, dict):
        return str(entry.get("value", "") or "").strip()
    return str(entry or "").strip()


def _pretty(key: str) -> str:
    return key.replace("_", " ").strip()


# Identity is always in the prompt; these categories compete for the remaining
# budget by recency.
_CATEGORY_LABELS = {
    "preferences":   "Preferences",
    "projects":      "Active projects / goals",
    "relationships": "People in their life",
    "wishes":        "Wishes / plans",
    "notes":         "Notes",
}

_IDENTITY_FIELDS = ["name", "age", "birthday", "city", "job",
                    "language", "school", "nationality"]


def format_memory_for_prompt(memory: dict | None) -> str:
    """Build the memory block that goes into the system prompt.

    This used to dump everything. It now sends three things:

      1. IDENTITY  - always, in full. It is small, and it is wrong for the
         assistant to have to look up your name.
      2. RECENT    - the most recently updated entries from every other
         category, up to PROMPT_CORE_CHARS. Recency is the cheapest useful
         relevance signal available without embeddings.
      3. AN INDEX  - the *keys* of everything else, values omitted.

    Point 3 is what makes recall work at all. A model cannot decide to look
    something up if it does not know the thing exists: with only points 1 and 2,
    "who is Ayse?" would get "I don't know" while ayse_sister sat on disk
    unread. The index costs a few hundred characters and turns recall from a
    gamble into a lookup.

    Net effect on latency: this block is SMALLER than the old full dump, so
    every session connects with fewer tokens. Occasionally the model spends one
    extra round trip on recall_memory - covered by the acknowledgment it
    already speaks before any slow step."""
    if not memory:
        return ""

    core_lines: list[str] = []

    # 1. Identity - always, in full
    identity = memory.get("identity", {}) or {}
    for field in _IDENTITY_FIELDS:
        val = _entry_value(identity.get(field))
        if not val:
            continue
        if field == "language":
            # Labelled as an observation, not a setting. A bare "Language:
            # English" line written months ago reads like a standing order and
            # was one of the reasons a Turkish question came back in English.
            core_lines.append(
                f"Has spoken to you in: {val} (an observation about the past — "
                f"always answer in the language of their CURRENT message)")
        else:
            core_lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in _IDENTITY_FIELDS:
            continue
        val = _entry_value(entry)
        if val:
            core_lines.append(f"{_pretty(key).title()}: {val}")

    # 2. Everything else, most recently updated first
    rest: list[tuple[str, str, str, str]] = []   # (updated, cat, key, value)
    for cat in _CATEGORY_LABELS:
        for key, entry in (memory.get(cat, {}) or {}).items():
            val = _entry_value(entry)
            if not val:
                continue
            updated = (entry.get("updated", "") if isinstance(entry, dict) else "") or "0000-00-00"
            rest.append((updated, cat, key, val))
    rest.sort(key=lambda t: t[0], reverse=True)

    used    = sum(len(l) + 1 for l in core_lines)
    shown: dict[str, list[str]] = {}
    overflow: dict[str, list[str]] = {}

    # Recency decides order, but no single category may take the whole budget.
    # Without the cap, someone with forty stored preferences gets a prompt that
    # is forty preferences and not one person's name — the categories that
    # matter most in conversation are also the ones that change least often, so
    # pure recency systematically buries them.
    per_cat_used: dict[str, int] = {}
    for _updated, cat, key, val in rest:
        line = f"  - {_pretty(key).title()}: {val}"
        if (per_cat_used.get(cat, 0) < PROMPT_MAX_PER_CATEGORY
                and used + len(line) + 1 <= PROMPT_CORE_CHARS):
            shown.setdefault(cat, []).append(line)
            per_cat_used[cat] = per_cat_used.get(cat, 0) + 1
            used += len(line) + 1
        else:
            overflow.setdefault(cat, []).append(_pretty(key))

    # The index is a table of contents, so it is interleaved across categories
    # rather than continuing in recency order. Sorted by recency it would list
    # twenty-four preferences before the first relationship, and the one entry
    # the index exists for — the old fact the model has no other way to know
    # about — would fall off the end.
    indexed: list[str] = []
    if overflow:
        cats  = [c for c in _CATEGORY_LABELS if overflow.get(c)]
        cursor = {c: 0 for c in cats}
        while cats:
            for cat in list(cats):
                i = cursor[cat]
                if i >= len(overflow[cat]):
                    cats.remove(cat)
                    continue
                indexed.append(overflow[cat][i])
                cursor[cat] = i + 1

    for cat, label in _CATEGORY_LABELS.items():
        if shown.get(cat):
            core_lines.append("")
            core_lines.append(f"{label}:")
            core_lines.extend(shown[cat])

    if not core_lines and not indexed:
        return ""

    out = [
        "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]",
        *core_lines,
    ]

    # 3. The index of what is on disk but not in this prompt
    if indexed:
        budget, names = PROMPT_INDEX_CHARS, []
        for n in indexed:
            if budget - len(n) - 2 < 0:
                break
            names.append(n)
            budget -= len(n) + 2
        if names:
            out.append("")
            out.append(
                "[ALSO REMEMBERED — values not shown here. Call recall_memory "
                "with a keyword to read any of these before saying you do not know]"
            )
            out.append(", ".join(names)
                       + (f" (+{len(indexed) - len(names)} more)"
                          if len(indexed) > len(names) else ""))

    # 4. Top active learned rules & user corrections
    try:
        learned = _get_active_top_semantic_memories(limit=4)
        if learned:
            out.append("")
            out.append(
                "[LEARNED RULES & USER PREFERENCES — adhere strictly to these over defaults]"
            )
            for lm in learned:
                c = _pretty(lm.get("concept", "")).title()
                out.append(f"  - {c}: {lm.get('lesson', '')}")
    except Exception:
        pass

    return "\n".join(out) + "\n"


# ── Recall ────────────────────────────────────────────────────────────────────

def _score(query_words: list[str], cat: str, key: str, value: str) -> int:
    """Cheap lexical relevance. No embeddings, no network, no model call - this
    runs in well under a millisecond, which is the entire point: recall must
    cost one model round trip, never two."""
    hay_key = _pretty(key).lower()
    hay_val = value.lower()
    score   = 0
    for w in query_words:
        if not w:
            continue
        if w == hay_key:
            score += 10
        elif w in hay_key:
            score += 6
        if w in hay_val:
            score += 3
        if w in cat:
            score += 1
    return score


def search_memory(query: str, limit: int = 8) -> str:
    """Find stored facts matching `query`. Backs the recall_memory tool.

    An empty query is treated as "show me everything you know", capped - the
    model asks that when the user says "what do you remember about me?"."""
    memory = load_memory()
    words  = [w for w in re.split(r"[^\w]+", (query or "").lower()) if len(w) > 1]

    rows: list[tuple[int, str, str, str]] = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue                     # skip 'sessions', which is a list
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            s = _score(words, cat, key, val) if words else 1
            if s > 0:
                rows.append((s, cat, key, val))

    sem_matches: list[dict] = []
    try:
        if query:
            sem_matches = retrieve_semantic_memories(query, top_k=max(2, limit // 2), threshold=0.30)
        else:
            store = load_semantic_store()
            sem_matches = [m for m in store.get("memories", []) if m.get("active", True)][:max(2, limit // 2)]
    except Exception:
        pass

    if not rows and not sem_matches:
        return (f"Nothing stored about '{query}'." if query
                else "I have not stored anything about this person yet.")

    rows.sort(key=lambda r: (-r[0], r[2]))
    lines = [f"{cat}/{_pretty(key)}: {val}" for _s, cat, key, val in rows[:max(1, limit)]]
    for sm in sem_matches:
        c = sm.get("concept", "rule")
        lines.append(f"learned/{c}: {sm.get('lesson', '')}")

    head  = (f"Stored facts matching '{query}':" if query
             else "Everything currently stored:")
    more  = (f"\n(+{len(rows) + len(sem_matches) - len(lines)} more — search with a narrower keyword)"
             if len(rows) + len(sem_matches) > len(lines) else "")
    return head + "\n" + "\n".join(lines) + more


def all_entries_for_ui() -> list[dict]:
    """Flat list for the memory panel: what ARC knows, and when it learned it.
    Sorted newest first so the panel opens on what changed most recently."""
    memory = load_memory()
    rows = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            rows.append({
                "category": cat,
                "key":      key,
                "value":    val,
                "updated":  (entry.get("updated", "") if isinstance(entry, dict) else ""),
            })

    try:
        sem_store = load_semantic_store()
        for mem in sem_store.get("memories", []):
            if not mem.get("active", True):
                continue
            m_type = mem.get("type", "lesson")
            rows.append({
                "category": f"learned ({m_type})",
                "key":      mem.get("concept", mem.get("id", "item")),
                "value":    mem.get("lesson", ""),
                "updated":  (mem.get("timestamp") or "")[:10],
            })
    except Exception:
        pass

    rows.sort(key=lambda r: (r["updated"] or "0000-00-00"), reverse=True)
    return rows

def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    if category and category.startswith("learned"):
        deactivated = deactivate_semantic_memory(key)
        if deactivated:
            return f"Forgotten learned memory: {key}"
        return f"Not found: {category}/{key}"

    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget


# ── Session memory ─────────────────────────────────────────────────────────────

_SESSION_MAX = 3   # safety cap — in practice 0-1 entries after pop


def save_session_summary(summary: str, language: str = "") -> None:
    """Append a 1-2 sentence session summary to long_term.json['sessions']."""
    summary = (summary or "").strip()
    if not summary:
        return
    memory   = load_memory()
    sessions = memory.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    entry: dict = {
        "date":    datetime.now().strftime("%Y-%m-%d"),
        "summary": summary[:280],
    }
    if language:
        entry["language"] = language
    sessions.append(entry)
    memory["sessions"] = sessions[-_SESSION_MAX:]
    with _lock:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(f"[Memory] 📝 Session saved ({entry['date']}): {summary[:60]}…")


def pop_last_session() -> dict | None:
    """
    Return AND remove the most recent session entry.
    Calling this consumes the entry so it is never repeated in future briefings.
    """
    with _lock:
        if not MEMORY_PATH.exists():
            return None
        try:
            memory   = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            sessions = memory.get("sessions", [])
            if not isinstance(sessions, list) or not sessions:
                return None
            entry = sessions.pop()          # remove the last entry
            memory["sessions"] = sessions
            MEMORY_PATH.write_text(
                json.dumps(memory, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return entry
        except Exception as e:
            print(f"[Memory] ⚠️ pop_last_session error: {e}")
            return None


# ==============================================================================
# ── Semantic & Persistent Learning Engine (Feature 2) ─────────────────────────
# ==============================================================================

_semantic_lock = Lock()

# Cross-language / cross-domain concept expansions
CONCEPT_EXPANSIONS = {
    "null": ["none", "nil", "undefined", "empty", "nullpointerexception", "attributeerror", "optional", "pointer", "npe"],
    "none": ["null", "nil", "undefined", "empty", "attributeerror", "nullpointerexception", "optional"],
    "python": ["java", "javascript", "typescript", "c++", "rust", "go", "py", "pep8"],
    "java": ["python", "javascript", "typescript", "c++", "c#", "kotlin", "jvm", "nullpointerexception"],
    "javascript": ["typescript", "python", "java", "node", "js", "ts", "undefined"],
    "typescript": ["javascript", "python", "java", "node", "types"],
    "indent": ["spaces", "tabs", "indentation", "pep8", "formatting", "style"],
    "tab": ["indent", "tabs", "spaces", "indentation", "formatting"],
    "spaces": ["indent", "tabs", "tab", "indentation", "formatting"],
    "error": ["exception", "bug", "crash", "traceback", "fail", "failure", "handling", "defensive"],
    "exception": ["error", "crash", "bug", "traceback", "throw", "catch", "defensive"],
    "screen": ["mirror", "display", "stream", "monitor", "cast", "phone", "websocket"],
    "mirror": ["screen", "display", "stream", "cast", "phone", "websocket"],
    "sir": ["greeting", "address", "user", "respect", "title", "polite"],
    "greeting": ["sir", "address", "hello", "morning", "evening", "welcome"],
}

FEEDBACK_PATTERNS = [
    (r"(?:that'?s|that is|it'?s|it is)\s+wrong[,.\s]*(.*)", "correction", 10),
    (r"(?:no|nope)[,.\s]+(?:it should be|use|always|don'?t|never)\s*(.*)", "correction", 10),
    (r"(?:don'?t|do not|stop)\s+(?:do(?:ing)? that|use|using)\s*[,.\s]*(.*)", "correction", 10),
    (r"never\s+(?:do that|use|say)\s*[,.\s]*(.*)", "correction", 10),
    (r"from now on[,.\s]+(.*)", "lesson", 9),
    (r"(?:always\s+remember\s+to|remember\s+to\s+always)\s+(.*)", "lesson", 9),
    (r"(?:you\s+should\s+always|always\s+make\s+sure\s+to)\s+(.*)", "lesson", 9),
    (r"i\s+prefer\s+(?:that|to|you\s+to)?\s*(.*)", "preference", 8),
    (r"i\s+like\s+(?:to|it\s+when)?\s*(.*)", "preference", 8),
    (r"instead of\s+([^,]+)[,.\s]+(?:always\s+)?(?:use|do)\s+(.*)", "correction", 10),
]


def _empty_semantic_store() -> dict:
    return {
        "version": 1,
        "last_updated": datetime.now().isoformat(),
        "memories": [],
    }


def load_semantic_store() -> dict:
    """Load semantic memories from disk."""
    if not SEMANTIC_PATH.exists():
        return _empty_semantic_store()
    with _semantic_lock:
        try:
            data = json.loads(SEMANTIC_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "memories" in data:
                return data
            return _empty_semantic_store()
        except Exception as e:
            print(f"[SemanticMemory] ⚠️ Load error: {e}")
            return _empty_semantic_store()


def save_semantic_store(store: dict) -> None:
    """Persist semantic memories to disk."""
    if not isinstance(store, dict):
        return
    store["last_updated"] = datetime.now().isoformat()
    SEMANTIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _semantic_lock:
        SEMANTIC_PATH.write_text(
            json.dumps(store, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "_", slug).strip("_")


def _extract_tags(text: str) -> list[str]:
    words = re.findall(r"\w+", text.lower())
    stopwords = {
        "the", "a", "an", "is", "in", "to", "for", "with", "and", "or",
        "of", "it", "on", "at", "by", "from", "be", "as", "do", "you",
        "my", "your", "that", "this", "should", "always", "never", "use",
    }
    seen = set()
    tags = []
    for w in words:
        if len(w) > 2 and w not in stopwords and w not in seen:
            seen.add(w)
            tags.append(w)
    return tags[:12]


def _parse_iso(iso_str: str) -> datetime | None:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str)
    except Exception:
        try:
            return datetime.strptime(iso_str[:10], "%Y-%m-%d")
        except Exception:
            return None


class SemanticMemoryEngine:
    """
    Dual-engine persistent semantic memory retriever and learner.
    - Primary: SentenceTransformers ('all-MiniLM-L6-v2') 384-dim dense vectors.
    - Fallback: Pure-Python / NumPy TF-IDF & BM25 conceptual vector engine.
    - 100% local, offline, private, zero external API calls.
    """

    def __init__(self):
        self._model = None
        self._model_failed = False
        self._cache: dict[str, np.ndarray] = {}  # mem_id -> vector
        self._cache_lock = Lock()

    def _get_model(self):
        if self._model is not None:
            return self._model
        if self._model_failed:
            return None
        try:
            from sentence_transformers import SentenceTransformer
            try:
                from core.gpu_accelerator import GPUAccelerator
                device = GPUAccelerator.get_optimal_torch_device()
                self._model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
            except Exception:
                self._model = SentenceTransformer("all-MiniLM-L6-v2")
            return self._model
        except Exception as e:
            print(f"[SemanticMemory] ⚠️ SentenceTransformer load fallback: {e}")
            self._model_failed = True
            return None

    def _encode(self, text: str) -> np.ndarray | None:
        model = self._get_model()
        if model is None:
            return None
        try:
            return model.encode(text, normalize_embeddings=True)
        except Exception as e:
            print(f"[SemanticMemory] ⚠️ Encode error: {e}")
            return None

    def _get_or_compute_embedding(self, mem: dict) -> np.ndarray | None:
        mem_id = mem.get("id", "")
        with self._cache_lock:
            if mem_id in self._cache:
                return self._cache[mem_id]

        rep = f"{mem.get('concept', '')}: {mem.get('lesson', '')} {' '.join(mem.get('tags', []))} {mem.get('context', '')}"
        vec = self._encode(rep)
        if vec is not None:
            with self._cache_lock:
                self._cache[mem_id] = vec
        return vec

    def _fallback_score(self, query: str, mem: dict) -> float:
        q_words = set(re.findall(r"\w+", query.lower()))
        q_words = {w for w in q_words if len(w) > 1}
        if not q_words:
            return 0.0

        expanded = set(q_words)
        for w in q_words:
            if w in CONCEPT_EXPANSIONS:
                expanded.update(CONCEPT_EXPANSIONS[w])

        mem_tags = set(mem.get("tags", []))
        concept_words = set(re.findall(r"\w+", mem.get("concept", "").lower()))
        lesson_words = set(re.findall(r"\w+", mem.get("lesson", "").lower()))

        score = 0.0
        score += len(expanded.intersection(mem_tags)) * 0.35
        score += len(expanded.intersection(concept_words)) * 0.40
        score += len(expanded.intersection(lesson_words)) * 0.15

        p = mem.get("priority", 5)
        score = score * (1.0 + (p / 20.0))
        return min(1.0, score)

    def apply_memory_expiry(
        self,
        idle_days_halve: int = 90,
        prune_age_days: int = 180,
        prune_priority_threshold: float = 1.0,
    ) -> dict:
        store = load_semantic_store()
        memories = store.get("memories", [])
        now = datetime.now()
        halved_count = 0
        pruned_count = 0

        for m in memories:
            if not m.get("active", True):
                continue

            last_acc_dt = _parse_iso(m.get("last_accessed") or m.get("timestamp", ""))
            if last_acc_dt:
                idle_days = (now - last_acc_dt).days
                if idle_days >= idle_days_halve:
                    cur_p = m.get("priority", 5)
                    new_p = max(0.5, round(cur_p / 2.0, 1))
                    if new_p != cur_p:
                        m["priority"] = new_p
                        halved_count += 1

            created_dt = _parse_iso(m.get("timestamp", ""))
            if created_dt:
                age_days = (now - created_dt).days
                if m.get("priority", 5) <= prune_priority_threshold and age_days > prune_age_days:
                    m["active"] = False
                    pruned_count += 1

        store["last_cleanup"] = now.isoformat()
        save_semantic_store(store)
        print(f"[SemanticMemory] [Expiry] Applied: {halved_count} memories halved, {pruned_count} pruned")
        return {"halved": halved_count, "pruned": pruned_count}

    def _check_weekly_cleanup(self) -> None:
        store = load_semantic_store()
        last_clean_str = store.get("last_cleanup")
        if not last_clean_str:
            self.apply_memory_expiry()
            return
        last_dt = _parse_iso(last_clean_str)
        if last_dt and (datetime.now() - last_dt).days >= 7:
            self.apply_memory_expiry()

    def retrieve(self, query: str, top_k: int = 4, threshold: float = 0.25) -> list[dict]:
        try:
            self._check_weekly_cleanup()
        except Exception:
            pass
        store = load_semantic_store()
        memories = [m for m in store.get("memories", []) if m.get("active", True)]
        if not memories or not query.strip():
            return []

        q_vec = self._encode(query)
        scored: list[tuple[float, dict]] = []

        for m in memories:
            if q_vec is not None:
                m_vec = self._get_or_compute_embedding(m)
                if m_vec is not None:
                    raw_sim = float(np.dot(q_vec, m_vec))
                    if raw_sim < 0.32:
                        continue
                    p = m.get("priority", 5)
                    final_score = raw_sim * (1.0 + (p / 20.0))
                    q_lower = query.lower()
                    if any(t in q_lower for t in m.get("tags", [])):
                        final_score += 0.15
                    if final_score >= threshold:
                        scored.append((final_score, m))
                    continue

            fb = self._fallback_score(query, m)
            if fb >= threshold:
                scored.append((fb, m))

        scored.sort(key=lambda item: item[0], reverse=True)
        results = [m for _, m in scored[:top_k]]
        if results:
            now_iso = datetime.now().isoformat()
            for m in results:
                m["last_accessed"] = now_iso
            try:
                save_semantic_store(store)
            except Exception:
                pass
        return results

    def add_memory(
        self,
        lesson: str,
        concept: str = "",
        mem_type: str = "lesson",
        source: str = "user_correction",
        priority: int = 10,
        tags: list[str] | None = None,
        context: str = "",
        supersede_threshold: float = 0.65,
    ) -> dict:
        lesson = lesson.strip()
        if not lesson:
            return {}

        store = load_semantic_store()
        memories = store.get("memories", [])

        new_id = f"mem_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        concept_slug = concept.strip() if concept.strip() else _slugify(lesson[:35])
        extracted_tags = tags or _extract_tags(lesson + " " + concept_slug)

        now_iso = datetime.now().isoformat()
        new_entry = {
            "id": new_id,
            "concept": concept_slug,
            "lesson": lesson,
            "type": mem_type,
            "source": source,
            "priority": int(priority),
            "tags": extracted_tags,
            "timestamp": now_iso,
            "last_accessed": now_iso,
            "active": True,
            "superseded_by": None,
            "context": context or "Learned from user interaction",
        }

        new_vec = self._encode(f"{new_entry['concept']}: {new_entry['lesson']}")

        # Conflict resolution / Superseding
        for m in memories:
            if not m.get("active", True):
                continue

            concept_match = (
                concept_slug.lower().replace("_", "") == m.get("concept", "").lower().replace("_", "")
            )
            sim_match = False
            if new_vec is not None:
                m_vec = self._get_or_compute_embedding(m)
                if m_vec is not None:
                    sim = float(np.dot(new_vec, m_vec))
                    if sim >= supersede_threshold:
                        sim_match = True

            if concept_match or sim_match:
                if new_entry["priority"] >= m.get("priority", 5):
                    m["active"] = False
                    m["superseded_by"] = new_id
                    print(f"[SemanticMemory] 🔄 Superseded conflicting memory '{m.get('id')}' ({m.get('concept')}) with '{new_id}'")

        memories.append(new_entry)
        store["memories"] = memories
        save_semantic_store(store)

        if new_vec is not None:
            with self._cache_lock:
                self._cache[new_id] = new_vec

        print(f"[SemanticMemory] 💾 Stored new {mem_type} memory: '{new_id}' ({concept_slug}) [priority={priority}]")
        return new_entry

    def deactivate(self, key_or_id: str) -> bool:
        store = load_semantic_store()
        memories = store.get("memories", [])
        changed = False
        k = key_or_id.lower().strip()
        for m in memories:
            if m.get("id") == key_or_id or m.get("concept", "").lower() == k:
                if m.get("active", True):
                    m["active"] = False
                    changed = True
                    print(f"[SemanticMemory] 🗑️ Deactivated memory: {m.get('id')} ({m.get('concept')})")
        if changed:
            save_semantic_store(store)
        return changed


_engine_instance = None
_engine_lock = Lock()


def get_semantic_engine() -> SemanticMemoryEngine:
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = SemanticMemoryEngine()
        return _engine_instance


def retrieve_semantic_memories(query: str, top_k: int = 4, threshold: float = 0.25) -> list[dict]:
    return get_semantic_engine().retrieve(query, top_k=top_k, threshold=threshold)


def add_semantic_memory(
    lesson: str,
    concept: str = "",
    mem_type: str = "lesson",
    source: str = "user_correction",
    priority: int = 10,
    tags: list[str] | None = None,
    context: str = "",
    supersede_threshold: float = 0.65,
) -> dict:
    return get_semantic_engine().add_memory(
        lesson=lesson,
        concept=concept,
        mem_type=mem_type,
        source=source,
        priority=priority,
        tags=tags,
        context=context,
        supersede_threshold=supersede_threshold,
    )


def deactivate_semantic_memory(key_or_id: str) -> bool:
    return get_semantic_engine().deactivate(key_or_id)


def _get_active_top_semantic_memories(limit: int = 4) -> list[dict]:
    store = load_semantic_store()
    active = [m for m in store.get("memories", []) if m.get("active", True)]
    active.sort(key=lambda m: (m.get("priority", 5), m.get("timestamp", "")), reverse=True)
    return active[:limit]


def ingest_user_feedback(user_statement: str, previous_asst_turn: str = "", context: str = "") -> dict | None:
    text = (user_statement or "").strip()
    if not text or len(text) < 5:
        return None

    for pat, mem_type, priority in FEEDBACK_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            extracted = m.group(1).strip() if m.groups() else text
            extracted = re.sub(r"^[,.:;\s]+", "", extracted)
            if len(extracted) < 4:
                extracted = text

            concept = _slugify(extracted[:30])
            engine = get_semantic_engine()
            return engine.add_memory(
                lesson=extracted,
                concept=concept,
                mem_type=mem_type,
                source="user_correction",
                priority=priority,
                context=context or (f"Prior assistant turn: {previous_asst_turn[:120]}" if previous_asst_turn else "User conversation feedback"),
            )
    return None


detect_and_ingest_feedback = ingest_user_feedback


def apply_memory_expiry(
    idle_days_halve: int = 90,
    prune_age_days: int = 180,
    prune_priority_threshold: float = 1.0,
) -> dict:
    """Trigger memory expiration and decay on semantic memories."""
    return get_semantic_engine().apply_memory_expiry(
        idle_days_halve=idle_days_halve,
        prune_age_days=prune_age_days,
        prune_priority_threshold=prune_priority_threshold,
    )


# ==============================================================================
# ── Episodic Memory System ───────────────────────────────────────────────────
# ==============================================================================

def load_episodes() -> list[dict]:
    """Load past episode memories from episodes.json."""
    if not EPISODES_PATH.exists():
        return []
    with _episodes_lock:
        try:
            data = json.loads(EPISODES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "episodes" in data:
                return data["episodes"]
            elif isinstance(data, list):
                return data
            return []
        except Exception as e:
            print(f"[Memory] ⚠️ Episodes load error: {e}")
            return []


def save_episodic_memory(
    summary: str,
    tools_used: list[str] | None = None,
    lessons_learned: list[str] | None = None,
    date: str = "",
) -> dict:
    """Save an episode record containing date, summary, tools used, and lessons learned."""
    summary = (summary or "").strip()
    if not summary:
        return {}

    episodes = load_episodes()
    ep_id = f"ep_{int(time.time())}_{uuid.uuid4().hex[:4]}"
    now_dt = datetime.now()
    entry = {
        "id": ep_id,
        "date": date or now_dt.strftime("%Y-%m-%d"),
        "summary": summary,
        "tools_used": list(tools_used or []),
        "lessons_learned": list(lessons_learned or []),
        "timestamp": now_dt.isoformat(),
    }
    episodes.append(entry)
    episodes = episodes[-100:]  # Keep latest 100 episodes
    EPISODES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _episodes_lock:
        EPISODES_PATH.write_text(
            json.dumps({"version": 1, "episodes": episodes}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(f"[Memory] [Episode] Saved: {summary[:50]}... (tools={entry['tools_used']})")
    return entry


def retrieve_episodes(query: str, top_k: int = 2) -> list[dict]:
    """Retrieve top-k relevant past episodes based on dense embedding or keyword overlap."""
    episodes = load_episodes()
    if not episodes or not query.strip():
        return []

    engine = get_semantic_engine()
    q_vec = engine._encode(query)

    scored: list[tuple[float, dict]] = []
    q_words = set(re.findall(r"\w+", query.lower()))
    q_words = {w for w in q_words if len(w) > 1}

    for ep in episodes:
        rep = f"{ep.get('summary', '')} {' '.join(ep.get('tools_used', []))} {' '.join(ep.get('lessons_learned', []))}"
        score = 0.0
        if q_vec is not None:
            ep_vec = engine._encode(rep)
            if ep_vec is not None:
                score = float(np.dot(q_vec, ep_vec))
        if score == 0.0 and q_words:
            rep_words = set(re.findall(r"\w+", rep.lower()))
            overlap = len(q_words.intersection(rep_words))
            score = overlap / max(1, len(q_words))
        if score > 0.15:
            scored.append((score, ep))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [ep for _, ep in scored[:top_k]]


# ==============================================================================
# ── Cross-Session Pending Tasks ───────────────────────────────────────────────
# ==============================================================================

def load_pending_tasks() -> list[dict]:
    """Load pending tasks across sessions from pending_tasks.json."""
    if not PENDING_TASKS_PATH.exists():
        return []
    with _tasks_lock:
        try:
            data = json.loads(PENDING_TASKS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "tasks" in data:
                return data["tasks"]
            elif isinstance(data, list):
                return data
            return []
        except Exception as e:
            print(f"[Memory] [Warning] Pending tasks load error: {e}")
            return []


def save_pending_task(description: str, metadata: dict | None = None) -> dict:
    """Save an incomplete task to be resumed in future sessions."""
    desc = (description or "").strip()
    if not desc:
        return {}
    tasks = load_pending_tasks()
    task_id = f"task_{int(time.time())}_{uuid.uuid4().hex[:4]}"
    now_iso = datetime.now().isoformat()
    entry = {
        "id": task_id,
        "description": desc,
        "status": "pending",
        "created_at": now_iso,
        "updated_at": now_iso,
        "metadata": metadata or {},
    }
    tasks.append(entry)
    PENDING_TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _tasks_lock:
        PENDING_TASKS_PATH.write_text(
            json.dumps({"version": 1, "tasks": tasks}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(f"[Memory] [Task] Pending task saved: {task_id} - {desc[:50]}")
    return entry


def update_pending_task(task_id: str, status: str) -> bool:
    """Update status of a pending task ('pending', 'in_progress', 'completed')."""
    tasks = load_pending_tasks()
    changed = False
    for t in tasks:
        if t.get("id") == task_id:
            t["status"] = status
            t["updated_at"] = datetime.now().isoformat()
            changed = True
            break
    if changed:
        with _tasks_lock:
            PENDING_TASKS_PATH.write_text(
                json.dumps({"version": 1, "tasks": tasks}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    return changed


def clear_pending_task(task_id: str) -> bool:
    """Remove a pending task by ID."""
    tasks = load_pending_tasks()
    orig_len = len(tasks)
    tasks = [t for t in tasks if t.get("id") != task_id]
    if len(tasks) != orig_len:
        with _tasks_lock:
            PENDING_TASKS_PATH.write_text(
                json.dumps({"version": 1, "tasks": tasks}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return True
    return False


def get_active_pending_tasks() -> list[dict]:
    """Return all tasks that are currently pending or in progress."""
    tasks = load_pending_tasks()
    return [t for t in tasks if t.get("status") in ("pending", "in_progress")]


def format_semantic_context_for_prompt(query: str, top_k: int = 4) -> str:
    matches = retrieve_semantic_memories(query, top_k=top_k)
    episodes = retrieve_episodes(query, top_k=2) if query else []
    if not matches and not episodes:
        return ""

    lines = []
    if matches:
        lines.append("[RELEVANT LEARNED CONTEXT & USER CORRECTIONS]")
        lines.append("Prioritize these user corrections, preferences, and verified patterns over standard defaults:")
        for m in matches:
            c = m.get("concept", "rule").replace("_", " ").title()
            lines.append(f"- [PRIORITY {m.get('priority', 5)} - {m.get('type', 'rule').upper()}] {c}: {m.get('lesson', '')}")

    if episodes:
        if lines:
            lines.append("")
        lines.append("[RELEVANT PAST EPISODES]")
        for ep in episodes:
            d = ep.get("date", "past")
            s = ep.get("summary", "")
            t = ", ".join(ep.get("tools_used", []))
            lines.append(f"- [{d}] {s}" + (f" (Tools used: {t})" if t else ""))

    return "\n".join(lines) + "\n"
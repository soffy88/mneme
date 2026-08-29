# DASHPLAYER-CAPABILITY-MAP

> Source audit: [solidSpoon/DashPlayer](https://github.com/solidSpoon/DashPlayer) (package `6.5.0`, latest release ~v6.4.1+, ~4.3k★)  
> Scope: **product / architecture capabilities only**. No source code copied.  
> Policy for Mneme: **INSPIRED_BY allowed; COPY_SOURCE / PORT_COMPONENT forbidden** (AGPL-3.0).  
> Audit date: 2026-08-29.  
> Mneme baseline referenced: RC2 `v0.1.0-rc2` / Migration head `5e7f8a9b0c12` (design-only; no code changed).

---

## 0. License boundary (binding)

| Class | Rule |
|-------|------|
| **INSPIRED_BY** | Allowed: UX patterns, product concepts, keyboard maps paraphrased, architecture research |
| **COPY_SOURCE** | Forbidden: TypeScript/React/Electron source, parsers, IPC, prompts, CSS, tests, assets |
| **PORT_COMPONENT** | Forbidden unless separately approved + license review |
| **DEPEND_ON_AGPL_COMPONENT** | Requires explicit license review; default = reject for Mneme network service |

**Canonical license:** GNU Affero General Public License v3.0 (`LICENSE` + GitHub SPDX).  
**Mismatch:** `package.json` still says `"license": "MIT"` — treat as boilerplate error; **AGPL-3.0 wins**.

Mneme implementation must be **clean-room**:
requirements/specification → independent implementation under Mneme license.

---

## 1. Tech stack overview (capability-relevant)

| Layer | Stack |
|-------|--------|
| Shell | Electron (~39), Electron Forge, Vite (main / preload / renderer) |
| UI | React, TypeScript, Tailwind, shadcn/Radix |
| Player | React Player, media-chrome |
| State | Zustand, electron-store |
| Persistence | SQLite + Drizzle (watch history, clips, tasks, translation cache, timing adjustments) |
| Media | FFmpeg / FFprobe |
| ASR | Local whisper.cpp and/or OpenAI Whisper |
| AI / NLP | OpenAI-compatible AI SDK; wink-nlp |
| Translation | Youdao (word), Tencent Cloud (subtitle MT), OpenAI alt |
| Platforms | macOS + Windows primary |

Architecture style: Electron main ↔ preload IPC ↔ React renderer; Controller → Service → Infrastructure.

---

## 2. Capability inventory

Complexity: **L** low · **M** medium · **H** high · **VH** very high  
License risk = temptation/risk of AGPL copy (all Mneme builds must remain greenfield).

### VIDEO_PLAYBACK

| Field | Value |
|-------|-------|
| DashPlayer capability | Local video via ReactPlayer; play/pause/seek/volume/fullscreen; resume |
| UX behavior | Standard chrome; resume from saved position; resizable panels |
| Data required | Local video path; container/MIME support |
| Mneme relevance | Medium–High (PWA `<video>`; not Electron parity) |
| Implementation complexity | M (web) / VH (desktop parity) |
| License risk | High if copying player shell |

### AUDIO_PLAYBACK

| Field | Value |
|-------|-------|
| DashPlayer capability | Common audio formats; **Podcast mode** hides video chrome |
| UX behavior | Audio-first transcript-centric study |
| Data required | Local audio + optional SRT |
| Mneme relevance | High (listening vertical) |
| Implementation complexity | L–M |
| License risk | Medium |

### SUBTITLE

| Field | Value |
|-------|-------|
| DashPlayer capability | Timed English captions (SRT primary; ASS as plain-text); side list; sync; ±0.2s cue adjust |
| UX behavior | Overlay + list; click cue seek; adjust ASR misalignment |
| Data required | Cues `{index,start,end,text}`; optional adjustment table |
| Mneme relevance | **Very high** — timed transcript = learning substrate |
| Implementation complexity | M |
| License risk | High (parsers) |

### BILINGUAL_SUBTITLE

| Field | Value |
|-------|-------|
| DashPlayer capability | EN / ZH / both / none (`e`/`c`/`b`); MT fills Chinese |
| UX behavior | Instant visibility toggles without leaving player |
| Data required | Source cues + translations (file or cache) |
| Mneme relevance | High for CN learners / scaffold fading |
| Implementation complexity | M |
| License risk | Medium |

### TRANSCRIPT

| Field | Value |
|-------|-------|
| DashPlayer capability | Transcript page: queue → ASR → sibling `.srt`; background progress |
| UX behavior | Add media → Transcribe → auto-attach |
| Data required | Media path; engine/model; output SRT |
| Mneme relevance | High; overlaps existing `transcribe_audio_substrate` |
| Implementation complexity | H |
| License risk | High |

### SENTENCE_NAVIGATION

| Field | Value |
|-------|-------|
| DashPlayer capability | Prev/next sentence (`←/a`, `→/d`); click cue jump |
| UX behavior | Fine listening without scrubbing timeline |
| Data required | Ordered timed cues + current index |
| Mneme relevance | **Very high** — atomic study unit UX |
| Implementation complexity | M |
| License risk | Medium |

### SEGMENT_LOOP

| Field | Value |
|-------|-------|
| DashPlayer capability | Click-drag multi-line subtitle range loop (v6.0+) |
| UX behavior | A–B cue range continuous loop |
| Data required | Cue index range + times |
| Mneme relevance | High for intensive listening |
| Implementation complexity | M |
| License risk | Medium |

### REPEAT

| Field | Value |
|-------|-------|
| DashPlayer capability | Replay current sentence (`↓/s`); single-repeat mode (`r`); auto-pause at cue end |
| UX behavior | Intensive listening modes with indicators |
| Data required | Current cue bounds; mode flags |
| Mneme relevance | Very high before practice/FSRS |
| Implementation complexity | M |
| License risk | Medium |

### PLAYBACK_SPEED

| Field | Value |
|-------|-------|
| DashPlayer capability | Variable rate; hotkey cycle |
| UX behavior | Speed without leaving immersion |
| Data required | Rate list in settings |
| Mneme relevance | High (comprehensible input) |
| Implementation complexity | L |
| License risk | Low |

### KEYBOARD_CONTROL

| Field | Value |
|-------|-------|
| DashPlayer capability | Customizable shortcuts; Bluetooth pad as keyboard |
| UX behavior | Hands-free sentence control |
| Data required | Shortcut map |
| Mneme relevance | Medium (keyboard-first web); gamepad optional |
| Implementation complexity | L–M |
| License risk | Low |

### VOCAB_LOOKUP

| Field | Value |
|-------|-------|
| DashPlayer capability | Hover word → Youdao/OpenAI dict; click TTS |
| UX behavior | Non-modal lookup; stay in flow |
| Data required | Tokenized words; dictionary API/cache |
| Mneme relevance | **Very high** — feed vocab KCs / FSRS via eligibility |
| Implementation complexity | M |
| License risk | Medium–High |

### TRANSLATION

| Field | Value |
|-------|-------|
| DashPlayer capability | Batch subtitle MT (Tencent/OpenAI); sliding window; serial long-file batches |
| UX behavior | ZH under EN as user watches |
| Data required | Cue texts; provider credentials; cache |
| Mneme relevance | High as scaffold, not mastery authority |
| Implementation complexity | M–H |
| License risk | Medium |

### AI_SUBTITLE

| Field | Value |
|-------|-------|
| DashPlayer capability | Local whisper.cpp and/or OpenAI Whisper |
| UX behavior | One-click generate when no SRT |
| Data required | Audio extract; models or API; SRT output |
| Mneme relevance | High for BYO media (Phase 2) |
| Implementation complexity | H–VH |
| License risk | High |

### LOCAL_MEDIA

| Field | Value |
|-------|-------|
| DashPlayer capability | Open file/folder; custom `dp://` protocol |
| UX behavior | Recent library; folder binge |
| Data required | Filesystem paths; watch-history |
| Mneme relevance | Medium — Mneme cloud-first → **upload** equivalent |
| Implementation complexity | M (upload) / H (Electron) |
| License risk | Medium |

### REMOTE_MEDIA

| Field | Value |
|-------|-------|
| DashPlayer capability | **No streaming playback**; Beta download-by-URL then local play |
| UX behavior | Paste link → download task → local file |
| Data required | URL, cookies, job state |
| Mneme relevance | Low for V1 — ToS/legal/DRM risk |
| Implementation complexity | H |
| License risk | Medium |

### PROGRESS

| Field | Value |
|-------|-------|
| DashPlayer capability | Auto-save playhead; home recent; resume |
| UX behavior | Continue across titles |
| Data required | Watch history (path, position, subtitle attach) |
| Mneme relevance | High — continuity ≠ CognitiveState |
| Implementation complexity | L–M |
| License risk | Low |

### BOOKMARK

| Field | Value |
|-------|-------|
| DashPlayer capability | Favorite current cue (`Shift+L`); FFmpeg cut clip + context |
| UX behavior | Collect hard moments; revisit |
| Data required | Clip file / metadata, cues, tags |
| Mneme relevance | High as bookmark metadata; clip encode optional |
| Implementation complexity | M (meta) / H (encode) |
| License risk | High if copying clip pipeline |

### SENTENCE_COLLECTION

| Field | Value |
|-------|-------|
| DashPlayer capability | Vocabulary Studio: scan cues for unknown words → auto-cut clips |
| UX behavior | Harvest i+1 sentences for review |
| Data required | Unknown set; cue–word index; clip artifacts |
| Mneme relevance | Very high with Mneme vocab FSRS — start cue→card |
| Implementation complexity | M (cue→card) / H (auto-cut) |
| License risk | High |

### CONTEXT_EXPLANATION

| Field | Value |
|-------|-------|
| DashPlayer capability | AI 整句学习 (`?`): vocab, phrases, grammar, examples, chat |
| UX behavior | Side panel while watching |
| Data required | Current + neighbor cues; LLM; optional TTS |
| Mneme relevance | High — explain only; never invent mastery |
| Implementation complexity | M–H |
| License risk | High |

---

## 3. Default keyboard map (product concept only)

| Action | Keys |
|--------|------|
| Previous sentence | `←` / `a` |
| Next sentence | `→` / `d` |
| Repeat current | `↓` / `s` |
| Play/pause | `↑` / `w` / `Space` |
| Single-sentence repeat mode | `r` |
| Toggle English subtitle | `e` |
| Toggle Chinese subtitle | `c` |
| Toggle both / hide | `b` |
| Theme | `t` |
| Cue start −0.2s / +0.2s | `z` / `x` |
| Sentence learning panel | `?` |

Mneme may adopt a **similar keyboard-first contract**, independently implemented.

---

## 4. What NOT to copy

- Any TypeScript/React/Electron source under `src/`
- Subtitle parsers, player controllers, Zustand slices, IPC route tables
- Whisper/ffmpeg orchestration, download/split pipelines
- UI components, CSS, prompts, assets, tests
- Drizzle schema dumps as drop-in
- Packaged binaries / `dp://` protocol implementation

---

## 5. Mneme takeaways (INSPIRED_BY only)

**Highest-ROI product concepts**

1. Sentence-timed immersion player (prev/next/repeat/loop/speed)
2. Bilingual scaffold with hide/reveal controls
3. Hover/tap vocab → eligibility-gated FSRS path
4. Bookmark sentence → later practice / transfer
5. AI explanation as scaffold, never as mastery authority

**Defer**

- Electron shell, Bluetooth pad, arbitrary URL downloader, client FFmpeg clip farm
- Full Vocabulary Studio auto-cut video library

---

## 6. Bottom line

| Question | Answer |
|----------|--------|
| What is DashPlayer? | AGPL-3.0 Electron immersion player: BYO media + sentence-level study |
| Direct source reuse allowed? | **NO** |
| What to take? | UX/product concepts for Media Learning Engine |
| Highest-ROI Mneme build | Web player + SRT/VTT + sentence nav + practice → LearningEvent → Evidence → Policy → FSRS |

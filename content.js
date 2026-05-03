/**
 * content.js — YouTube Activity Analyzer
 *
 * - Detects YouTube video navigation (SPA-safe)
 * - Waits 5 seconds of actual watch time before tracking
 * - POST /analyze → popup stats (immediate)
 * - POST /track   → saves snapshot to youtube_tracking.json (after 5s)
 */

const BACKEND_ANALYZE = "http://127.0.0.1:8001/analyze";
const BACKEND_TRACK   = "http://127.0.0.1:8001/track";
const TRACK_DELAY_MS  = 5000; // 5 seconds watch time before tracking

// ─── State ────────────────────────────────────────────────────────────────────

let lastVideoId   = null;
let trackTimer    = null;   // setTimeout handle for the 5s delay
let isTracked     = false;  // prevent double-tracking the same video

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getVideoIdFromUrl(url) {
  try {
    const u = new URL(url);
    if (u.pathname === "/watch") return u.searchParams.get("v");
  } catch (_) {}
  return null;
}

function cancelPendingTrack() {
  if (trackTimer) {
    clearTimeout(trackTimer);
    trackTimer = null;
    console.log("[YT Analyzer] Track timer cancelled (user navigated away)");
  }
}

// ─── Analyze: immediate — updates popup ──────────────────────────────────────

async function analyzeVideo(videoId) {
  try {
    const res = await fetch(BACKEND_ANALYZE, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: videoId }),
    });
    if (!res.ok) { console.error(`[YT Analyzer] /analyze ${res.status}`); return; }

    const data = await res.json();

    console.group(`%c[YT Analyzer] ${data.title}`, "color:#ff0000;font-weight:bold;");
    console.log(`👁  Views      : ${data.views.toLocaleString()}`);
    console.log(`👍 Likes      : ${data.likes.toLocaleString()}`);
    console.log(`💬 Comments   : ${data.comments.toLocaleString()}`);
    console.log(`📊 Engagement : ${data.engagement_rate}%`);
    console.log(`💡 Insight    : ${data.insight}`);
    console.groupEnd();

    chrome.storage.local.set({ latestAnalysis: data }, () => {
      if (chrome.runtime.lastError) console.warn("[YT Analyzer] Storage error:", chrome.runtime.lastError.message);
    });

    chrome.runtime.sendMessage({ type: "VIDEO_ANALYZED", payload: data }, () => {
      if (chrome.runtime.lastError) { /* popup closed */ }
    });

  } catch (err) {
    console.info("[YT Analyzer] /analyze failed — backend offline?");
  }
}

// ─── Track: after 5s — saves snapshot to JSON ────────────────────────────────

async function trackVideo(videoId) {
  if (isTracked) return; // already tracked this video session
  isTracked = true;

  console.log(`[YT Analyzer] ⏱ 5s reached — tracking ${videoId}`);

  try {
    const res = await fetch(BACKEND_TRACK, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: videoId }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      console.warn(`[YT Analyzer] /track error: ${err.detail || res.status}`);
      return;
    }

    const result = await res.json();
    console.log(`[YT Analyzer] ✅ Tracked: "${result.title}" — ${result.total_snapshots} total snapshot(s)`);

    // Store tracking result so popup can show a badge
    chrome.storage.local.set({ lastTracked: result }, () => {
      if (chrome.runtime.lastError) { /* ignore */ }
    });

    // Notify popup
    chrome.runtime.sendMessage({ type: "VIDEO_TRACKED", payload: result }, () => {
      if (chrome.runtime.lastError) { /* popup closed */ }
    });

  } catch (err) {
    console.info("[YT Analyzer] /track failed — backend offline?");
  }
}

// ─── Navigation handler ───────────────────────────────────────────────────────

function handleNavigation() {
  const videoId = getVideoIdFromUrl(window.location.href);

  // Not a video page, or same video — do nothing
  if (!videoId || videoId === lastVideoId) return;

  // New video detected
  console.log(`[YT Analyzer] 🎬 New video: ${videoId}`);
  cancelPendingTrack();   // cancel any pending 5s timer from previous video

  lastVideoId = videoId;
  isTracked   = false;

  // 1. Analyze immediately (updates popup)
  analyzeVideo(videoId);

  // 2. Schedule tracking after 5 seconds
  console.log(`[YT Analyzer] ⏳ Will track in 5s if user stays on this video…`);
  trackTimer = setTimeout(() => {
    trackVideo(videoId);
    trackTimer = null;
  }, TRACK_DELAY_MS);
}

// ─── SPA navigation listeners ─────────────────────────────────────────────────

document.addEventListener("yt-navigate-finish", handleNavigation);
handleNavigation(); // also run on direct page load
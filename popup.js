/**
 * popup.js — Listens for VIDEO_ANALYZED messages from content.js
 * and renders the analysis in the popup UI.
 */

const resultsEl   = document.getElementById("results");
const dotEl       = document.getElementById("dot");
const statusEl    = document.getElementById("status-text");

function formatNum(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

function insightClass(insight) {
  if (!insight) return "insight-low";
  insight = insight.toLowerCase();

  if (insight.includes("high")) return "insight-high";
  if (insight.includes("average")) return "insight-average";
  return "insight-low";
}

function render(data) {
  dotEl.classList.add("active");
  statusEl.textContent = "Analysis complete ✅";

  const insightText = data.insight?.toLowerCase() || "";

  const badge = insightText.includes("high") ? "🔥" :
                insightText.includes("average") ? "📊" : "📉";

  const safeNum = (n) => (n ? formatNum(n) : "N/A");

  resultsEl.innerHTML = `
    <div class="card">
      <div class="label">Title</div>
      <div class="value" title="${data.title}">
        ${data.title.length > 60 ? data.title.slice(0, 60) + "..." : data.title}
      </div>
    </div>

    <div class="card">
      <div class="label">Engagement Rate</div>
      <div class="value big">
        ${data.engagement_rate ?? "N/A"}
        <span style="font-size:12px;color:#555">%</span>
      </div>
    </div>

    <div class="stats-grid">
      <div class="stat">
        <div class="s-val">${safeNum(data.views)}</div>
        <div class="s-lbl">Views</div>
      </div>
      <div class="stat">
        <div class="s-val">${safeNum(data.likes)}</div>
        <div class="s-lbl">Likes</div>
      </div>
      <div class="stat">
        <div class="s-val">${safeNum(data.comments)}</div>
        <div class="s-lbl">Comments</div>
      </div>
    </div>

    <div class="insight-bar ${insightClass(data.insight)}">
      ${badge} ${data.insight ?? "No insight available"}
    </div>
  `;
}

// Listen for messages sent by content.js via chrome.runtime.sendMessage
chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "VIDEO_ANALYZED") {
    
    // ✅ store safely here
    chrome.storage.local.set({ latestAnalysis: message.payload });

    render(message.payload);
  }
});

// On popup open, query the active tab and ask content.js for the latest data
document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.local.get("latestAnalysis", (result) => {
    if (result.latestAnalysis) {
      render(result.latestAnalysis);
    } else {
      statusEl.textContent = "No video analyzed yet";
    }
  });
});
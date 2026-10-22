const state = {
  tool: "prompt",
  mediaType: "image",
  busy: {
    prompt: false,
    media: false,
  },
  threadIds: {
    prompt: "",
    media: "",
  },
};

const toolButtons = Array.from(document.querySelectorAll(".tool-item"));
const panels = Array.from(document.querySelectorAll(".tool-panel"));
const topbarKicker = document.getElementById("topbarKicker");
const topbarTitle = document.getElementById("topbarTitle");
const systemStatus = document.getElementById("systemStatus");
const promptCount = document.getElementById("promptCount");

const promptForm = document.getElementById("promptForm");
const promptInput = document.getElementById("promptInput");
const promptMessages = document.getElementById("promptMessages");

const mediaForm = document.getElementById("mediaForm");
const mediaInput = document.getElementById("mediaInput");
const mediaMessages = document.getElementById("mediaMessages");
const stageTabs = Array.from(document.querySelectorAll(".stage-tab"));
const aspectRatio = document.getElementById("aspectRatio");
const previewEmpty = document.getElementById("previewEmpty");
const previewEmptyLabel = document.getElementById("previewEmptyLabel");
const previewResult = document.getElementById("previewResult");
const previewPrompt = document.getElementById("previewPrompt");
const previewType = document.getElementById("previewType");

const toolCopy = {
  prompt: {
    kicker: "PROMPT STUDIO",
    title: "提示词工坊",
  },
  media: {
    kicker: "MEDIA STUDIO",
    title: "影像生成",
  },
};

function loadThreadId(tool) {
  const storageKey = `prompt-atelier-thread-${tool}`;

  try {
    const existing = localStorage.getItem(storageKey);

    if (existing) {
      return existing;
    }

    const created = crypto.randomUUID();
    localStorage.setItem(storageKey, created);
    return created;
  } catch {
    return crypto.randomUUID();
  }
}

function saveThreadId(tool, threadId) {
  if (!threadId) {
    return;
  }

  state.threadIds[tool] = threadId;

  try {
    localStorage.setItem(
      `prompt-atelier-thread-${tool}`,
      threadId,
    );
  } catch {
    // Conversation still works for the current page session.
  }
}

function switchTool(toolName) {
  state.tool = toolName;

  toolButtons.forEach((button) => {
    const active = button.dataset.tool === toolName;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });

  panels.forEach((panel) => {
    const active = panel.id === `panel-${toolName}`;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });

  const copy = toolCopy[toolName];
  topbarKicker.textContent = copy.kicker;
  topbarTitle.textContent = copy.title;

  try {
    localStorage.setItem("prompt-atelier-tool", toolName);
  } catch {
    // The interface still works when storage is unavailable.
  }

  const activeInput = toolName === "prompt" ? promptInput : mediaInput;
  requestAnimationFrame(() => activeInput.focus());
}

function resizeTextarea(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
}

function scrollMessages(container) {
  requestAnimationFrame(() => {
    container.scrollTop = container.scrollHeight;
  });
}

function createCopyButton(text) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "icon-button";
  button.title = "复制提示词";
  button.setAttribute("aria-label", "复制提示词");
  button.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="8" y="8" width="11" height="12" rx="2" stroke="currentColor" stroke-width="1.6"/>
      <path d="M5 16V5a2 2 0 0 1 2-2h9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
    </svg>
  `;
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      button.title = "已复制";
      button.setAttribute("aria-label", "已复制");
      window.setTimeout(() => {
        button.title = "复制提示词";
        button.setAttribute("aria-label", "复制提示词");
      }, 1200);
    } catch {
      button.title = "复制失败";
    }
  });
  return button;
}

function appendMessage(
  container,
  role,
  text,
  {
    stateLabel = "",
    copyText = "",
    sources = [],
  } = {},
) {
  const article = document.createElement("article");
  article.className = `message message--${role}`;

  if (role === "assistant" || role === "error") {
    const meta = document.createElement("div");
    meta.className = "message-meta";

    const mark = document.createElement("span");
    mark.className = "message-mark";
    mark.setAttribute("aria-hidden", "true");

    const name = document.createElement("span");
    name.textContent = role === "error" ? "SYSTEM" : "Prompt Atelier";

    const status = document.createElement("span");
    status.className = "message-state";
    status.textContent = stateLabel || (role === "error" ? "ERROR" : "DONE");

    meta.append(mark, name, status);
    article.appendChild(meta);
  }

  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text;
  article.appendChild(body);

  if (copyText) {
    const actions = document.createElement("div");
    actions.className = "message-actions";
    actions.appendChild(createCopyButton(copyText));
    article.appendChild(actions);
  }

  if (sources.length > 0) {
    const sourceList = document.createElement("div");
    sourceList.className = "message-sources";

    const sourceLabel = document.createElement("span");
    sourceLabel.className = "message-sources__label";
    sourceLabel.textContent = "WEB SOURCES";

    const links = document.createElement("div");
    links.className = "message-sources__links";

    sources.forEach((source) => {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = source.title || source.url;
      links.appendChild(link);
    });

    sourceList.append(sourceLabel, links);
    article.appendChild(sourceList);
  }

  container.appendChild(article);
  scrollMessages(container);
  return article;
}

function appendTyping(container, label = "COMPOSING") {
  const article = document.createElement("article");
  article.className = "message message--assistant";

  const meta = document.createElement("div");
  meta.className = "message-meta";

  const mark = document.createElement("span");
  mark.className = "message-mark";
  mark.setAttribute("aria-hidden", "true");

  const name = document.createElement("span");
  name.textContent = "Prompt Atelier";

  const status = document.createElement("span");
  status.className = "message-state";
  status.textContent = label;

  meta.append(mark, name, status);

  const body = document.createElement("div");
  body.className = "message-body";

  const typing = document.createElement("span");
  typing.className = "typing";
  typing.setAttribute("aria-label", "正在生成");
  typing.innerHTML = "<span></span><span></span><span></span>";

  body.appendChild(typing);
  article.append(meta, body);
  container.appendChild(article);
  scrollMessages(container);
  return article;
}

function setBusy(tool, busy) {
  state.busy[tool] = busy;
  const form = tool === "prompt" ? promptForm : mediaForm;
  const button = form.querySelector(".send-button");
  form.classList.toggle("is-busy", busy);
  button.disabled = busy;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail || "请求失败，请稍后再试。");
  }

  return data;
}

async function submitPrompt(event) {
  event.preventDefault();

  if (state.busy.prompt) {
    return;
  }

  const message = promptInput.value.trim();

  if (!message) {
    promptInput.focus();
    return;
  }

  appendMessage(promptMessages, "user", message);
  promptInput.value = "";
  resizeTextarea(promptInput);
  setBusy("prompt", true);
  const typing = appendTyping(promptMessages, "RETRIEVING");

  try {
    const data = await postJson("/api/prompt", {
      message,
      thread_id: state.threadIds.prompt,
    });
    saveThreadId("prompt", data.thread_id);
    typing.remove();

    if (data.response_type === "clarification") {
      appendMessage(
        promptMessages,
        "assistant",
        data.reply,
        {
          stateLabel: "CLARIFY",
        },
      );
      return;
    }

    appendMessage(
      promptMessages,
      "assistant",
      data.prompt,
      {
        stateLabel: data.cached ? "CACHED" : "LIVE",
        copyText: data.prompt,
          sources: data.sources || [],
      },
    );
  } catch (error) {
    typing.remove();
    appendMessage(
      promptMessages,
      "error",
      error instanceof Error ? error.message : "生成失败。",
    );
  } finally {
    setBusy("prompt", false);
    promptInput.focus();
  }
}

async function submitMedia(event) {
  event.preventDefault();

  if (state.busy.media) {
    return;
  }

  const message = mediaInput.value.trim();

  if (!message) {
    mediaInput.focus();
    return;
  }

  appendMessage(mediaMessages, "user", message);
  mediaInput.value = "";
  resizeTextarea(mediaInput);
  setBusy("media", true);
  previewEmpty.hidden = false;
  previewResult.hidden = true;
  previewEmptyLabel.textContent = "正在检索视觉参考并组织提示词…";
  const typing = appendTyping(mediaMessages, "DIRECTING");

  try {
    const data = await postJson("/api/media", {
      message,
      media_type: state.mediaType,
      aspect_ratio: aspectRatio.value,
      thread_id: state.threadIds.media,
    });
    saveThreadId("media", data.thread_id);

    typing.remove();

    if (data.response_type === "clarification") {
      previewEmpty.hidden = false;
      previewResult.hidden = true;
      previewEmptyLabel.textContent = "等待补充修改方向";
      appendMessage(
        mediaMessages,
        "assistant",
        data.reply,
        {
          stateLabel: "CLARIFY",
        },
      );
      return;
    }

    previewEmpty.hidden = true;
    previewResult.hidden = false;
    previewType.textContent = data.media_type === "image"
      ? "IMAGE PROMPT"
      : "VIDEO PROMPT";
    previewPrompt.textContent = data.prompt;

    appendMessage(
      mediaMessages,
      "assistant",
      `最终提示词已生成。\n\n${data.note}`,
      {
        stateLabel: data.cached ? "CACHED" : "LIVE",
        copyText: data.prompt,
        sources: data.sources || [],
      },
    );
  } catch (error) {
    typing.remove();
    previewEmpty.hidden = false;
    previewResult.hidden = true;
    previewEmptyLabel.textContent = "本次请求没有生成可用结果。";
    appendMessage(
      mediaMessages,
      "error",
      error instanceof Error ? error.message : "影像方案生成失败。",
    );
  } finally {
    setBusy("media", false);
    mediaInput.focus();
  }
}

function initializeExamples() {
  document.querySelectorAll(".example-chip").forEach((button) => {
    button.addEventListener("click", () => {
      promptInput.value = button.dataset.example || "";
      resizeTextarea(promptInput);
      promptInput.focus();
    });
  });
}

function initializeTextareas() {
  [promptInput, mediaInput].forEach((textarea) => {
    textarea.addEventListener("input", () => resizeTextarea(textarea));
    textarea.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        textarea.form?.requestSubmit();
      }
    });
  });
}

function initializeMediaTabs() {
  stageTabs.forEach((button) => {
    button.addEventListener("click", () => {
      state.mediaType = button.dataset.mediaType || "image";
      stageTabs.forEach((item) => {
        const active = item === button;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-selected", String(active));
      });
    });
  });
}

async function initializeHealth() {
  try {
    const response = await fetch("/api/health");

    if (!response.ok) {
      throw new Error("offline");
    }

    const data = await response.json();
    systemStatus.querySelector("span:last-child").textContent = "本地服务在线";
    promptCount.textContent = `${data.prompt_count || 0} PROMPTS`;
  } catch {
    systemStatus.classList.add("is-error");
    systemStatus.querySelector("span:last-child").textContent = "服务未连接";
  }
}

toolButtons.forEach((button) => {
  button.addEventListener("click", () => {
    switchTool(button.dataset.tool || "prompt");
  });
});

promptForm.addEventListener("submit", submitPrompt);
mediaForm.addEventListener("submit", submitMedia);

initializeExamples();
initializeTextareas();
initializeMediaTabs();
initializeHealth();
saveThreadId("prompt", loadThreadId("prompt"));
saveThreadId("media", loadThreadId("media"));

try {
  const storedTool = localStorage.getItem("prompt-atelier-tool");

  if (storedTool === "prompt" || storedTool === "media") {
    switchTool(storedTool);
  }
} catch {
  switchTool("prompt");
}

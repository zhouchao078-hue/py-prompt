const state = {
  tool: "prompt",
  mediaType: "image",
  busy: {
    prompt: false,
    media: false,
    agent: false,
  },
  threadIds: {
    prompt: "",
    media: "",
    agent: "",
  },
  threadTokens: {
    prompt: "",
    media: "",
    agent: "",
  },
  imageContexts: {
    media: null,
    agent: null,
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
const agentForm = document.getElementById("agentForm");
const agentInput = document.getElementById("agentInput");
const agentMessages = document.getElementById("agentMessages");
const agentLiveStatus = document.getElementById("agentLiveStatus");
const agentTraceStatus = document.getElementById("agentTraceStatus");
const agentTraceDetail = document.getElementById("agentTraceDetail");
const agentTraceSteps = document.getElementById("agentTraceSteps");
const agentProgressBar = document.getElementById("agentProgressBar");
const agentDecisions = document.getElementById("agentDecisions");
const agentTools = document.getElementById("agentTools");
const agentResult = document.getElementById("agentResult");
const agentResultImage = document.getElementById("agentResultImage");
const agentImageActions = document.getElementById("agentImageActions");
const agentResultText = document.getElementById("agentResultText");
let agentImageObjectUrl = "";
let agentPendingToolRow = null;
const stageTabs = Array.from(document.querySelectorAll(".stage-tab"));
const aspectRatio = document.getElementById("aspectRatio");
const previewEmpty = document.getElementById("previewEmpty");
const previewEmptyLabel = document.getElementById("previewEmptyLabel");
const previewResult = document.getElementById("previewResult");
const previewPrompt = document.getElementById("previewPrompt");
const previewType = document.getElementById("previewType");
const previewStatus = document.getElementById("previewStatus");
const previewImageWrap = document.getElementById("previewImageWrap");
const previewImage = document.getElementById("previewImage");
const previewImageActions = document.getElementById("previewImageActions");
const providerNote = document.getElementById("providerNote");
let previewObjectUrl = "";
const downloadPreviewImage = document.getElementById("downloadPreviewImage");
const copyPreviewPrompt = document.getElementById("copyPreviewPrompt");
const editPreviewImage = document.getElementById("editPreviewImage");
const downloadAgentImage = document.getElementById("downloadAgentImage");
const copyAgentPrompt = document.getElementById("copyAgentPrompt");
const editAgentImage = document.getElementById("editAgentImage");

const imageEditorDialog = document.getElementById("imageEditorDialog");
const closeImageEditor = document.getElementById("closeImageEditor");
const cancelImageEdit = document.getElementById("cancelImageEdit");
const applyImageEdit = document.getElementById("applyImageEdit");
const imageEditorSource = document.getElementById("imageEditorSource");
const imageEditorCanvas = document.getElementById("imageEditorCanvas");
const imageEditorCanvasShell = document.getElementById(
  "imageEditorCanvasShell",
);
const imageEditorStatus = document.getElementById("imageEditorStatus");
const imageEditInstruction = document.getElementById(
  "imageEditInstruction",
);
const imageBrushSize = document.getElementById("imageBrushSize");
const imageBrushSizeLabel = document.getElementById("imageBrushSizeLabel");
const undoImageMark = document.getElementById("undoImageMark");
const clearImageMarks = document.getElementById("clearImageMarks");
const editorTools = Array.from(document.querySelectorAll(".editor-tool[data-editor-tool]"));
const imageEditorState = {
  target: "",
  context: null,
  tool: "brush",
  brushSize: 28,
  strokes: [],
  activeStroke: null,
  drawing: false,
  busy: false,
};
const addPromptButton = document.getElementById("addPromptButton");
const deleteThreadButton = document.getElementById("deleteThreadButton");
const promptDialog = document.getElementById("promptDialog");
const addPromptForm = document.getElementById("addPromptForm");
const addPromptText = document.getElementById("addPromptText");
const addPromptCategory = document.getElementById("addPromptCategory");
const cancelPromptDialog = document.getElementById("cancelPromptDialog");
const savePromptButton = document.getElementById("savePromptButton");

const historyButton = document.getElementById("historyButton");
const historyDialog = document.getElementById("historyDialog");
const historyList = document.getElementById("historyList");
const closeHistoryDialog = document.getElementById("closeHistoryDialog");
const newConversationButton = document.getElementById("newConversationButton");

const sessionButton = document.getElementById("sessionButton");
const sessionDialog = document.getElementById("sessionDialog");
const closeSessionDialog = document.getElementById("closeSessionDialog");
const sessionCodeBox = document.getElementById("sessionCodeBox");
const sessionCodeValue = document.getElementById("sessionCodeValue");
const copySessionCodeButton = document.getElementById("copySessionCode");
const issueSessionCodeButton = document.getElementById("issueSessionCode");
const resetSessionButton = document.getElementById("resetSessionButton");
const restoreCodeInput = document.getElementById("restoreCodeInput");
const restoreSessionButton = document.getElementById("restoreSessionButton");

const toolCopy = {
  prompt: {
    kicker: "PROMPT STUDIO",
    title: "提示词工坊",
  },
  media: {
    kicker: "MEDIA STUDIO",
    title: "影像生成",
  },
  agent: {
    kicker: "AGENT STUDIO",
    title: "任务 Agent",
  },
};

const DEMO_TOKEN_KEY = "prompt-atelier-token";

function accessToken() {
  try {
    return localStorage.getItem(DEMO_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function storeAccessToken(value) {
  try {
    localStorage.setItem(DEMO_TOKEN_KEY, value);
  } catch {
    // 存储不可用时只在本次会话生效
  }
}

function authHeaders(extra = {}) {
  const token = accessToken();

  if (!token) {
    return extra;
  }

  return { ...extra, Authorization: `Bearer ${token}` };
}

function requestAccessCode() {
  const entered = window.prompt("请输入演示访问口令");

  if (!entered || !entered.trim()) {
    return false;
  }

  storeAccessToken(entered.trim());
  return true;
}

function clearPreviewImage() {
  state.imageContexts.media = null;
  previewImageActions.hidden = true;

  if (previewObjectUrl) {
    URL.revokeObjectURL(previewObjectUrl);
    previewObjectUrl = "";
  }

  previewImage.removeAttribute("src");
  previewImage.alt = "";
}

async function fetchImageBlob(url) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const response = await fetch(url, {
      headers: authHeaders(),
    });

    if (
      response.status === 401
      && attempt === 0
      && requestAccessCode()
    ) {
      continue;
    }

    if (!response.ok) {
      throw new Error("图片加载失败，请刷新后重试。");
    }

    return response.blob();
  }

  throw new Error("图片加载失败，请检查访问口令。");
}

async function setPreviewImage(url, alt) {
  const blob = await fetchImageBlob(url);
  clearPreviewImage();
  previewObjectUrl = URL.createObjectURL(blob);
  previewImage.src = previewObjectUrl;
  previewImage.alt = alt;
}

function messageContainer(tool) {
  if (tool === "media") {
    return mediaMessages;
  }

  return tool === "agent" ? agentMessages : promptMessages;
}

function formForTool(tool) {
  if (tool === "media") {
    return mediaForm;
  }

  return tool === "agent" ? agentForm : promptForm;
}

function clearAgentImage() {
  state.imageContexts.agent = null;
  agentImageActions.hidden = true;

  if (agentImageObjectUrl) {
    URL.revokeObjectURL(agentImageObjectUrl);
    agentImageObjectUrl = "";
  }

  agentResultImage.removeAttribute("src");
  agentResultImage.hidden = true;
  agentResultImage.alt = "";
}

async function setAgentImage(url, alt) {
  const blob = await fetchImageBlob(url);
  clearAgentImage();
  agentImageObjectUrl = URL.createObjectURL(blob);
  agentResultImage.src = agentImageObjectUrl;
  agentResultImage.alt = alt;
  agentResultImage.hidden = false;
}

function inferAspectRatio(prompt, fallback = "1:1") {
  const match = String(prompt || "").match(
    /--ar\s+(\d+)\s*:\s*(\d+)/i,
  );

  if (!match) {
    return fallback;
  }

  const ratio = `${match[1]}:${match[2]}`;
  return ["1:1", "3:2", "2:3"].includes(ratio) ? ratio : fallback;
}

function setImageContext(target, data, objectUrl) {
  const prompt = data.prompt || "";
  const context = {
    imageId: data.image_id || "",
    imageUrl: data.image_url,
    objectUrl,
    prompt,
    aspectRatio: data.aspect_ratio
      || inferAspectRatio(prompt, target === "media" ? aspectRatio.value : "1:1"),
  };

  state.imageContexts[target] = context;

  if (target === "media") {
    previewImageActions.hidden = false;
  } else {
    agentImageActions.hidden = false;
  }

  return context;
}

async function downloadImageTarget(target) {
  const context = state.imageContexts[target];

  if (!context) {
    return;
  }

  const blob = await fetchImageBlob(context.imageUrl);
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const extension = context.imageUrl.split(".").pop() || "png";
  link.href = objectUrl;
  link.download = `aigc-${context.imageId || Date.now()}.${extension}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

async function copyPromptForTarget(target) {
  const prompt = state.imageContexts[target]?.prompt || "";

  if (!prompt) {
    return;
  }

  await navigator.clipboard.writeText(prompt);
}

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

function loadThreadToken(tool) {
  try {
    return localStorage.getItem(`prompt-atelier-thread-token-${tool}`) || "";
  } catch {
    return "";
  }
}

function threadHeaders() {
  // 身份现在由服务端 HttpOnly cookie 承载，请求头不需要再带任何东西。
  return {};
}

function saveThreadId(tool, threadId, threadToken) {
  if (!threadId) {
    return;
  }

  state.threadIds[tool] = threadId;
  state.threadTokens[tool] = threadToken || "";

  try {
    localStorage.setItem(`prompt-atelier-thread-${tool}`, threadId);

    if (threadToken) {
      localStorage.setItem(
        `prompt-atelier-thread-token-${tool}`,
        threadToken,
      );
    }
  } catch {
    // Conversation still works for the current page session.
  }
}

function dropStaleThread(tool) {
  // 清掉本地残留的会话，静默开一个新的（不打扰用户）
  try {
    localStorage.removeItem(`prompt-atelier-thread-${tool}`);
    localStorage.removeItem(`prompt-atelier-thread-token-${tool}`);
  } catch {
    // 存储不可用时只清内存状态
  }

  state.threadIds[tool] = "";
  state.threadTokens[tool] = "";
  saveThreadId(tool, loadThreadId(tool), "");
}

function resetThread(tool) {
  // 只清界面与"当前对话"指针；服务端会话和 cookie 都不动
  state.threadIds[tool] = "";
  state.threadTokens[tool] = "";

  const container = messageContainer(tool);
  container.replaceChildren();
  appendMessage(container, "assistant", "会话已清空，可以重新开始。", {
    stateLabel: "CLEARED",
  });
}

async function deleteConversation(tool) {
  const threadId = state.threadIds[tool];

  if (threadId) {
    const response = await fetch(
      `/api/history/${encodeURIComponent(threadId)}`,
      {
        method: "DELETE",
        headers: authHeaders(threadHeaders(tool)),
      },
    );

    // 403 说明本地会话已经不可访问（签名过期/缺失），当作已删除处理
    if (!response.ok && response.status !== 404 && response.status !== 403) {
      throw new Error("删除失败，请稍后再试。");
    }
  }

  resetThread(tool);
}

function initializeThreadDeletion() {
  if (!deleteThreadButton) {
    return;
  }

  deleteThreadButton.addEventListener("click", async () => {
    const tool = state.tool;

    if (!window.confirm("删除当前会话的全部历史记录？此操作不可恢复。")) {
      return;
    }

    try {
      await deleteConversation(tool);
    } catch (error) {
      appendMessage(
        messageContainer(tool),
        "error",
        error instanceof Error ? error.message : "删除失败。",
      );
    }
  });
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

  const activeInput = toolName === "media"
    ? mediaInput
    : toolName === "agent"
      ? agentInput
      : promptInput;
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
    actionLabel = "",
    onAction = null,
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

  if (actionLabel && onAction) {
    const actions = article.querySelector(".message-actions")
      || document.createElement("div");
    actions.className = "message-actions";

    const button = document.createElement("button");
    button.type = "button";
    button.className = "message-action-button";
    button.textContent = actionLabel;
    button.addEventListener("click", onAction);
    actions.appendChild(button);

    if (!actions.parentElement) {
      article.appendChild(actions);
    }
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

function openPromptDialog(prefill = "") {
  addPromptText.value = prefill;
  addPromptCategory.value = "";
  promptDialog.showModal();
  requestAnimationFrame(() => addPromptText.focus());
}

function addPromptFromNotFound(query) {
  return () => openPromptDialog(query);
}

function activeMessageContainer() {
  return state.tool === "media" ? mediaMessages : promptMessages;
}

async function submitPromptAddition(event) {
  event.preventDefault();

  const promptText = addPromptText.value.trim();
  if (!promptText) {
    addPromptText.focus();
    return;
  }

  savePromptButton.disabled = true;
  savePromptButton.textContent = "保存中...";

  try {
    const data = await postJson("/api/prompts", {
      prompt_text: promptText,
      category: addPromptCategory.value.trim() || null,
    });
    promptDialog.close();
    appendMessage(
      activeMessageContainer(),
      "assistant",
      data.inserted
        ? "提示词已添加到本地库，可以重新搜索。"
        : "这条提示词已经在本地库中。",
      {
        stateLabel: data.inserted ? "SAVED" : "EXISTS",
      },
    );
    await initializeHealth();
  } catch (error) {
    appendMessage(
      activeMessageContainer(),
      "error",
      error instanceof Error ? error.message : "添加提示词失败。",
    );
  } finally {
    savePromptButton.disabled = false;
    savePromptButton.textContent = "保存到提示词库";
  }
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
  const form = formForTool(tool);
  const button = form.querySelector(".send-button");
  form.classList.toggle("is-busy", busy);
  button.disabled = busy;
}

async function postJson(url, payload, extraHeaders = {}) {
  const send = () =>
    fetch(url, {
      method: "POST",
      headers: authHeaders({
        "Content-Type": "application/json",
        ...extraHeaders,
      }),
      body: JSON.stringify(payload),
    });

  let response = await send();

  if (response.status === 401 && requestAccessCode()) {
    response = await send();
  }

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      data.message || data.detail || "请求失败，请稍后再试。",
    );
  }

  return data;
}

const STAGE_LABELS = {
  intent: "UNDERSTANDING",
  retrieval: "RETRIEVING",
};

function setTypingStage(article, stage) {
  const label = article.querySelector(".message-state");
  const text = STAGE_LABELS[stage];

  if (label && text) {
    label.textContent = text;
  }
}

function parseSseChunk(chunk) {
  let event = "message";
  const dataLines = [];

  chunk.split("\n").forEach((line) => {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  });

  if (!dataLines.length) {
    return null;
  }

  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

async function streamPrompt(message, threadId, onStage, onToken) {
  // 服务端预算是 45s，客户端留一倍余量；否则服务端假死时页面会一直转圈。
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 90000);
  let started = false;

  const send = () =>
    fetch("/api/prompt/stream", {
      method: "POST",
      signal: controller.signal,
      headers: authHeaders({
        "Content-Type": "application/json",
        ...threadHeaders("prompt"),
      }),
      body: JSON.stringify({ message, thread_id: threadId }),
    });

  try {
    let response = await send();

    if (response.status === 401 && requestAccessCode()) {
      response = await send();
    }

    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => ({}));
      throw new Error(
        data.message || data.detail || "请求失败，请稍后再试。",
      );
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result = null;

    for (;;) {
      const { value, done } = await reader.read();

      if (done) {
        break;
      }

      started = true;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");

      while (boundary >= 0) {
        const chunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseSseChunk(chunk);

        if (parsed && parsed.event === "stage") {
          onStage(parsed.data.stage);
        } else if (parsed && parsed.event === "token") {
          onToken(parsed.data.text);
        } else if (parsed && parsed.event === "result") {
          result = parsed.data;
        } else if (parsed && parsed.event === "error") {
          throw new Error(parsed.data.message || "生成失败。");
        }

        boundary = buffer.indexOf("\n\n");
      }
    }

    if (!result) {
      throw new Error("生成中断，请稍后重试。");
    }

    return result;
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new Error("请求超时，请稍后重试。");
    }

    // 已经收到过服务端事件，说明它可能算完了，只是连接被切断。
    if (started) {
      throw new Error(
        "连接中断，服务端可能已生成完成，刷新页面即可查看结果。",
      );
    }

    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function appendStreamingText(article, text) {
  const body = article.querySelector(".message-body");

  if (!body) {
    return;
  }

  let target = body.querySelector(".streaming-text");

  if (!target) {
    // 第一段 token 到达时，把"正在生成"的三个点替换成正文。
    body.replaceChildren();
    target = document.createElement("span");
    target.className = "streaming-text";
    body.appendChild(target);

    const label = article.querySelector(".message-state");

    if (label) {
      label.textContent = "STREAMING";
    }
  }

  target.textContent += text;
  scrollMessages(article.parentElement);
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
    const data = await streamPrompt(
      message,
      state.threadIds.prompt,
      (stage) => setTypingStage(typing, stage),
      (text) => appendStreamingText(typing, text),
    );
    saveThreadId("prompt", data.thread_id, data.thread_token);
    typing.remove();

    if (data.response_type !== "prompt") {
      const notFound = data.response_type === "not_found";
      appendMessage(
        promptMessages,
        "assistant",
        data.reply,
        {
          stateLabel: notFound
            ? "NO MATCH"
            : data.response_type === "clarification"
              ? "CLARIFY"
              : "MESSAGE",
          actionLabel: notFound ? "添加这条提示词" : "",
          onAction: notFound
            ? addPromptFromNotFound(message)
            : null,
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
        actionLabel: "用此提示词直接生图",
        onAction: () => generateFromPrompt(data.prompt),
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

function activateImageMode() {
  state.mediaType = "image";
  stageTabs.forEach((item) => {
    const active = item.dataset.mediaType === "image";
    item.classList.toggle("is-active", active);
    item.setAttribute("aria-selected", String(active));
  });
}

async function renderGeneratedImage(data, fallbackPrompt = "") {
  previewEmpty.hidden = true;
  previewResult.hidden = false;
  previewResult.classList.add("has-image");
  previewImageWrap.hidden = false;
  previewType.textContent = "GENERATED IMAGE";
  previewStatus.textContent = "GENERATED";
  providerNote.textContent = data.image_cached
    ? "OPENAI COMPATIBLE · CACHE HIT"
    : "OPENAI COMPATIBLE · GENERATED";
  previewPrompt.textContent = data.prompt || fallbackPrompt;
  await setPreviewImage(
    data.image_url,
    data.prompt || fallbackPrompt || "生成的图片",
  );
  setImageContext("media", data, previewObjectUrl);
}

async function pollImageJob(jobId) {
  // 生图可能耗时 1~2 分钟，长连接会被网关切断，改成短轮询。
  for (let attempt = 0; attempt < 120; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1500));

    const response = await fetch(`/api/images/jobs/${jobId}`, {
      headers: authHeaders(),
    });

    if (!response.ok) {
      throw new Error("图片任务查询失败。");
    }

    const job = await response.json();

    if (job.status === "done") {
      return job;
    }

    if (job.status === "failed") {
      throw new Error(job.message || "图片生成失败。");
    }
  }

  throw new Error("图片生成超时，请稍后重试。");
}

function setImageEditorStatus(message, isError = false) {
  imageEditorStatus.textContent = message;
  imageEditorStatus.classList.toggle("is-error", isError);
}

function setImageEditorTool(tool) {
  imageEditorState.tool = tool;
  editorTools.forEach((button) => {
    const active = button.dataset.editorTool === tool;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function updateImageEditorAvailability() {
  const hasMarks = imageEditorState.strokes.some(
    (stroke) => stroke.tool === "brush" && stroke.points.length > 0,
  );
  undoImageMark.disabled = imageEditorState.strokes.length === 0;
  clearImageMarks.disabled = imageEditorState.strokes.length === 0;
  applyImageEdit.disabled = imageEditorState.busy || !hasMarks;
}

function configureImageEditorCanvas() {
  if (
    !imageEditorDialog.open
    || !imageEditorSource.naturalWidth
    || !imageEditorSource.naturalHeight
  ) {
    return;
  }

  const rect = imageEditorSource.getBoundingClientRect();
  const pixelRatio = Math.max(1, window.devicePixelRatio || 1);
  imageEditorCanvas.style.width = `${rect.width}px`;
  imageEditorCanvas.style.height = `${rect.height}px`;
  imageEditorCanvas.width = Math.max(1, Math.round(rect.width * pixelRatio));
  imageEditorCanvas.height = Math.max(1, Math.round(rect.height * pixelRatio));
  drawImageEditor();
}

function drawImageEditorStroke(context, stroke, width, height) {
  if (!stroke.points.length) {
    return;
  }

  context.save();
  context.globalCompositeOperation = stroke.tool === "eraser"
    ? "destination-out"
    : "source-over";
  context.strokeStyle = "rgba(217, 119, 87, 0.62)";
  context.fillStyle = "rgba(217, 119, 87, 0.62)";
  context.lineWidth = stroke.brushSize;
  context.lineCap = "round";
  context.lineJoin = "round";

  const points = stroke.points.map((point) => ({
    x: point.x * width,
    y: point.y * height,
  }));

  if (points.length === 1) {
    context.beginPath();
    context.arc(
      points[0].x,
      points[0].y,
      stroke.brushSize / 2,
      0,
      Math.PI * 2,
    );
    context.fill();
  } else {
    context.beginPath();
    context.moveTo(points[0].x, points[0].y);
    points.slice(1).forEach((point) => {
      context.lineTo(point.x, point.y);
    });
    context.stroke();
  }

  context.restore();
}

function drawImageEditor() {
  const context = imageEditorCanvas.getContext("2d");
  const width = imageEditorCanvas.clientWidth;
  const height = imageEditorCanvas.clientHeight;
  const pixelRatio = Math.max(1, window.devicePixelRatio || 1);

  if (!context || !width || !height) {
    return;
  }

  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);
  imageEditorState.strokes.forEach((stroke) => {
    drawImageEditorStroke(context, stroke, width, height);
  });
}

function imageEditorPoint(event) {
  const rect = imageEditorCanvas.getBoundingClientRect();

  return {
    x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
    y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
  };
}

function beginImageMark(event) {
  if (imageEditorState.busy || event.button !== 0) {
    return;
  }

  event.preventDefault();
  imageEditorState.drawing = true;
  imageEditorCanvas.setPointerCapture(event.pointerId);
  imageEditorState.activeStroke = {
    tool: imageEditorState.tool,
    brushSize: imageEditorState.brushSize,
    points: [imageEditorPoint(event)],
  };
  imageEditorState.strokes.push(imageEditorState.activeStroke);
  drawImageEditor();
  setImageEditorStatus("正在标记修改区域");
  updateImageEditorAvailability();
}

function continueImageMark(event) {
  if (!imageEditorState.drawing || !imageEditorState.activeStroke) {
    return;
  }

  event.preventDefault();
  const point = imageEditorPoint(event);
  const points = imageEditorState.activeStroke.points;
  const previous = points[points.length - 1];

  if (Math.hypot(point.x - previous.x, point.y - previous.y) < 0.002) {
    return;
  }

  points.push(point);
  drawImageEditor();
}

function finishImageMark(event) {
  if (!imageEditorState.drawing) {
    return;
  }

  event.preventDefault();
  imageEditorState.drawing = false;
  imageEditorState.activeStroke = null;
  updateImageEditorAvailability();
  setImageEditorStatus("区域已标记，填写修改要求后即可应用");
}

function createImageEditMask() {
  const naturalWidth = imageEditorSource.naturalWidth;
  const naturalHeight = imageEditorSource.naturalHeight;
  const displayRect = imageEditorCanvas.getBoundingClientRect();
  const maskCanvas = document.createElement("canvas");
  const context = maskCanvas.getContext("2d");

  if (
    !context
    || !naturalWidth
    || !naturalHeight
    || !displayRect.width
    || !displayRect.height
  ) {
    throw new Error("图片尚未加载完成。");
  }

  maskCanvas.width = naturalWidth;
  maskCanvas.height = naturalHeight;
  const brushScale = Math.min(naturalWidth, naturalHeight)
    / Math.min(displayRect.width, displayRect.height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, naturalWidth, naturalHeight);

  imageEditorState.strokes.forEach((stroke) => {
    if (!stroke.points.length) {
      return;
    }

    context.save();
    // OpenAI-compatible masks mark the editable area with transparency.
    context.globalCompositeOperation = stroke.tool === "eraser"
      ? "source-over"
      : "destination-out";
    context.strokeStyle = "#ffffff";
    context.fillStyle = "#ffffff";
    context.lineWidth = Math.max(1, stroke.brushSize * brushScale);
    context.lineCap = "round";
    context.lineJoin = "round";
    const points = stroke.points.map((point) => ({
      x: point.x * naturalWidth,
      y: point.y * naturalHeight,
    }));

    if (points.length === 1) {
      context.beginPath();
      context.arc(
        points[0].x,
        points[0].y,
        context.lineWidth / 2,
        0,
        Math.PI * 2,
      );
      context.fill();
    } else {
      context.beginPath();
      context.moveTo(points[0].x, points[0].y);
      points.slice(1).forEach((point) => {
        context.lineTo(point.x, point.y);
      });
      context.stroke();
    }

    context.restore();
  });

  const pixels = context.getImageData(
    0,
    0,
    naturalWidth,
    naturalHeight,
  ).data;
  let hasEditableArea = false;

  for (let index = 3; index < pixels.length; index += 16) {
    if (pixels[index] === 0) {
      hasEditableArea = true;
      break;
    }
  }

  if (!hasEditableArea) {
    throw new Error("请先标记一个需要修改的区域。");
  }

  return maskCanvas.toDataURL("image/png");
}

async function openImageEditor(target) {
  const context = state.imageContexts[target];

  if (!context) {
    return;
  }

  imageEditorState.target = target;
  imageEditorState.context = context;
  imageEditorState.strokes = [];
  imageEditorState.activeStroke = null;
  imageEditorState.drawing = false;
  imageEditorState.busy = false;
  imageEditorState.brushSize = Number(imageBrushSize.value) || 28;
  imageEditInstruction.value = "";
  setImageEditorTool("brush");
  imageBrushSizeLabel.textContent = `${imageEditorState.brushSize} px`;
  setImageEditorStatus("在图片上涂抹要修改的区域");
  imageEditorSource.alt = context.prompt || "待编辑图片";
  imageEditorSource.src = context.objectUrl;
  imageEditorDialog.showModal();

  try {
    await imageEditorSource.decode();
  } catch {
    // The load event will still size the canvas in browsers without decode().
  }

  requestAnimationFrame(() => {
    configureImageEditorCanvas();
    updateImageEditorAvailability();
  });
}

function closeImageEditorDialog() {
  if (!imageEditorState.busy) {
    imageEditorDialog.close();
  }
}

async function applyImageEditorChanges() {
  if (imageEditorState.busy) {
    return;
  }

  const instruction = imageEditInstruction.value.trim();

  if (!instruction) {
    setImageEditorStatus("请填写具体要修改的内容。", true);
    imageEditInstruction.focus();
    return;
  }

  let maskDataUrl = "";

  try {
    maskDataUrl = createImageEditMask();
  } catch (error) {
    setImageEditorStatus(
      error instanceof Error ? error.message : "请先标记修改区域。",
      true,
    );
    return;
  }

  const context = imageEditorState.context;
  imageEditorState.busy = true;
  applyImageEdit.disabled = true;
  closeImageEditor.disabled = true;
  cancelImageEdit.disabled = true;
  setImageEditorStatus("正在提交局部修改任务…");

  try {
    const job = await postJson("/api/images/edits/jobs", {
      prompt: instruction,
      image_url: context.imageUrl,
      mask_data_url: maskDataUrl,
      aspect_ratio: context.aspectRatio || "1:1",
    });
    const data = await pollImageJob(job.job_id);
    const target = imageEditorState.target;

    if (target === "media") {
      await renderGeneratedImage(data, instruction);
      appendMessage(mediaMessages, "assistant", "已按标记区域完成图片修改。", {
        stateLabel: "IMAGE EDITED",
        copyText: instruction,
      });
    } else {
      await setAgentImage(data.image_url, instruction);
      setImageContext("agent", data, agentImageObjectUrl);
      agentResult.hidden = false;
      agentResultText.textContent = instruction;
      appendMessage(agentMessages, "assistant", "已按标记区域完成图片修改。", {
        stateLabel: "IMAGE EDITED",
        copyText: instruction,
      });
    }

    imageEditorDialog.close();
  } catch (error) {
    setImageEditorStatus(
      error instanceof Error ? error.message : "局部修改失败，请稍后重试。",
      true,
    );
  } finally {
    imageEditorState.busy = false;
    closeImageEditor.disabled = false;
    cancelImageEdit.disabled = false;
    updateImageEditorAvailability();
  }
}

async function generateFromPrompt(prompt) {
  if (!prompt || state.busy.media) {
    return;
  }

  activateImageMode();
  switchTool("media");

  // 提示词必须一起带过来：填进输入框、显示在预览区。
  // 生图要等几十秒，只给一个转圈会让人以为提示词丢了。
  mediaInput.value = prompt;
  resizeTextarea(mediaInput);

  appendMessage(mediaMessages, "user", prompt);
  setBusy("media", true);

  previewEmpty.hidden = true;
  previewResult.hidden = false;
  previewResult.classList.remove("has-image");
  previewImageWrap.hidden = true;
  clearPreviewImage();
  previewType.textContent = "IMAGE PROMPT";
  previewStatus.textContent = "RENDERING";
  previewPrompt.textContent = prompt;
  providerNote.textContent = "GENERATION PROVIDER · WORKING";

  const typing = appendTyping(mediaMessages, "RENDERING");

  try {
    const job = await postJson("/api/images/jobs", {
      prompt,
      aspect_ratio: aspectRatio.value,
    });
    const data = await pollImageJob(job.job_id);
    typing.remove();
    await renderGeneratedImage(data, prompt);
    appendMessage(
      mediaMessages,
      "assistant",
      data.image_cached
        ? "已复用缓存图片。"
        : "图片已生成并保存。",
      {
        stateLabel: data.image_cached ? "IMAGE CACHED" : "GENERATED",
        copyText: data.prompt || prompt,
      },
    );
  } catch (error) {
    typing.remove();
    // 失败也把提示词留在预览区，用户可以复制或改完再试
    previewEmpty.hidden = true;
    previewResult.hidden = false;
    previewResult.classList.remove("has-image");
    previewImageWrap.hidden = true;
    clearPreviewImage();
    previewType.textContent = "IMAGE PROMPT";
    previewStatus.textContent = "PROMPT ONLY";
    previewPrompt.textContent = prompt;
    providerNote.textContent = "GENERATION PROVIDER · ERROR";
    appendMessage(
      mediaMessages,
      "error",
      error instanceof Error ? error.message : "图片生成失败。",
    );
  } finally {
    setBusy("media", false);
  }
}

async function renderImageInBackground(prompt) {
  // 提示词先落地，图片交给后台任务渲染，避免长请求被网关切断。
  providerNote.textContent = "GENERATION PROVIDER · RENDERING";

  try {
    const job = await postJson("/api/images/jobs", {
      prompt,
      aspect_ratio: aspectRatio.value,
    });
    const rendered = await pollImageJob(job.job_id);

    previewResult.classList.add("has-image");
    previewImageWrap.hidden = false;
    previewType.textContent = "GENERATED IMAGE";
    previewStatus.textContent = "GENERATED";
    providerNote.textContent = rendered.image_cached
      ? "OPENAI COMPATIBLE · CACHE HIT"
      : "OPENAI COMPATIBLE · GENERATED";
    await setPreviewImage(rendered.image_url, prompt);
    setImageContext(
      "media",
      { ...rendered, prompt },
      previewObjectUrl,
    );

    appendMessage(
      mediaMessages,
      "assistant",
      rendered.image_cached ? "已复用缓存图片。" : "图片已生成并保存。",
      {
        stateLabel: rendered.image_cached ? "IMAGE CACHED" : "GENERATED",
        copyText: prompt,
      },
    );
  } catch (error) {
    providerNote.textContent = "GENERATION PROVIDER · PROMPT ONLY";
    appendMessage(
      mediaMessages,
      "error",
      error instanceof Error ? error.message : "图片生成失败。",
    );
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
  previewResult.classList.remove("has-image");
  previewImageWrap.hidden = true;
  clearPreviewImage();
  providerNote.textContent = "GENERATION PROVIDER · WORKING";
  previewEmptyLabel.textContent = state.mediaType === "image"
    ? "正在生成图片并保存结果…"
    : "正在检索视觉参考并组织提示词…";
  const typing = appendTyping(mediaMessages, "DIRECTING");

  try {
    const data = await postJson(
      "/api/media",
      {
        message,
        media_type: state.mediaType,
        aspect_ratio: aspectRatio.value,
        thread_id: state.threadIds.media,
        render_image: false,
      },
      threadHeaders("media"),
    );
    saveThreadId("media", data.thread_id, data.thread_token);

    typing.remove();

    if (data.response_type !== "prompt") {
      const notFound = data.response_type === "not_found";
      previewEmpty.hidden = false;
      previewResult.hidden = true;
      previewEmptyLabel.textContent = notFound
        ? "未检索到匹配提示词"
        : "等待补充修改方向";
      appendMessage(
        mediaMessages,
        "assistant",
        data.reply,
        {
          stateLabel: notFound
            ? "NO MATCH"
            : data.response_type === "clarification"
              ? "CLARIFY"
              : "MESSAGE",
          actionLabel: notFound ? "添加这条提示词" : "",
          onAction: notFound
            ? addPromptFromNotFound(message)
            : null,
        },
      );
      return;
    }

    previewEmpty.hidden = true;
    previewResult.hidden = false;
    const hasImage = Boolean(data.image_url);

    previewResult.classList.toggle("has-image", hasImage);
    previewImageWrap.hidden = !hasImage;
    previewType.textContent = hasImage
      ? "GENERATED IMAGE"
      : data.media_type === "image"
        ? "IMAGE PROMPT"
        : "VIDEO PROMPT";
    previewStatus.textContent = hasImage
      ? "GENERATED"
      : "PROMPT ONLY";
    providerNote.textContent = hasImage
      ? data.image_cached
        ? "OPENAI COMPATIBLE · CACHE HIT"
        : "OPENAI COMPATIBLE · GENERATED"
      : "GENERATION PROVIDER · PROMPT ONLY";
    previewPrompt.textContent = data.prompt;

    if (hasImage) {
      await setPreviewImage(
        data.image_url,
        data.prompt || "生成的图片",
      );
      setImageContext("media", data, previewObjectUrl);
    } else {
      clearPreviewImage();
    }

    appendMessage(
      mediaMessages,
      "assistant",
      hasImage
        ? `图片已生成。\n\n提示词：${data.prompt}`
        : `最终提示词已生成。\n\n${data.note}`,
      {
        stateLabel: data.image_cached
          ? "IMAGE CACHED"
          : data.cached
            ? "PROMPT CACHED"
            : "LIVE",
        copyText: data.prompt,
        sources: data.sources || [],
      },
    );

    if (!hasImage && state.mediaType === "image" && data.prompt) {
      renderImageInBackground(data.prompt);
    }
  } catch (error) {
    typing.remove();
    previewEmpty.hidden = false;
    previewResult.hidden = true;
    previewResult.classList.remove("has-image");
    previewImageWrap.hidden = true;
    clearPreviewImage();
    providerNote.textContent = "GENERATION PROVIDER · ERROR";
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

function createAgentTraceItem(text, state = "done", statusText = "") {
  const row = document.createElement("li");
  row.className = "agent-trace-item";
  row.dataset.state = state;

  const node = document.createElement("span");
  node.className = "agent-trace-node";
  node.setAttribute("aria-hidden", "true");

  const copy = document.createElement("span");
  copy.className = "agent-trace-copy";
  copy.textContent = text;

  row.append(node, copy);

  if (statusText) {
    const status = document.createElement("span");
    status.className = "agent-trace-state";
    status.textContent = statusText;
    row.appendChild(status);
  }

  return row;
}

function renderAgentTraceList(element, items) {
  element.replaceChildren();

  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "agent-trace-empty";
    empty.textContent = "暂无记录";
    element.appendChild(empty);
    return;
  }

  items.forEach((item) => {
    element.appendChild(createAgentTraceItem(item));
  });
}

function renderAgentTrace(data) {
  const status = String(data.status || "unknown").toLowerCase();
  const steps = Number(data.steps) || 0;
  agentTraceSteps.textContent = `${steps} STEPS`;

  if (status === "completed") {
    setAgentLiveState(
      "任务完成",
      `Agent 已完成本次任务，共执行 ${steps} 个规划步骤。`,
      "success",
    );
  } else if (status === "waiting_user") {
    setAgentLiveState(
      "等待补充",
      "Agent 已暂停，需要你提供更多信息。",
      "waiting",
    );
  } else if (status === "failed") {
    setAgentLiveState(
      "任务中断",
      data.reply || "本次执行没有生成可用结果。",
      "error",
    );
  } else {
    setAgentLiveState(
      "任务收尾",
      "Agent 正在同步最终结果。",
      "running",
    );
  }

  if (!agentDecisions.querySelector(".agent-trace-item")) {
    renderAgentTraceList(
      agentDecisions,
      data.decision_summaries || [],
    );
  }

  if (!agentTools.querySelector(".agent-trace-item")) {
    renderAgentTraceList(agentTools, data.tool_names || []);
  }
}

const AGENT_PHASE_LABELS = {
  planning: "理解目标",
  plan: "制定计划",
  tool: "执行工具",
  evaluate: "校验结果",
  finalize: "整理输出",
  waiting_user: "等待补充",
};

const AGENT_PHASE_DETAILS = {
  planning: "正在理解你的目标，并判断下一步该做什么。",
  plan: "Agent 已形成下一步决策，准备交给执行器。",
  tool: "工具已经返回结果，Agent 正在接收观察结果。",
  evaluate: "正在判断当前结果是否足够，是否需要继续执行。",
  finalize: "执行阶段结束，正在整理可以交付的结果。",
  waiting_user: "任务暂停，需要你补充信息后才能继续。",
};

function setAgentLiveState(label, detail, stateName) {
  agentLiveStatus.dataset.state = stateName;
  agentProgressBar.dataset.state = stateName;
  agentTraceStatus.textContent = label;
  agentTraceDetail.textContent = detail;
}

function appendAgentTraceItem(
  element,
  text,
  state = "done",
  statusText = "",
) {
  const empty = element.querySelector(".agent-trace-empty");

  if (empty) {
    empty.remove();
  }

  const row = createAgentTraceItem(text, state, statusText);
  element.appendChild(row);
  return row;
}

function appendPendingAgentTool(toolName) {
  agentPendingToolRow = appendAgentTraceItem(
    agentTools,
    toolName,
    "running",
    "运行中",
  );
}

function settlePendingAgentTool(event) {
  const row = agentPendingToolRow
    || agentTools.querySelector('.agent-trace-item[data-state="running"]');

  if (!row) {
    return;
  }

  const ok = event.ok === true;
  const elapsed = Number.isFinite(event.elapsed_ms)
    ? ` · ${event.elapsed_ms}ms`
    : "";
  const outcome = ok ? "完成" : (event.error_code || "失败");
  const copy = row.querySelector(".agent-trace-copy");
  const status = row.querySelector(".agent-trace-state");

  row.dataset.state = ok ? "success" : "error";
  copy.textContent = `${event.tool_name || "工具"}${elapsed}`;
  status.textContent = outcome;
  agentPendingToolRow = null;
}

function handleAgentStreamEvent(event) {
  if (event.event === "result") {
    const data = event.data || {};
    const failed = data.status === "failed";
    const steps = Number(data.steps) || 0;
    setAgentLiveState(
      failed ? "任务中断" : "任务完成",
      failed
        ? (data.reply || "本次执行没有生成可用结果。")
        : `结果已整理完成，共执行 ${steps} 个规划步骤。`,
      failed ? "error" : "success",
    );
    return failed ? "FAILED" : "DONE";
  }

  if (event.event === "error") {
    setAgentLiveState(
      "执行中断",
      event.message || "Agent 执行失败，请稍后重试。",
      "error",
    );
    return "ERROR";
  }

  if (event.event === "stage") {
    const label = AGENT_PHASE_LABELS[event.phase]
      || String(event.phase || "RUNNING").toUpperCase();
    setAgentLiveState(
      label,
      event.label || AGENT_PHASE_DETAILS[event.phase]
        || "Agent 正在继续执行。",
      "running",
    );
    return label;
  }

  if (event.event !== "step") {
    return "";
  }

  if (Number.isFinite(event.steps)) {
    agentTraceSteps.textContent = `${event.steps} STEPS`;
  }

  if (event.phase === "plan" && event.reason) {
    appendAgentTraceItem(agentDecisions, event.reason);

    if (event.action === "call_tool" && event.tool_name) {
      appendPendingAgentTool(event.tool_name);
      setAgentLiveState(
        "准备执行",
        `下一步将调用 ${event.tool_name}，等待工具返回结果。`,
        "running",
      );
      return "ACTING";
    }
  }

  if (event.phase === "waiting_user" && event.reason) {
    appendAgentTraceItem(agentDecisions, event.reason);
    setAgentLiveState(
      "等待补充",
      event.reason,
      "waiting",
    );
    return "WAITING";
  }

  if (event.phase === "tool" && event.tool_name) {
    settlePendingAgentTool(event);
    setAgentLiveState(
      event.ok ? "工具完成" : "工具失败",
      event.ok
        ? `${event.tool_name} 已返回结果，Agent 正在读取观察结果。`
        : (event.message || `${event.tool_name} 执行失败。`),
      event.ok ? "success" : "error",
    );
    return event.ok ? "OBSERVING" : "RETRYING";
  }

  if (event.phase === "evaluate") {
    setAgentLiveState(
      "校验结果",
      AGENT_PHASE_DETAILS.evaluate,
      "running",
    );
    return "EVALUATING";
  }

  const label = AGENT_PHASE_LABELS[event.phase] || "RUNNING";
  setAgentLiveState(
    label,
    AGENT_PHASE_DETAILS[event.phase] || "Agent 正在继续执行。",
    "running",
  );
  return label;
}

async function streamAgent(message, threadId, onEvent) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000);

  const send = () =>
    fetch("/api/agent/stream", {
      method: "POST",
      signal: controller.signal,
      headers: authHeaders({
        "Content-Type": "application/json",
        ...threadHeaders("agent"),
      }),
      body: JSON.stringify({
        message,
        thread_id: threadId,
      }),
    });

  try {
    let response = await send();

    if (response.status === 401 && requestAccessCode()) {
      response = await send();
    }

    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => ({}));
      throw new Error(
        data.message || data.detail || "Agent 请求失败。",
      );
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result = null;

    for (;;) {
      const { value, done } = await reader.read();

      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");

      while (boundary >= 0) {
        const chunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseSseChunk(chunk);

        if (parsed && parsed.event === "agent") {
          onEvent(parsed.data);

          if (parsed.data.event === "result") {
            result = parsed.data.data;
          } else if (parsed.data.event === "error") {
            throw new Error(
              parsed.data.message || "Agent 执行失败。",
            );
          }
        } else if (parsed && parsed.event === "error") {
          throw new Error(
            parsed.data.message || "Agent 执行失败。",
          );
        }

        boundary = buffer.indexOf("\n\n");
      }
    }

    if (!result) {
      throw new Error("Agent 连接中断，请刷新页面查看历史。");
    }

    return result;
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new Error("Agent 执行超时，请稍后重试。");
    }

    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function submitAgent(event) {
  event.preventDefault();

  if (state.busy.agent) {
    return;
  }

  const message = agentInput.value.trim();

  if (!message) {
    agentInput.focus();
    return;
  }

  appendMessage(agentMessages, "user", message);
  agentInput.value = "";
  resizeTextarea(agentInput);
  setBusy("agent", true);
  agentPendingToolRow = null;
  setAgentLiveState(
    "准备开始",
    "正在连接 Agent，并读取最近的对话上下文。",
    "running",
  );
  agentTraceSteps.textContent = "0 STEPS";
  renderAgentTraceList(agentDecisions, []);
  renderAgentTraceList(agentTools, []);
  agentResult.hidden = true;
  agentResultText.textContent = "";
  clearAgentImage();
  const typing = appendTyping(agentMessages, "PLANNING");
  const typingStatus = typing.querySelector(".message-state");

  try {
    const data = await streamAgent(
      message,
      state.threadIds.agent,
      (event) => {
        const label = handleAgentStreamEvent(event);

        if (label && typingStatus) {
          typingStatus.textContent = label;
        }
      },
    );
    saveThreadId("agent", data.thread_id);
    typing.remove();
    renderAgentTrace(data);
    agentResult.hidden = false;

    if (data.response_type === "image" && data.image_url) {
      await setAgentImage(
        data.image_url,
        data.prompt || "Agent 生成的图片",
      );
      setImageContext("agent", data, agentImageObjectUrl);
      agentResultText.textContent = data.prompt || data.reply || "";
      appendMessage(
        agentMessages,
        "assistant",
        data.reply || "图片已生成。",
        {
          stateLabel: "IMAGE",
          copyText: data.prompt || "",
        },
      );
      return;
    }

    if (data.response_type === "prompt" && data.prompt) {
      agentResultText.textContent = data.prompt;
      appendMessage(
        agentMessages,
        "assistant",
        data.prompt,
        {
          stateLabel: "PROMPT",
          copyText: data.prompt,
          actionLabel: "用此提示词直接生图",
          onAction: () => generateFromPrompt(data.prompt),
          sources: data.sources || [],
        },
      );
      return;
    }

    agentResultText.textContent = data.reply || "Agent 执行结束。";
    appendMessage(
      agentMessages,
      data.response_type === "failed" ? "error" : "assistant",
      data.reply || "Agent 执行结束。",
      {
        stateLabel: String(data.status || "DONE").toUpperCase(),
        sources: data.sources || [],
      },
    );
  } catch (error) {
    typing.remove();
    setAgentLiveState(
      "执行中断",
      error instanceof Error ? error.message : "Agent 执行失败。",
      "error",
    );
    appendMessage(
      agentMessages,
      "error",
      error instanceof Error ? error.message : "Agent 执行失败。",
    );
  } finally {
    setBusy("agent", false);
    agentInput.focus();
  }
}

function initializeExamples() {
  document.querySelectorAll(".example-chip[data-example]").forEach((button) => {
    button.addEventListener("click", () => {
      promptInput.value = button.dataset.example || "";
      resizeTextarea(promptInput);
      promptInput.focus();
    });
  });

  document.querySelectorAll(".example-chip[data-agent-example]").forEach(
    (button) => {
      button.addEventListener("click", () => {
        agentInput.value = button.dataset.agentExample || "";
        resizeTextarea(agentInput);
        agentInput.focus();
      });
    },
  );
}

function initializeTextareas() {
  [promptInput, mediaInput, agentInput].forEach((textarea) => {
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

      if (state.mediaType !== "image") {
        previewResult.classList.remove("has-image");
        previewImageWrap.hidden = true;
        clearPreviewImage();
      }
    });
  });
}

function initializePromptDialog() {
  addPromptButton.addEventListener("click", () => openPromptDialog());
  cancelPromptDialog.addEventListener("click", () => promptDialog.close());
  addPromptForm.addEventListener("submit", submitPromptAddition);

  promptDialog.addEventListener("click", (event) => {
    if (event.target === promptDialog) {
      promptDialog.close();
    }
  });
}

async function getJson(path) {
  const response = await fetch(path, { headers: authHeaders({}) });

  if (response.status === 401 && requestAccessCode()) {
    return getJson(path);
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "请求失败，请稍后再试。");
  }

  return response.json();
}

function activeTool() {
  return state.tool === "media" || state.tool === "agent"
    ? state.tool
    : "prompt";
}

function formatHistoryTime(value) {
  return typeof value === "string" && value.length >= 16
    ? `${value.slice(5, 10)} ${value.slice(11, 16)}`
    : "";
}

async function refreshConversationList() {
  const tool = activeTool();
  const data = await getJson(`/api/conversations?tool=${tool}`);
  const items = data.items || [];

  historyList.replaceChildren();

  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "dialog-hint";
    empty.textContent = "还没有历史对话，先聊一句再来。";
    historyList.appendChild(empty);
    return;
  }

  items.forEach((item) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "history-item";

    const title = document.createElement("span");
    title.className = "history-item__title";
    title.textContent = item.title || "未命名对话";

    const meta = document.createElement("span");
    meta.className = "history-item__meta";
    meta.textContent =
      `${item.message_count} 条 · ${formatHistoryTime(item.updated_at)}`;

    row.append(title, meta);
    row.addEventListener("click", async () => {
      state.threadIds[tool] = item.thread_id;
      historyDialog.close();
      await loadConversationHistory(tool, item.thread_id);
    });

    historyList.appendChild(row);
  });
}

async function openHistoryDialog() {
  historyDialog.showModal();

  try {
    await refreshConversationList();
  } catch {
    historyList.replaceChildren();
  }
}

async function startNewConversation() {
  const tool = activeTool();
  const container = messageContainer(tool);

  try {
    const data = await postJson("/api/conversations", { tool });
    state.threadIds[tool] = data.thread_id;
    container.replaceChildren();
    historyDialog.close();
    appendMessage(container, "assistant", "新对话已开始。", {
      stateLabel: "NEW",
    });
  } catch (error) {
    appendMessage(
      container,
      "error",
      error instanceof Error ? error.message : "新建对话失败。",
    );
  }
}

async function issueSessionCode() {
  try {
    const data = await postJson("/api/session/code", {});
    sessionCodeValue.textContent = data.code;
    sessionCodeBox.hidden = false;
  } catch (error) {
    window.alert(error instanceof Error ? error.message : "生成会话码失败。");
  }
}

async function copySessionCode() {
  const code = sessionCodeValue.textContent || "";

  if (!code) {
    return;
  }

  try {
    await navigator.clipboard.writeText(code);
    copySessionCodeButton.textContent = "已复制";
    window.setTimeout(() => {
      copySessionCodeButton.textContent = "复制";
    }, 1500);
  } catch {
    restoreCodeInput.value = code;
  }
}

async function restoreSession() {
  const code = restoreCodeInput.value.trim();

  if (!code) {
    return;
  }

  try {
    await postJson("/api/session/restore", { code });
    sessionDialog.close();
    promptMessages.replaceChildren();
    mediaMessages.replaceChildren();
    state.threadIds.prompt = "";
    state.threadIds.media = "";
    agentMessages.replaceChildren();
    state.threadIds.agent = "";
    await bootstrapSession();
    appendMessage(promptMessages, "assistant", "会话已恢复。", {
      stateLabel: "RESTORED",
    });
  } catch (error) {
    window.alert(error instanceof Error ? error.message : "恢复失败。");
  }
}

async function resetSession() {
  try {
    await postJson("/api/session/reset", {});
    sessionDialog.close();
    promptMessages.replaceChildren();
    mediaMessages.replaceChildren();
    agentMessages.replaceChildren();
    state.threadIds.prompt = "";
    state.threadIds.media = "";
    state.threadIds.agent = "";
    await bootstrapSession();
    appendMessage(promptMessages, "assistant", "已切换到新会话。", {
      stateLabel: "NEW SESSION",
    });
  } catch (error) {
    window.alert(error instanceof Error ? error.message : "切换失败。");
  }
}

async function bootstrapSession() {
  try {
    // 服务端会下发 HttpOnly cookie，之后所有请求自动带上
    await getJson("/api/session");
  } catch {
    return;
  }

  await loadConversationHistory("prompt");
  await loadConversationHistory("media");
  await loadConversationHistory("agent");
}

function initializeHistoryDialog() {
  historyButton.addEventListener("click", () => {
    openHistoryDialog();
  });
  closeHistoryDialog.addEventListener("click", () => {
    historyDialog.close();
  });
  newConversationButton.addEventListener("click", () => {
    startNewConversation();
  });
}

function initializeSessionDialog() {
  sessionButton.addEventListener("click", () => {
    sessionDialog.showModal();
    sessionCodeBox.hidden = true;
    sessionCodeValue.textContent = "";
    restoreCodeInput.value = "";
  });
  closeSessionDialog.addEventListener("click", () => {
    sessionDialog.close();
  });
  issueSessionCodeButton.addEventListener("click", () => {
    issueSessionCode();
  });
  copySessionCodeButton.addEventListener("click", () => {
    copySessionCode();
  });
  restoreSessionButton.addEventListener("click", () => {
    restoreSession();
  });
  resetSessionButton.addEventListener("click", () => {
    resetSession();
  });
}

async function loadConversationHistory(tool, threadId) {
  const container = messageContainer(tool);

  try {
    let target = threadId;

    if (!target) {
      const list = await getJson(`/api/conversations?tool=${tool}`);
      const latest = (list.items || [])[0];

      if (!latest) {
        return;
      }

      target = latest.thread_id;
    }

    const data = await getJson(
      `/api/history/${encodeURIComponent(target)}?limit=500`,
    );
    const messages = data.messages || [];

    state.threadIds[tool] = target;

    if (!messages.length && !data.summary) {
      return;
    }

    container.replaceChildren();

    if (data.summary) {
      appendMessage(
        container,
        "assistant",
        `较早对话摘要：${data.summary}`,
        {
          stateLabel: "SUMMARY",
        },
      );
    }

    messages.forEach((message) => {
      appendMessage(
        container,
        message.role,
        message.content,
        {
          stateLabel: message.role === "assistant" ? "HISTORY" : "",
          copyText: message.role === "assistant"
            ? message.content
            : "",
        },
      );
    });
  } catch {
    // Keep the in-memory conversation when history cannot be loaded.
  }
}

async function initializeHealth() {
  const label = systemStatus.querySelector("span:last-child");

  try {
    const response = await fetch("/api/health");

    if (!response.ok) {
      throw new Error("offline");
    }

    const data = await response.json();
    const dbDown = data.db === "down";
    const degraded = data.status !== "ok";

    systemStatus.classList.toggle("is-error", dbDown);
    systemStatus.classList.toggle("is-degraded", degraded && !dbDown);

    if (dbDown) {
      label.textContent = "数据库不可用";
    } else if (degraded) {
      label.textContent = "服务降级运行";
    } else {
      label.textContent = "本地服务在线";
    }

    promptCount.textContent = data.prompt_count
      ? `${data.prompt_count} PROMPTS`
      : "INDEX EMPTY";
  } catch {
    systemStatus.classList.remove("is-degraded");
    systemStatus.classList.add("is-error");
    label.textContent = "服务未连接";
  }
}

toolButtons.forEach((button) => {
  button.addEventListener("click", () => {
    switchTool(button.dataset.tool || "prompt");
  });
});

promptForm.addEventListener("submit", submitPrompt);
mediaForm.addEventListener("submit", submitMedia);
agentForm.addEventListener("submit", submitAgent);

downloadPreviewImage.addEventListener("click", () => {
  downloadImageTarget("media").catch((error) => {
    window.alert(error instanceof Error ? error.message : "图片下载失败。");
  });
});
downloadAgentImage.addEventListener("click", () => {
  downloadImageTarget("agent").catch((error) => {
    window.alert(error instanceof Error ? error.message : "图片下载失败。");
  });
});
copyPreviewPrompt.addEventListener("click", () => {
  copyPromptForTarget("media").catch(() => {
    window.alert("提示词复制失败，请检查浏览器剪贴板权限。");
  });
});
copyAgentPrompt.addEventListener("click", () => {
  copyPromptForTarget("agent").catch(() => {
    window.alert("提示词复制失败，请检查浏览器剪贴板权限。");
  });
});
editPreviewImage.addEventListener("click", () => openImageEditor("media"));
editAgentImage.addEventListener("click", () => openImageEditor("agent"));

editorTools.forEach((button) => {
  button.addEventListener("click", () => {
    setImageEditorTool(button.dataset.editorTool || "brush");
  });
});
imageBrushSize.addEventListener("input", () => {
  imageEditorState.brushSize = Number(imageBrushSize.value) || 28;
  imageBrushSizeLabel.textContent = `${imageEditorState.brushSize} px`;
});
undoImageMark.addEventListener("click", () => {
  imageEditorState.strokes.pop();
  drawImageEditor();
  updateImageEditorAvailability();
  setImageEditorStatus(
    imageEditorState.strokes.length
      ? "已撤销上一笔"
      : "尚未标记区域",
  );
});
clearImageMarks.addEventListener("click", () => {
  imageEditorState.strokes = [];
  imageEditorState.activeStroke = null;
  drawImageEditor();
  updateImageEditorAvailability();
  setImageEditorStatus("尚未标记区域");
});
imageEditorCanvas.addEventListener("pointerdown", beginImageMark);
imageEditorCanvas.addEventListener("pointermove", continueImageMark);
imageEditorCanvas.addEventListener("pointerup", finishImageMark);
imageEditorCanvas.addEventListener("pointercancel", finishImageMark);
imageEditorSource.addEventListener("load", configureImageEditorCanvas);
closeImageEditor.addEventListener("click", closeImageEditorDialog);
cancelImageEdit.addEventListener("click", closeImageEditorDialog);
applyImageEdit.addEventListener("click", applyImageEditorChanges);
imageEditorDialog.addEventListener("cancel", (event) => {
  if (imageEditorState.busy) {
    event.preventDefault();
  }
});

if ("ResizeObserver" in window) {
  const imageEditorResizeObserver = new ResizeObserver(() => {
    if (imageEditorDialog.open) {
      configureImageEditorCanvas();
    }
  });
  imageEditorResizeObserver.observe(imageEditorSource);
}

initializeExamples();
initializeTextareas();
initializeMediaTabs();
initializePromptDialog();
initializeThreadDeletion();
initializeHistoryDialog();
initializeSessionDialog();
initializeHealth();
bootstrapSession();

try {
  const storedTool = localStorage.getItem("prompt-atelier-tool");

  if (
    storedTool === "prompt"
    || storedTool === "media"
    || storedTool === "agent"
  ) {
    switchTool(storedTool);
  }
} catch {
  switchTool("prompt");
}

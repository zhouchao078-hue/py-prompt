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
  threadTokens: {
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
const previewStatus = document.getElementById("previewStatus");
const previewImageWrap = document.getElementById("previewImageWrap");
const previewImage = document.getElementById("previewImage");
const providerNote = document.getElementById("providerNote");
const addPromptButton = document.getElementById("addPromptButton");
const deleteThreadButton = document.getElementById("deleteThreadButton");
const promptDialog = document.getElementById("promptDialog");
const addPromptForm = document.getElementById("addPromptForm");
const addPromptText = document.getElementById("addPromptText");
const addPromptCategory = document.getElementById("addPromptCategory");
const cancelPromptDialog = document.getElementById("cancelPromptDialog");
const savePromptButton = document.getElementById("savePromptButton");

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

function threadHeaders(tool) {
  const token = state.threadTokens[tool] || loadThreadToken(tool);

  if (!token) {
    return {};
  }

  return { "x-thread-token": token };
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

function resetThread(tool) {
  try {
    localStorage.removeItem(`prompt-atelier-thread-${tool}`);
    localStorage.removeItem(`prompt-atelier-thread-token-${tool}`);
  } catch {
    // 存储不可用时只清内存状态
  }

  state.threadIds[tool] = "";
  state.threadTokens[tool] = "";

  const container = tool === "prompt" ? promptMessages : mediaMessages;
  container.replaceChildren();
  appendMessage(container, "assistant", "会话已清空，可以重新开始。", {
    stateLabel: "CLEARED",
  });

  saveThreadId(tool, loadThreadId(tool), loadThreadToken(tool));
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

    if (!response.ok && response.status !== 404) {
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
        tool === "prompt" ? promptMessages : mediaMessages,
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
  const form = tool === "prompt" ? promptForm : mediaForm;
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

function renderGeneratedImage(data, fallbackPrompt = "") {
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
  previewImage.src = data.image_url;
  previewImage.alt = data.prompt || fallbackPrompt || "生成的图片";
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

async function generateFromPrompt(prompt) {
  if (!prompt || state.busy.media) {
    return;
  }

  activateImageMode();
  switchTool("media");
  appendMessage(
    mediaMessages,
    "user",
    "直接使用当前提示词生成图片",
  );
  setBusy("media", true);
  previewEmpty.hidden = false;
  previewResult.hidden = true;
  previewResult.classList.remove("has-image");
  previewImageWrap.hidden = true;
  previewImage.removeAttribute("src");
  previewEmptyLabel.textContent = "正在使用当前提示词生成图片…";
  providerNote.textContent = "GENERATION PROVIDER · WORKING";
  const typing = appendTyping(mediaMessages, "RENDERING");

  try {
    const job = await postJson("/api/images/jobs", {
      prompt,
      aspect_ratio: aspectRatio.value,
    });
    const data = await pollImageJob(job.job_id);
    typing.remove();
    renderGeneratedImage(data, prompt);
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
    previewEmpty.hidden = false;
    previewResult.hidden = true;
    previewResult.classList.remove("has-image");
    previewImageWrap.hidden = true;
    previewImage.removeAttribute("src");
    previewEmptyLabel.textContent = "当前提示词未能生成图片。";
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
    previewImage.src = rendered.image_url;
    previewImage.alt = prompt;

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
  previewImage.removeAttribute("src");
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
      previewImage.src = data.image_url;
      previewImage.alt = data.prompt || "生成的图片";
    } else {
      previewImage.removeAttribute("src");
      previewImage.alt = "";
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
    previewImage.removeAttribute("src");
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

      if (state.mediaType !== "image") {
        previewResult.classList.remove("has-image");
        previewImageWrap.hidden = true;
        previewImage.removeAttribute("src");
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

async function loadConversationHistory(tool) {
  const threadId = state.threadIds[tool];
  if (!threadId) {
    return;
  }

  const container = tool === "prompt" ? promptMessages : mediaMessages;

  try {
    const response = await fetch(
      `/api/history/${encodeURIComponent(threadId)}?limit=500`,
      { headers: authHeaders(threadHeaders(tool)) },
    );
    if (!response.ok) {
      return;
    }

    const data = await response.json();
    const messages = data.messages || [];
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

initializeExamples();
initializeTextareas();
initializeMediaTabs();
initializePromptDialog();
initializeThreadDeletion();
initializeHealth();
saveThreadId("prompt", loadThreadId("prompt"), loadThreadToken("prompt"));
saveThreadId("media", loadThreadId("media"), loadThreadToken("media"));
loadConversationHistory("prompt");
loadConversationHistory("media");

try {
  const storedTool = localStorage.getItem("prompt-atelier-tool");

  if (storedTool === "prompt" || storedTool === "media") {
    switchTool(storedTool);
  }
} catch {
  switchTool("prompt");
}

(function exposeChatState(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AutoEditorChatState = api;
})(typeof globalThis === 'object' ? globalThis : this, function chatStateFactory() {
  'use strict';

  const EVENT_TYPES = Object.freeze([
    'user_message', 'assistant_message',
    'analysis_started', 'analysis_progress', 'analysis_complete',
    'render_started', 'render_progress', 'render_heartbeat',
    'render_complete', 'render_warning', 'render_error', 'render_cancelled',
  ]);
  const EVENT_TYPE_SET = new Set(EVENT_TYPES);
  const SNAPSHOT_SCHEMA = 'autoeditor-chat/v1';
  const MAX_SNAPSHOT_MESSAGES = 500;
  const MAX_SNAPSHOT_LOGS = 200;
  const MAX_SNAPSHOT_TEXT = 20000;
  const MAX_SNAPSHOT_LOG_CHARS = 40000;
  const MAX_SNAPSHOT_CHARS = 450000;

  function createConversationState(options = {}) {
    return {
      platform: options.platform || '',
      messages: [],
      activeAnalysis: null,
      activeRender: null,
      latestResultPath: '',
      sequence: 0,
    };
  }

  function nextId(state, prefix) {
    state.sequence += 1;
    return `${prefix}-${state.sequence}`;
  }

  function nowValue(value) {
    return Number.isFinite(Number(value)) ? Number(value) : Date.now();
  }

  function dispatch(state, event, clock) {
    if (!state || typeof state !== 'object') throw new TypeError('conversation state is required');
    if (!event || !EVENT_TYPE_SET.has(event.type)) {
      throw new Error(`unsupported conversation event: ${event?.type || ''}`);
    }
    const now = nowValue(clock ?? event.at);
    switch (event.type) {
      case 'user_message': {
        const message = {
          id: event.id || nextId(state, 'user'), role: 'user', kind: 'text',
          content: String(event.content || ''),
          attachments: Array.isArray(event.attachments) ? [...event.attachments] : [],
          targetResultPath: String(event.targetResultPath || ''), at: now,
        };
        state.messages.push(message);
        return message;
      }
      case 'assistant_message': {
        const message = {
          id: event.id || nextId(state, 'assistant'), role: 'assistant',
          kind: event.kind || 'text', content: String(event.content || ''),
          sources: Array.isArray(event.sources) ? [...event.sources] : [], at: now,
        };
        state.messages.push(message);
        return message;
      }
      case 'analysis_started': {
        const analysis = {
          id: event.id || nextId(state, 'analysis'), role: 'assistant',
          kind: 'analysis', stage: String(event.stage || 'Inspecting the video locally...'),
          startedAt: now, lastActivityAt: now, logs: [], at: now,
        };
        state.activeAnalysis = analysis;
        state.messages.push(analysis);
        return analysis;
      }
      case 'analysis_progress': {
        const analysis = state.activeAnalysis;
        if (!analysis) return null;
        if (event.stage || event.message) {
          analysis.stage = String(event.message || event.stage);
        }
        if (event.log) analysis.logs.push(String(event.log));
        if (event.engineActivity !== false) analysis.lastActivityAt = now;
        return analysis;
      }
      case 'analysis_complete': {
        const analysis = state.activeAnalysis;
        const message = analysis || {
          id: event.id || nextId(state, 'assistant'), role: 'assistant', at: now,
        };
        message.kind = event.kind || 'text';
        message.content = String(event.content || 'Analysis complete.');
        message.sources = Array.isArray(event.sources) ? [...event.sources] : [];
        message.proposal = event.proposal || null;
        message.canApply = event.canApply === true;
        message.targetResultPath = String(event.targetResultPath || '');
        message.completedAt = now;
        if (!analysis) state.messages.push(message);
        state.activeAnalysis = null;
        return message;
      }
      case 'render_started': {
        const render = {
          id: event.id || nextId(state, 'render'), role: 'assistant', kind: 'render',
          stage: String(event.stage || 'Starting the local edit...'), status: 'running',
          startedAt: nowValue(event.startedAt ?? now),
          lastActivityAt: nowValue(event.lastActivityAt ?? now),
          now, measurable: false, progress: null, logs: [], at: now,
        };
        state.activeRender = render;
        state.messages.push(render);
        return render;
      }
      case 'render_progress': {
        const render = state.activeRender;
        if (!render) return null;
        if (event.stage || event.message) render.stage = String(event.message || event.stage);
        if (event.log) render.logs.push(String(event.log));
        if (event.engineActivity !== false) render.lastActivityAt = now;
        render.now = now;
        if (event.measurable === true && Number.isFinite(Number(event.progress))) {
          render.measurable = true;
          render.progress = Math.max(0, Math.min(100, Math.round(Number(event.progress))));
        } else if (event.measurable === false) {
          render.measurable = false;
          render.progress = null;
        }
        return render;
      }
      case 'render_heartbeat': {
        if (!state.activeRender) return null;
        state.activeRender.now = now;
        return state.activeRender;
      }
      case 'render_complete':
      case 'render_warning': {
        const render = state.activeRender || {
          id: event.id || nextId(state, 'render'), role: 'assistant', logs: [], at: now,
        };
        render.kind = event.type === 'render_warning' ? 'warning' : 'video';
        render.status = event.type === 'render_warning' ? 'needs_review' : 'complete';
        render.content = String(event.content || (event.type === 'render_warning'
          ? 'A playable draft was created, but it needs review.'
          : 'Your edited video is ready. Tell me what you want changed.'));
        render.warning = String(event.warning || '');
        render.videoPath = String(event.videoPath || '');
        render.outputs = event.outputs && typeof event.outputs === 'object'
          ? { ...event.outputs } : {};
        render.completedAt = now;
        render.now = now;
        if (!state.activeRender) state.messages.push(render);
        state.latestResultPath = render.videoPath || state.latestResultPath;
        state.activeRender = null;
        return render;
      }
      case 'render_error': {
        const render = state.activeRender || {
          id: event.id || nextId(state, 'render'), role: 'assistant', logs: [], at: now,
        };
        render.kind = 'error';
        render.status = 'error';
        render.failedStage = String(event.stage || render.stage || 'rendering');
        render.content = String(event.error || 'The render could not finish.');
        render.retry = event.retry !== false;
        render.completedAt = now;
        if (!state.activeRender) state.messages.push(render);
        state.activeRender = null;
        return render;
      }
      case 'render_cancelled': {
        const render = state.activeRender || {
          id: event.id || nextId(state, 'render'), role: 'assistant', logs: [], at: now,
        };
        render.kind = 'cancelled';
        render.status = 'cancelled';
        render.content = String(event.content || 'Render canceled.');
        render.completedAt = now;
        if (!state.activeRender) state.messages.push(render);
        state.activeRender = null;
        return render;
      }
      default:
        return null;
    }
  }

  function formatDuration(milliseconds) {
    const seconds = Math.max(0, Math.floor(Number(milliseconds || 0) / 1000));
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    if (minutes < 1) return `${remainder}s`;
    return `${minutes}m ${String(remainder).padStart(2, '0')}s`;
  }

  function renderTiming(render, clock) {
    const now = nowValue(clock ?? render?.now);
    const startedAt = nowValue(render?.startedAt ?? now);
    const lastActivityAt = nowValue(render?.lastActivityAt ?? startedAt);
    const sinceActivity = Math.max(0, now - lastActivityAt);
    return {
      elapsed: formatDuration(now - startedAt),
      lastActivity: sinceActivity < 1000 ? 'just now' : `${formatDuration(sinceActivity)} ago`,
      stale: sinceActivity >= 60000,
    };
  }

  function liveStatusReply(state, clock, snapshot) {
    const render = state?.activeRender || snapshot || null;
    if (!render) {
      if (state?.latestResultPath) return 'No render is running. The latest video finished and is available above.';
      return 'No render is running right now.';
    }
    const timing = renderTiming(render, clock);
    const stage = String(render.stage || render.message || 'Working on the local edit');
    const activity = timing.stale
      ? `Still working; the last engine update was ${timing.lastActivity}.`
      : `The last engine update was ${timing.lastActivity}.`;
    return `Yes — it is rendering. Current stage: ${stage} Elapsed: ${timing.elapsed}. ${activity}`;
  }

  function isRenderCommand(text) {
    return /^(?:please\s+)?(?:render(?:\s+(?:it|this|these changes))?|start\s+(?:the\s+)?render|go ahead(?:\s+and\s+render)?)\s*[.!]?$/i
      .test(String(text || '').trim());
  }

  function isStatusQuestion(text) {
    return /\b(?:is it rendering|are you rendering|render status|how(?:'s| is) (?:the )?render|is (?:the )?render (?:running|stuck|done)|what(?:'s| is) (?:the )?(?:render )?status)\b/i
      .test(String(text || '').trim());
  }

  function limitedText(value, limit = MAX_SNAPSHOT_TEXT) {
    return typeof value === 'string' ? value.slice(0, limit) : '';
  }

  function snapshotMessage(message) {
    if (!message || typeof message !== 'object' ||
        (message.role !== 'user' && message.role !== 'assistant')) return null;
    const saved = {
      id: limitedText(message.id, 100), role: message.role,
      kind: limitedText(message.kind || 'text', 40),
      content: limitedText(message.content), at: nowValue(message.at),
    };
    for (const key of ['stage', 'status', 'warning', 'videoPath',
      'targetResultPath', 'failedStage']) {
      if (typeof message[key] === 'string') saved[key] = limitedText(message[key]);
    }
    for (const key of ['startedAt', 'lastActivityAt', 'completedAt']) {
      if (Number.isFinite(Number(message[key]))) saved[key] = Number(message[key]);
    }
    if (Array.isArray(message.attachments)) {
      saved.attachments = message.attachments
        .filter((value) => typeof value === 'string').slice(0, 20)
        .map((value) => limitedText(value, 4096));
    }
    if (Array.isArray(message.logs)) {
      saved.logs = message.logs.slice(-MAX_SNAPSHOT_LOGS)
        .filter((value) => typeof value === 'string')
        .map((value) => limitedText(value, 4000));
      let logChars = saved.logs.reduce((sum, value) => sum + value.length, 0);
      while (saved.logs.length && logChars > MAX_SNAPSHOT_LOG_CHARS) {
        logChars -= saved.logs.shift().length;
      }
    }
    if (message.outputs && typeof message.outputs === 'object' &&
        !Array.isArray(message.outputs)) {
      saved.outputs = Object.fromEntries(Object.entries(message.outputs).slice(0, 20)
        .filter(([, value]) => typeof value === 'string')
        .map(([key, value]) => [limitedText(key, 100), limitedText(value, 4096)]));
    }
    if (Array.isArray(message.sources)) {
      saved.sources = message.sources.slice(0, 12).map((source) => ({
        title: limitedText(source?.title || source?.source, 500),
        url: limitedText(source?.url, 2048), date: limitedText(source?.date, 100),
      })).filter((source) => source.url);
    }
    if (message.measurable === true && Number.isFinite(Number(message.progress))) {
      saved.measurable = true;
      saved.progress = Math.max(0, Math.min(100, Math.round(Number(message.progress))));
    } else if (message.kind === 'render') {
      saved.measurable = false;
      saved.progress = null;
    }
    if (message.retry === true) saved.retry = true;
    // Main-process proposal authorization lasts for one launch. Preserve the
    // readable plan, but require a fresh plan before applying after relaunch.
    if (message.canApply === true) saved.canApply = false;
    return saved;
  }

  function conversationSnapshot(state) {
    const sourceMessages = Array.isArray(state?.messages) ? state.messages : [];
    const candidates = sourceMessages.slice(-MAX_SNAPSHOT_MESSAGES)
      .map(snapshotMessage).filter(Boolean);
    const messages = [];
    let snapshotChars = 0;
    for (let index = candidates.length - 1; index >= 0; index -= 1) {
      const candidateChars = JSON.stringify(candidates[index]).length;
      if (messages.length && snapshotChars + candidateChars > MAX_SNAPSHOT_CHARS) break;
      messages.unshift(candidates[index]);
      snapshotChars += candidateChars;
    }
    const offset = Math.max(0, sourceMessages.length - messages.length);
    const activeAnalysisIndex = state?.activeAnalysis
      ? sourceMessages.indexOf(state.activeAnalysis) - offset : -1;
    const activeRenderIndex = state?.activeRender
      ? sourceMessages.indexOf(state.activeRender) - offset : -1;
    return {
      schema: SNAPSHOT_SCHEMA,
      platform: limitedText(state?.platform, 20), messages,
      activeAnalysisIndex: activeAnalysisIndex >= 0 ? activeAnalysisIndex : -1,
      activeRenderIndex: activeRenderIndex >= 0 ? activeRenderIndex : -1,
      latestResultPath: limitedText(state?.latestResultPath, 4096),
      sequence: Number.isSafeInteger(state?.sequence) ? state.sequence : messages.length,
    };
  }

  function restoreConversation(value, options = {}) {
    if (!value || typeof value !== 'object' || value.schema !== SNAPSHOT_SCHEMA ||
        !Array.isArray(value.messages)) return createConversationState(options);
    const state = createConversationState({ platform: options.platform || value.platform });
    state.messages = value.messages.slice(-MAX_SNAPSHOT_MESSAGES)
      .map(snapshotMessage).filter(Boolean);
    const offset = Math.max(0, value.messages.length - state.messages.length);
    const analysisIndex = Number(value.activeAnalysisIndex) - offset;
    const renderIndex = Number(value.activeRenderIndex) - offset;
    if (Number.isSafeInteger(analysisIndex) && analysisIndex >= 0 &&
        state.messages[analysisIndex]?.kind === 'analysis') {
      state.activeAnalysis = state.messages[analysisIndex];
    }
    if (Number.isSafeInteger(renderIndex) && renderIndex >= 0 &&
        state.messages[renderIndex]?.kind === 'render') {
      state.activeRender = state.messages[renderIndex];
    }
    state.latestResultPath = limitedText(value.latestResultPath, 4096);
    state.sequence = Number.isSafeInteger(value.sequence)
      ? Math.max(value.sequence, state.messages.length) : state.messages.length;
    return state;
  }

  return Object.freeze({
    EVENT_TYPES, SNAPSHOT_SCHEMA, createConversationState, dispatch, formatDuration,
    renderTiming, liveStatusReply, isRenderCommand, isStatusQuestion,
    conversationSnapshot, restoreConversation,
  });
});

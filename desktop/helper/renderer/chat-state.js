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

  return Object.freeze({
    EVENT_TYPES, createConversationState, dispatch, formatDuration,
    renderTiming, liveStatusReply, isRenderCommand, isStatusQuestion,
  });
});

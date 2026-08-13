(function exposeViewState(root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AutoEditorViewState = api;
})(typeof globalThis === 'object' ? globalThis : this, function viewStateFactory(root) {
  'use strict';

  const DEFAULT_BOTTOM_THRESHOLD = 64;

  function finiteNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function isNearBottom(transcript, threshold = DEFAULT_BOTTOM_THRESHOLD) {
    if (!transcript) return true;
    const remaining = finiteNumber(transcript.scrollHeight) -
      finiteNumber(transcript.clientHeight) - finiteNumber(transcript.scrollTop);
    return remaining <= Math.max(0, finiteNumber(threshold, DEFAULT_BOTTOM_THRESHOLD));
  }

  function captureTranscriptView(transcript) {
    if (!transcript) {
      return { followBottom: true, scrollTop: 0, openDetails: [], media: {} };
    }
    const openDetails = Array.from(
      transcript.querySelectorAll?.('details[data-details-key][open]') || [],
    ).map((details) => details.dataset?.detailsKey || '')
      .filter(Boolean);
    const media = {};
    Array.from(transcript.querySelectorAll?.('video[data-media-key]') || [])
      .forEach((video) => {
        const key = video.dataset?.mediaKey;
        if (!key) return;
        media[key] = {
          currentTime: Math.max(0, finiteNumber(video.currentTime)),
          muted: Boolean(video.muted),
          volume: Math.max(0, Math.min(1, finiteNumber(video.volume, 1))),
          playbackRate: finiteNumber(video.playbackRate, 1) || 1,
          wasPlaying: video.paused === false && video.ended !== true,
        };
      });
    return {
      followBottom: isNearBottom(transcript),
      scrollTop: Math.max(0, finiteNumber(transcript.scrollTop)),
      openDetails,
      media,
    };
  }

  function restoreVideo(video, saved) {
    if (!video || !saved) return;
    video.muted = saved.muted;
    video.volume = saved.volume;
    video.playbackRate = saved.playbackRate;
    const restoreTime = () => {
      try { video.currentTime = saved.currentTime; }
      catch (_) { /* Metadata may not be available yet. */ }
      if (saved.wasPlaying && typeof video.play === 'function') {
        const playback = video.play();
        if (playback && typeof playback.catch === 'function') playback.catch(() => {});
      }
    };
    if (Number(video.readyState) < 1 && typeof video.addEventListener === 'function') {
      video.addEventListener('loadedmetadata', restoreTime, { once: true });
    } else restoreTime();
  }

  function restoreTranscriptView(transcript, snapshot, options = {}) {
    if (!transcript || !snapshot) return;
    const openDetails = new Set(snapshot.openDetails || []);
    Array.from(transcript.querySelectorAll?.('details[data-details-key]') || [])
      .forEach((details) => {
        details.open = openDetails.has(details.dataset?.detailsKey || '');
      });
    Array.from(transcript.querySelectorAll?.('video[data-media-key]') || [])
      .forEach((video) => restoreVideo(video, snapshot.media?.[video.dataset?.mediaKey]));

    const restoreScroll = () => {
      const maxScroll = Math.max(0,
        finiteNumber(transcript.scrollHeight) - finiteNumber(transcript.clientHeight));
      transcript.scrollTop = options.forceFollow || snapshot.followBottom
        ? maxScroll : Math.min(snapshot.scrollTop, maxScroll);
    };
    restoreScroll();
    if (typeof root?.requestAnimationFrame === 'function') {
      root.requestAnimationFrame(restoreScroll);
    }
  }

  function preserveTranscriptScroll(transcript, mutation) {
    if (!transcript || typeof mutation !== 'function') return false;
    const followBottom = isNearBottom(transcript);
    const scrollTop = Math.max(0, finiteNumber(transcript.scrollTop));
    const restore = () => {
      const maxScroll = Math.max(0,
        finiteNumber(transcript.scrollHeight) - finiteNumber(transcript.clientHeight));
      transcript.scrollTop = followBottom ? maxScroll : Math.min(scrollTop, maxScroll);
    };
    const result = mutation();
    restore();
    if (typeof root?.requestAnimationFrame === 'function') {
      root.requestAnimationFrame(restore);
    }
    return result !== false;
  }

  function updateActivityView(row, message, timingText = '') {
    if (!row || !message) return false;
    const card = row.querySelector?.('.activity-card');
    const stage = card?.querySelector?.('.activity-stage');
    const detailsLog = card?.querySelector?.('.technical-details pre');
    if (!card || !stage || !detailsLog) return false;
    stage.textContent = message.stage || 'Working...';
    const logs = Array.isArray(message.logs) ? message.logs : [];
    detailsLog.textContent = logs.length
      ? logs.join('\n') : 'Waiting for engine output...';

    const timing = card.querySelector?.('.activity-timing');
    if (timing && timingText) timing.textContent = timingText;
    const measurable = message.kind === 'render' && message.measurable === true &&
      Number.isFinite(Number(message.progress));
    const progressWrap = card.querySelector?.('.activity-progress');
    const progress = progressWrap?.querySelector?.('progress');
    const progressLabel = progressWrap?.querySelector?.('.progress-label');
    const working = card.querySelector?.('.working-indicator');
    if (progressWrap) progressWrap.hidden = !measurable;
    if (working) working.hidden = measurable;
    if (measurable && progress && progressLabel) {
      const value = Math.max(0, Math.min(100, Math.round(Number(message.progress))));
      progress.value = value;
      progress.textContent = `${value}%`;
      progressLabel.textContent = `${value}%`;
    }
    return true;
  }

  return Object.freeze({
    DEFAULT_BOTTOM_THRESHOLD, isNearBottom, captureTranscriptView,
    restoreTranscriptView, preserveTranscriptScroll, updateActivityView,
  });
});

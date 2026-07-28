import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {GOLD, WHITE, FONT, bg, strokeShadow} from './brand';

/** Full-frame stat scene: giant gold number counts up over a subtle ring,
 *  label beneath — the "87% OF ASSEMBLY AUTOMATED" moment. */
export const StatViz: React.FC<{value: string; label: string; h: number; w: number}> = ({
  value, label, w, h,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const m = /([\d,.]+)\s*(%|x|k|m)?/i.exec(value ?? '');
  const target = m ? parseFloat(m[1].replace(/,/g, '')) : 0;
  const suffix = m?.[2] ?? '';
  const t = interpolate(frame, [8, Math.round(fps * 1.4)], [0, 1],
                        {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const eased = 1 - Math.pow(1 - t, 3);
  const cur = target * eased;
  const decimals = target < 10 && target % 1 !== 0 ? 1 : 0;
  const shown = cur.toLocaleString('en-US', {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  }) + suffix;
  const fs = Math.round(h * 0.09);
  const inS = spring({frame, fps, config: {damping: 200}});
  const fadeOut = interpolate(frame, [durationInFrames - 12, durationInFrames - 2],
                              [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const ring = Math.min(w, h) * 0.52;
  return (
    <AbsoluteFill style={{...bg, fontFamily: FONT, opacity: fadeOut,
      justifyContent: 'center', alignItems: 'center'}}>
      <div style={{
        position: 'absolute', width: ring, height: ring, borderRadius: '50%',
        border: `3px solid rgba(232,199,167,${0.25 * eased})`,
        transform: `scale(${0.7 + 0.3 * eased})`,
      }} />
      <div style={{
        color: GOLD, fontSize: fs, fontWeight: 900, textShadow: strokeShadow,
        opacity: inS, transform: `translateY(${(1 - inS) * 40}px)`,
      }}>{shown}</div>
      <div style={{
        color: WHITE, fontSize: fs * 0.3, fontWeight: 900, marginTop: 10,
        textShadow: strokeShadow, textAlign: 'center', maxWidth: w * 0.8,
        opacity: interpolate(frame, [12, 26], [0, 1],
          {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
      }}>{label}</div>
    </AbsoluteFill>
  );
};

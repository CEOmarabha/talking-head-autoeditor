import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {GOLD, WHITE, BLACK, FONT, bg, strokeShadow} from './brand';

/** Numbered steps reveal: gold circles + labels slide in — "step 1, step 2,
 *  step 3" while Omar explains a method. */
export const StepsViz: React.FC<{title: string; items: string[]; h: number; w: number}> = ({
  title, items, w, h,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const steps = (items ?? []).slice(0, 5);
  const fs = Math.round(h * 0.030);
  const fadeOut = interpolate(frame, [durationInFrames - 12, durationInFrames - 2],
                              [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const titleIn = spring({frame, fps, config: {damping: 200}});
  return (
    <AbsoluteFill style={{...bg, fontFamily: FONT, opacity: fadeOut}}>
      <div style={{
        position: 'absolute', top: h * 0.15, width: '100%', textAlign: 'center',
        color: GOLD, fontSize: fs * 1.5, fontWeight: 900,
        textShadow: strokeShadow, opacity: titleIn,
      }}>{title}</div>
      <div style={{
        position: 'absolute', top: h * 0.27, left: w * 0.14,
        display: 'flex', flexDirection: 'column', gap: Math.round(h * 0.028),
      }}>
        {steps.map((label, i) => {
          const at = Math.round(fps * (0.5 + i * 0.6));
          const s = spring({frame: frame - at, fps, config: {damping: 15, mass: 0.6}});
          const d = fs * 1.9;
          return (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: fs * 0.8,
              opacity: s, transform: `translateX(${(1 - s) * 70}px)`,
            }}>
              <div style={{
                width: d, height: d, borderRadius: '50%', background: GOLD,
                color: BLACK, fontSize: fs, fontWeight: 900,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: '0 8px 22px rgba(0,0,0,.5)', flexShrink: 0,
              }}>{i + 1}</div>
              <div style={{
                color: WHITE, fontSize: fs, fontWeight: 900,
                textShadow: strokeShadow, maxWidth: w * 0.62,
              }}>{label}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

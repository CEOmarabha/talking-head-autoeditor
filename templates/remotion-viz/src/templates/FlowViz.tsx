import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {GOLD, WHITE, FONT, bg, strokeShadow} from './brand';

/** Process/pipeline flow: title, then boxes assemble one by one with
 *  connecting arrows — "this feeds into this feeds into this". */
export const FlowViz: React.FC<{title: string; items: string[]; h: number; w: number}> = ({
  title, items, w, h,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const boxes = (items ?? []).slice(0, 5);
  const fs = Math.round(h * 0.032);
  const fadeOut = interpolate(frame, [durationInFrames - 12, durationInFrames - 2],
                              [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const titleIn = spring({frame, fps, config: {damping: 200}});
  return (
    <AbsoluteFill style={{...bg, fontFamily: FONT, opacity: fadeOut}}>
      <div style={{
        position: 'absolute', top: h * 0.14, width: '100%', textAlign: 'center',
        color: GOLD, fontSize: fs * 1.5, fontWeight: 900,
        textShadow: strokeShadow, opacity: titleIn,
        transform: `translateY(${(1 - titleIn) * 30}px)`,
      }}>{title}</div>
      <div style={{
        position: 'absolute', top: h * 0.26, width: '100%',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        gap: Math.round(h * 0.012),
      }}>
        {boxes.map((label, i) => {
          const at = Math.round(fps * (0.5 + i * 0.55));
          const s = spring({frame: frame - at, fps, config: {damping: 16, mass: 0.7}});
          return (
            <React.Fragment key={i}>
              {i > 0 && (
                <div style={{
                  color: GOLD, fontSize: fs * 1.1, lineHeight: 1,
                  opacity: interpolate(frame, [at - 6, at], [0, 1],
                    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
                }}>▼</div>
              )}
              <div style={{
                minWidth: w * 0.56, padding: `${fs * 0.55}px ${fs * 1.1}px`,
                border: `3px solid ${GOLD}`, borderRadius: fs * 0.45,
                background: 'rgba(20,20,20,0.92)',
                color: WHITE, fontSize: fs, fontWeight: 900, textAlign: 'center',
                textShadow: strokeShadow,
                boxShadow: '0 10px 30px rgba(0,0,0,.55)',
                opacity: s, transform: `scale(${0.85 + 0.15 * s})`,
              }}>{label}</div>
            </React.Fragment>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

import React from 'react';
import {Composition} from 'remotion';
import {FlowViz} from './templates/FlowViz';
import {StepsViz} from './templates/StepsViz';
import {StatViz} from './templates/StatViz';

// Shared metadata: duration/size come from --props so hermes-pse-edit
// controls everything per render. fps is locked to 30 (pipeline standard).
const meta = ({props}: {props: any}) => ({
  durationInFrames: Math.max(45, Math.round((props.durSec ?? 4) * 30)),
  width: props.w ?? 1080,
  height: props.h ?? 1920,
});

const defaults = {
  durSec: 4,
  w: 1080,
  h: 1920,
  title: 'THE SYSTEM',
  items: ['INPUT', 'PROCESS', 'OUTPUT'],
  value: '87%',
  label: 'AUTOMATED',
};

export const Root: React.FC = () => (
  <>
    <Composition id="FlowViz" component={FlowViz} fps={30}
      durationInFrames={120} width={1080} height={1920}
      defaultProps={defaults} calculateMetadata={meta} />
    <Composition id="StepsViz" component={StepsViz} fps={30}
      durationInFrames={120} width={1080} height={1920}
      defaultProps={defaults} calculateMetadata={meta} />
    <Composition id="StatViz" component={StatViz} fps={30}
      durationInFrames={120} width={1080} height={1920}
      defaultProps={defaults} calculateMetadata={meta} />
  </>
);

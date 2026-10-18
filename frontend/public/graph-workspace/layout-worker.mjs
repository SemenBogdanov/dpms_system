import { arrangeGraph } from './layout-engine.mjs';

self.onmessage = ({ data }) => {
  const requestId = data?.requestId;
  try {
    const result = arrangeGraph(data?.input);
    self.postMessage({ requestId, result });
  } catch (error) {
    self.postMessage({ requestId, error: error instanceof Error ? error.message : 'Graph layout failed' });
  }
};

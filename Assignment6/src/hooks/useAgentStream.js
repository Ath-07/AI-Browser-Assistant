import { useState, useRef, useCallback } from 'react';

export default function useAgentStream() {
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState(null);
  const [result, setResult] = useState(null);
  const wsRef = useRef(null);

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const connect = useCallback((taskId) => {
    disconnect();
    setLogs([]);
    setStatus('pending');
    setResult(null);

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const url = `${protocol}//${host}/ws/status/${taskId}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'done') {
          setStatus(data.status);
          setResult(data.result);
          ws.close();
          return;
        }
      } catch {
        // plain text log message
      }
      setLogs((prev) => [...prev, event.data]);
    };

    ws.onerror = () => {
      setLogs((prev) => [...prev, '[WebSocket error]']);
    };

    ws.onclose = () => {
      wsRef.current = null;
    };
  }, [disconnect]);

  return { logs, status, result, connect, disconnect };
}

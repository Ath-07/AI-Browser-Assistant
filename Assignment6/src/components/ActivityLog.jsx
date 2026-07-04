import { useEffect, useRef } from 'react';

export default function ActivityLog({ logs, status, result, taskId }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  if (!taskId) {
    return (
      <div className="rounded border border-gray-700 bg-gray-800 p-4 text-sm text-gray-500">
        No active task. Submit a command above.
      </div>
    );
  }

  return (
    <div className="rounded border border-gray-700 bg-gray-800">
      <div className="border-b border-gray-700 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
        Activity Log
        {status && (
          <span
            className={`ml-2 font-normal normal-case ${
              status === 'completed'
                ? 'text-green-400'
                : status === 'failed'
                ? 'text-red-400'
                : 'text-yellow-400'
            }`}
          >
            [{status}]
          </span>
        )}
      </div>

      <div className="max-h-80 overflow-y-auto p-4 space-y-1 font-mono text-xs">
        {logs.length === 0 && (
          <p className="text-gray-500 italic">Waiting for logs…</p>
        )}
        {logs.map((msg, i) => (
          <div key={i} className="text-gray-300 break-words">
            {msg}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {result && (
        <div className="border-t border-gray-700 px-4 py-2">
          <span className="text-xs font-semibold text-gray-400">Result: </span>
          <span className="text-sm text-green-300">{result}</span>
        </div>
      )}
    </div>
  );
}

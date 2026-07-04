import { useState } from 'react';
import CommandBar from './components/CommandBar';
import ActivityLog from './components/ActivityLog';
import ProfileSettings from './components/ProfileSettings';
import useAgentStream from './hooks/useAgentStream';

export default function App() {
  const [taskId, setTaskId] = useState(null);
  const [error, setError] = useState(null);
  const { logs, status, result, connect, disconnect } = useAgentStream();

  const handleCommand = async (command) => {
    setError(null);
    disconnect();
    try {
      const resp = await fetch('/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text_command: command }),
      });
      if (!resp.ok) {
        const msg = `Backend returned ${resp.status}`;
        setError(msg);
        return;
      }
      const data = await resp.json();
      setTaskId(data.task_id);
      connect(data.task_id);
    } catch (err) {
      setError(`Cannot reach backend — is the FastAPI server running? (${err.message})`);
    }
  };

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <header className="border-b border-gray-700 pb-4">
        <h1 className="text-2xl font-bold tracking-tight">Agent Console</h1>
        <p className="text-sm text-gray-400">Assignment 6 — Full-Stack Agent UI</p>
      </header>

      {error && (
        <div className="rounded border border-red-600 bg-red-900/50 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      <main className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 space-y-4">
          <CommandBar onSend={handleCommand} />
          <ActivityLog logs={logs} status={status} result={result} taskId={taskId} />
        </section>

        <aside>
          <ProfileSettings onError={setError} />
        </aside>
      </main>
    </div>
  );
}

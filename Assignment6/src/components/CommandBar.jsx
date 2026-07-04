import { useState } from 'react';

export default function CommandBar({ onSend }) {
  const [value, setValue] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setValue('');
  };

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Type a command… (e.g. go to google.com)"
        className="flex-1 rounded bg-gray-800 border border-gray-600 px-4 py-2 text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      <button
        type="submit"
        className="rounded bg-blue-600 px-5 py-2 text-sm font-medium hover:bg-blue-500 transition-colors"
      >
        Send
      </button>
    </form>
  );
}

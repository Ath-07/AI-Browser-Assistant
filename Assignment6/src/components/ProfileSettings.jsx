import { useState, useEffect } from 'react';

const INITIAL = { name: '', email: '', phone: '', address: '', resume_text: '' };

export default function ProfileSettings({ onError }) {
  const [form, setForm] = useState(INITIAL);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const resp = await fetch('/user/profile');
        if (resp.ok) {
          const data = await resp.json();
          setForm(data);
        }
      } catch (err) {
        onError?.(`Cannot reach backend — is the FastAPI server running? (${err.message})`);
      }
    })();
  }, []);

  const handleChange = (e) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setMessage('');
    try {
      const resp = await fetch('/user/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (resp.ok) {
        setMessage('Profile saved');
      } else {
        setMessage('Failed to save');
      }
    } catch (err) {
      setMessage('Network error');
      onError?.(`Cannot reach backend — is the FastAPI server running? (${err.message})`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded border border-gray-700 bg-gray-800 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3">
        Profile Settings
      </h2>

      <form onSubmit={handleSubmit} className="space-y-3">
        {(['name', 'email', 'phone', 'address', 'resume_text']).map((field) => (
          <div key={field}>
            <label className="block text-xs text-gray-400 mb-1 capitalize">
              {field.replace('_', ' ')}
            </label>
            {field === 'resume_text' ? (
              <textarea
                name={field}
                value={form[field]}
                onChange={handleChange}
                rows={3}
                className="w-full rounded bg-gray-900 border border-gray-600 px-3 py-1.5 text-xs placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
            ) : (
              <input
                type={field === 'email' ? 'email' : 'text'}
                name={field}
                value={form[field]}
                onChange={handleChange}
                className="w-full rounded bg-gray-900 border border-gray-600 px-3 py-1.5 text-xs placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            )}
          </div>
        ))}

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded bg-green-700 py-2 text-xs font-medium hover:bg-green-600 disabled:opacity-50 transition-colors"
        >
          {loading ? 'Saving…' : 'Save Profile'}
        </button>

        {message && (
          <p className="text-xs text-center text-gray-300">{message}</p>
        )}
      </form>
    </div>
  );
}

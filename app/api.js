import { API_BASE_URL } from './config';

async function request(path, options = {}) {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const details = data.error || data.detail;
      throw new Error(typeof details === 'string' ? details : `Server error (${response.status})`);
    }
    return data;
  } catch (error) {
    if (error instanceof TypeError || error.message === 'Network request failed') {
      throw new Error('Cannot reach Sebastian’s backend. Make sure both phones and the server are on the same Wi-Fi.');
    }
    throw error;
  }
}

function postJSON(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export const getExpenses = () => request('/expenses');
export const getLimits = () => request('/limits');
export const saveLimit = (category, limitCents) => postJSON('/limits', { category, limitCents });
export const getSettings = () => request('/settings');
export const saveSettings = (settings) => postJSON('/settings', settings);

export function logTextExpense(text) {
  const form = new FormData();
  form.append('source', 'voice');
  form.append('text', text);
  // React Native sets the multipart boundary; do not set Content-Type manually.
  return request('/log-expense', { method: 'POST', body: form });
}

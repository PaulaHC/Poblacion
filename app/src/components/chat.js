import { API_BASE } from '../config.js';

export function mountChat() {
  const messages = document.getElementById('chat-messages');
  const form     = document.getElementById('chat-form');
  const input    = document.getElementById('chat-input');
  const btnOpen  = document.getElementById('btn-toggle-chat');
  const btnClose = document.getElementById('btn-close-chat');

  if (!form || !messages) return; 

  // Drawer (móvil/tablet)
  btnOpen ?.addEventListener('click', () => document.body.classList.add('chat-open'));
  btnClose?.addEventListener('click', () => document.body.classList.remove('chat-open'));

  // Sugerencias clicables
  messages.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (chip) {
      input.value = chip.dataset.prompt;
      form.requestSubmit();
    }
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    addMessage('user', text);

    const typing = addMessage('assistant typing', 'Pensando…');

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) throw new Error('chat ' + res.status);
      const data = await res.json();
      typing.remove();
      addMessage('assistant', data.text || '(sin respuesta)');
    } catch (err) {
      typing.remove();
      addMessage('assistant', 'Lo siento, no he podido responder. Comprueba que el servicio de chat está disponible.');
      console.error(err);
    }
  });

  function addMessage(role, text) {
    const welcome = messages.querySelector('.chat__welcome');
    if (welcome) welcome.remove();

    const div = document.createElement('div');
    const base = role === 'user' ? 'user'
               : role.startsWith('assistant typing') ? 'assistant'
               : 'assistant';
    div.className = `chat__msg chat__msg--${base}` +
                    (role.includes('typing') ? ' chat__msg--typing' : '');
    div.textContent = text;

    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }
}
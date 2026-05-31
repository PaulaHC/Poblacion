import { API_BASE } from '../config.js';
import { setState } from '../state/store.js';

export function mountChat() {
  const messages = document.getElementById('chat-messages');
  const form     = document.getElementById('chat-form');
  const input    = document.getElementById('chat-input');
  const btnOpen  = document.getElementById('btn-toggle-chat');
  const btnClose = document.getElementById('btn-close-chat');

  if (!form || !messages) return; // si quitas el chat del HTML, no rompe nada

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
      addMessage('assistant', data.text || '(sin respuesta)', data.action);
    } catch (err) {
      typing.remove();
      addMessage('assistant', 'Lo siento, no he podido responder. Comprueba que el servicio de chat está disponible.');
      console.error(err);
    }
  });

  function addMessage(role, text, action) {
    const welcome = messages.querySelector('.chat__welcome');
    if (welcome) welcome.remove();

    const div = document.createElement('div');
    const cls = role === 'user' ? 'user'
              : role.startsWith('assistant typing') ? 'assistant chat__msg--typing'
              : 'assistant';
    div.className = `chat__msg chat__msg--${cls.split(' ')[0]}` +
                    (cls.includes('typing') ? ' chat__msg--typing' : '');
    div.textContent = text;

    if (action && action.type) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chat__msg__action';
      btn.textContent = action.label || 'Ver en el mapa';
      btn.addEventListener('click', () => applyAction(action));
      div.appendChild(document.createElement('br'));
      div.appendChild(btn);
    }

    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  function applyAction(action) {
    switch (action.type) {
      case 'setFilter':
        if (action.filters) setState(action.filters);
        break;
      case 'focusProvincia':
        setState({ provincia: String(action.id) });
        break;
      case 'focusMunicipio':
        setState({ municipio: String(action.id) });
        break;
      default:
        console.warn('[chat] acción desconocida', action);
    }
  }
}

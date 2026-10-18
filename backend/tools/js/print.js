export function onReady(callback) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', callback, { once: true });
  } else {
    callback();
  }
}

export function qs(selector, root = document) {
  return root.querySelector(selector);
}

export function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

export function getPageType() {
  return document.body?.dataset?.pageType
    || document.body?.dataset?.printType
    || document.body?.dataset?.pageType || 'generic';
}

export function formatDate(date, options = {}) {
  const value = date instanceof Date ? date : new Date(date);
  return new Intl.DateTimeFormat('ja-JP', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    ...options,
  }).format(value);
}

export function escapeHtml(value = '') {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function createElement(tag, attrs = {}, children = []) {
  const element = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (value === null || value === undefined) return;
    if (key === 'className') {
      element.className = value;
      return;
    }
    element.setAttribute(key, value);
  });

  children.forEach((child) => {
    if (typeof child === 'string') {
      element.insertAdjacentHTML('beforeend', child);
      return;
    }
    if (child instanceof Node) {
      element.appendChild(child); 
    }
  });

  return element;
}

export function getDataAttributes(node) {
  if (!node) return {};
  return Object.fromEntries(
    Array.from(node.attributes)
      .filter((attr) => attr.name.startsWith('data-'))
      .map((attr) => [attr.name.replace(/^data-/, ''), attr.value])
  );
}

export function toCurrency(value) {
  return Number(value || 0).toLocaleString('ja-JP');
}

export function safeParseJSON(value, fallback = {}) {
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

export function readLocalStorage(key, fallback = null) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? safeParseJSON(raw, fallback) : fallback;
  } catch {
    return fallback;
  }
}

export function writeLocalStorage(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

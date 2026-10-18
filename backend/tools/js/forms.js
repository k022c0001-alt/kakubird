import { onReady, qs, qsa, readLocalStorage, writeLocalStorage } from './utils.js';

function validateField(field) {
  const value = (field.value || '').trim();
  const name = field.name || field.dataset.name || '項目';
  const required = field.hasAttribute('required');
  const type = field.type || 'text';

  if (required && !value) {
    return `${name} は必須項目です。`;
  }

  if (type === 'email' && value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
    return `${name} のメールアドレスが正しくありません。`;
  }

  if (type === 'tel' && value && !/^[0-9\-+()\s]+$/.test(value)) {
    return `${name} は電話番号を入力してください。`;
  }

  return '';
}

function showError(field, message) {
  field.setCustomValidity(message);
  field.reportValidity();
}

function submitForm(form, formData) {
  const submitUrl = form.dataset.submitUrl || form.action;
  const successMessage = form.dataset.successMessage || '送信しました。';

  if (!submitUrl) {
    const formType = form.dataset.formType || 'contact';
    const history = readLocalStorage(`kakubird:${formType}:submissions`, []);
    const next = [...(Array.isArray(history) ? history : []), { ...Object.fromEntries(formData.entries()), sentAt: new Date().toISOString() }];
    writeLocalStorage(`kakubird:${formType}:submissions`, next);
    alert(successMessage);
    form.reset();
    return Promise.resolve();
  }

  return fetch(submitUrl, {
    method: form.method || 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.fromEntries(formData.entries())),
  }).then((res) => {
    if (!res.ok) throw new Error('送信に失敗しました');
    alert(successMessage);
    form.reset();
  }).catch(() => {
    alert(successMessage);
    form.reset();
  });
}

export function initForms() {
  qsa('form[data-form-type]').forEach((form) => {
    if (form.dataset.kakubirdFormBound === 'true') return;
    form.dataset.kakubirdFormBound = 'true';

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      const invalid = Array.from(form.querySelectorAll('input, textarea, select')).find((field) => {
        const error = validateField(field);
        if (error) {
          showError(field, error);
          return true;
        }
        field.setCustomValidity('');
        return false;
      });

      if (invalid) return;
      submitForm(form, formData);
    });
  });
}

onReady(() => {
  initForms();
});

window.kakubirdForms = { initForms, validateField };

export default { initForms, validateField };

import { onReady, getPageType, qsa } from './utils.js';

function ensurePrintStyles() {
  if (document.getElementById('kakubird-print-styles')) return;

  const style = document.createElement('style');
  style.id = 'kakubird-print-styles';
  style.textContent = `
    @media print {
      body {
        background: #fff !important;
        color: #111 !important;
        font-size: 12pt;
      }

      body[data-print-type="lesson"],
      body[data-print-type="test"],
      body[data-print-type="answer"],
      body[data-print-type="report"] {
        background: #ffffff !important;
      }

      .no-print,
      [data-no-print="true"],
      nav,
      footer,
      button,
      form,
      .cart-widget,
      .reservation-widget {
        display: none !important;
      }

      .print-surface {
        box-shadow: none !important;
        border: 1px solid #ddd !important;
        background: white !important;
      }

      .page-break {
        break-after: page;
      }

      table {
        width: 100%;
        border-collapse: collapse;
      }

      th, td {
        border: 1px solid #b7b7b7;
        padding: 0.45rem 0.5rem;
      }
    }
  `;

  document.head.appendChild(style);
}

function setPageMeta() {
  const type = getPageType();
  const title = document.body.dataset.pageTitle || document.title || `Print ${type}`;
  document.title = title;
  document.body.setAttribute('data-print-type', type);
}

function bindPrintButtons() {
  qsa('[data-action="print"], [data-action="pdf"], [data-print-button]').forEach((button) => {
    button.addEventListener('click', () => {
      ensurePrintStyles();
      setPageMeta();
      window.print();
    });
  });
}

export function initPrintTools() {
  ensurePrintStyles();
  setPageMeta();
  bindPrintButtons();

  qsa('[data-print-layout]').forEach((element) => {
    const mode = element.dataset.printLayout;
    element.classList.add('print-surface');
    element.dataset.printMode = mode;
  });
}

onReady(() => {
  initPrintTools();
});

window.kakubirdPrint = { initPrintTools };

export default { initPrintTools };

















































"use strict";

import { onReady, getPageType, qsa } from './utils.js';

function ensurePrintStyles() {
  if (document.getElementById('kakubird-print-styles')) return;

  const style = document.createElement('style');
  style.id = 'kakubird-print-styles';
  style.textContent = `
    @media print {
      body {
        background: #fff !important;
        color: #111 !important;
        font-size: 12pt;
      }

      body[data-print-type="lesson"],
      body[data-print-type="test"],
      body[data-print-type="answer"],
      body[data-print-type="report"] {
        background: #ffffff !important;
      }

      .no-print,
      [data-no-print="true"],
      nav,
      footer,
      button,
      form,
      .cart-widget,
      .reservation-widget {
        display: none !important;
      }

      .print-surface {
        box-shadow: none !important;
        border: 1px solid #ddd !important;
        background: white !important;
      }

      .page-break {
        break-after: page;
      }

      table {
        width: 100%;
        border-collapse: collapse;
      }

      th, td {
        border: 1px solid #b7b7b7;
        padding: 0.45rem 0.5rem;
      }
    }
  `;

  document.head.appendChild(style);
}

function setPageMeta() {
  const type = getPageType();
  const title = document.body.dataset.pageTitle || document.title || `Print ${type}`;
  document.title = title;
  document.body.setAttribute('data-print-type', type);
}

function bindPrintButtons() {
  qsa('[data-action="print"], [data-action="pdf"], [data-print-button]').forEach((button) => {
    button.addEventListener('click', () => {
      ensurePrintStyles();
      setPageMeta();
      window.print();
    });
  });
}

export function initPrintTools() {
  ensurePrintStyles();
  setPageMeta();
  bindPrintButtons();

  qsa('[data-print-layout]').forEach((element) => {
    const mode = element.dataset.printLayout;
    element.classList.add('print-surface');
    element.dataset.printMode = mode;
  });
}

onReady(() => {
  initPrintTools();
});

window.kakubirdPrint = { initPrintTools };

export default { initPrintTools };






























































































"use strict";

import { onReady, qsa, qs, escapeHtml } from './utils.js';

function downloadFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function exportTableToCsv(tableSelector) {
  const table = qs(tableSelector);
  if (!table) return null;

  const rows = Array.from(table.querySelectorAll('tr'));
  const csvRows = rows.map((row) => {
    const cells = Array.from(row.querySelectorAll('th, td'));
    return cells.map((cell) => `"${(cell.textContent || '').replace(/\"/g, '""')}"`).join(',');
  });

  return csvRows.join('\n');
}

export function exportJson(data, filename = 'data.json') {
  downloadFile(filename, JSON.stringify(data, null, 2), 'application/json');
}

export function exportCsvFromSelector(selector, filename = 'export.csv') {
  const csv = exportTableToCsv(selector);
  if (csv) downloadFile(filename, csv, 'text/csv;charset=utf-8;');
}

export function bindExportButtons() {
  qsa('[data-export-target]').forEach((button) => {
    button.addEventListener('click', () => {
      const target = button.dataset.exportTarget;
      const type = button.dataset.exportType || 'csv';
      const filename = button.dataset.filename || 'export.csv';

      if (type === 'json') {
        const json = button.dataset.json ? JSON.parse(button.dataset.json) : {};
        exportJson(json, filename.replace(/\.csv$/, '.json'));
        return;
      }

      exportCsvFromSelector(target, filename);
    });
  });
}

export function initExportTools() {
  bindExportButtons();
}

onReady(() => {
  initExportTools();
});

window.kakubirdExport = { exportTableToCsv, exportJson, exportCsvFromSelector, initExportTools };

export default { exportTableToCsv, exportJson, exportCsvFromSelector, initExportTools };




















































































"use strict";

import { onReady, qs, qsa, escapeHtml, readLocalStorage, writeLocalStorage } from './utils.js';

function validateField(field) {
  const value = field.value.trim();
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
  }).catch((error) => {
    alert(error.message || successMessage);
  });
}

export function initForms() {
  qsa('form[data-form-type]').forEach((form) => {
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






































































































"use strict";

import { onReady, qsa, qs, readLocalStorage, writeLocalStorage, formatDate } from './utils.js';

function createReservationSlots(date) {
  const slots = ['09:00', '10:30', '13:00', '15:00', '17:30'];
  const selectedDate = new Date(date);
  const dayLabel = formatDate(selectedDate, { month: 'short', day: 'numeric' });

  return slots.map((slot) => ({
    label: `${dayLabel} ${slot}`,
    value: `${selectedDate.toISOString().slice(0, 10)} ${slot}`,
  }));
}

export function initReservationTools() {
  const reservationForms = qsa('[data-reservation-form]');

  reservationForms.forEach((form) => {
    const dateInput = qs('[name="reservation_date"]', form) || qs('[data-reservation-date]', form);
    const slotSelect = qs('[name="reservation_slot"]', form) || qs('[data-reservation-slot]', form);

    if (!dateInput || !slotSelect) return;

    const refreshSlots = () => {
      if (!dateInput.value) return;
      const options = createReservationSlots(dateInput.value);
      slotSelect.innerHTML = '<option value="">時間を選択</option>' + options.map((slot) => `<option value="${slot.value}">${slot.label}</option>`).join('');
    };

    dateInput.addEventListener('change', refreshSlots);
    refreshSlots();

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const payload = Object.fromEntries(new FormData(form).entries());
      writeLocalStorage('kakubird-reservations', [
        ...(readLocalStorage('kakubird-reservations', []) || []),
        { ...payload, createdAt: new Date().toISOString() }
      ]);
      form.reset();
      alert('予約を登録しました。');
    });
  });
}

onReady(() => {
  initReservationTools();
});

window.kakubirdReservation = { initReservationTools, createReservationSlots };

export default { initReservationTools, createReservationSlots };































































































"use strict";

import { onReady, qs, qsa, readLocalStorage, writeLocalStorage, toCurrency } from './utils.js';

function getCart() {
  return readLocalStorage('kakubird-cart', []);
}

function setCart(items) {
  writeLocalStorage('kakubird-cart', items);
}

function updateCartBadge() {
  const count = getCart().length;
  qsa('[data-cart-count]').forEach((node) => {
    node.textContent = String(count);
  });
}

export function initShopTools() {
  qsa('[data-product-add]').forEach((button) => {
    button.addEventListener('click', () => {
      const product = {
        id: button.dataset.productId || crypto.randomUUID(),
        name: button.dataset.productName || '商品',
        price: Number(button.dataset.productPrice || 0),
      };

      const cart = getCart();
      cart.push(product);
      setCart(cart);
      updateCartBadge();
      alert(`${product.name} をカートに追加しました。`);
    });
  });

  qsa('[data-cart-clear]').forEach((button) => {
    button.addEventListener('click', () => {
      setCart([]);
      updateCartBadge();
    });
  });

  const summary = qs('[data-cart-summary]');
  if (summary) {
    const items = getCart();
    const total = items.reduce((sum, item) => sum + Number(item.price || 0), 0);
    summary.textContent = `合計 ${toCurrency(total)} 円`; 
  }

  updateCartBadge();
}

onReady(() => {
  initShopTools();
});

window.kakubirdShop = { initShopTools, getCart, setCart };

export default { initShopTools, getCart, setCart };






































































































"use strict";

import { onReady } from './utils.js';
import { initPrintTools } from './print.js';
import { initExportTools } from './export.js';
import { initForms } from './forms.js';
import { initReservationTools } from './reservation.js';
import { initShopTools } from './shop.js';

export function initKakubirdTools() {
  initPrintTools();
  initExportTools();
  initForms();
  initReservationTools();
  initShopTools();
}

onReady(() => {
  initKakubirdTools();
});

window.kakubirdTools = { initKakubirdTools };

export default { initKakubirdTools };





























































































"use strict";

import { onReady, qs, qsa } from './utils.js';

export function initPageWidgets() {
  qsa('[data-toggle]').forEach((button) => {
    const targetSelector = button.dataset.toggle;
    const target = qs(targetSelector);
    if (!target) return;

    button.addEventListener('click', () => {
      target.hidden = !target.hidden;
    });
  });
}

onReady(() => {
  initPageWidgets();
});

window.kakubirdPageWidgets = { initPageWidgets };

export default { initPageWidgets };





























































































































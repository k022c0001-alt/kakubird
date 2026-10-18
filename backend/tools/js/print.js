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
      body[data-print-type="report"],
      body[data-business-type] {
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
  const title = document.body?.dataset?.pageTitle || document.title || `Print ${type}`;
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

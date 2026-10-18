import { onReady, qs, qsa, escapeHtml } from './utils.js';

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

import { onReady } from './utils.js';
import { initPrintTools } from './print.js';
import { initExportTools } from './export.js';
import { initForms } from './forms.js';
import { initReservationTools } from './reservation.js';
import { initShopTools } from './shop.js';
import { initBusinessProfile } from './business.js';

export function initKakubirdTools() {
  initPrintTools();
  initExportTools();
  initForms();
  initReservationTools();
  initShopTools();
  initBusinessProfile();
}

onReady(() => {
  initKakubirdTools();
});

window.kakubirdTools = { initKakubirdTools };

export default { initKakubirdTools };

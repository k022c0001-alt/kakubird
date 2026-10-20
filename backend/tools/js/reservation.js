import { onReady, qs, qsa, formatDate, readLocalStorage, writeLocalStorage } from './utils.js';

const DEFAULT_SLOTS = ['09:00', '10:30', '13:00', '15:00', '17:30'];

function getBusinessProfile() {
  return window.kakubirdBusinessProfile || null;
}

function getSlotOptions(dateValue, profile = null) {
  const selectedProfile = profile || getBusinessProfile();
  const slots = selectedProfile?.reservation?.enabled
    ? (selectedProfile.reservation.slots || DEFAULT_SLOTS)
    : DEFAULT_SLOTS;

  const selectedDate = dateValue ? new Date(dateValue) : new Date();
  const labelDate = formatDate(selectedDate, { month: 'short', day: 'numeric' });

  return slots.map((slot) => ({
    label: `${labelDate} ${slot}`,
    value: `${selectedDate.toISOString().slice(0, 10)} ${slot}`,
  }));
}

function refreshReservationForms() {
  const profile = getBusinessProfile();

  qsa('[data-reservation-form]').forEach((form) => {
    const dateInput = qs('[name="reservation_date"]', form) || qs('[data-reservation-date]', form);
    const slotSelect = qs('[name="reservation_slot"]', form) || qs('[data-reservation-slot]', form);
    if (!dateInput || !slotSelect) return;

    if (form.dataset.kakubirdBound !== 'true') {
      dateInput.addEventListener('change', () => {
        const options = getSlotOptions(dateInput.value, profile);
        slotSelect.innerHTML = '<option value="">時間を選択</option>' + options
          .map((option) => `<option value="${option.value}">${option.label}</option>`)
          .join('');
      });
      form.dataset.kakubirdBound = 'true';
    }

    const options = getSlotOptions(dateInput.value || new Date().toISOString(), profile);
    slotSelect.innerHTML = '<option value="">時間を選択</option>' + options
      .map((option) => `<option value="${option.value}">${option.label}</option>`)
      .join('');
  });
}

export function initReservationTools() {
  const reservationForms = qsa('[data-reservation-form]');

  reservationForms.forEach((form) => {
    const dateInput = qs('[name="reservation_date"]', form) || qs('[data-reservation-date]', form);
    const slotSelect = qs('[name="reservation_slot"]', form) || qs('[data-reservation-slot]', form);

    if (!dateInput || !slotSelect) return;

    const handleSubmit = (event) => {
      event.preventDefault();
      const payload = Object.fromEntries(new FormData(form).entries());
      const existing = readLocalStorage('kakubird-reservations', []);
      const next = [...(Array.isArray(existing) ? existing : []), { ...payload, createdAt: new Date().toISOString() }];
      writeLocalStorage('kakubird-reservations', next);
      form.reset();
      alert('予約を登録しました。');
    };

    if (!form.dataset.kakubirdSubmitBound) {
      form.addEventListener('submit', handleSubmit);
      form.dataset.kakubirdSubmitBound = 'true';
    }

    const options = getSlotOptions(dateInput.value || new Date().toISOString(), getBusinessProfile());
    slotSelect.innerHTML = '<option value="">時間を選択</option>' + options
      .map((option) => `<option value="${option.value}">${option.label}</option>`)
      .join('');
  });

  refreshReservationForms();
}

document.addEventListener('kakubird:businessProfileLoaded', refreshReservationForms);

onReady(() => {
  initReservationTools();
});

window.kakubirdReservation = { initReservationTools, getSlotOptions };

export default { initReservationTools, getSlotOptions };

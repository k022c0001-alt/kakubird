import { onReady, qs, qsa, readLocalStorage, writeLocalStorage, formatDate } from './utils.js';

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

import { qs, qsa, escapeHtml, formatDate, readLocalStorage, writeLocalStorage } from './utils.js';

export async function initBusinessProfile() {
  const businessType = document.body?.dataset?.businessType;
  const businessName = document.body?.dataset?.businessName || '';
  if (!businessType) return;

  let profiles = {};
  try {
    const res = await fetch('/backend/tools/js/business-profiles.json');
    profiles = await res.json();
  } catch (e) {
    // fail silently
    return;
  }

  const profile = profiles[businessType] || profiles['generic'];

  // set page title if not overridden
  if (profile.title) {
    document.title = (profile.title || '').replace('{{name}}', businessName || document.title);
  }

  // populate services list if present
  const servicesNode = qs('[data-services]');
  if (servicesNode && profile.services) {
    servicesNode.innerHTML = profile.services
      .map((s) => `<div class="service"><h4>${escapeHtml(s.name)}</h4><p>${escapeHtml(s.desc)}</p></div>`)
      .join('');
  }

  // Configure contact forms: add or require fields according to profile
  qsa('form[data-form-type]').forEach((form) => {
    const formType = form.dataset.formType;
    // Only configure contact-like forms
    if (!['contact','reservation','inquiry'].includes(formType)) return;

    const requiredFields = profile.contactFields || [];
    requiredFields.forEach((name) => {
      const field = qs(`[name="${name}"]`, form) || qs(`[data-name="${name}"]`, form);
      if (field) {
        field.required = true;
      } else {
        // if form misses common field, optionally insert hidden / visible input
        const wrapper = qs('[data-form-fields]') || form;
        const input = document.createElement('input');
        input.name = name;
        input.placeholder = name;
        input.required = true;
        input.style.display = 'none';
        wrapper.appendChild(input);
      }
    });
  });

  // Reservation configuration: populate slot selects with profile slots
  if (profile.reservation && profile.reservation.enabled) {
    qsa('[data-reservation-form]').forEach((form) => {
      const dateInput = qs('[name="reservation_date"]', form) || qs('[data-reservation-date]', form);
      const slotSelect = qs('[name="reservation_slot"]', form) || qs('[data-reservation-slot]', form);
      if (!dateInput || !slotSelect) return;

      const slots = profile.reservation.slots || [];

      const refresh = () => {
        const selectedDate = dateInput.value ? new Date(dateInput.value) : new Date();
        const labelDate = formatDate(selectedDate, { month: 'short', day: 'numeric' });
        slotSelect.innerHTML = '<option value="">時間を選択</option>' + slots
          .map((s) => `<option value="${selectedDate.toISOString().slice(0,10)} ${s}">${labelDate} ${s}</option>`)
          .join('');
      };

      dateInput.addEventListener('change', refresh);
      refresh();
    });
  }

  // Shop: expose profile flags and defaults for shop UI
  if (profile.shopEnabled) {
    // show shop widgets if hidden
    qsa('[data-shop-widget]').forEach((node) => node.hidden = false);

    // set default inventory if none exists in localStorage
    const invKey = `kakubird-inventory-${businessType}`;
    const existing = readLocalStorage(invKey, null);
    if (!existing) {
      const sample = [
        { id: 'sample-1', name: `${businessName || '商品'} A`, price: 1000 },
        { id: 'sample-2', name: `${businessName || '商品'} B`, price: 2500 }
      ];
      writeLocalStorage(invKey, sample);
    }
  }

  // expose profile on window for debugging/custom hooks
  window.kakubirdBusinessProfile = profile;
}

export default { initBusinessProfile };

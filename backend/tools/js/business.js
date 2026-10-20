import { qs, qsa, escapeHtml, formatDate, readLocalStorage, writeLocalStorage } from './utils.js';

const defaultProfile = {
  title: '{{name}} - 予約・お問い合わせ',
  description: '汎用のビジネス向けテンプレート',
  reservation: {
    enabled: true,
    slots: ['09:00', '10:30', '13:00', '15:00', '17:30'],
    slotDurationMinutes: 60,
  },
  contactFields: ['name', 'email', 'tel', 'message'],
  shopEnabled: false,
};

export function resolveBusinessProfile(businessType = null, businessName = '') {
  const type = businessType || document.body?.dataset?.businessType || 'generic';
  const name = businessName || document.body?.dataset?.businessName || '店舗';

  const profile = {
    ...defaultProfile,
    reservation: {
      ...defaultProfile.reservation,
    },
  };

  const withType = window.__kakubirdBusinessProfiles?.[type] || {};
  return {
    ...profile,
    ...withType,
    reservation: {
      ...profile.reservation,
      ...(withType.reservation || {}),
    },
    title: (withType.title || profile.title || '{{name}}').replace('{{name}}', name),
    businessType: type,
    businessName: name,
  };
}

export async function initBusinessProfile() {
  const businessType = document.body?.dataset?.businessType || 'generic';
  const businessName = document.body?.dataset?.businessName || '';

  try {
    const res = await fetch('/backend/tools/js/business-profiles.json', { cache: 'no-store' });
    if (!res.ok) throw new Error('failed to load profiles');
    const profiles = await res.json();
    window.__kakubirdBusinessProfiles = profiles;
  } catch (error) {
    window.__kakubirdBusinessProfiles = {};
  }

  const profile = resolveBusinessProfile(businessType, businessName);
  window.kakubirdBusinessProfile = profile;

  if (profile.title) {
    document.title = profile.title;
  }

  const servicesNode = qs('[data-services]');
  if (servicesNode && Array.isArray(profile.services)) {
    servicesNode.innerHTML = profile.services
      .map((service) => `<div class="service"><h4>${escapeHtml(service.name)}</h4><p>${escapeHtml(service.desc)}</p></div>`)
      .join('');
  }

  qsa('form[data-form-type]').forEach((form) => {
    const formType = form.dataset.formType;
    if (!['contact', 'reservation', 'inquiry'].includes(formType)) return;

    const requiredFields = profile.contactFields || [];
    requiredFields.forEach((name) => {
      const field = qs(`[name="${name}"]`, form) || qs(`[data-name="${name}"]`, form);
      if (field) {
        field.required = true;
      } else {
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

  if (profile.shopEnabled) {
    qsa('[data-shop-widget]').forEach((node) => {
      node.hidden = false;
    });

    const invKey = `kakubird-inventory-${businessType}`;
    const existing = readLocalStorage(invKey, null);
    if (!existing) {
      const sample = [
        { id: 'sample-1', name: `${businessName || '商品'} A`, price: 1000 },
        { id: 'sample-2', name: `${businessName || '商品'} B`, price: 2500 },
      ];
      writeLocalStorage(invKey, sample);
    }
  }

  document.dispatchEvent(new CustomEvent('kakubird:businessProfileLoaded', {
    detail: { profile, businessType },
  }));
}

export default { initBusinessProfile, resolveBusinessProfile };

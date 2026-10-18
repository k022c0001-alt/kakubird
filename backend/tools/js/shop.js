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

window.HuaboshiCatalog = {
  open(itemId, title) {
    sendText(decodeURIComponent(title), 'catalog_plan', decodeURIComponent(itemId));
  }
};

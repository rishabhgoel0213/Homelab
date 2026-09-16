async () => {
  // Evaluate with zen-devtools.evaluate_privileged_script in the disposable
  // automation profile. This exercises the actual browser controls.
  const checks = [];
  const waitFor = async predicate => {
    for (let attempt = 0; attempt < 50; attempt++) {
      if (predicate()) {
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  };
  const expect = (condition, name) => {
    if (!condition) {
      throw new Error(`Zen chrome regression: ${name}`);
    }
    checks.push(name);
  };
  const closePopups = () => {
    for (const popup of document.querySelectorAll("panel,menupopup")) {
      if (popup.state === "open") {
        popup.hidePopup();
      }
    }
  };

  await gZenWorkspaces.promiseInitialized;
  await waitFor(() => gBrowserInit.delayedStartupFinished);
  window.focus();
  if (gURLBar.hasAttribute("zen-newtab")) {
    gZenUIManager.handleUrlbarClose();
  }
  const spaces = gZenWorkspaces.getWorkspaces();
  expect(
    spaces.length > 0 && spaces.every(space =>
      space.theme && Array.isArray(space.theme.gradientColors)
    ),
    "Spaces have renderable themes"
  );

  try {
    for (const [buttonId, popupId] of [
      ["downloads-button", "downloadsPanel"],
      ["zen-create-new-button", "zenCreateNewPopup"],
    ]) {
      closePopups();
      const button = document.getElementById(buttonId);
      expect(Boolean(button.getAttribute("label")), `${buttonId} has a label`);
      button.click();
      const popup = document.getElementById(popupId);
      await waitFor(() => popup.state === "open");
      expect(popup.state === "open", `${popupId} opens`);
      const items = [...popup.querySelectorAll("menuitem[data-l10n-id]")];
      expect(
        items.length > 0 && items.every(item => item.getAttribute("label")),
        `${popupId} menu items are localized`
      );
    }
    closePopups();
    const newTab = document.getElementById("tabs-newtab-button");
    expect(Boolean(newTab.getAttribute("label")), "New Tab has a label");
    newTab.click();
    await waitFor(() => document.getElementById("urlbar").hasAttribute("open"));
    expect(document.getElementById("urlbar").hasAttribute("open"), "New Tab opens the address bar");
  } finally {
    closePopups();
    if (gURLBar.hasAttribute("zen-newtab")) {
      gZenUIManager.handleUrlbarClose();
    }
    gURLBar.view.close();
    gURLBar.blur();
  }
  return { checks, spaces: spaces.map(space => space.name) };
}

async () => {
  // Evaluate with zen-devtools.evaluate_privileged_script in the disposable
  // automation profile. This exercises the actual browser controls.
  const checks = [];
  const pause = () => new Promise(resolve => setTimeout(resolve, 250));
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
      await pause();
      const popup = document.getElementById(popupId);
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
    await pause();
    expect(document.getElementById("urlbar").hasAttribute("open"), "New Tab opens the address bar");
  } finally {
    closePopups();
    gURLBar.view.close();
    gURLBar.blur();
  }
  return { checks, spaces: spaces.map(space => space.name) };
}

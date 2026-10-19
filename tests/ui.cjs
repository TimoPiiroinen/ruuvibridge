const { chromium } = require("@playwright/test");
const assert = require("node:assert/strict");
const fs = require("node:fs");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1280, height: 1100 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const url = process.env.RUUVI_URL || "http://127.0.0.1:8766";
  fs.mkdirSync("artifacts", { recursive: true });
  try {
    const stateResponse = await page.request.get(url + "/api/state");
    assert.equal(
      (await stateResponse.json()).demo,
      true,
      "UI tests require demo mode",
    );
    await page.goto(url);
    await page
      .getByRole("heading", { name: "Ruuvi Bridge", exact: true })
      .waitFor();
    await page.locator(".sensor").first().waitFor();
    assert.equal(await page.locator("html").getAttribute("lang"), "fi");
    const copy = await page.locator("body").innerText();
    assert(
      !copy.includes("Kodin olosuhteet") &&
        !copy.includes("Mittaukset pysyvät omassa verkossasi"),
    );
    assert(copy.includes("RuuviTag → Windows → Home Assistant"));
    await page.getByRole("button", { name: "Asetukset", exact: true }).click();
    await page.locator("#tray-metric").selectOption("temperature");
    await page.getByRole("button", { name: "Tallenna asetukset" }).click();
    await page.locator("#settings-dialog").waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "Asetukset", exact: true }).click();
    assert.equal(
      await page.locator("#tray-metric").inputValue(),
      "temperature",
    );
    await page.getByRole("button", { name: "Sulje", exact: true }).click();
    await page
      .getByRole("button", { name: "Muokkaa", exact: true })
      .first()
      .click();
    await page.locator("#tag-name").fill("Olohuone (demo)");
    await page.getByRole("button", { name: "Tallenna", exact: true }).click();
    await page.locator("#tag-dialog").waitFor({ state: "hidden" });
    await page
      .getByRole("button", { name: "Historia", exact: true })
      .first()
      .click();
    assert.match(page.url(), /view=history/);
    assert.equal(await page.locator("#history-metric").count(), 0);
    assert.equal(
      await page.getByRole("button", { name: "Ilmoitus", exact: true }).count(),
      0,
    );
    assert.equal(await page.locator(".charts canvas").count(), 3);
    await page.getByRole("button", { name: "7 vrk", exact: true }).click();
    await page.waitForFunction(() =>
      document
        .querySelector("#chart-temperature")
        .getAttribute("aria-label")
        .includes("168 tuntia"),
    );
    await page.getByRole("button", { name: "24 h", exact: true }).click();
    await page.waitForFunction(() =>
      [...document.querySelectorAll(".charts canvas")].every((c) =>
        c.getAttribute("aria-label").includes("24 tuntia"),
      ),
    );
    const csv = await page.request.get(
      await page
        .locator("#export")
        .getAttribute("href")
        .then((h) => url + h),
    );
    assert.match(
      await csv.text(),
      /^time,temperature,humidity,pressure,battery,rssi/,
    );
    for (const key of ["humidity", "temperature", "pressure"]) {
      assert(
        await page.locator("#chart-" + key).evaluate((canvas) => {
          const data = canvas
            .getContext("2d")
            .getImageData(0, 0, canvas.width, canvas.height).data;
          let colored = 0;
          for (let i = 0; i < data.length; i += 4)
            if (
              data[i + 3] > 0 &&
              Math.max(data[i], data[i + 1], data[i + 2]) -
                Math.min(data[i], data[i + 1], data[i + 2]) >
                40
            )
              colored++;
          return colored > 100;
        }),
        key + " chart must contain a visible measurement curve",
      );
    }
    const readings = await page
      .locator(".readings .value")
      .evaluateAll((elements) =>
        elements.map((el) => el.firstChild.textContent),
      );
    assert(
      readings.every((value) => /\d,\d$/.test(value)),
      "measurements show one decimal",
    );
    await page.screenshot({ path: "artifacts/desktop.png", fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(250);
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      "mobile overflow",
    );
    await page.screenshot({ path: "artifacts/mobile.png", fullPage: true });
    await page.getByRole("button", { name: "Asetukset", exact: true }).click();
    assert(
      await page
        .locator("#settings-dialog")
        .evaluate((el) => el.getBoundingClientRect().width <= innerWidth),
      "mobile dialog overflow",
    );
    await page.screenshot({ path: "artifacts/mobile-settings.png" });
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#settings-dialog").isVisible(), false);
    assert.deepEqual(errors, []);
    console.log(
      "PASS: Finnish UI, settings persistence, sensor editing, three charts, shared range, one decimal, CSV, desktop + mobile",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

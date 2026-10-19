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
  const catalog = JSON.parse(
    fs.readFileSync("ruuvi_bridge/static/i18n.json", "utf8"),
  );
  fs.mkdirSync("artifacts", { recursive: true });
  try {
    const state = await (await page.request.get(url + "/api/state")).json();
    assert.equal(state.demo, true, "UI tests require demo mode");
    // Make this test repeatable without touching a live installation.
    await page.request.post(url + "/api/settings", {
      headers: { "X-Ruuvi-Token": state.token },
      data: { language: "en" },
    });
    await page.goto(url);
    await page.locator(".sensor").first().waitFor();
    for (const lang of ["en", "fi"]) {
      const t = (key) => (lang === "fi" ? key : catalog[key]);
      if (lang === "fi") {
        await page
          .getByRole("button", { name: "Settings", exact: true })
          .click();
        await page.locator("#language").selectOption("fi");
        await page
          .getByRole("button", { name: "Save settings", exact: true })
          .click();
        await page.waitForFunction(
          () => document.documentElement.lang === "fi",
        );
      }
      await page.reload();
      await page.waitForFunction(
        (language) =>
          document.documentElement.lang === language &&
          document.querySelector(".sensor"),
        lang,
      );
      assert.equal(await page.title(), "Ruuvi Bridge · " + t("Mittaukset"));
      // Verify all static labels, including currently closed dialogs, use the catalog.
      const labels = await page
        .locator("[data-i18n]")
        .evaluateAll((elements) =>
          elements.map((el) => [el.dataset.i18n, el.textContent]),
        );
      for (const [key, value] of labels) {
        assert(Object.hasOwn(catalog, key), "Missing translation: " + key);
        if (!["Bluetooth käynnistyy…", "MQTT käynnistyy…"].includes(key))
          assert.equal(value, t(key));
      }
      assert(
        (await page.locator("#demo").innerText()).includes(
          lang === "fi" ? "Esikatselu" : "Preview",
        ),
      );
      assert(
        (await page.locator("#bluetooth-status").innerText()).includes(
          lang === "fi" ? "esimerkkimittauksia" : "sample measurements",
        ),
      );
      assert(
        (await page.locator("body").innerText()).includes(
          "RuuviTag → Windows → Home Assistant",
        ),
      );
      await page
        .getByRole("button", { name: t("Asetukset"), exact: true })
        .click();
      assert.equal(await page.locator("#language").inputValue(), lang);
      await page.locator("#mqtt-host").fill("bad/host");
      await page.getByRole("button", { name: t("Tallenna asetukset") }).click();
      await page
        .getByText(t("Anna MQTT-palvelimen nimi tai IP-osoite"), {
          exact: true,
        })
        .waitFor();
      await page.locator("#mqtt-host").fill("127.0.0.1");
      await page.locator("#tray-metric").selectOption("temperature");
      await page.getByRole("button", { name: t("Tallenna asetukset") }).click();
      await page.locator("#settings-dialog").waitFor({ state: "hidden" });
      await page
        .getByRole("button", { name: t("Asetukset"), exact: true })
        .click();
      assert.equal(
        await page.locator("#tray-metric").inputValue(),
        "temperature",
      );
      await page.getByRole("button", { name: t("Sulje"), exact: true }).click();
      await page
        .getByRole("button", { name: t("Muokkaa"), exact: true })
        .first()
        .click();
      await page.locator("#tag-name").fill("Demo sensor");
      await page
        .getByRole("button", { name: t("Tallenna"), exact: true })
        .click();
      await page.locator("#tag-dialog").waitFor({ state: "hidden" });
      await page
        .getByRole("button", { name: t("Historia"), exact: true })
        .first()
        .click();
      assert.match(page.url(), /view=history/);
      assert.equal(await page.locator(".charts canvas").count(), 3);
      await page.getByRole("button", { name: t("7 vrk"), exact: true }).click();
      await page.waitForFunction(() =>
        document
          .querySelector("#chart-temperature")
          .getAttribute("aria-label")
          .includes("168"),
      );
      await page.getByRole("button", { name: "24 h", exact: true }).click();
      await page.waitForFunction(
        (language) =>
          [...document.querySelectorAll(".charts canvas")].every((c) =>
            c
              .getAttribute("aria-label")
              .includes(language === "fi" ? "24 tuntia" : "24 hours"),
          ),
        lang,
      );
      const csv = await page.request.get(
        url + (await page.locator("#export").getAttribute("href")),
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
          key + " chart must contain a measurement curve",
        );
      }
      const readings = await page
        .locator(".readings .value")
        .evaluateAll((elements) =>
          elements.map((el) => el.firstChild.textContent),
        );
      assert(
        readings.every((value) =>
          (lang === "fi" ? /\d,\d$/ : /\d\.\d$/).test(value),
        ),
        "one decimal in selected locale",
      );
      await page.setViewportSize({ width: 1280, height: 1100 });
      await page.screenshot({
        path: `artifacts/desktop-${lang}.png`,
        fullPage: true,
      });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(250);
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        "mobile overflow",
      );
      await page.screenshot({
        path: `artifacts/mobile-${lang}.png`,
        fullPage: true,
      });
      await page
        .getByRole("button", { name: t("Asetukset"), exact: true })
        .click();
      assert(
        await page
          .locator("#settings-dialog")
          .evaluate(
            (el) =>
              el.scrollWidth <= el.clientWidth &&
              el.getBoundingClientRect().width <= innerWidth,
          ),
        "mobile dialog overflow",
      );
      await page.screenshot({ path: `artifacts/mobile-settings-${lang}.png` });
      await page.keyboard.press("Escape");
      assert.equal(await page.locator("#settings-dialog").isVisible(), false);
      await page.setViewportSize({ width: 1280, height: 1100 });
    }
    await page.getByRole("button", { name: "Asetukset", exact: true }).click();
    await page.locator("#language").selectOption("en");
    await page.getByRole("button", { name: "Tallenna asetukset" }).click();
    await page.getByText("Settings saved.", { exact: true }).waitFor();
    assert.equal(await page.locator("html").getAttribute("lang"), "en");
    assert.deepEqual(errors, []);
    console.log(
      "PASS: English/Finnish persistence, labels, errors, locale, settings, editing, three charts, CSV, desktop + mobile",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

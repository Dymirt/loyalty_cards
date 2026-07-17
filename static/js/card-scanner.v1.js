(() => {
  "use strict";

  const scanner = document.querySelector("[data-card-scanner]");
  if (!scanner || !window.ZXing || !navigator.mediaDevices?.getUserMedia) return;

  const trigger = scanner.querySelector("[data-scan-trigger]");
  const closeButton = scanner.querySelector("[data-camera-close]");
  const panel = scanner.querySelector("[data-camera-panel]");
  const video = scanner.querySelector("[data-camera-video]");
  const status = scanner.querySelector("[data-scanner-status]");
  const barcode = document.getElementById("id_barcode");
  const preview = scanner.querySelector("[data-card-preview]");
  const previewWrapper = scanner.querySelector("[data-card-preview-wrapper]");
  const prefix = scanner.dataset.cardPrefix;
  const mediaPrefix = scanner.dataset.mediaPrefix;
  const escapedPrefix = prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const cardPattern = new RegExp(`^${escapedPrefix}-([1-9][0-9]{0,5})$`);
  const reader = new window.ZXing.BrowserBarcodeReader();
  let stream = null;

  const stopCamera = () => {
    reader.reset();
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    video.srcObject = null;
    panel.classList.add("hidden");
    trigger.focus();
  };

  const showResult = (value) => {
    const normalized = value.trim().toUpperCase();
    barcode.value = normalized;
    const match = cardPattern.exec(normalized);
    if (match) {
      const number = match[1];
      preview.src = `${mediaPrefix}cards/card-${number}/${prefix}-${number}_front.jpg`;
      previewWrapper.classList.remove("hidden");
      status.textContent = "Kod został odczytany.";
    } else {
      status.textContent = `Odczytany kod nie pasuje do formatu ${prefix}-numer.`;
    }
  };

  trigger.classList.remove("hidden");
  trigger.addEventListener("click", async () => {
    panel.classList.remove("hidden");
    status.textContent = "Uruchamianie kamery…";
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
        audio: false,
      });
      video.srcObject = stream;
      status.textContent = "Ustaw kod karty w ramce.";
      const result = await reader.decodeOnceFromStream(stream, video);
      if (result?.text) showResult(result.text);
    } catch (error) {
      if (error?.name !== "NotFoundException") {
        status.textContent = "Nie udało się odczytać kodu. Możesz wpisać go ręcznie.";
      }
    } finally {
      stopCamera();
    }
  });

  closeButton.addEventListener("click", stopCamera);
  window.addEventListener("pagehide", () => {
    if (stream) stream.getTracks().forEach((track) => track.stop());
  });
})();

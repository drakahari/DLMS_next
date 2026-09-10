(() => {
  const menuButton = document.getElementById("menuButton");
  const sidebar = document.getElementById("dashboardSidebar");
  menuButton?.addEventListener("click", () => {
    sidebar?.classList.toggle("open");
  });

  const prompt = document.getElementById("externalAiPrompt");
  const copyButton = document.getElementById("externalAiCopyPrompt");
  const status = document.getElementById("externalAiCopyStatus");

  async function copyPrompt() {
    if (!prompt?.value || !copyButton) return;
    try {
      await navigator.clipboard.writeText(prompt.value);
    } catch (_error) {
      prompt.focus();
      prompt.select();
      if (!document.execCommand("copy")) throw _error;
    }
    if (status) status.textContent = "Prompt copied. Paste it into your chosen conversational AI.";
    copyButton.textContent = "Copied";
    window.setTimeout(() => {
      copyButton.textContent = "Copy Prompt";
    }, 1800);
  }

  copyButton?.addEventListener("click", () => {
    copyPrompt().catch(() => {
      if (status) status.textContent = "Copy was unavailable. Select the prompt and copy it manually.";
      prompt?.focus();
      prompt?.select();
    });
  });

  document.getElementById("externalAiErrors")?.focus();
})();

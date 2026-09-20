(() => {
  document.getElementById("menuButton")?.addEventListener("click", () => {
    document.getElementById("dashboardSidebar")?.classList.toggle("open");
  });

  const cards = [...document.querySelectorAll(".pdf-import-question-card")];
  const form = document.getElementById("pdfReviewForm");
  const selectionCount = document.getElementById("pdfSelectionCount");
  const confirmSelected = document.getElementById("questionReviewConfirmSelected");
  const bulkStatus = document.getElementById("questionReviewBulkConfirmationStatus");
  const skippedDetails = document.getElementById("questionReviewSkippedDetails");
  const skippedSummary = document.getElementById("questionReviewSkippedSummary");
  const skippedList = document.getElementById("questionReviewSkippedList");

  function normalized(value, foldCase = true) {
    const text = String(value || "").normalize("NFKC").trim().replace(/\s+/g, " ");
    return foldCase ? text.toLocaleLowerCase() : text;
  }

  function pairRows(card) {
    return [...card.querySelectorAll('[data-matching-role="pair-row"]')];
  }

  function resetConfirmation(card) {
    const confirmation = card.querySelector('[data-matching-role="review-confirmed"]');
    if (confirmation) confirmation.checked = false;
  }

  function selectedCards() {
    return cards.filter(
      (card) => card.querySelector('[data-pdf-role="select"]')?.checked,
    );
  }

  function updateSelectionCount() {
    const count = selectedCards().length;
    if (selectionCount) selectionCount.textContent = `${count} selected`;
    if (confirmSelected) confirmSelected.disabled = count === 0;
  }

  function cardValidity(card) {
    if (card.querySelector('[data-pdf-role="delete"]')?.checked) {
      return { valid: false, reason: "excluded" };
    }
    if (!normalized(card.querySelector('[data-pdf-role="question"]')?.value)) {
      return { valid: false, reason: "needs question text" };
    }
    const rows = pairRows(card);
    if (rows.length < 2 || rows.length > 100) {
      return { valid: false, reason: "needs 2–100 pairs" };
    }
    const left = rows.map((row) =>
      normalized(row.querySelector('[data-matching-role="left"]')?.value, false),
    );
    const right = rows.map((row) =>
      normalized(row.querySelector('[data-matching-role="right"]')?.value),
    );
    if (left.some((value) => !value) || right.some((value) => !value)) {
      return { valid: false, reason: "has an incomplete pair" };
    }
    if (new Set(left).size !== left.length || new Set(right).size !== right.length) {
      return { valid: false, reason: "has duplicate or ambiguous pairs" };
    }
    const roundSize = Number(
      card.querySelector('[data-matching-role="round-size"]')?.value,
    );
    if (!Number.isInteger(roundSize) || roundSize < 2 || roundSize > rows.length) {
      return { valid: false, reason: "has an invalid pairs-per-attempt value" };
    }
    const concepts = String(
      card.querySelector('[data-pdf-role="concepts"]')?.value || "",
    ).split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
    const conceptKeys = concepts.map((value) => normalized(value));
    if (
      concepts.length > 24 ||
      concepts.some((value) => value.length > 120) ||
      new Set(conceptKeys).size !== conceptKeys.length
    ) {
      return { valid: false, reason: "has invalid concepts" };
    }
    return { valid: true, reason: "" };
  }

  function syncPairControls(card) {
    const rows = pairRows(card);
    rows.forEach((row, index) => {
      const up = row.querySelector('[data-matching-action="pair-up"]');
      const down = row.querySelector('[data-matching-action="pair-down"]');
      const remove = row.querySelector('[data-matching-action="pair-delete"]');
      if (up) up.disabled = index === 0;
      if (down) down.disabled = index === rows.length - 1;
      if (remove) remove.disabled = rows.length <= 2;
    });
    const add = card.querySelector('[data-matching-action="pair-add"]');
    if (add) add.disabled = rows.length >= 100;
    const roundSize = card.querySelector('[data-matching-role="round-size"]');
    if (roundSize) roundSize.max = String(Math.max(2, rows.length));
  }

  function createPairRow(card) {
    const original = pairRows(card)[0];
    if (!original || pairRows(card).length >= 100) return null;
    const row = original.cloneNode(true);
    row.querySelectorAll("input, textarea").forEach((control) => {
      control.value = "";
    });
    row.querySelector(".ocr-matching-pair-provenance")?.remove();
    return row;
  }

  document.querySelectorAll(".pdf-import-filter-row button").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".pdf-import-filter-row button").forEach((item) => {
        const selected = item === button;
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      });
      cards.forEach((card) => {
        card.hidden = button.dataset.filter !== "all" &&
          card.dataset.status !== button.dataset.filter;
      });
    });
  });

  cards.forEach((card) => {
    card.querySelector('[data-pdf-role="select"]')?.addEventListener(
      "change", updateSelectionCount,
    );
    card.addEventListener("input", (event) => {
      if (event.target.matches(
        '[data-pdf-role="question"],[data-pdf-role="explanation"],' +
        '[data-pdf-role="concepts"],[data-matching-role="round-size"],' +
        '[data-matching-role="left"],[data-matching-role="right"],' +
        '[data-matching-role="category"],[data-matching-role="pair-explanation"]',
      )) resetConfirmation(card);
    });
    card.addEventListener("change", (event) => {
      if (event.target.matches(
        '[data-matching-role="direction"],[data-pdf-role="delete"]',
      )) {
        resetConfirmation(card);
      }
    });
    card.addEventListener("click", (event) => {
      const button = event.target.closest("[data-matching-action]");
      if (!button) return;
      const action = button.dataset.matchingAction;
      const row = button.closest('[data-matching-role="pair-row"]');
      const list = card.querySelector('[data-matching-role="pair-list"]');
      if (action === "pair-add") {
        const added = createPairRow(card);
        if (added && list) {
          list.appendChild(added);
          added.querySelector('[data-matching-role="left"]')?.focus();
        }
      } else if (action === "pair-delete" && row && pairRows(card).length > 2) {
        row.remove();
      } else if (action === "pair-up" && row?.previousElementSibling) {
        list.insertBefore(row, row.previousElementSibling);
      } else if (action === "pair-down" && row?.nextElementSibling) {
        list.insertBefore(row.nextElementSibling, row);
      }
      resetConfirmation(card);
      syncPairControls(card);
    });
    syncPairControls(card);
  });

  document.getElementById("pdfSelectAllVisible")?.addEventListener("click", () => {
    cards.filter((card) => !card.hidden).forEach((card) => {
      const checkbox = card.querySelector('[data-pdf-role="select"]');
      if (checkbox) checkbox.checked = true;
    });
    updateSelectionCount();
  });
  document.getElementById("pdfClearSelection")?.addEventListener("click", () => {
    cards.forEach((card) => {
      const checkbox = card.querySelector('[data-pdf-role="select"]');
      if (checkbox) checkbox.checked = false;
    });
    updateSelectionCount();
  });
  document.getElementById("pdfDeleteSelected")?.addEventListener("click", () => {
    const selected = selectedCards();
    if (!selected.length || !confirm(
      `Mark ${selected.length} selected question(s) for deletion/exclusion?`,
    )) return;
    selected.forEach((card) => {
      const checkbox = card.querySelector('[data-pdf-role="delete"]');
      if (checkbox) checkbox.checked = true;
      resetConfirmation(card);
    });
  });
  document.getElementById("pdfKeepSelected")?.addEventListener("click", () => {
    selectedCards().forEach((card) => {
      const checkbox = card.querySelector('[data-pdf-role="delete"]');
      if (checkbox) checkbox.checked = false;
      resetConfirmation(card);
    });
  });
  confirmSelected?.addEventListener("click", () => {
    const skipped = [];
    let confirmed = 0;
    selectedCards().forEach((card) => {
      const validity = cardValidity(card);
      if (!validity.valid) {
        skipped.push({ number: card.dataset.questionNumber, reason: validity.reason });
        return;
      }
      const checkbox = card.querySelector('[data-matching-role="review-confirmed"]');
      if (checkbox) checkbox.checked = true;
      confirmed += 1;
    });
    if (bulkStatus) {
      bulkStatus.textContent = `${confirmed} confirmed. ${skipped.length} skipped.`;
      bulkStatus.hidden = false;
    }
    if (skippedDetails && skippedSummary && skippedList) {
      skippedList.replaceChildren();
      skipped.forEach((item) => {
        const detail = document.createElement("li");
        detail.textContent = `Question ${item.number}: ${item.reason}.`;
        skippedList.appendChild(detail);
      });
      skippedSummary.textContent = `Show skipped questions (${skipped.length})`;
      skippedDetails.hidden = skipped.length === 0;
    }
  });

  form?.addEventListener("submit", () => {
    const payload = cards.map((card) => {
      const concepts = String(
        card.querySelector('[data-pdf-role="concepts"]')?.value || "",
      ).split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
      return {
        index: Number(card.dataset.questionIndex || 0),
        number: Number(card.dataset.questionNumber || 0),
        delete: !!card.querySelector('[data-pdf-role="delete"]')?.checked,
        question: card.querySelector('[data-pdf-role="question"]')?.value || "",
        direction: card.querySelector('[data-matching-role="direction"]')?.value || "",
        round_size: Number(
          card.querySelector('[data-matching-role="round-size"]')?.value,
        ),
        pairs: pairRows(card).map((row) => ({
          left: row.querySelector('[data-matching-role="left"]')?.value || "",
          right: row.querySelector('[data-matching-role="right"]')?.value || "",
          category: row.querySelector('[data-matching-role="category"]')?.value || "",
          explanation:
            row.querySelector('[data-matching-role="pair-explanation"]')?.value || "",
        })),
        review_confirmed:
          !!card.querySelector('[data-matching-role="review-confirmed"]')?.checked,
        explanation: card.querySelector('[data-pdf-role="explanation"]')?.value || "",
        concepts,
      };
    });
    const hidden = document.getElementById("pdfReviewPayload");
    if (hidden) hidden.value = JSON.stringify(payload);
  });

  updateSelectionCount();
})();

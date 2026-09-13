(() => {
  "use strict";

  const SCHEMA_VERSION = 1;
  const RUNTIME_VERSION = "quiz-recovery-v1";
  const STORAGE_PREFIX = "dlms.quiz-progress.v1:";
  const MAX_RECORD_BYTES = 512 * 1024;
  const MAX_UNACKNOWLEDGED_STUDY_EVENTS = 256;
  const MAX_STRING_LENGTH = 2048;
  const EXPIRY_MS = 30 * 24 * 60 * 60 * 1000;

  const finiteInteger = (value, minimum, maximum) => (
    Number.isInteger(value) && value >= minimum && value <= maximum
  );

  const boundedString = (value, maximum = MAX_STRING_LENGTH) => (
    typeof value === "string" && value.length > 0 && value.length <= maximum
  );

  const exactKeys = (value, expected) => {
    const actual = Object.keys(value).sort();
    return actual.length === expected.length
      && actual.every((key, index) => key === expected.slice().sort()[index]);
  };

  const randomToken = () => {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `quiz_${Date.now()}_${Math.random().toString(36).slice(2)}_${Math.random().toString(36).slice(2)}`;
  };

  const storageBytes = value => new TextEncoder().encode(value).byteLength;

  function sha256Fallback(bytes) {
    const constants = [
      0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
      0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
      0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
      0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
      0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
      0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
      0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
      0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ];
    const state = [
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ];
    const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
    const padded = new Uint8Array(paddedLength);
    padded.set(bytes);
    padded[bytes.length] = 0x80;
    const view = new DataView(padded.buffer);
    const bitLength = bytes.length * 8;
    view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000), false);
    view.setUint32(paddedLength - 4, bitLength >>> 0, false);
    const words = new Uint32Array(64);
    const rotateRight = (value, shift) => (value >>> shift) | (value << (32 - shift));
    for (let offset = 0; offset < paddedLength; offset += 64) {
      for (let word = 0; word < 16; word += 1) words[word] = view.getUint32(offset + word * 4, false);
      for (let word = 16; word < 64; word += 1) {
        const a = words[word - 15];
        const b = words[word - 2];
        const s0 = rotateRight(a, 7) ^ rotateRight(a, 18) ^ (a >>> 3);
        const s1 = rotateRight(b, 17) ^ rotateRight(b, 19) ^ (b >>> 10);
        words[word] = (words[word - 16] + s0 + words[word - 7] + s1) >>> 0;
      }
      let [a, b, c, d, e, f, g, h] = state;
      for (let word = 0; word < 64; word += 1) {
        const sigma1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
        const choose = (e & f) ^ (~e & g);
        const first = (h + sigma1 + choose + constants[word] + words[word]) >>> 0;
        const sigma0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
        const majority = (a & b) ^ (a & c) ^ (b & c);
        const second = (sigma0 + majority) >>> 0;
        h = g; g = f; f = e; e = (d + first) >>> 0;
        d = c; c = b; b = a; a = (first + second) >>> 0;
      }
      [a, b, c, d, e, f, g, h].forEach((value, index) => {
        state[index] = (state[index] + value) >>> 0;
      });
    }
    return state.map(value => value.toString(16).padStart(8, "0")).join("");
  }

  async function sha256(value) {
    if (typeof TextEncoder === "undefined") throw new Error("Strong browser fingerprinting is unavailable");
    const bytes = new TextEncoder().encode(value);
    if (window.crypto?.subtle) {
      try {
        const digest = await window.crypto.subtle.digest("SHA-256", bytes);
        return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
      } catch (_error) {
        // Non-secure LAN origins can expose crypto without SubtleCrypto digest.
      }
    }
    return sha256Fallback(bytes);
  }

  async function quizFingerprint({rawQuizText, quizId, quizFile, examMinutes}) {
    const identity = [
      RUNTIME_VERSION,
      String(SCHEMA_VERSION),
      String(quizId),
      String(quizFile),
      String(examMinutes),
      String(rawQuizText),
    ].join("\u0000");
    return `sha256:${await sha256(identity)}`;
  }

  function questionDescriptors(rawQuiz) {
    return rawQuiz.map(question => {
      const type = String(question?.type || "choice").toLowerCase();
      if (type === "matching") {
        const pairCount = Array.isArray(question.pairs) ? question.pairs.length : 0;
        const requested = Number(question.round_size);
        const matchingCount = Number.isFinite(requested) && requested >= 2 && requested < pairCount
          ? Math.floor(requested) : pairCount;
        const configuredDirection = String(question.direction || "term_to_definition");
        return {type, pairCount, matchingCount, configuredDirection};
      }
      if (type === "hotspot") return {type};
      return {type: "choice", choiceCount: Array.isArray(question?.choices) ? question.choices.length : 0};
    });
  }

  function validPermutation(values, size) {
    if (!Array.isArray(values) || values.length !== size) return false;
    return values.every(value => finiteInteger(value, 0, size - 1))
      && new Set(values).size === size;
  }

  function validateAnswers(answers, descriptors, matchingVariants) {
    if (!answers || typeof answers !== "object" || Array.isArray(answers)) return false;
    if (Object.keys(answers).length > descriptors.length) return false;
    for (const [rawIndex, record] of Object.entries(answers)) {
      const index = Number(rawIndex);
      if (!finiteInteger(index, 0, descriptors.length - 1)) return false;
      if (String(index) !== rawIndex) return false;
      if (!record || typeof record !== "object" || Array.isArray(record)) return false;
      if (!exactKeys(record, ["selected", "type"])) return false;
      const descriptor = descriptors[index];
      if (record.type !== descriptor.type) return false;
      const selected = record.selected;
      if (descriptor.type === "choice") {
        if (!Array.isArray(selected) || selected.length > descriptor.choiceCount) return false;
        if (!selected.every(value => finiteInteger(value, 0, descriptor.choiceCount - 1))) return false;
        if (new Set(selected).size !== selected.length) return false;
      } else if (descriptor.type === "hotspot") {
        if (!selected || typeof selected !== "object" || Array.isArray(selected)) return false;
        if (!exactKeys(selected, ["x", "y"])) return false;
        if (!Number.isFinite(selected.x) || !Number.isFinite(selected.y)) return false;
        if (selected.x < 0 || selected.x > 1 || selected.y < 0 || selected.y > 1) return false;
      } else {
        const variant = matchingVariants[rawIndex];
        if (!variant) return false;
        if (!selected || typeof selected !== "object" || Array.isArray(selected)) return false;
        const used = new Set();
        for (const [left, right] of Object.entries(selected)) {
          const leftIndex = Number(left);
          if (!finiteInteger(leftIndex, 0, variant.sourcePairIndexes.length - 1)) return false;
          if (String(leftIndex) !== left) return false;
          if (!finiteInteger(right, 0, variant.sourcePairIndexes.length - 1)) return false;
          if (used.has(right)) return false;
          used.add(right);
        }
      }
    }
    return true;
  }

  function validateMatchingVariants(variants, descriptors) {
    if (!variants || typeof variants !== "object" || Array.isArray(variants)) return false;
    const expectedKeys = descriptors.flatMap((descriptor, index) => descriptor.type === "matching" ? [String(index)] : []);
    if (!exactKeys(variants, expectedKeys)) return false;
    for (let index = 0; index < descriptors.length; index += 1) {
      const descriptor = descriptors[index];
      if (descriptor.type !== "matching") continue;
      const variant = variants[String(index)];
      if (!variant || typeof variant !== "object" || Array.isArray(variant)) return false;
      if (!exactKeys(variant, ["direction", "optionOrder", "sourcePairIndexes"])) return false;
      const source = variant.sourcePairIndexes;
      if (!Array.isArray(source) || source.length !== descriptor.matchingCount) return false;
      if (!source.every(value => finiteInteger(value, 0, descriptor.pairCount - 1))) return false;
      if (new Set(source).size !== source.length) return false;
      if (descriptor.matchingCount === descriptor.pairCount && source.some((value, sourceIndex) => value !== sourceIndex)) return false;
      if (!["term_to_definition", "definition_to_term"].includes(variant.direction)) return false;
      if (descriptor.configuredDirection !== "random" && variant.direction !== descriptor.configuredDirection) return false;
      if (variant.optionOrder !== null && !validPermutation(variant.optionOrder, source.length)) return false;
    }
    return true;
  }

  function validateStudyEvents(events, quizId, sessionId, descriptors, matchingVariants) {
    if (!Array.isArray(events) || events.length > MAX_UNACKNOWLEDGED_STUDY_EVENTS) return false;
    const eventIds = new Set();
    return events.every(record => {
      if (!record || typeof record !== "object" || Array.isArray(record)) return false;
      if (!exactKeys(record, ["eventId", "payload", "questionKey", "state"])) return false;
      if (!boundedString(record.eventId, 128) || !boundedString(record.questionKey, 256)) return false;
      if (eventIds.has(record.eventId)) return false;
      eventIds.add(record.eventId);
      if (!["saving", "failed"].includes(record.state)) return false;
      const payload = record.payload;
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
      if (!exactKeys(payload, ["eventId", "questionOrdinal", "questionType", "quizId", "selected", "sessionId", "wasCorrect"])) return false;
      if (!(String(payload.quizId) === String(quizId)
        && payload.sessionId === sessionId
        && payload.eventId === record.eventId
        && finiteInteger(payload.questionOrdinal, 1, descriptors.length)
        && ["choice", "matching", "hotspot"].includes(payload.questionType)
        && (payload.wasCorrect === null || typeof payload.wasCorrect === "boolean"))) return false;
      if (record.questionKey !== `${sessionId}:${payload.questionOrdinal}`) return false;
      const descriptor = descriptors[payload.questionOrdinal - 1];
      if (payload.questionType !== descriptor.type) return false;
      if (descriptor.type === "choice") {
        if (!Array.isArray(payload.selected) || payload.selected.length > descriptor.choiceCount) return false;
        if (!payload.selected.every(value => typeof value === "string" && /^[A-Z]$/.test(value))) return false;
        const selectedIndexes = payload.selected.map(value => value.charCodeAt(0) - 65);
        if (selectedIndexes.some(value => value >= descriptor.choiceCount) || new Set(selectedIndexes).size !== selectedIndexes.length) return false;
      } else if (descriptor.type === "hotspot") {
        const selected = payload.selected;
        if (!selected || typeof selected !== "object" || Array.isArray(selected)) return false;
        if (!exactKeys(selected, ["x", "y"])) return false;
        if (!Number.isFinite(selected.x) || !Number.isFinite(selected.y)) return false;
        if (selected.x < 0 || selected.x > 1 || selected.y < 0 || selected.y > 1) return false;
      } else {
        const answer = {[String(payload.questionOrdinal - 1)]: {type: "matching", selected: payload.selected}};
        if (!validateAnswers(answer, descriptors, matchingVariants)) return false;
      }
      return true;
    });
  }

  function validatePendingAttempt(pending, quizId, descriptors, matchingVariants, maximumSeconds) {
    if (pending === null) return true;
    if (!pending || typeof pending !== "object" || Array.isArray(pending)) return false;
    if (!exactKeys(pending, ["attemptId", "completedAt", "quizId", "responses", "startedAt", "timeRemaining"])) return false;
    if (!boundedString(pending.attemptId, 128)) return false;
    if (String(pending.quizId) !== String(quizId)) return false;
    if (!boundedString(pending.startedAt, 128) || !boundedString(pending.completedAt, 128)) return false;
    if (Number.isNaN(Date.parse(pending.startedAt)) || Number.isNaN(Date.parse(pending.completedAt))) return false;
    if (Date.parse(pending.completedAt) < Date.parse(pending.startedAt)) return false;
    if (!finiteInteger(pending.timeRemaining, 0, maximumSeconds)) return false;
    if (!Array.isArray(pending.responses) || pending.responses.length !== descriptors.length) return false;
    const responseAnswers = {};
    for (let index = 0; index < pending.responses.length; index += 1) {
      const response = pending.responses[index];
      if (!response || typeof response !== "object" || Array.isArray(response)) return false;
      if (!exactKeys(response, ["questionIndex", "selected", "type"])) return false;
      if (response.questionIndex !== index || response.type !== descriptors[index].type) return false;
      if (!Object.hasOwn(response, "selected")) return false;
      if (response.type === "hotspot" && response.selected === null) continue;
      responseAnswers[String(index)] = {type: response.type, selected: response.selected};
    }
    return validateAnswers(responseAnswers, descriptors, matchingVariants);
  }

  function validateRecordEnvelope(record, now = Date.now()) {
    if (!record || typeof record !== "object" || Array.isArray(record)) return false;
    if (!exactKeys(record, ["answers", "learningSessionId", "matchingVariants", "pendingAttempt", "quiz", "runtimeVersion", "schemaVersion", "session", "timer", "unacknowledgedStudyEvents", "view"])) return false;
    if (record.schemaVersion !== SCHEMA_VERSION || record.runtimeVersion !== RUNTIME_VERSION) return false;
    const quiz = record.quiz;
    if (!quiz || typeof quiz !== "object" || Array.isArray(quiz)) return false;
    if (!exactKeys(quiz, ["examMinutes", "file", "fingerprint", "id"])) return false;
    if (!boundedString(quiz.id, 128) || !boundedString(quiz.file, MAX_STRING_LENGTH)) return false;
    if (!boundedString(quiz.fingerprint, 71) || !/^sha256:[0-9a-f]{64}$/.test(quiz.fingerprint)) return false;
    if (!finiteInteger(quiz.examMinutes, 1, 1440)) return false;
    const session = record.session;
    if (!session || typeof session !== "object" || Array.isArray(session)) return false;
    if (!exactKeys(session, ["createdAt", "expiresAt", "id", "mode", "ownerToken", "phase", "revision", "updatedAt"])) return false;
    if (!boundedString(session.id, 128) || !boundedString(session.ownerToken, 128)) return false;
    if (!["Study", "Exam"].includes(session.mode) || !["active", "submitting"].includes(session.phase)) return false;
    if (session.phase === "submitting" && session.mode !== "Exam") return false;
    if (!finiteInteger(session.revision, 0, Number.MAX_SAFE_INTEGER)) return false;
    for (const field of ["createdAt", "updatedAt", "expiresAt"]) {
      if (!Number.isFinite(session[field]) || session[field] <= 0) return false;
    }
    if (session.expiresAt <= now || session.updatedAt < session.createdAt) return false;
    if (session.expiresAt !== session.updatedAt + EXPIRY_MS || session.expiresAt > now + EXPIRY_MS) return false;
    const view = record.view;
    if (!view || typeof view !== "object" || Array.isArray(view)) return false;
    if (!exactKeys(view, ["ankiQuestionIndexes", "matchingInteractionMode", "questionIndex"])) return false;
    if (!finiteInteger(view.questionIndex, 0, Number.MAX_SAFE_INTEGER)) return false;
    if (!["drag", "select"].includes(view.matchingInteractionMode)) return false;
    if (!Array.isArray(view.ankiQuestionIndexes)) return false;
    if (!record.answers || typeof record.answers !== "object" || Array.isArray(record.answers)) return false;
    if (!record.matchingVariants || typeof record.matchingVariants !== "object" || Array.isArray(record.matchingVariants)) return false;
    if (!boundedString(record.learningSessionId, 128)) return false;
    if (!Array.isArray(record.unacknowledgedStudyEvents) || record.unacknowledgedStudyEvents.length > MAX_UNACKNOWLEDGED_STUDY_EVENTS) return false;
    if (record.pendingAttempt !== null && (typeof record.pendingAttempt !== "object" || Array.isArray(record.pendingAttempt))) return false;
    if (session.mode === "Exam") {
      if (!record.timer || typeof record.timer !== "object" || Array.isArray(record.timer)) return false;
      if (!exactKeys(record.timer, ["paused", "remainingSeconds", "startedAt"])) return false;
      if (!finiteInteger(record.timer.remainingSeconds, 0, quiz.examMinutes * 60)) return false;
      if (typeof record.timer.paused !== "boolean") return false;
      if (!boundedString(record.timer.startedAt, 128) || Number.isNaN(Date.parse(record.timer.startedAt))) return false;
    } else if (record.timer !== null) return false;
    if (session.phase === "submitting" && record.pendingAttempt === null) return false;
    if (session.phase === "active" && record.pendingAttempt !== null) return false;
    return true;
  }

  function validateRecord(record, context, now = Date.now()) {
    if (!validateRecordEnvelope(record, now)) return false;
    if (!exactKeys(record, ["answers", "learningSessionId", "matchingVariants", "pendingAttempt", "quiz", "runtimeVersion", "schemaVersion", "session", "timer", "unacknowledgedStudyEvents", "view"])) return false;
    if (record.schemaVersion !== SCHEMA_VERSION || record.runtimeVersion !== RUNTIME_VERSION) return false;
    const quiz = record.quiz;
    if (!quiz || typeof quiz !== "object" || Array.isArray(quiz)) return false;
    if (!exactKeys(quiz, ["examMinutes", "file", "fingerprint", "id"])) return false;
    if (!boundedString(quiz.file, MAX_STRING_LENGTH) || !/^sha256:[0-9a-f]{64}$/.test(quiz.fingerprint)) return false;
    if (String(quiz.id) !== String(context.quizId) || quiz.file !== context.quizFile) return false;
    if (quiz.fingerprint !== context.fingerprint || quiz.examMinutes !== context.examMinutes) return false;
    const session = record.session;
    if (!session || typeof session !== "object" || Array.isArray(session)) return false;
    if (!exactKeys(session, ["createdAt", "expiresAt", "id", "mode", "ownerToken", "phase", "revision", "updatedAt"])) return false;
    if (!boundedString(session.id, 128) || !boundedString(session.ownerToken, 128)) return false;
    if (!["Study", "Exam"].includes(session.mode) || !["active", "submitting"].includes(session.phase)) return false;
    if (session.phase === "submitting" && session.mode !== "Exam") return false;
    if (!finiteInteger(session.revision, 0, Number.MAX_SAFE_INTEGER)) return false;
    for (const field of ["createdAt", "updatedAt", "expiresAt"]) {
      if (!Number.isFinite(session[field]) || session[field] <= 0) return false;
    }
    if (session.expiresAt <= now || session.updatedAt < session.createdAt) return false;
    if (session.expiresAt !== session.updatedAt + EXPIRY_MS || session.expiresAt > now + EXPIRY_MS) return false;
    const view = record.view;
    if (!view || typeof view !== "object" || Array.isArray(view)) return false;
    if (!exactKeys(view, ["ankiQuestionIndexes", "matchingInteractionMode", "questionIndex"])) return false;
    if (!finiteInteger(view.questionIndex, 0, context.descriptors.length - 1)) return false;
    if (!["drag", "select"].includes(view.matchingInteractionMode)) return false;
    if (!Array.isArray(view.ankiQuestionIndexes)) return false;
    if (!view.ankiQuestionIndexes.every(value => finiteInteger(value, 0, context.descriptors.length - 1))) return false;
    if (new Set(view.ankiQuestionIndexes).size !== view.ankiQuestionIndexes.length) return false;
    if (!validateMatchingVariants(record.matchingVariants, context.descriptors)) return false;
    if (!validateAnswers(record.answers, context.descriptors, record.matchingVariants)) return false;
    if (!boundedString(record.learningSessionId, 128)) return false;
    if (!validateStudyEvents(record.unacknowledgedStudyEvents, context.quizId, record.learningSessionId, context.descriptors, record.matchingVariants)) return false;
    if (session.mode === "Exam" && record.unacknowledgedStudyEvents.length !== 0) return false;
    if (session.mode === "Exam") {
      if (!record.timer || typeof record.timer !== "object" || Array.isArray(record.timer)) return false;
      if (!exactKeys(record.timer, ["paused", "remainingSeconds", "startedAt"])) return false;
      if (!finiteInteger(record.timer.remainingSeconds, 0, context.examMinutes * 60) || typeof record.timer.paused !== "boolean") return false;
      if (!boundedString(record.timer.startedAt, 128) || Number.isNaN(Date.parse(record.timer.startedAt))) return false;
    } else if (record.timer !== null) return false;
    if (!validatePendingAttempt(record.pendingAttempt, context.quizId, context.descriptors, record.matchingVariants, context.examMinutes * 60)) return false;
    if (session.phase === "submitting" && record.pendingAttempt === null) return false;
    if (session.phase === "active" && record.pendingAttempt !== null) return false;
    if (record.pendingAttempt) {
      for (const response of record.pendingAttempt.responses) {
        const answer = record.answers[String(response.questionIndex)];
        const fallback = response.type === "hotspot" ? null : (response.type === "matching" ? {} : []);
        const saved = answer ? answer.selected : fallback;
        if (JSON.stringify(response.selected) !== JSON.stringify(saved)) return false;
      }
    }
    return true;
  }

  function recoveryStorageKeys() {
    const keys = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (typeof key === "string" && key.startsWith(STORAGE_PREFIX)) keys.push(key);
    }
    return keys;
  }

  function storedQuizId(key) {
    try {
      const suffix = key.slice(STORAGE_PREFIX.length);
      const decoded = decodeURIComponent(suffix);
      return decoded && `${STORAGE_PREFIX}${encodeURIComponent(decoded)}` === key ? decoded : null;
    } catch (_error) {
      return null;
    }
  }

  function removeStoredQuiz(quizId) {
    try {
      localStorage.removeItem(`${STORAGE_PREFIX}${encodeURIComponent(String(quizId))}`);
      return true;
    } catch (_error) {
      return false;
    }
  }

  function clearAllStoredRecords() {
    try {
      const keys = recoveryStorageKeys();
      let removed = 0;
      keys.forEach(key => {
        try {
          localStorage.removeItem(key);
          removed += 1;
        } catch (_error) {
          // Recovery cleanup must never block the owning server-side workflow.
        }
      });
      return {available: true, examined: keys.length, removed};
    } catch (_error) {
      return {available: false, examined: 0, removed: 0};
    }
  }

  function pruneStoredRecords({activeQuizIds = null, now = Date.now()} = {}) {
    try {
      const active = activeQuizIds === null
        ? null
        : new Set(Array.from(activeQuizIds, value => String(value)));
      const keys = recoveryStorageKeys();
      let removed = 0;
      keys.forEach(key => {
        let keep = false;
        try {
          const quizId = storedQuizId(key);
          const raw = localStorage.getItem(key);
          if (quizId !== null && raw !== null && storageBytes(raw) <= MAX_RECORD_BYTES) {
            const record = JSON.parse(raw);
            keep = validateRecordEnvelope(record, now)
              && String(record.quiz.id) === quizId
              && (active === null || active.has(quizId));
          }
        } catch (_error) {
          keep = false;
        }
        if (!keep) {
          try {
            localStorage.removeItem(key);
            removed += 1;
          } catch (_error) {
            // Recovery cleanup must never block page behavior.
          }
        }
      });
      return {available: true, examined: keys.length, removed};
    } catch (_error) {
      return {available: false, examined: 0, removed: 0};
    }
  }

  function listStoredRecords({activeQuizIds = null, now = Date.now()} = {}) {
    try {
      const active = activeQuizIds === null
        ? null
        : new Set(Array.from(activeQuizIds, value => String(value)));
      const records = [];
      recoveryStorageKeys().forEach(key => {
        try {
          const quizId = storedQuizId(key);
          const raw = localStorage.getItem(key);
          if (quizId === null || raw === null || storageBytes(raw) > MAX_RECORD_BYTES) return;
          const record = JSON.parse(raw);
          if (!validateRecordEnvelope(record, now)
              || String(record.quiz.id) !== quizId
              || (active !== null && !active.has(quizId))) return;
          records.push({
            quizId,
            mode: record.session.mode,
            phase: record.session.phase,
            questionIndex: record.view.questionIndex,
            updatedAt: record.session.updatedAt,
          });
        } catch (_error) {
          // Listing is read-only; malformed records are left for normal pruning.
        }
      });
      records.sort((left, right) => (
        right.updatedAt - left.updatedAt
        || left.quizId.localeCompare(right.quizId)
      ));
      return {available: true, records};
    } catch (_error) {
      return {available: false, records: []};
    }
  }

  function createController(options) {
    const context = {
      quizId: String(options.quizId),
      quizFile: String(options.quizFile),
      examMinutes: Number(options.examMinutes),
      fingerprint: String(options.fingerprint),
      descriptors: questionDescriptors(options.rawQuiz),
    };
    const storageKey = `${STORAGE_PREFIX}${encodeURIComponent(context.quizId)}`;
    const ownerToken = randomToken();
    let owned = false;
    let revision = 0;
    let createdAt = Date.now();
    let savedRecord = null;
    let storageWarningShown = false;
    let recoveryPanel = null;

    const notify = message => options.notify?.(String(message));
    const storageWarning = () => {
      if (storageWarningShown) return;
      storageWarningShown = true;
      notify("Quiz recovery is unavailable in this browser. The quiz will continue normally.");
    };

    function removeStored() {
      try { localStorage.removeItem(storageKey); }
      catch (_error) { storageWarning(); }
    }

    function readStored({discardInvalid = true} = {}) {
      let raw;
      try { raw = localStorage.getItem(storageKey); }
      catch (_error) { storageWarning(); return null; }
      if (!raw) return null;
      if (storageBytes(raw) > MAX_RECORD_BYTES) {
        if (discardInvalid) removeStored();
        return null;
      }
      try {
        const parsed = JSON.parse(raw);
        if (!validateRecord(parsed, context)) throw new Error("invalid recovery record");
        return parsed;
      } catch (_error) {
        if (discardInvalid) removeStored();
        return null;
      }
    }

    function writeSnapshot({allowTakeover = false} = {}) {
      if (!owned) return false;
      let current = null;
      try {
        const raw = localStorage.getItem(storageKey);
        if (raw) {
          if (storageBytes(raw) > MAX_RECORD_BYTES) {
            localStorage.removeItem(storageKey);
          } else {
            const parsed = JSON.parse(raw);
            if (validateRecord(parsed, context)) current = parsed;
            else localStorage.removeItem(storageKey);
          }
        }
      } catch (_error) {
        try { localStorage.removeItem(storageKey); }
        catch (_storageError) { storageWarning(); return false; }
      }
      if (!current && savedRecord !== null && !allowTakeover) {
        owned = false;
        notify("Recoverable progress for this quiz was cleared by another DLMS page. This tab will no longer update the saved session.");
        return false;
      }
      if (current && current.session?.ownerToken !== ownerToken && !allowTakeover) {
        owned = false;
        notify("Recoverable progress for this quiz is active in another tab. This tab will no longer update the saved session.");
        return false;
      }
      if (!allowTakeover && current && current.session?.ownerToken === ownerToken && current.session.revision !== revision) {
        owned = false;
        notify("Recoverable progress for this quiz changed in another tab. This tab will no longer update the saved session.");
        return false;
      }
      const snapshot = options.capture();
      const now = Date.now();
      revision = Math.max(revision, Number(current?.session?.revision) || 0) + 1;
      const record = {
        schemaVersion: SCHEMA_VERSION,
        runtimeVersion: RUNTIME_VERSION,
        quiz: {
          id: context.quizId,
          file: context.quizFile,
          fingerprint: context.fingerprint,
          examMinutes: context.examMinutes,
        },
        session: {
          id: snapshot.recoverySessionId,
          mode: snapshot.mode,
          phase: snapshot.phase,
          ownerToken,
          revision,
          createdAt,
          updatedAt: now,
          expiresAt: now + EXPIRY_MS,
        },
        view: snapshot.view,
        answers: snapshot.answers,
        matchingVariants: snapshot.matchingVariants,
        timer: snapshot.timer,
        learningSessionId: snapshot.learningSessionId,
        unacknowledgedStudyEvents: snapshot.unacknowledgedStudyEvents,
        pendingAttempt: snapshot.pendingAttempt,
      };
      if (!validateRecord(record, context, now)) {
        console.warn("Quiz recovery refused an invalid runtime snapshot.");
        return false;
      }
      const raw = JSON.stringify(record);
      if (storageBytes(raw) > MAX_RECORD_BYTES) {
        storageWarning();
        return false;
      }
      try {
        localStorage.setItem(storageKey, raw);
        savedRecord = record;
        return true;
      } catch (_error) {
        storageWarning();
        return false;
      }
    }

    function claimNew() {
      owned = true;
      revision = 0;
      createdAt = Date.now();
      savedRecord = null;
      return writeSnapshot({allowTakeover: true});
    }

    function claimStored(record) {
      const current = readStored();
      if (!current || current.session.revision !== record.session.revision) return null;
      const now = Date.now();
      const claimed = {
        ...current,
        session: {
          ...current.session,
          ownerToken,
          revision: current.session.revision + 1,
          updatedAt: now,
          expiresAt: now + EXPIRY_MS,
        },
      };
      if (!validateRecord(claimed, context, now)) return null;
      try {
        localStorage.setItem(storageKey, JSON.stringify(claimed));
      } catch (_error) {
        storageWarning();
        return null;
      }
      owned = true;
      revision = claimed.session.revision;
      createdAt = claimed.session.createdAt;
      savedRecord = claimed;
      return claimed;
    }

    function hidePanel() {
      if (recoveryPanel) recoveryPanel.hidden = true;
    }

    function resumeSaved() {
      const record = readStored();
      if (!record) { hidePanel(); return; }
      const claimed = claimStored(record);
      if (!claimed) return;
      options.restore(claimed);
      hidePanel();
      writeSnapshot();
    }

    function finishSavedSubmission() {
      const record = readStored();
      if (!record || record.session.phase !== "submitting") { hidePanel(); return; }
      const claimed = claimStored(record);
      if (!claimed) return;
      options.restore(claimed);
      hidePanel();
      options.finishSubmission(claimed.pendingAttempt);
    }

    function startOver() {
      owned = false;
      savedRecord = null;
      removeStored();
      hidePanel();
      options.startOver?.();
    }

    function renderPanel(record) {
      const modeSelect = document.getElementById("modeSelect");
      if (!modeSelect) return;
      const panel = document.createElement("section");
      panel.className = "quiz-recovery-panel";
      panel.setAttribute("aria-labelledby", "quizRecoveryTitle");

      const title = document.createElement("h3");
      title.id = "quizRecoveryTitle";
      title.textContent = record.session.phase === "submitting"
        ? "A submitted attempt may still need confirmation"
        : "Continue your saved quiz?";
      panel.appendChild(title);

      const summary = document.createElement("p");
      const savedTime = new Date(record.session.updatedAt).toLocaleString();
      summary.textContent = record.session.phase === "submitting"
        ? `${record.session.mode} Mode · submitted ${savedTime}`
        : `${record.session.mode} Mode · Question ${record.view.questionIndex + 1} of ${context.descriptors.length} · saved ${savedTime}`;
      panel.appendChild(summary);

      const actions = document.createElement("div");
      actions.className = "quiz-recovery-actions";
      const resume = document.createElement("button");
      resume.type = "button";
      resume.className = "quiz-recovery-resume";
      resume.textContent = record.session.phase === "submitting" ? "Finish Saving Submitted Attempt" : "Resume";
      resume.addEventListener("click", record.session.phase === "submitting" ? finishSavedSubmission : resumeSaved);
      actions.appendChild(resume);
      const reset = document.createElement("button");
      reset.type = "button";
      reset.className = "quiz-recovery-start-over";
      reset.textContent = "Start Over";
      reset.addEventListener("click", startOver);
      actions.appendChild(reset);
      panel.appendChild(actions);
      modeSelect.prepend(panel);
      recoveryPanel = panel;
    }

    function initialize() {
      pruneStoredRecords();
      savedRecord = readStored();
      if (savedRecord) renderPanel(savedRecord);
      window.addEventListener("storage", event => {
        if (event.key !== storageKey || !owned) return;
        let incoming = null;
        try { incoming = event.newValue ? JSON.parse(event.newValue) : null; }
        catch (_error) { incoming = null; }
        if (!incoming || incoming.session?.ownerToken !== ownerToken) {
          owned = false;
          notify(incoming
            ? "Recoverable progress for this quiz is active in another tab. This tab will no longer update the saved session."
            : "Recoverable progress for this quiz was cleared by another DLMS page. This tab will no longer update the saved session.");
        }
      });
      window.addEventListener("pagehide", () => writeSnapshot());
      return Boolean(savedRecord);
    }

    function complete() {
      if (owned) removeStored();
      owned = false;
      savedRecord = null;
    }

    return {
      initialize,
      claimNew,
      checkpoint: writeSnapshot,
      complete,
      discard: startOver,
      storageKey,
      ownerToken,
      get hasSavedState() { return Boolean(savedRecord); },
      get ownsState() { return owned; },
    };
  }

  window.DLMSQuizRecovery = {
    SCHEMA_VERSION,
    RUNTIME_VERSION,
    STORAGE_PREFIX,
    MAX_RECORD_BYTES,
    EXPIRY_MS,
    quizFingerprint,
    createController,
    validateRecord,
    validateRecordEnvelope,
    pruneStoredRecords,
    listStoredRecords,
    removeStoredQuiz,
    clearAllStoredRecords,
  };
})();

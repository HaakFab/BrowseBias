/*
 * Autocomplete Bias — Content Script
 * ====================================
 * Observes Google Search autocomplete suggestions via MutationObserver,
 * applies bias-indicator coloring, and optionally scrapes suggestion data.
 */

(function () {
  'use strict';

  // ─── State ──────────────────────────────────────────────────────────
  let highlightingEnabled = true;
  let scrapingEnabled = false;
  let lastScrapedQuery = '';
  let lastScrapedSuggestions = '';

  // ─── Settings ───────────────────────────────────────────────────────
  // Load initial settings from chrome.storage
  chrome.storage.local.get(
    ['highlightingEnabled', 'scrapingEnabled', 'consentGiven'],
    (settings) => {
      highlightingEnabled = settings.highlightingEnabled !== false; // default true
      scrapingEnabled = settings.scrapingEnabled === true && settings.consentGiven === true;
    }
  );

  // Listen for settings changes in real-time (e.g. user toggles in popup)
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes.highlightingEnabled) {
      highlightingEnabled = changes.highlightingEnabled.newValue;
      if (!highlightingEnabled) {
        clearAllHighlights();
      }
    }
    if (changes.scrapingEnabled || changes.consentGiven) {
      chrome.storage.local.get(['scrapingEnabled', 'consentGiven'], (s) => {
        scrapingEnabled = s.scrapingEnabled === true && s.consentGiven === true;
      });
    }
  });

  // ─── DOM Selectors ──────────────────────────────────────────────────
  // Google's autocomplete uses ARIA roles for accessibility.
  // These are more stable than obfuscated class names.
  //
  // Primary:  ul[role="listbox"] li — the suggestion list items
  // Fallback: [role="option"], [role="presentation"] within the dropdown
  //
  // The search input is typically: input[name="q"], textarea[name="q"]
  // (Google has been migrating between input and textarea)

  const SUGGESTION_SELECTORS = [
    'ul[role="listbox"] li',
    'div[role="listbox"] [role="option"]',
    'div[role="listbox"] [role="presentation"]'
  ];

  const SEARCH_INPUT_SELECTORS = [
    'textarea[name="q"]',
    'input[name="q"]',
    'input[aria-label="Search"]',
    'textarea[aria-label="Search"]'
  ];

  // ─── Core: Find suggestion elements ─────────────────────────────────

  /**
   * Query the DOM for autocomplete suggestion elements.
   * Tries multiple selectors for resilience against Google DOM changes.
   *
   * @returns {Element[]} Array of suggestion elements found.
   */
  function findSuggestions() {
    for (const selector of SUGGESTION_SELECTORS) {
      const elements = document.querySelectorAll(selector);
      if (elements.length > 0) {
        return Array.from(elements);
      }
    }
    return [];
  }

  /**
   * Get the current search query from the input field.
   *
   * @returns {string} The current query text, or empty string if not found.
   */
  function getSearchQuery() {
    for (const selector of SEARCH_INPUT_SELECTORS) {
      const input = document.querySelector(selector);
      if (input && input.value) {
        return input.value.trim();
      }
    }
    return '';
  }

  /**
   * Cleanly extract autocomplete suggestion text from a DOM element,
   * stripping embedded <style> tags, scripts, SVG icons, and Google UI buttons.
   *
   * @param {Element} el - The suggestion DOM element.
   * @returns {string} The cleaned suggestion text.
   */
  function extractSuggestionText(el) {
    if (!el) return '';

    // Prefer dedicated Google autocomplete text elements if present
    const primarySpan = el.querySelector('.wM6W7d, .sbqs_c, [role="option"] span, div.wM6W7d');
    if (primarySpan && primarySpan.textContent) {
      const text = primarySpan.textContent.trim();
      if (text && !text.includes('{')) {
        return text;
      }
    }

    // Fallback: clone element and remove non-content tags
    try {
      const clone = el.cloneNode(true);
      const unwanted = clone.querySelectorAll('style, script, svg, button, .sbai, .Bi9oQd, .MagqMc, [aria-hidden="true"]');
      unwanted.forEach((node) => node.remove());

      let text = (clone.innerText || clone.textContent || '').trim();

      // Strip any residual CSS rule text or Google UI badges
      if (text.includes('{')) {
        text = text.split('{')[0];
      }
      text = text.replace(/(\s*AI Mode|\s*See more|\s*Delete|\s*Feedback geben|\s*Löschen|\s*Melden)+$/i, '');
      return text.replace(/\s+/g, ' ').trim();
    } catch (e) {
      let raw = (el.innerText || el.textContent || '').trim();
      return raw.split('{')[0].trim();
    }
  }

  // ─── Visual Confidence & Source Attribution Tooltip Overlay ────────
  let tooltipEl = null;

  function ensureTooltipElement() {
    if (tooltipEl && document.body.contains(tooltipEl)) return tooltipEl;
    tooltipEl = document.createElement('div');
    tooltipEl.className = 'ab-tooltip-bubble';
    document.body.appendChild(tooltipEl);
    return tooltipEl;
  }

  function showTooltip(targetEl, info) {
    if (!highlightingEnabled) return;
    const tooltip = ensureTooltipElement();

    const dotColor = info.hex || '#3b82f6';
    tooltip.innerHTML = `
      <div class="ab-tooltip-header">
        <div class="ab-tooltip-title-group">
          <span class="ab-tooltip-dot" style="background: ${dotColor}; box-shadow: 0 0 6px ${dotColor};"></span>
          <span>${info.label}</span>
        </div>
        <span class="ab-tooltip-confidence">${info.confidence} Confidence</span>
      </div>
      <div class="ab-tooltip-body">
        ${info.explanation}
      </div>
      <div class="ab-tooltip-footer">
        <span>📚 ${info.source}</span>
      </div>
    `;

    const rect = targetEl.getBoundingClientRect();
    const tooltipWidth = 280;

    // Prefer positioning to the right of the suggestion dropdown, fallback to inside/underneath
    let left = rect.right + 12;
    if (left + tooltipWidth > window.innerWidth - 16) {
      left = Math.max(16, rect.left + 24);
    }
    let top = rect.top + (rect.height / 2) - 28;
    if (top < 10) top = 10;
    if (top + 100 > window.innerHeight) top = window.innerHeight - 110;

    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
    tooltip.classList.add('ab-visible');
  }

  function hideTooltip() {
    if (tooltipEl) {
      tooltipEl.classList.remove('ab-visible');
    }
  }

  // Hide tooltip when scrolling or clicking outside
  window.addEventListener('scroll', hideTooltip, { passive: true });
  document.addEventListener('click', hideTooltip);

  // ─── Core: Apply bias highlighting ──────────────────────────────────

  /**
   * Process a single suggestion element: score it and apply color & attribution tooltip.
   *
   * @param {Element} el - The suggestion DOM element.
   */
  function processSuggestion(el) {
    if (el.dataset.abProcessed === 'true') return; // already processed

    const text = extractSuggestionText(el);
    if (!text) return;

    // Get continuous numerical score from the verified bias lexicon (bias.js)
    const score = getBiasScore(text);

    if (score !== null && score > 0) {
      // Apply continuous score via data attribute and CSS variable
      el.setAttribute('data-bias-score', score);
      el.style.setProperty('--bias-score', score);

      // Add rich tooltip and source attribution
      const info = getBiasDisplayInfo(score, text);
      el.title = `🔍 ${info.label} (${info.confidence} Confidence)\n• ${info.explanation}\n• Source: ${info.source}`;

      // Attach hover listeners for floating micro-card tooltip
      el.addEventListener('mouseenter', () => showTooltip(el, info));
      el.addEventListener('mouseleave', hideTooltip);
    } else {
      el.removeAttribute('data-bias-score');
      el.style.removeProperty('--bias-score');
      el.removeAttribute('title');
    }

    el.dataset.abProcessed = 'true';
  }

  /**
   * Remove all bias highlights from the page.
   */
  function clearAllHighlights() {
    hideTooltip();
    const processed = document.querySelectorAll('[data-ab-processed="true"]');
    processed.forEach((el) => {
      el.removeAttribute('data-bias-score');
      el.style.removeProperty('--bias-score');
      el.removeAttribute('data-ab-processed');
      el.removeAttribute('title');
    });
  }

  /**
   * Process all currently visible suggestions.
   */
  function processAllSuggestions() {
    if (!highlightingEnabled) return;

    const suggestions = findSuggestions();
    suggestions.forEach(processSuggestion);

    // Scrape if enabled
    if (scrapingEnabled && suggestions.length > 0) {
      scrapeData(suggestions);
    }
  }

  // ─── Core: Data scraping ────────────────────────────────────────────

  /**
   * Scrape the current query and suggestions, buffer them locally.
   * Only runs if the user has opted in (scrapingEnabled + consentGiven).
   *
   * @param {Element[]} suggestionElements - The suggestion DOM elements.
   */
  function scrapeData(suggestionElements) {
    const query = getSearchQuery();
    if (!query) return;

    // Extract suggestion texts and their numerical bias scores
    const suggestions = suggestionElements
      .map((el) => {
        const text = extractSuggestionText(el);
        if (!text) return null;
        const scoreAttr = el.getAttribute('data-bias-score');
        return {
          text: text,
          score: scoreAttr ? parseFloat(scoreAttr) : null
        };
      })
      .filter(Boolean);

    if (suggestions.length === 0) return;

    // Deduplicate: don't re-scrape if query + suggestions haven't changed
    const fingerprint = query + '|' + suggestions.map((s) => s.text).join('|');
    if (fingerprint === lastScrapedSuggestions) return;
    lastScrapedSuggestions = fingerprint;

    const VERSION_TAG = 'Silurian';
    const manifestVersion = chrome.runtime.getManifest().version;

    // Buffer in chrome.storage.local
    chrome.storage.local.get({ pendingData: [], user_pseudonym: 'anonymous' }, (result) => {
      const userTag = result.user_pseudonym || 'anonymous';
      const entry = {
        timestamp: new Date().toISOString(),
        query: query,
        suggestions: suggestions,
        googleTld: window.location.hostname, // e.g. "www.google.de"
        language: navigator.language || 'unknown',
        user_pseudonym: userTag,
        user_tag: userTag,
        version: manifestVersion,
        extensionVersion: manifestVersion,
        v_tag: VERSION_TAG,
        versionTag: VERSION_TAG
      };

      const pending = result.pendingData;
      pending.push(entry);

      // Safety cap: keep at most 5000 entries locally to prevent storage overflow
      if (pending.length > 5000) {
        pending.splice(0, pending.length - 5000);
      }

      chrome.storage.local.set({ pendingData: pending });
    });
  }

  // ─── Reporting & Query Inspection Listener ──────────────────────────
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'getSuggestionsForReport') {
      const query = getSearchQuery();
      const suggestionElements = findSuggestions();
      const suggestions = suggestionElements
        .map((el) => {
          const text = extractSuggestionText(el);
          if (!text) return null;
          const scoreAttr = el.getAttribute('data-bias-score');
          return {
            text: text,
            score: scoreAttr ? parseFloat(scoreAttr) : null
          };
        })
        .filter(Boolean);

      sendResponse({
        query: query,
        suggestions: suggestions,
        googleTld: window.location.hostname,
        language: navigator.language || 'unknown',
        version: chrome.runtime.getManifest().version,
        v_tag: 'Ordovician'
      });
      return true;
    }
  });

  // ─── MutationObserver ───────────────────────────────────────────────

  /**
   * Observe the DOM for autocomplete suggestion changes.
   *
   * Strategy:
   * 1. Observe document.body with childList + subtree (broad but necessary
   *    because Google dynamically creates and destroys the suggestion container)
   * 2. On each mutation batch, check if any added nodes are suggestion-related
   * 3. If so, process all suggestions (re-scan is cheap and handles race conditions)
   *
   * Performance note: The callback is debounced to avoid excessive processing
   * when Google rapidly updates the DOM during typing.
   */

  let debounceTimer = null;

  const observer = new MutationObserver((mutations) => {
    // Quick check: do any mutations involve potentially relevant nodes?
    let relevant = false;
    for (const mutation of mutations) {
      if (mutation.type !== 'childList' || mutation.addedNodes.length === 0) continue;

      for (const node of mutation.addedNodes) {
        if (node.nodeType !== Node.ELEMENT_NODE) continue;

        // Check if the node itself or its children could be suggestions
        if (
          node.getAttribute?.('role') === 'listbox' ||
          node.getAttribute?.('role') === 'option' ||
          node.getAttribute?.('role') === 'presentation' ||
          node.querySelector?.('[role="listbox"], [role="option"]')
        ) {
          relevant = true;
          break;
        }
      }
      if (relevant) break;
    }

    if (!relevant) return;

    // Debounce: wait 50ms after the last mutation before processing
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(processAllSuggestions, 50);
  });

  // Start observing
  observer.observe(document.body, {
    childList: true,
    subtree: true
  });

  // Also process on input events (catches cases where DOM mutations
  // don't fire but suggestions are already present)
  function attachInputListener() {
    for (const selector of SEARCH_INPUT_SELECTORS) {
      const input = document.querySelector(selector);
      if (input) {
        input.addEventListener('input', () => {
          // Reset processed flags so suggestions get re-evaluated
          const processed = document.querySelectorAll('[data-ab-processed="true"]');
          processed.forEach((el) => {
            el.dataset.abProcessed = 'false';
          });

          clearTimeout(debounceTimer);
          debounceTimer = setTimeout(processAllSuggestions, 100);
        });
        return;
      }
    }

    // If search input isn't in the DOM yet, retry
    setTimeout(attachInputListener, 500);
  }

  attachInputListener();

  // Initial scan in case suggestions are already visible
  setTimeout(processAllSuggestions, 300);

})();

/*
 * Autocomplete Bias — Onboarding Logic
 */

document.addEventListener('DOMContentLoaded', () => {
  const stepWelcome = document.getElementById('step-welcome');
  const stepConsent = document.getElementById('step-consent');
  const stepDone = document.getElementById('step-done');

  const btnNextConsent = document.getElementById('btn-next-consent');
  const btnConsentYes = document.getElementById('btn-consent-yes');
  const btnConsentNo = document.getElementById('btn-consent-no');
  const btnStart = document.getElementById('btn-start');

  const doneMessage = document.getElementById('done-message');
  const badgeScraping = document.getElementById('badge-scraping');

  // ─── Step navigation ───────────────────────────────────────────
  function showStep(stepEl) {
    [stepWelcome, stepConsent, stepDone].forEach((s) => {
      s.style.display = 'none';
    });
    stepEl.style.display = 'block';
    // Scroll to top of card
    stepEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ─── Step 1 → Step 2 ──────────────────────────────────────────
  btnNextConsent.addEventListener('click', () => {
    showStep(stepConsent);
  });

  // ─── Step 2: Consent YES ──────────────────────────────────────
  btnConsentYes.addEventListener('click', () => {
    chrome.storage.local.set({
      consentGiven: true,
      scrapingEnabled: true,
      consentDate: new Date().toISOString()
    }, () => {
      doneMessage.textContent =
        'Thank you for supporting our research! Your anonymized search data will help us understand bias in autocomplete suggestions.';
      badgeScraping.textContent = 'Enabled';
      badgeScraping.classList.add('badge-on');
      showStep(stepDone);
    });
  });

  // ─── Step 2: Consent NO ───────────────────────────────────────
  btnConsentNo.addEventListener('click', () => {
    chrome.storage.local.set({
      consentGiven: false,
      scrapingEnabled: false
    }, () => {
      doneMessage.textContent =
        'No problem! You can still use all bias highlighting features. If you change your mind, you can enable data collection anytime from the extension popup.';
      badgeScraping.textContent = 'Disabled';
      badgeScraping.classList.remove('badge-on');
      showStep(stepDone);
    });
  });

  // ─── Step 3: Close onboarding ─────────────────────────────────
  btnStart.addEventListener('click', () => {
    // Navigate to Google Search so the user can see the extension in action
    window.location.href = 'https://www.google.com';
  });
});

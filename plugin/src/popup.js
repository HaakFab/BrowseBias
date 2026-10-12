/*
 * Autocomplete Bias — Popup Logic
 */

document.addEventListener('DOMContentLoaded', () => {
  const VERSION_TAG = 'Silurian';

  const toggleHighlighting = document.getElementById('toggle-highlighting');
  const toggleScraping = document.getElementById('toggle-scraping');
  const selectSyncInterval = document.getElementById('select-sync-interval');
  const inputPseudonym = document.getElementById('input-pseudonym');
  const btnSavePseudonym = document.getElementById('btn-save-pseudonym');
  const btnRandomPseudonym = document.getElementById('btn-random-pseudonym');
  const consentNotice = document.getElementById('consent-notice');
  const btnGiveConsent = document.getElementById('btn-give-consent');
  const btnUploadNow = document.getElementById('btn-upload-now');
  const btnDownloadDataset = document.getElementById('btn-download-dataset');
  const btnDeleteData = document.getElementById('btn-delete-data');
  const pendingCountEl = document.getElementById('pending-count');
  const lexiconCountEl = document.getElementById('lexicon-count');
  const lastUploadEl = document.getElementById('last-upload');
  const nextSyncStatusEl = document.getElementById('next-sync-status');
  const statusVtagEl = document.getElementById('status-vtag');
  const versionEl = document.getElementById('version-number');
  const vtagEl = document.getElementById('vtag-number');
  const headerTagBadge = document.getElementById('header-tag-badge');

  // Report elements
  const contextTextEl = document.getElementById('context-text');
  const btnReportProblematic = document.getElementById('btn-report-problematic');
  const btnReportWrongBias = document.getElementById('btn-report-wrong-bias');
  const reportDetails = document.getElementById('report-details');
  const selectedReportTypeEl = document.getElementById('selected-report-type');
  const reportCommentEl = document.getElementById('report-comment');
  const btnSubmitReport = document.getElementById('btn-submit-report');
  const btnCancelReport = document.getElementById('btn-cancel-report');

  let activeReportType = null;
  let activeTabContext = {
    query: '',
    suggestions: [],
    googleTld: '',
    language: ''
  };

  // ─── Set version display ─────────────────────────────────────────
  const manifest = chrome.runtime.getManifest();
  const currentVersion = manifest.version || '1.0.3';
  if (versionEl) versionEl.textContent = currentVersion;
  if (vtagEl) vtagEl.textContent = VERSION_TAG;
  if (statusVtagEl) statusVtagEl.textContent = VERSION_TAG;
  if (headerTagBadge) headerTagBadge.textContent = `v${currentVersion} [${VERSION_TAG}]`;

  // ─── Load current settings ──────────────────────────────────────
  chrome.storage.local.get(
    [
      'highlightingEnabled',
      'scrapingEnabled',
      'consentGiven',
      'pendingData',
      'biasLexicon',
      'lastUploadTime',
      'autoSyncEnabled',
      'uploadIntervalMinutes',
      'user_pseudonym',
      'versionTag'
    ],
    (settings) => {
      toggleHighlighting.checked = settings.highlightingEnabled !== false;
      toggleScraping.checked = settings.scrapingEnabled === true;

      if (inputPseudonym && settings.user_pseudonym) {
        inputPseudonym.value = settings.user_pseudonym;
      }

      if (selectSyncInterval) {
        if (settings.autoSyncEnabled === false) {
          selectSyncInterval.value = 'manual';
        } else {
          selectSyncInterval.value = String(settings.uploadIntervalMinutes || 60);
        }
      }

      updateStatus(settings);
    }
  );

  // ─── Pseudonym Handlers ─────────────────────────────────────────
  if (btnSavePseudonym && inputPseudonym) {
    btnSavePseudonym.addEventListener('click', () => {
      const val = inputPseudonym.value.trim();
      if (!val) {
        showToast('⚠️ Pseudonym cannot be empty');
        return;
      }
      chrome.storage.local.set({ user_pseudonym: val }, () => {
        showToast(`✅ Pseudonym saved: ${val}`);
      });
    });

    inputPseudonym.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        btnSavePseudonym.click();
      }
    });
  }

  if (btnRandomPseudonym) {
    btnRandomPseudonym.addEventListener('click', () => {
      chrome.runtime.sendMessage({ type: 'generateNewPseudonym' }, (res) => {
        if (res && res.pseudonym) {
          if (inputPseudonym) inputPseudonym.value = res.pseudonym;
          showToast(`🎲 New pseudonym: ${res.pseudonym}`);
        }
      });
    });
  }

  // ─── Download Dataset Button ────────────────────────────────────
  if (btnDownloadDataset) {
    btnDownloadDataset.addEventListener('click', () => {
      chrome.storage.local.get('serverUrl', (res) => {
        const serverBase = (res.serverUrl || 'http://localhost:8765/api/upload').replace(/\/api\/upload\/?$/, '');
        const downloadUrl = `${serverBase}/api/download/suggestions.jsonl`;
        chrome.tabs.create({ url: downloadUrl });
      });
    });
  }

  // ─── Highlighting toggle ────────────────────────────────────────
  toggleHighlighting.addEventListener('change', () => {
    chrome.storage.local.set({ highlightingEnabled: toggleHighlighting.checked }, () => {
      showToast(toggleHighlighting.checked ? 'Bias highlighting enabled' : 'Bias highlighting disabled');
    });
  });

  // ─── Auto-Sync Interval Change ──────────────────────────────────
  if (selectSyncInterval) {
    selectSyncInterval.addEventListener('change', () => {
      const val = selectSyncInterval.value;
      if (val === 'manual') {
        chrome.storage.local.set({ autoSyncEnabled: false }, () => {
          showToast('Auto-sync set to manual only');
        });
      } else {
        const minutes = parseInt(val, 10);
        chrome.storage.local.set({
          autoSyncEnabled: true,
          uploadIntervalMinutes: minutes
        }, () => {
          const label = minutes >= 1440 ? 'Daily (24h)' : `Every ${minutes} min`;
          showToast(`Auto-sync set to ${label}`);
        });
      }
    });
  }

  // ─── Scraping / Logging toggle ──────────────────────────────────
  toggleScraping.addEventListener('change', () => {
    if (toggleScraping.checked) {
      chrome.storage.local.get('consentGiven', (result) => {
        if (result.consentGiven) {
          chrome.storage.local.set({ scrapingEnabled: true }, () => {
            showToast('Data logging enabled');
          });
        } else {
          toggleScraping.checked = false;
          consentNotice.style.display = 'block';
        }
      });
    } else {
      chrome.storage.local.set({ scrapingEnabled: false }, () => {
        consentNotice.style.display = 'none';
        showToast('Data logging disabled');
      });
    }
  });

  // ─── Consent button ────────────────────────────────────────────
  btnGiveConsent.addEventListener('click', () => {
    chrome.tabs.create({ url: chrome.runtime.getURL('src/onboarding.html') });
    window.close();
  });

  // ─── Detect active Google search context ───────────────────────
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || tabs.length === 0) {
      contextTextEl.textContent = 'No active Google search tab';
      return;
    }

    const activeTab = tabs[0];
    if (!activeTab.url || !activeTab.url.includes('google.')) {
      contextTextEl.textContent = 'Active tab is not Google Search';
      return;
    }

    // Request active search query & suggestions from content script
    chrome.tabs.sendMessage(
      activeTab.id,
      { type: 'getSuggestionsForReport' },
      (response) => {
        if (chrome.runtime.lastError || !response) {
          contextTextEl.textContent = 'Google tab detected (no suggestions active)';
          return;
        }

        activeTabContext = {
          query: response.query || '',
          suggestions: response.suggestions || [],
          googleTld: response.googleTld || '',
          language: response.language || ''
        };

        if (activeTabContext.query) {
          const suggCount = activeTabContext.suggestions.length;
          contextTextEl.textContent = `Query: "${activeTabContext.query}" (${suggCount} sugg.)`;
        } else {
          contextTextEl.textContent = 'Google Search tab ready';
        }
      }
    );
  });

  // ─── Reporting Handlers ─────────────────────────────────────────
  function openReportForm(type, label) {
    activeReportType = type;
    selectedReportTypeEl.textContent = `Report: ${label}`;
    btnReportProblematic.classList.toggle('active', type === 'problematic_suggestions');
    btnReportWrongBias.classList.toggle('active', type === 'wrong_bias_label');
    reportDetails.style.display = 'block';
    reportCommentEl.focus();
  }

  function closeReportForm() {
    activeReportType = null;
    btnReportProblematic.classList.remove('active');
    btnReportWrongBias.classList.remove('active');
    reportDetails.style.display = 'none';
    reportCommentEl.value = '';
  }

  btnReportProblematic.addEventListener('click', () => {
    openReportForm('problematic_suggestions', '🚨 Problematic Suggestions');
  });

  btnReportWrongBias.addEventListener('click', () => {
    openReportForm('wrong_bias_label', '🏷️ Wrong Bias Labels');
  });

  btnCancelReport.addEventListener('click', () => {
    closeReportForm();
  });

  btnSubmitReport.addEventListener('click', () => {
    if (!activeReportType) return;

    btnSubmitReport.disabled = true;
    btnSubmitReport.textContent = 'Submitting...';

    const reportPayload = {
      reportType: activeReportType,
      query: activeTabContext.query || '',
      suggestions: activeTabContext.suggestions || [],
      comment: reportCommentEl.value.trim(),
      googleTld: activeTabContext.googleTld || '',
      language: activeTabContext.language || navigator.language || 'unknown',
      version: currentVersion,
      extensionVersion: currentVersion,
      v_tag: VERSION_TAG,
      versionTag: VERSION_TAG,
      timestamp: new Date().toISOString()
    };

    chrome.runtime.sendMessage({ type: 'sendReport', data: reportPayload }, (response) => {
      btnSubmitReport.disabled = false;
      btnSubmitReport.textContent = '🚀 Submit Report';

      if (response && response.success) {
        showToast('✅ Report submitted! Thank you.');
        closeReportForm();
      } else {
        const errorMsg = response?.error || 'Failed to submit';
        showToast(`❌ Error: ${errorMsg}`);
      }
    });
  });

  // ─── Manual Upload Button ──────────────────────────────────────
  if (btnUploadNow) {
    btnUploadNow.addEventListener('click', () => {
      btnUploadNow.disabled = true;
      btnUploadNow.textContent = '⏳ Syncing...';

      chrome.runtime.sendMessage({ type: 'triggerManualUpload' }, (response) => {
        btnUploadNow.disabled = false;
        btnUploadNow.textContent = '⚡ Sync & Upload Now';

        if (response && response.success) {
          const upCount = response.upload?.count || 0;
          const lexCount = response.lexicon?.count || 0;
          const isLexSynced = response.lexicon?.success;

          if (upCount > 0 && isLexSynced) {
            showToast(`✅ Uploaded ${upCount} entries · Synced ${lexCount} lexicon terms!`);
          } else if (isLexSynced) {
            showToast(`✅ Synced ${lexCount} bias lexicon terms from server!`);
          } else if (upCount > 0) {
            showToast(`✅ Uploaded ${upCount} search entries!`);
          } else {
            showToast('✅ Lexicon & data are up to date.');
          }
        } else {
          const err = response?.upload?.error || response?.error || 'Sync failed';
          showToast(`❌ Error: ${err}`);
        }
      });
    });
  }

  // ─── Delete data button ────────────────────────────────────────
  btnDeleteData.addEventListener('click', () => {
    if (confirm('Delete all buffered search data? This cannot be undone.')) {
      chrome.runtime.sendMessage({ type: 'clearData' }, (response) => {
        if (response?.success) {
          pendingCountEl.textContent = '0';
          showToast('Buffered data deleted');
        }
      });
    }
  });

  // ─── Status updates ────────────────────────────────────────────
  function updateStatus(settings) {
    const count = settings.pendingData?.length || 0;
    pendingCountEl.textContent = count.toLocaleString();

    if (lexiconCountEl) {
      const lexCount = Object.keys(settings.biasLexicon || {}).length;
      lexiconCountEl.textContent = `${lexCount} terms`;
    }

    if (settings.lastUploadTime) {
      const date = new Date(settings.lastUploadTime);
      lastUploadEl.textContent = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else {
      lastUploadEl.textContent = 'Never';
    }

    if (nextSyncStatusEl) {
      if (settings.scrapingEnabled !== true || settings.consentGiven !== true) {
        nextSyncStatusEl.textContent = 'Paused (Logging Off)';
      } else if (settings.autoSyncEnabled === false) {
        nextSyncStatusEl.textContent = 'Manual Only';
      } else {
        const mins = settings.uploadIntervalMinutes || 60;
        nextSyncStatusEl.textContent = mins >= 1440 ? 'Daily (24h)' : `Every ${mins}m`;
      }
    }

    if (statusVtagEl) {
      statusVtagEl.textContent = settings.versionTag || VERSION_TAG;
    }
  }

  // ─── Simple toast notification ─────────────────────────────────
  function showToast(message) {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    toast.style.cssText = `
      position: fixed; bottom: 10px; left: 50%; transform: translateX(-50%);
      background: #1e293b; color: #f8fafc; padding: 6px 14px; border-radius: 6px;
      font-size: 11.5px; font-weight: 500; opacity: 0; transition: opacity 0.2s ease;
      z-index: 9999; box-shadow: 0 4px 12px rgba(0,0,0,0.15); max-width: 90%;
      text-align: center;
    `;
    document.body.appendChild(toast);
    requestAnimationFrame(() => { toast.style.opacity = '1'; });
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 200);
    }, 2200);
  }

  // ─── Listen for storage changes to keep UI in sync ─────────────
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    chrome.storage.local.get(
      ['pendingData', 'lastUploadTime', 'scrapingEnabled', 'consentGiven', 'highlightingEnabled', 'versionTag'],
      updateStatus
    );
  });
});

/*
 * Autocomplete Bias — Service Worker (Background)
 * =================================================
 * Handles:
 *  - Extension installation (default settings, onboarding page)
 *  - Periodic batch upload of scraped data via chrome.alarms (default 60 mins / 1 hr)
 *  - Automated background sync scheduling & manual upload triggers
 *  - Message handling from content script & popup
 */

// ─── Version & Tag ─────────────────────────────────────────────────
const VERSION_TAG = 'Silurian';

// ─── Pseudonym Generator ───────────────────────────────────────────
function generatePseudonym() {
  const adjectives = [
    'Curious', 'Swift', 'Silent', 'Bright', 'Amber', 'Cosmic', 'Lunar', 'Solar',
    'Silver', 'Alpine', 'Brave', 'Calm', 'Clever', 'Gentle', 'Jovial', 'Keen',
    'Noble', 'Quick', 'Rustic', 'Vibrant', 'Astral', 'Zenith', 'Polar', 'Mossy'
  ];
  const animals = [
    'Fox', 'Otter', 'Falcon', 'Badger', 'Panda', 'Lynx', 'Dolphin', 'Hawk',
    'Koala', 'Raven', 'Beaver', 'Osprey', 'Tiger', 'Robin', 'Wolf', 'Jaguar',
    'Heron', 'Finch', 'Crane', 'Orca', 'Seal', 'Ibex', 'Marten', 'Quokka'
  ];
  const adj = adjectives[Math.floor(Math.random() * adjectives.length)];
  const animal = animals[Math.floor(Math.random() * animals.length)];
  const num = Math.floor(10 + Math.random() * 90);
  return `${adj}-${animal}-${num}`;
}

// ─── Server Configurations ─────────────────────────────────────────
const DEFAULT_ONLINE_SERVER = 'https://browsebias.onrender.com';
const DEFAULT_LOCAL_SERVER = 'http://localhost:8765';

function computeEndpoints(mode = 'online', customUrl = '') {
  let base = DEFAULT_ONLINE_SERVER;
  if (mode === 'local') {
    base = DEFAULT_LOCAL_SERVER;
  } else if (mode === 'custom' && customUrl) {
    base = customUrl.replace(/\/+$/, '');
  }
  return {
    serverBaseUrl: base,
    serverUrl: `${base}/api/upload`,
    lexiconUrl: `${base}/api/lexicon`,
    reportUrl: `${base}/api/report`,
  };
}

// ─── Default settings ──────────────────────────────────────────────

const initialEndpoints = computeEndpoints('online');

const DEFAULT_SETTINGS = {
  highlightingEnabled: true,
  scrapingEnabled: false,          // opt-OUT by default (GDPR)
  consentGiven: false,
  autoSyncEnabled: true,          // automated background sync
  uploadIntervalMinutes: 60,      // 60 minutes (1 hour) default batch interval
  serverMode: 'online',           // 'online' (default Hugging Face), 'local', or 'custom'
  onlineServerUrl: DEFAULT_ONLINE_SERVER,
  localServerUrl: DEFAULT_LOCAL_SERVER,
  customServerUrl: '',
  serverBaseUrl: initialEndpoints.serverBaseUrl,
  serverUrl: initialEndpoints.serverUrl,
  lexiconUrl: initialEndpoints.lexiconUrl,
  reportUrl: initialEndpoints.reportUrl,
  user_pseudonym: '',             // auto-assigned or custom pseudonym tag
  pendingData: [],
  lastUploadTime: null,
  installDate: null,
  versionTag: VERSION_TAG
};

// ─── Alarm Management ──────────────────────────────────────────────

/**
 * Configure or reset the background upload alarm based on user settings.
 */
async function configureUploadAlarm() {
  const settings = await chrome.storage.local.get([
    'scrapingEnabled',
    'consentGiven',
    'autoSyncEnabled',
    'uploadIntervalMinutes'
  ]);

  const shouldRun = (settings.scrapingEnabled === true) &&
                    (settings.consentGiven === true) &&
                    (settings.autoSyncEnabled !== false);

  const interval = parseInt(settings.uploadIntervalMinutes || DEFAULT_SETTINGS.uploadIntervalMinutes, 10) || 60;

  await chrome.alarms.clear('batchUpload');

  if (shouldRun) {
    chrome.alarms.create('batchUpload', { periodInMinutes: interval });
    console.log(`[Autocomplete Bias] Background auto-sync alarm scheduled every ${interval} minutes.`);
  } else {
    console.log('[Autocomplete Bias] Background auto-sync alarm paused (data logging disabled or sync off).');
  }
}

// ─── Upload Execution ──────────────────────────────────────────────

/**
 * Perform upload of pending search data to the research server.
 *
 * @param {boolean} isManual - Whether this upload was triggered manually by the user.
 * @returns {Promise<{ success: boolean, count: number, error?: string }>}
 */
async function performUpload(isManual = false) {
  const settings = await chrome.storage.local.get([
    'scrapingEnabled',
    'consentGiven',
    'pendingData',
    'serverUrl',
    'user_pseudonym'
  ]);

  // Only upload if user has consented AND opted in (unless manual forced, but still check consent)
  if (!settings.consentGiven) {
    return { success: false, count: 0, error: 'User consent not provided' };
  }

  if (!isManual && !settings.scrapingEnabled) {
    return { success: false, count: 0, error: 'Data logging disabled' };
  }

  const pending = settings.pendingData || [];
  if (pending.length === 0) {
    return { success: true, count: 0, message: 'No pending entries to upload' };
  }

  const serverUrl = settings.serverUrl || DEFAULT_SETTINGS.serverUrl;
  const manifestVersion = chrome.runtime.getManifest().version;
  const userTag = settings.user_pseudonym || 'anonymous';

  // Attach user tag to each individual entry if not already present
  const taggedEntries = pending.map((entry) => ({
    ...entry,
    user_pseudonym: entry.user_pseudonym || userTag,
    user_tag: entry.user_tag || userTag
  }));

  try {
    const response = await fetch(serverUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        entries: taggedEntries,
        user_pseudonym: userTag,
        user_tag: userTag,
        uploadedAt: new Date().toISOString(),
        extensionVersion: manifestVersion,
        version: manifestVersion,
        v_tag: VERSION_TAG,
        versionTag: VERSION_TAG
      })
    });

    if (response.ok) {
      const count = pending.length;
      await chrome.storage.local.set({
        pendingData: [],
        lastUploadTime: new Date().toISOString()
      });
      console.log(`[Autocomplete Bias] Successfully uploaded ${count} entries.`);
      return { success: true, count: count };
    } else {
      const msg = `Upload failed with HTTP ${response.status}`;
      console.warn(`[Autocomplete Bias] ${msg}. Will retry next interval.`);
      return { success: false, count: 0, error: msg };
    }
  } catch (err) {
    console.error('[Autocomplete Bias] Upload error:', err.message);
    return { success: false, count: 0, error: err.message };
  }
}

async function syncLexicon() {
  const settings = await chrome.storage.local.get('lexiconUrl');
  const lexiconUrl = settings.lexiconUrl || DEFAULT_SETTINGS.lexiconUrl;
  try {
    const response = await fetch(lexiconUrl);
    if (response.ok) {
      const data = await response.json();
      if (data && data.lexicon) {
        const count = Object.keys(data.lexicon).length;
        await chrome.storage.local.set({
          biasLexicon: data.lexicon,
          lastLexiconSync: new Date().toISOString()
        });
        console.log(`[Autocomplete Bias] Synced ${count} lexicon entries from server.`);
        return { success: true, count: count };
      }
    }
    return { success: false, error: `HTTP ${response.status}` };
  } catch (err) {
    console.debug('[Autocomplete Bias] Lexicon sync skipped (server unreachable):', err.message);
    return { success: false, error: err.message };
  }
}

// ─── Installation ──────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(async (details) => {
  const existing = await chrome.storage.local.get([
    'versionTag',
    'uploadIntervalMinutes',
    'autoSyncEnabled',
    'user_pseudonym',
    'serverMode',
    'customServerUrl'
  ]);

  const assignedPseudonym = existing.user_pseudonym || generatePseudonym();
  const currentMode = existing.serverMode || DEFAULT_SETTINGS.serverMode;
  const currentCustom = existing.customServerUrl || '';
  const endpoints = computeEndpoints(currentMode, currentCustom);

  if (details.reason === 'install') {
    // Set default settings
    await chrome.storage.local.set({
      ...DEFAULT_SETTINGS,
      user_pseudonym: assignedPseudonym,
      installDate: new Date().toISOString()
    });

    // Open the onboarding/consent page
    chrome.tabs.create({ url: chrome.runtime.getURL('src/onboarding.html') });
  } else {
    // Make sure user_pseudonym and active endpoints exist for existing installs too
    await chrome.storage.local.set({
      versionTag: VERSION_TAG,
      user_pseudonym: assignedPseudonym,
      uploadIntervalMinutes: existing.uploadIntervalMinutes || DEFAULT_SETTINGS.uploadIntervalMinutes,
      autoSyncEnabled: existing.autoSyncEnabled !== undefined ? existing.autoSyncEnabled : DEFAULT_SETTINGS.autoSyncEnabled,
      serverMode: currentMode,
      customServerUrl: currentCustom,
      ...endpoints
    });
  }

  // Configure periodic batch upload alarm (1 hour / 60 minutes default)
  await configureUploadAlarm();

  // Initial lexicon sync
  await syncLexicon();
});

// ─── Re-configure alarm on startup or storage changes ──────────────

chrome.runtime.onStartup?.addListener(async () => {
  await configureUploadAlarm();
  await syncLexicon();
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  if (
    changes.scrapingEnabled ||
    changes.consentGiven ||
    changes.autoSyncEnabled ||
    changes.uploadIntervalMinutes
  ) {
    configureUploadAlarm();
  }
});

// ─── Alarm Handler: Batch Upload ───────────────────────────────────

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== 'batchUpload') return;
  console.log('[Autocomplete Bias] Batch upload alarm triggered.');
  await performUpload(false);
  await syncLexicon();
});

// ─── Message Handler ───────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'getStatus') {
    chrome.storage.local.get(
      [
        'pendingData',
        'lastUploadTime',
        'scrapingEnabled',
        'consentGiven',
        'highlightingEnabled',
        'autoSyncEnabled',
        'uploadIntervalMinutes',
        'user_pseudonym'
      ],
      (settings) => {
        let pseudonym = settings.user_pseudonym;
        if (!pseudonym) {
          pseudonym = generatePseudonym();
          chrome.storage.local.set({ user_pseudonym: pseudonym });
        }
        sendResponse({
          pendingCount: settings.pendingData?.length || 0,
          lastUploadTime: settings.lastUploadTime,
          scrapingEnabled: settings.scrapingEnabled === true,
          highlightingEnabled: settings.highlightingEnabled !== false,
          consentGiven: settings.consentGiven === true,
          autoSyncEnabled: settings.autoSyncEnabled !== false,
          uploadIntervalMinutes: settings.uploadIntervalMinutes || DEFAULT_SETTINGS.uploadIntervalMinutes,
          user_pseudonym: pseudonym,
          version: chrome.runtime.getManifest().version,
          v_tag: VERSION_TAG
        });
      }
    );
    return true; // keep message channel open for async response
  }

  if (message.type === 'generateNewPseudonym') {
    const newTag = generatePseudonym();
    chrome.storage.local.set({ user_pseudonym: newTag }, () => {
      sendResponse({ success: true, pseudonym: newTag });
    });
    return true;
  }

  if (message.type === 'triggerManualUpload') {
    Promise.all([performUpload(true), syncLexicon()]).then(([uploadRes, lexiconRes]) => {
      sendResponse({
        upload: uploadRes,
        lexicon: lexiconRes,
        success: (uploadRes && uploadRes.success) || (lexiconRes && lexiconRes.success)
      });
    });
    return true;
  }

  if (message.type === 'setServerMode') {
    const mode = message.serverMode || 'online';
    const custom = (message.customServerUrl || '').trim();
    const endpoints = computeEndpoints(mode, custom);
    chrome.storage.local.set({
      serverMode: mode,
      customServerUrl: custom,
      ...endpoints
    }, () => {
      // Sync lexicon immediately from newly selected server
      syncLexicon().then(lexRes => {
        sendResponse({ success: true, mode, endpoints, lexicon: lexRes });
      });
    });
    return true;
  }

  if (message.type === 'getVersionInfo') {
    sendResponse({
      version: chrome.runtime.getManifest().version,
      v_tag: VERSION_TAG
    });
    return true;
  }

  if (message.type === 'clearData') {
    chrome.storage.local.set({ pendingData: [], recentCaptures: [] }, () => {
      sendResponse({ success: true });
    });
    return true;
  }

  if (message.type === 'sendReport') {
    chrome.storage.local.get(['reportUrl', 'user_pseudonym'], async (res) => {
      const userTag = res.user_pseudonym || 'anonymous';
      const reportData = {
        ...message.data,
        user_pseudonym: userTag,
        user_tag: userTag,
        version: chrome.runtime.getManifest().version,
        extensionVersion: chrome.runtime.getManifest().version,
        v_tag: VERSION_TAG,
        versionTag: VERSION_TAG,
        timestamp: message.data?.timestamp || new Date().toISOString()
      };

      const reportUrl = res.reportUrl || DEFAULT_SETTINGS.reportUrl;
      try {
        const resp = await fetch(reportUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(reportData)
        });
        const json = await resp.json();
        sendResponse({ success: resp.ok, status: resp.status, data: json });
      } catch (err) {
        console.error('[Autocomplete Bias] Report submission failed:', err);
        sendResponse({ success: false, error: err.message });
      }
    });
    return true;
  }
});

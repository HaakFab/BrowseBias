/**
 * Autocomplete Bias — Continuous Numerical Bias Evaluation Engine
 * =================================================================
 *
 * Evaluates autocomplete suggestions against the numerical Bias Lexicon
 * synchronized from the research server / Bradley-Terry quantification engine.
 *
 * Supports:
 *   1. O(1) Instantaneous Exact Matches (e.g., "climate change hoax")
 *   2. High-Performance Pre-Compiled Template Matches with Anchor Indexing
 *      (e.g., "[PERSON] epstein files" matching "Hillary Clinton epstein files",
 *             "[PERSON] fraud" matching "Donald Trump fraud")
 *
 * Bias scores are continuous real numbers in [0.0, 1.0].
 * Unrated suggestions return `null` and remain uncolored in their natural state.
 */

// ─── Default Fallback Lexicon ───────────────────────────────────────
const DEFAULT_LEXICON = {
  "climate change hoax": {
    "score": 0.85,
    "scores": { "conspiracy": 0.85, "accusation": 0.40 },
    "mouseover": "This suggestion is associated with conspiracy theories (score: 0.85)."
  },
  "[PERSON] fraud": {
    "score": 0.62,
    "scores": { "political": 0.62, "accusation": 0.58 },
    "mouseover": "This suggestion reflects political ideology bias (score: 0.62)."
  },
  "[PERSON] epstein files": {
    "score": 0.78,
    "scores": { "conspiracy": 0.78, "accusation": 0.65 },
    "mouseover": "This suggestion associates individuals with conspiracy or criminal allegations (score: 0.78)."
  },
  "is the earth flat": {
    "score": 0.90,
    "scores": { "conspiracy": 0.90 },
    "mouseover": "This suggestion is associated with conspiracy theories (score: 0.90)."
  },
  "vaccines cause autism": {
    "score": 0.88,
    "scores": { "conspiracy": 0.88, "accusation": 0.50 },
    "mouseover": "This suggestion is associated with conspiracy theories (score: 0.88)."
  },
  "vaccine safety studies": {
    "score": 0.0,
    "scores": {},
    "mouseover": "This suggestion appears neutral."
  },
  "election fraud": {
    "score": 0.55,
    "scores": { "political": 0.55, "conspiracy": 0.45 },
    "mouseover": "This suggestion reflects political ideology bias (score: 0.55)."
  },
  "[PERSON] corrupt": {
    "score": 0.75,
    "scores": { "political": 0.75, "accusation": 0.70 },
    "mouseover": "This suggestion contains accusatory or defamatory language (score: 0.70)."
  }
};

// ─── In-Memory Lexicon Store & Pre-compiled Index ───────────────────
let currentLexicon = { ...DEFAULT_LEXICON };
let exactLexiconMap = new Map();
let compiledTemplates = [];

/**
 * Rebuild index for O(1) exact matching and fast indexed template evaluation.
 * Runs once upon lexicon load or sync, NOT on every keystroke.
 *
 * @param {object} lexiconObj - Dictionary mapping term/template to score entry object.
 */
function rebuildLexiconIndex(lexiconObj) {
  exactLexiconMap = new Map();
  compiledTemplates = [];

  if (!lexiconObj || typeof lexiconObj !== 'object') {
    return;
  }

  const ENTITY_TAG_PATTERN = /\[(PERSON|PER|ORG|GPE|LOC|NORP|PRODUCT|FACILITY|EVENT|LAW|LANGUAGE)\]/i;
  const anchoredTemplates = [];
  const barePlaceholderTemplates = [];

  for (const [key, entry] of Object.entries(lexiconObj)) {
    if (!key || typeof key !== 'string') continue;
    const lowerKey = key.trim().toLowerCase();

    if (ENTITY_TAG_PATTERN.test(key)) {
      // 1. Extract non-entity literal anchor keywords to enable instant string pre-filtering
      const anchorKeywords = lowerKey
        .replace(/\[[a-z_]+\]/gi, ' ')
        .split(/\s+/)
        .map(w => w.trim())
        .filter(w => w.length >= 2);

      const anchorLength = anchorKeywords.join(' ').length;

      // 2. Build regex pattern for entity placeholder
      // Placeholder matches 1 to 4 entity words (e.g. "Hillary Clinton", "Donald Trump", "Green Party")
      // Handles international characters, dots, hyphens, and apostrophes
      const escaped = key
        .replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

      const maxExtraWords = anchorKeywords.length > 0 ? 3 : 1;
      const regexPattern = '^' + escaped
        .replace(/\\\[(PERSON|PER|ORG|GPE|LOC|NORP|PRODUCT|FACILITY|EVENT|LAW|LANGUAGE)\\\]/gi, `[a-z0-9äöüßéèêáàâñç\\.\\\'-]+(?:\\s+[a-z0-9äöüßéèêáàâñç\\.\\\'-]+){0,${maxExtraWords}}`)
        .replace(/\s+/g, '\\s+') + '$';

      try {
        const compiledRegex = new RegExp(regexPattern, 'i');
        const item = {
          pattern: key,
          regex: compiledRegex,
          anchors: anchorKeywords,
          anchorLength: anchorLength,
          score: (typeof entry === 'object' && entry ? (entry.score || entry.maxScore || 0) : (typeof entry === 'number' ? entry : 0)),
          entry: entry
        };

        if (anchorKeywords.length > 0) {
          anchoredTemplates.push(item);
        } else {
          barePlaceholderTemplates.push(item);
        }
      } catch (e) {
        console.debug('[Autocomplete Bias] Template regex compilation error:', key, e);
      }
    } else {
      // Literal string exact match
      exactLexiconMap.set(lowerKey, entry);
    }
  }

  // Sort anchored templates: most specific anchor length first, then anchor count, then higher bias score
  anchoredTemplates.sort((a, b) => {
    if (b.anchorLength !== a.anchorLength) return b.anchorLength - a.anchorLength;
    if (b.anchors.length !== a.anchors.length) return b.anchors.length - a.anchors.length;
    return (b.score || 0) - (a.score || 0);
  });

  // Combine: Specific anchored templates checked first; bare placeholders checked last
  compiledTemplates = [...anchoredTemplates, ...barePlaceholderTemplates];
}

// Initial index compilation
rebuildLexiconIndex(currentLexicon);

// Load synchronized lexicon from chrome.storage.local
if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
  chrome.storage.local.get('biasLexicon', (res) => {
    if (res && res.biasLexicon && typeof res.biasLexicon === 'object') {
      currentLexicon = { ...DEFAULT_LEXICON, ...res.biasLexicon };
      rebuildLexiconIndex(currentLexicon);
    }
  });

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.biasLexicon) {
      const updated = changes.biasLexicon.newValue;
      if (updated && typeof updated === 'object') {
        currentLexicon = { ...DEFAULT_LEXICON, ...updated };
        rebuildLexiconIndex(currentLexicon);
      }
    }
  });
}

/**
 * Look up a suggestion in the bias lexicon with sub-millisecond performance.
 *
 * Uses:
 *   1. O(1) Map lookup for exact phrases
 *   2. Fast keyword anchor filtering before pre-compiled RegExp testing for templates
 *
 * @param {string} suggestionText - The text content of the autocomplete suggestion.
 * @returns {object|null} The lexicon entry object or null if unrated.
 */
function lookupSuggestion(suggestionText) {
  if (!suggestionText) return null;
  const text = suggestionText.toLowerCase().trim();

  // 1. Direct O(1) exact match lookup
  const exact = exactLexiconMap.get(text);
  if (exact !== undefined) {
    return exact;
  }

  // 2. High-speed Indexed Template Matching
  const tmplCount = compiledTemplates.length;
  for (let i = 0; i < tmplCount; i++) {
    const tmpl = compiledTemplates[i];

    // Fast string rejection: All non-placeholder anchor words must be in text
    let matchesAnchors = true;
    const anchors = tmpl.anchors;
    const anchorCount = anchors.length;
    for (let j = 0; j < anchorCount; j++) {
      if (!text.includes(anchors[j])) {
        matchesAnchors = false;
        break;
      }
    }

    if (matchesAnchors && tmpl.regex.test(text)) {
      return tmpl.entry;
    }
  }

  return null;
}

/**
 * Get the numerical bias score for a suggestion.
 *
 * Returns a continuous numerical score in [0.0, 1.0] if scored, or null if unrated/neutral.
 *
 * @param {string} suggestionText - The text content of the autocomplete suggestion.
 * @returns {number|null} Continuous bias score (0.01 - 1.0) or null if unrated or 0.0.
 */
function getBiasScore(suggestionText) {
  const entry = lookupSuggestion(suggestionText);
  if (!entry) {
    return null; // Unrated
  }

  let num = 0.0;
  if (typeof entry === 'number') {
    num = entry;
  } else if (typeof entry === 'object') {
    num = entry.score !== undefined ? entry.score : (entry.maxScore !== undefined ? entry.maxScore : 0.0);
  }

  return num > 0.0 ? num : null;
}

/**
 * Convert numerical score and suggestion text to rich display info for tooltips.
 *
 * @param {number|null} score - The continuous bias score in [0.0, 1.0].
 * @param {string} [suggestionText] - The suggestion text to look up specific details for.
 * @returns {{
 *   score: number,
 *   scorePercentage: number,
 *   confidence: string,
 *   hex: string,
 *   source: string,
 *   explanation: string,
 *   scores: object,
 *   fullAttribution: string
 * }}
 */
function getBiasDisplayInfo(score, suggestionText) {
  const entry = suggestionText ? lookupSuggestion(suggestionText) : null;
  const numScore = (typeof score === 'number') ? score : (entry && (entry.score || entry.maxScore)) || 0.0;

  // Dynamic confidence & label based purely on numeric scale
  let confidence = 'Neutral';
  let label = 'Neutral';
  let hex = '#94a3b8';

  if (numScore >= 0.65) {
    confidence = 'High';
    label = `High Bias (${(numScore * 100).toFixed(0)}%)`;
    hex = '#DC2626';
  } else if (numScore >= 0.35) {
    confidence = 'Moderate';
    label = `Moderate Bias (${(numScore * 100).toFixed(0)}%)`;
    hex = '#F59E0B';
  } else if (numScore > 0) {
    confidence = 'Provisional';
    label = `Low Bias (${(numScore * 100).toFixed(0)}%)`;
    hex = '#FBBF24';
  }

  let explanation = 'This suggestion appears neutral or has not yet been scored by the bias engine.';
  let source = 'Unrated';
  let scores = {};

  if (entry) {
    source = 'Bias Lexicon · Bradley-Terry Engine';
    if (typeof entry === 'object') {
      if (entry.mouseover) explanation = entry.mouseover;
      if (entry.scores) scores = entry.scores;
    }
  }

  return {
    score: numScore,
    scorePercentage: Math.round(numScore * 100),
    confidence,
    label,
    hex,
    source,
    explanation,
    scores,
    fullAttribution: `${label} [Score ${numScore.toFixed(2)}]: ${explanation}`
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    lookupSuggestion,
    getBiasScore,
    getBiasDisplayInfo,
    rebuildLexiconIndex,
    DEFAULT_LEXICON
  };
}

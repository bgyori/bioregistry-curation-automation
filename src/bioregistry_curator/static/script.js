/**
 * Bioregistry Curation Automation - Frontend Application
 * Handles PMID metadata extraction, contributor management, and PMID rankings display
 */

// ============================================================================
// Constants
// ============================================================================

const SESSION_CONTRIBUTOR_KEY = 'bioregistry_session_contributor';
const ORCID_PATTERN = /^\d{4}-\d{4}-\d{4}-\d{4}$/;
const PMID_PATTERN = /^[0-9]+$/;
const COPY_MESSAGE_TIMEOUT = 2000;

const API_ENDPOINTS = {
  EXTRACT: '/extract',
  PMID_RANKINGS: '/pmid-rankings'
};

const STATUS_MESSAGES = {
  EXTRACTING: 'Extracting metadata...',
  SCRAPING: 'Scraping database information...',
  DONE: 'Done. You can edit the JSON below.',
  LOADING_PMIDS: 'Loading suggested PMIDs...',
  NO_PMIDS: 'No PMIDs available',
  INVALID_PMID: 'Please enter a numeric PMID (e.g., 12345678).',
  INVALID_ORCID: 'ORCID should be in format: 0000-0000-0000-0000'
};

// ============================================================================
// DOM Elements
// ============================================================================

// Main app elements
const pmidInput = document.getElementById('pmid');
const extractBtn = document.getElementById('extract');
const statusEl = document.getElementById('status');
const outputArea = document.getElementById('output-area');
const jsonOutput = document.getElementById('json-output');
const copyBtn = document.getElementById('copy');
const copyMsg = document.getElementById('copy-msg');
const startOverBtn = document.getElementById('start-over');
const mainApp = document.getElementById('main-app');

// PMID Rankings elements
const pmidRankingsStatus = document.getElementById('pmid-rankings-status');
const pmidRankingsList = document.getElementById('pmid-rankings-list');

// Contributor modal elements
const contributorModal = document.getElementById('contributor-modal');
const contributorForm = document.getElementById('contributor-form');
const contributorNameInput = document.getElementById('contributor-name');
const contributorEmailInput = document.getElementById('contributor-email');
const contributorOrcidInput = document.getElementById('contributor-orcid');
const contributorGithubInput = document.getElementById('contributor-github');

// Contributor banner elements
const contributorBanner = document.getElementById('contributor-banner');
const contributorDisplay = document.getElementById('contributor-display');
const editContributorBtn = document.getElementById('edit-contributor');

// ============================================================================
// Contributor Management Functions
// ============================================================================

/**
 * Get stored contributor information from session storage
 * @returns {Object|null} Contributor object or null if not found
 */
function getContributor() {
  const sessionStored = sessionStorage.getItem(SESSION_CONTRIBUTOR_KEY);
  if (sessionStored) {
    try {
      return JSON.parse(sessionStored);
    } catch (e) {
      console.error('Failed to parse contributor data:', e);
      return null;
    }
  }
  return null;
}

/**
 * Save contributor information to session storage
 * @param {Object} contributor - Contributor object with name, email, orcid, github
 */
function saveContributor(contributor) {
  sessionStorage.setItem(SESSION_CONTRIBUTOR_KEY, JSON.stringify(contributor));
}

/**
 * Populate and show the contributor modal
 */
function showContributorModal() {
  const contributor = getContributor();
  if (contributor) {
    contributorNameInput.value = contributor.name || '';
    contributorEmailInput.value = contributor.email || '';
    contributorOrcidInput.value = contributor.orcid || '';
    contributorGithubInput.value = contributor.github || '';
  }
  contributorModal.classList.remove('hidden');
  mainApp.classList.add('hidden');
  contributorNameInput.focus();
}

/**
 * Hide the contributor modal and show the main app
 */
function hideContributorModal() {
  contributorModal.classList.add('hidden');
  mainApp.classList.remove('hidden');
  updateContributorBanner();
}

/**
 * Update the contributor banner display with current contributor info
 */
function updateContributorBanner() {
  const contributor = getContributor();
  if (contributor && contributor.name) {
    let displayText = `Contributing as: <strong>${contributor.name}</strong>`;
    if (contributor.github) {
      displayText += ` (@${contributor.github})`;
    }
    contributorDisplay.innerHTML = displayText;
    contributorBanner.style.display = 'flex';
  } else {
    contributorBanner.style.display = 'none';
  }
}

/**
 * Validate ORCID format
 * @param {string} orcid - ORCID to validate
 * @returns {boolean} True if valid or empty, false otherwise
 */
function validateOrcid(orcid) {
  return !orcid || ORCID_PATTERN.test(orcid);
}

// ============================================================================
// Event Handlers
// ============================================================================

/**
 * Handle contributor form submission
 */
contributorForm.addEventListener('submit', (e) => {
  e.preventDefault();

  const contributor = {
    name: contributorNameInput.value.trim(),
    email: contributorEmailInput.value.trim(),
    orcid: contributorOrcidInput.value.trim(),
    github: contributorGithubInput.value.trim()
  };

  // Validate ORCID format if provided
  if (!validateOrcid(contributor.orcid)) {
    alert(STATUS_MESSAGES.INVALID_ORCID);
    contributorOrcidInput.focus();
    return;
  }

  saveContributor(contributor);
  hideContributorModal();
});

/**
 * Handle edit contributor button click
 */
editContributorBtn.addEventListener('click', (e) => {
  e.preventDefault();
  showContributorModal();
});

/**
 * Handle start over button click
 */
startOverBtn.addEventListener('click', (e) => {
  e.preventDefault();
  reset();
});

// ============================================================================
// UI Helper Functions
// ============================================================================

/**
 * Set the status message displayed to the user
 * @param {string} msg - Status message to display
 */
function setStatus(msg) {
  statusEl.textContent = msg;
}

/**
 * Show the JSON output area
 */
function showOutput() {
  outputArea.classList.remove('hidden');
}

/**
 * Hide the JSON output area
 */
function hideOutput() {
  outputArea.classList.add('hidden');
}

/**
 * Reset the form to initial state while preserving contributor info
 */
function reset() {
  // Save current contributor info before resetting (for "Start Over")
  const contributor = getContributor();
  if (contributor) {
    sessionStorage.setItem(SESSION_CONTRIBUTOR_KEY, JSON.stringify(contributor));
  }

  pmidInput.value = '';
  setStatus('');
  jsonOutput.value = '';
  hideOutput();
  copyMsg.textContent = '';
}

/**
 * Handle metadata extraction
 */
extractBtn.addEventListener('click', async (e) => {
  e.preventDefault();
  copyMsg.textContent = '';

  const pmid = pmidInput.value.trim();
  if (!PMID_PATTERN.test(pmid)) {
    setStatus(STATUS_MESSAGES.INVALID_PMID);
    return;
  }

  // Get contributor info to send with request
  const contributor = getContributor() || { name: '', email: '', orcid: '', github: '' };

  setStatus(STATUS_MESSAGES.EXTRACTING);
  hideOutput();

  try {
    const resp = await fetch(API_ENDPOINTS.EXTRACT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pmid, contributor })
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ message: 'Unknown error' }));
      setStatus('Error: ' + (err.message || resp.statusText));
      return;
    }

    const body = await resp.json();
    if (body.status !== 'success') {
      setStatus('Error: ' + (body.message || 'Extraction failed'));
      return;
    }

    setStatus(STATUS_MESSAGES.SCRAPING);
    // The backend performs scraping; show the result
    const formatted = JSON.stringify(body.data, null, 2);
    jsonOutput.value = formatted;
    showOutput();
    setStatus(STATUS_MESSAGES.DONE);
  } catch (err) {
    console.error('Extraction error:', err);
    setStatus('Unexpected error: ' + err.message);
  }
});

/**
 * Handle copy to clipboard button click
 */
copyBtn.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(jsonOutput.value);
    copyMsg.textContent = 'Copied!';
    setTimeout(() => copyMsg.textContent = '', COPY_MESSAGE_TIMEOUT);
  } catch (e) {
    console.error('Copy failed:', e);
    copyMsg.textContent = 'Copy failed';
  }
});

// ============================================================================
// PMID Rankings Functions
// ============================================================================

/**
 * Create a clickable PMID item element
 * @param {Object} entry - PMID entry data
 * @returns {HTMLElement} PMID item element
 */
function createPmidItem(entry) {
  const pmidItem = document.createElement('div');
  pmidItem.className = 'pmid-item';

  const pmidLink = document.createElement('a');
  pmidLink.href = '#';
  pmidLink.className = 'pmid-link';
  pmidLink.textContent = entry.pubmed || entry.pmid || 'N/A';
  pmidLink.title = 'Click to auto-fill this PMID';

  // Auto-fill on click
  pmidLink.addEventListener('click', (e) => {
    e.preventDefault();
    const pmid = entry.pubmed || entry.pmid;
    if (pmid && PMID_PATTERN.test(pmid)) {
      pmidInput.value = pmid;
      pmidInput.focus();
      // Scroll to input area
      document.getElementById('input-area').scrollIntoView({
        behavior: 'smooth',
        block: 'center'
      });
    }
  });

  pmidItem.appendChild(pmidLink);

  // Add any additional info from the TSV if available
  if (entry.name || entry.title) {
    const infoSpan = document.createElement('span');
    infoSpan.className = 'pmid-info';
    infoSpan.textContent = entry.name || entry.title || '';
    pmidItem.appendChild(infoSpan);
  }

  return pmidItem;
}

/**
 * Display PMID rankings in the UI
 * @param {Array} pmidData - Array of PMID entry objects
 */
function displayPmidRankings(pmidData) {
  pmidRankingsList.innerHTML = '';

  pmidData.forEach((entry) => {
    const pmidItem = createPmidItem(entry);
    pmidRankingsList.appendChild(pmidItem);
  });

  const count = pmidData.length;
  pmidRankingsStatus.textContent = `${count} suggested PMID${count !== 1 ? 's' : ''} (updates hourly)`;
  pmidRankingsStatus.className = 'rankings-status success';
}

/**
 * Fetch and display PMID rankings from the backend
 */
async function fetchPmidRankings() {
  pmidRankingsStatus.textContent = STATUS_MESSAGES.LOADING_PMIDS;
  pmidRankingsStatus.className = 'rankings-status loading';
  pmidRankingsList.innerHTML = '';

  try {
    const resp = await fetch(API_ENDPOINTS.PMID_RANKINGS);

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
    }

    const body = await resp.json();

    if (body.status !== 'success') {
      throw new Error(body.message || 'Failed to fetch PMID rankings');
    }

    const pmidData = body.data || [];

    if (pmidData.length === 0) {
      pmidRankingsStatus.textContent = STATUS_MESSAGES.NO_PMIDS;
      pmidRankingsStatus.className = 'rankings-status';
      return;
    }

    displayPmidRankings(pmidData);

  } catch (err) {
    console.error('Failed to fetch PMID rankings:', err);
    pmidRankingsStatus.textContent = `Error loading PMIDs: ${err.message}`;
    pmidRankingsStatus.className = 'rankings-status error';
  }
}

// ============================================================================
// Session Management
// ============================================================================

// Clear session storage on fresh page load (BEFORE init runs)
if (performance.getEntriesByType('navigation')[0].type === 'reload') {
  sessionStorage.removeItem(SESSION_CONTRIBUTOR_KEY);
}

// ============================================================================
// Application Initialization
// ============================================================================

/**
 * Initialize the application
 * - Check for existing contributor info
 * - Show/hide contributor modal accordingly
 * - Fetch PMID rankings
 */
function init() {
  const contributor = getContributor();

  reset();

  if (contributor && contributor.name) {
    // Contributor info exists from previous extraction in same session
    hideContributorModal();
  } else {
    // No contributor info, show the modal
    showContributorModal();
  }

  // Fetch PMID rankings after initialization
  fetchPmidRankings();
}

// Start the application
init();
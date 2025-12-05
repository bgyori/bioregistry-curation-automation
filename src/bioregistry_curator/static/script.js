// DOM Elements - Main app
const pmidInput = document.getElementById('pmid');
const extractBtn = document.getElementById('extract');
const statusEl = document.getElementById('status');
const outputArea = document.getElementById('output-area');
const jsonOutput = document.getElementById('json-output');
const copyBtn = document.getElementById('copy');
const copyMsg = document.getElementById('copy-msg');
const startOverBtn = document.getElementById('start-over');
const mainApp = document.getElementById('main-app');

// DOM Elements - Contributor modal
const contributorModal = document.getElementById('contributor-modal');
const contributorForm = document.getElementById('contributor-form');
const contributorNameInput = document.getElementById('contributor-name');
const contributorEmailInput = document.getElementById('contributor-email');
const contributorOrcidInput = document.getElementById('contributor-orcid');
const contributorGithubInput = document.getElementById('contributor-github');

// DOM Elements - Contributor banner
const contributorBanner = document.getElementById('contributor-banner');
const contributorDisplay = document.getElementById('contributor-display');
const editContributorBtn = document.getElementById('edit-contributor');

// Storage keys for contributor info
const SESSION_CONTRIBUTOR_KEY = 'bioregistry_session_contributor'; // For "Start Over" persistence

// Get stored contributor info
function getContributor() {
  // Check sessionStorage (from "Start Over" or same session)
  const sessionStored = sessionStorage.getItem(SESSION_CONTRIBUTOR_KEY);
  if (sessionStored) {
    try {
      return JSON.parse(sessionStored);
    } catch (e) {
      return null;
    }
  }
  return null;
}

// Save contributor info
function saveContributor(contributor) {
  sessionStorage.setItem(SESSION_CONTRIBUTOR_KEY, JSON.stringify(contributor));
}

// Show contributor modal
function showContributorModal(editMode = false) {
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

// Hide contributor modal and show main app
function hideContributorModal() {
  contributorModal.classList.add('hidden');
  mainApp.classList.remove('hidden');
  updateContributorBanner();
}

// Update the contributor banner display
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

// Handle contributor form submission
contributorForm.addEventListener('submit', (e) => {
  e.preventDefault();

  const contributor = {
    name: contributorNameInput.value.trim(),
    email: contributorEmailInput.value.trim(),
    orcid: contributorOrcidInput.value.trim(),
    github: contributorGithubInput.value.trim()
  };

  // Validate ORCID format if provided
  if (contributor.orcid && !/^\d{4}-\d{4}-\d{4}-\d{4}$/.test(contributor.orcid)) {
    alert('ORCID should be in format: 0000-0000-0000-0000');
    contributorOrcidInput.focus();
    return;
  }

  saveContributor(contributor);
  hideContributorModal();
});

// Edit contributor button handler
editContributorBtn.addEventListener('click', (e) => {
  e.preventDefault();
  showContributorModal(true);
});

function setStatus(msg){
  statusEl.textContent = msg;
}

function showOutput(){
  outputArea.classList.remove('hidden');
}

function hideOutput(){
  outputArea.classList.add('hidden');
}

function reset(){
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

startOverBtn.addEventListener('click', (e)=>{ e.preventDefault(); reset(); });

extractBtn.addEventListener('click', async (e)=>{
  e.preventDefault();
  copyMsg.textContent = '';
  const pmid = pmidInput.value.trim();
  if(!/^[0-9]+$/.test(pmid)){
    setStatus('Please enter a numeric PMID (e.g., 12345678).');
    return;
  }

  // Get contributor info to send with request
  const contributor = getContributor() || {name: '', email: '', orcid: '', github: ''};

  setStatus('Extracting metadata...');
  hideOutput();
  try{
    const resp = await fetch('/extract', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({pmid, contributor})
    });

    if(!resp.ok){
      const err = await resp.json().catch(()=>({message: 'Unknown error'}));
      setStatus('Error: ' + (err.message || resp.statusText));
      return;
    }

    const body = await resp.json();
    if(body.status !== 'success'){
      setStatus('Error: ' + (body.message || 'Extraction failed'));
      return;
    }

    setStatus('Scraping database information...');
    // The backend performs scraping; show the result
    const formatted = JSON.stringify(body.data, null, 2);
    jsonOutput.value = formatted;
    showOutput();
    setStatus('Done. You can edit the JSON below.');
  }catch(err){
    setStatus('Unexpected error: ' + err.message);
  }
});

copyBtn.addEventListener('click', async ()=>{
  try{
    await navigator.clipboard.writeText(jsonOutput.value);
    copyMsg.textContent = 'Copied!';
    setTimeout(()=>copyMsg.textContent = '', 2000);
  }catch(e){
    copyMsg.textContent = 'Copy failed';
  }
});

// Clear session storage on fresh page load (BEFORE init runs)
if (performance.getEntriesByType('navigation')[0].type === 'reload') {
  // This is a page refresh - clear contributor
  sessionStorage.removeItem(SESSION_CONTRIBUTOR_KEY);
}

// Initialize application
function init() {
  // Check if contributor info exists from same session
  const contributor = getContributor();
  
  reset();

  if (contributor && contributor.name) {
    // Contributor info exists from previous extraction in same session
    hideContributorModal();
  } else {
    // No contributor info, show the modal
    showContributorModal();
  }
}

init();
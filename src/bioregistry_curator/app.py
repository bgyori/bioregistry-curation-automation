"""
Bioregistry Curation Automation - Flask Application

This application provides automated extraction of database metadata from PubMed publications
and web scraping of database homepages for bioregistry curation.
"""

from flask import Flask, request, jsonify, render_template
import re
import asyncio
import logging
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
import requests
import csv
from io import StringIO
from datetime import datetime, timedelta
from threading import Lock

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Constants
CACHE_DURATION = timedelta(hours=1)
TSV_URL = "https://raw.githubusercontent.com/biopragmatics/bioregistry/main/exports/analyses/paper_ranking/predictions.tsv"
PUBMED_REQUEST_TIMEOUT = 10
ORCID_PATTERN = r'^\d{4}-\d{4}-\d{4}-\d{4}$'
PMID_PATTERN = r'\d+'
URL_PATTERN = r"https?://[^\s\)\]]+"

# Cache for PMID rankings data
pmid_cache: Dict[str, Any] = {
    'data': None,
    'last_fetched': None,
    'lock': Lock()
}


# Helper Functions

def extract_year_from_pubdate(pubdate: str) -> Optional[int]:
    """Extract year from publication date string."""
    match = re.search(r"(19|20)\d{2}", pubdate)
    return int(match.group(0)) if match else None


def extract_first_author(authors: List[Any]) -> str:
    """Extract first author name from authors list."""
    if not authors:
        return ""

    if isinstance(authors[0], dict):
        return authors[0].get("name") or authors[0].get("fullname") or ""
    return str(authors[0])


def extract_urls_from_text(text: str) -> List[str]:
    """Extract and clean URLs from text."""
    raw_urls = re.findall(URL_PATTERN, text)
    # Clean trailing punctuation
    return [re.sub(r"[\.,;:]+$", "", url) for url in raw_urls]


def extract_keywords(item: Dict[str, Any]) -> List[str]:
    """Extract keywords from PubMed metadata item."""
    if not isinstance(item, dict):
        return []

    kw = item.get('keywords') or item.get('mesh_terms') or item.get('keyword') or item.get('subject')
    if not kw:
        return []

    if isinstance(kw, (list, tuple)):
        return [str(x).strip() for x in kw if x]

    return [k.strip() for k in str(kw).split(',') if k.strip()]


def extract_pubmed_metadata(pmid: str) -> Dict[str, Any]:
    """
    Extract metadata for a PMID using INDRA's pubmed client.

    Args:
        pmid: PubMed ID as a string

    Returns:
        Dictionary with keys: title, doi, abstract, first_author, pmid, year,
        homepage (if found), keywords, or error key if extraction failed
    """
    try:
        from indra.literature.pubmed_client import get_metadata_for_ids
    except Exception as e:
        return {"error": f"INDRA import error: {e}"}

    try:
        # Request abstracts from INDRA so we can search the full abstract text for URLs
        raw = get_metadata_for_ids([str(pmid)], get_abstracts=True, detailed_authors=False)
    except Exception as e:
        return {"error": f"PubMed fetch error: {e}"}

    if not raw:
        return {"error": "No metadata returned from PubMed"}

    # raw is usually a dict keyed by pmid
    item = raw.get(str(pmid)) if isinstance(raw, dict) else raw
    if not item and isinstance(raw, dict):
        item = list(raw.values())[0]

    # Extract basic metadata
    title = item.get("title") or ""
    doi = item.get("doi") or item.get("elocationid") or ""
    abstract = item.get("abstract") or ""

    # Extract first author
    authors = item.get("authors") or item.get("author_list") or []
    first_author = extract_first_author(authors)

    # Extract year
    year = None
    if item.get("year"):
        try:
            year = int(item.get("year"))
        except (ValueError, TypeError):
            year = None
    else:
        pubdate = item.get("pubdate") or ""
        year = extract_year_from_pubdate(pubdate)

    # Find homepage URLs in abstract
    urls = extract_urls_from_text(abstract)
    homepage = urls[0] if urls else ""

    # Extract keywords
    keywords = extract_keywords(item)

    return {
        "title": title,
        "doi": doi,
        "abstract": abstract,
        "first_author": first_author,
        "pmid": str(pmid),
        "year": year,
        "homepage": homepage,
        "keywords": keywords,
    }


# Browser scraping constants
BROWSER_AGENT_MODEL = "gpt-4o"
BROWSER_AGENT_PROMPT = r"""Visit {homepage_url} and extract database information.

DO NOT USE REGISTRY SITES: Avoid bioregistry.io, biopragmatics.github.io, identifiers.org. Use primary sources only.

CRITICAL: Extract only observed data - never invent or guess - use EMPTY if not found.

Return EXACTLY these 10 fields:

Name: [full official database name - the acronym expansion]
Prefix: [short acronym in lowercase, only alphabet]
Description: [one sentence describing what identifiers represent and their purpose]
Example: [one typical identifier, base format without versions]
Pattern: [regex pattern matching the identifier format]
URI_Format: [URL pattern with $1 as ID placeholder]
Contact_Name: [contact person full name]
Contact_Email: [email address]
Contact_Orcid: [orcid]
Keywords: [exactly 3 lowercase scientific terms, comma-separated]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EXTRACTION GUIDE

1. NAME - Official Acronym Expansion

Check: Publications (abstract/intro), About page, homepage header, documentation
Look for: "[Full Name] ([ACRONYM])" or "[ACRONYM] stands for [Full Name]"

Priority:
1. Official expansion (e.g., "PSSKB" → "Protein Structure and Stability Knowledge Base")
2. If no expansion found, use acronym (e.g., "RiboCirc")

Clean the name:
- Strip versions: "DATA 3.0" → "DATA"
- Remove suffixes: "PDB (updated)" → "PDB", "GenBank-nr" → "GenBank"
- Keep core acronym: no numbers, "v[X]", years, "-[suffix]"

Examples:
✓ "Protein Structure and Stability Knowledge Base"
✓ "RiboCirc"
✗ "comprehensive database of translatable circRNAs" (description, not name)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2. DESCRIPTION - What identifiers represent and why

Format: "Identifiers correspond to [entities] for [purpose]"

Required: Entity type + Purpose/use case
Focus: What the IDs represent, not the database itself

Examples:
✓ "Identifiers correspond to biosynthetic gene clusters producing specialized metabolites for comparative genomics analysis"
✓ "Identifiers correspond to small molecules with biochemical activity data for drug discovery"
✗ "ChEMBL is a database created in 2009" (database history, not identifier purpose)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3. EXAMPLE - One canonical identifier (base format)

Source: Extract from entry URLs when finding URI_Format
- URLs: /browse/RCDDd001, /browse/RCDDd002 → Use "RCDDd001"

Base format only:
- "BGC0000001.5" → Use "BGC0000001"
- "?id=12345" → Use "12345"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

4. PATTERN - Regex for identifier format

WORKFLOW:
a) Extract IDs from entry URLs on browse page
b) Collect 3-5 different example IDs
c) Check total entry count for digit range
d) Build pattern supporting full range

Example:
- URLs: /browse/RCDDd001, /browse/RCDDd002, /browse/RCDDd003
- Total entries: 1108
- Pattern needs: ^RCDD[di]\d{{1,4}}$ (not \d{{3}})

Handle variable formats:
- If seeing: /entry/7O1K_A AND /entry/3CIA_D308_D388
- Pattern: ^[A-Z0-9]{{4}}_[A-Z](\d+_[A-Z]\d+)?$

No version patterns (\.\d or _v\d)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

5. URI_FORMAT - URL to individual entries

5. URI_FORMAT - URL to individual entries

ABSOLUTE RULE: Only extract patterns from OBSERVED clickable links.
NEVER construct or guess URL patterns.

METHOD:
1. Navigate to Browse/Database → Wait 10s → Scroll
2. When table loads, inspect for clickable links:

   CHECK IN THIS ORDER:
   a) ID column: Look for <a> tags (will be indexed as clickable)
   b) Action columns: "View", "Details", "More", "Info" buttons
   c) Table row: Click entry, wait 10s, check if:
      - URL changed (extract new URL as pattern)
      - Detail panel appeared (no stable URI → EMPTY)
      - Nothing happened (no stable URI → EMPTY)

3. If you find clickable <a> tag with href:
   - Click it → Note URL that loads
   - Extract pattern, replace ID with $1
   - Navigate to URL with 2nd Example ID
   - Confirm page loads successfully
   - Output verified pattern

4. If NO clickable links found:
   - Use `evaluate` to inspect table cell HTML
   - Look for href attributes in parent elements
   - Check for data-url or data-link attributes
   - If still no links found → Mark EMPTY

VERIFICATION CHECKLIST (must complete before marking EMPTY):
□ Checked ID column for <a> tags
□ Checked all action columns for links/buttons
□ Clicked 3+ different entries to test behavior
□ Used `evaluate` to inspect table HTML for hidden hrefs
□ Scrolled entire table to check for link variations
□ Checked Tutorial/FAQ for documented URL structure

CRITICAL - WHEN TO MARK EMPTY:
✓ If clicking entry loads details but URL stays same → EMPTY
✓ If clicking entry does nothing → EMPTY
✓ If no <a> tags found anywhere in table → EMPTY
✓ If Tutorial/FAQ show no entry URL format → EMPTY

FORBIDDEN:
✗ NEVER test URLs like /details/$1 or /entry/$1 without observing them
✗ NEVER assume common patterns exist
✗ If you're typing a URL in navigate that you haven't seen → STOP

Format: Full URL with $1 placeholder (only if observed and verified)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

6. CONTACT - Find contact person

Primary sources: About, Contact, Team pages, Footer, GitHub
Prioritize: PI > Lead Developer > Corresponding Author

ORCID search required:
If contact name found but no ORCID on site → Search externally:
- "[Contact Name] [Email] ORCID"
- "[Contact Name] [Institution] ORCID"
Check: ORCID.org, Google Scholar, PubMed, university pages

Only mark Contact_Orcid EMPTY after external search fails.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

7. KEYWORDS - 3 specific scientific terms

Include: Entity type + Scientific domain + Application
Lowercase, spaces allowed

Examples:
✓ "biosynthetic gene clusters, secondary metabolites, genomics"
✗ "database, comprehensive, curated" (too generic)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NAVIGATION STRATEGY

1. Homepage → About/Docs (Name, Description, Contact)
2. Browse/Search → Entry links (Example, Pattern, URI_Format)
3. Verify URI_Format by testing with multiple IDs
4. Publications/External search (ORCID if not found)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PERSISTENCE REQUIREMENTS (CRITICAL - READ CAREFULLY)

SPAs are slow - DO NOT give up easily:

FOR EVERY PAGE THAT APPEARS BLANK:
1. Wait 10 seconds (not 3-5)
2. Scroll down to bottom
3. Scroll back to top
4. Wait another 5 seconds
5. Refresh page
6. Repeat steps 1-5 at least 3 times

"Page readiness timeout" warnings are NORMAL - ignore them and keep trying.

BEFORE marking Example/Pattern/URI_Format as EMPTY, you MUST:

□ Try Browse page: 3+ refresh cycles (wait, scroll, refresh)
□ Try Search page: 3+ refresh cycles
□ Try Tutorial/FAQ/Documentation pages
□ Search with Example ID from external sources
□ After search, wait 10s + scroll even if blank
□ Try constructing entry URLs manually (e.g., /motif/card/EXAMPLE_ID)
□ Navigate to constructed URLs 3+ times with different IDs
□ Try all alternative browse links (Database, Entries, List, etc.)

MINIMUM EFFORT REQUIRED:
- 20+ steps attempting to load primary site
- 10+ navigation attempts to different pages
- 5+ attempts to verify each potential URI pattern

Only mark EMPTY after exhausting ALL attempts above.

WHEN YOU FIND AN EXAMPLE ID FROM EXTERNAL SOURCES:
DO NOT immediately mark fields as EMPTY just because browse failed.
Instead:
1. Construct potential URI patterns based on site structure
2. Try: /motif/$1, /entry/$1, /card/$1, /details/$1, /view/$1
3. Navigate to each pattern with Example ID
4. Test 3+ variations before giving up

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VERIFICATION CHECKLIST

□ Name: Official expansion found (not invented)
□ Example: Extracted from entry URLs (base format)
□ Pattern: Built from multiple IDs, supports full range
□ URI_Format: Tested by navigating with 2+ IDs
□ Contact_Orcid: Searched externally if not on site
□ Persistence: 20+ steps on primary site before EMPTY
□ All fields: Based on observed data only

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return ONLY the 10 lines in exact format shown. No extra text, no JSON, no markdown formatting."""


def parse_browser_agent_result(text: str) -> Dict[str, Any]:
    """
    Parse browser agent output text into structured data.

    Args:
        text: Raw text output from browser agent

    Returns:
        Dictionary with extracted fields
    """
    # Replace escaped newlines with actual newlines
    text = (text or "").replace('\\n', '\n')

    # Initialize result dictionary
    extracted = {
        'name': '', 'prefix': '', 'description': '', 'example': '',
        'pattern': '', 'uri_format': '', 'contact_name': '',
        'contact_email': '', 'contact_orcid': '', 'keywords': []
    }

    # Parse line by line
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        match = re.match(r"^\s*([^:]+)\s*:\s*(.*)$", ln)
        if not match:
            continue

        raw_label = match.group(1).strip()
        val = match.group(2).strip()

        # Normalize label for matching
        label_norm = re.sub(r"[_\-\s]+", "_", raw_label).lower()

        if label_norm == 'name':
            extracted['name'] = val
        elif label_norm == 'prefix':
            extracted['prefix'] = val.lower()
        elif label_norm == 'description':
            extracted['description'] = val
        elif label_norm == 'example':
            extracted['example'] = val
        elif label_norm == 'pattern':
            # Unescape regex patterns (e.g., \\d becomes \d)
            extracted['pattern'] = val.replace('\\\\', '\\')
        elif 'uri' in label_norm and 'format' in label_norm:
            extracted['uri_format'] = val
        elif label_norm == 'contact_name':
            extracted['contact_name'] = val
        elif label_norm == 'contact_email':
            extracted['contact_email'] = val
        elif label_norm == 'contact_orcid':
            extracted['contact_orcid'] = val
        elif label_norm == 'keywords':
            # Parse comma-separated keywords
            extracted['keywords'] = [kw.strip() for kw in val.split(',') if kw.strip()][:3]

    return extracted


def post_process_extracted_data(extracted: Dict[str, Any], homepage_url: str) -> Dict[str, Any]:
    """
    Post-process extracted data to fill in missing fields and validate.

    Args:
        extracted: Raw extracted data from browser agent
        homepage_url: Homepage URL of the database

    Returns:
        Processed and validated extracted data
    """
    # Extract email from contact name if email is empty
    if not extracted['contact_email'] and extracted['contact_name']:
        email_match = re.search(
            r'([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})',
            extracted['contact_name']
        )
        if email_match:
            extracted['contact_email'] = email_match.group(1)
            extracted['contact_name'] = re.sub(
                r'\s*[\(\[]?[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}[\)\]]?\s*',
                '',
                extracted['contact_name']
            ).strip()

    # Infer pattern from example if pattern is empty
    if not extracted['pattern'] and extracted['example']:
        example = extracted['example']
        if re.match(r'^[A-Z]+\d+$', example):
            letters = re.match(r'^([A-Z]+)', example).group(1)
            digits = len(re.findall(r'\d', example))
            extracted['pattern'] = f"^{letters}\\d{{{digits}}}$"
        elif re.match(r'^\d+$', example):
            digits = len(example)
            extracted['pattern'] = f"^\\d{{{digits}}}$"

    # Use homepage_url directly, strip trailing slash
    homepage = homepage_url.rstrip('/')

    # Derive prefix from name if not provided
    if not extracted['prefix'] and extracted['name']:
        # Simple derivation: get first letters of each word
        words = extracted['name'].split()
        extracted['prefix'] = ''.join([w[0] for w in words if w]).lower()

    # Log warnings for URI_format issues
    if extracted['uri_format']:
        uri = extracted['uri_format']
        if '/index.html' in uri or '/default.html' in uri:
            logging.warning(f"⚠️  URI format contains index.html: {uri}")
            logging.warning("   This may indicate a post-redirect URL. Verify this is the entry point.")
        if uri.count('/') > 4:
            logging.warning(f"⚠️  URI format has deep nesting: {uri}")
            logging.warning("   This may indicate a post-redirect URL. Check if a simpler URL exists.")

    logging.info(
        f"Extracted - Name: {extracted['name']}, "
        f"Prefix: {extracted['prefix']}, "
        f"Keywords: {extracted['keywords']}"
    )

    return {
        "name": extracted['name'],
        "prefix": extracted['prefix'],
        "description": extracted['description'],
        "homepage": homepage,
        "example": extracted['example'],
        "pattern": extracted['pattern'],
        "uri_format": extracted['uri_format'],
        "keywords": extracted['keywords'],
        "contact": {
            "email": extracted['contact_email'],
            "name": extracted['contact_name'],
            "orcid": extracted['contact_orcid']
        }
    }


async def extract_database_info(homepage_url: str) -> Dict[str, Any]:
    """
    Use browser_use Agent to extract database information from homepage.

    Args:
        homepage_url: URL of the database homepage to scrape

    Returns:
        Dictionary containing extracted database metadata
    """
    from browser_use import Agent

    logging.info(f"Initializing browser agent for {homepage_url}")
    
    task_prompt = BROWSER_AGENT_PROMPT.replace('{homepage_url}', homepage_url)

    agent = Agent(
        task=task_prompt,
        llm_model=BROWSER_AGENT_MODEL,
    )

    logging.info("Running browser agent...")
    result = await agent.run()

    logging.info("Browser agent completed, parsing results...")
    final = result.final_result() if hasattr(result, 'final_result') else str(result)

    # Parse the result
    extracted = parse_browser_agent_result(final)

    # Post-process and validate
    return post_process_extracted_data(extracted, homepage_url)


def derive_name_from_homepage(homepage: str) -> str:
    """Derive a database name from its homepage URL."""
    match = re.search(r"https?://(?:www\.)?([^/\.]+)", homepage)
    return match.group(1) if match else "database"


def derive_prefix_from_name(name: str) -> str:
    """Derive a database prefix from its name."""
    # Remove version suffixes from name first
    clean_name = re.sub(r"(?i)\s*(?:v|version)\s*\d+(?:\.\d+)*$", "", name).strip()
    # Create prefix from clean name (alphanumeric only, lowercase)
    prefix = re.sub(r"[^0-9a-zA-Z]+", "", clean_name).lower()
    return prefix or "database_key"


def format_bioregistry_json(pubmed: Optional[Dict[str, Any]], db: Optional[Dict[str, Any]], contributor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Format the final Bioregistry JSON output.

    Args:
        pubmed: PubMed metadata dictionary
        db: Database metadata from web scraping
        contributor: Contributor information

    Returns:
        Formatted bioregistry JSON dictionary
    """
    # Get name and prefix from db data
    name = (db.get("name") if db else "").strip()
    prefix = (db.get("prefix") if db else "").strip()

    # If no name, derive from homepage
    if not name:
        homepage = (db.get("homepage") if db else "") or (pubmed.get("homepage", "") if pubmed else "")
        name = derive_name_from_homepage(homepage)

    # If no prefix, derive from name
    if not prefix:
        prefix = derive_prefix_from_name(name)

    # Use prefix as database key
    db_key = prefix

    # Extract contact info from db
    contact = {"email": "", "name": "", "orcid": ""}
    if db and db.get("contact"):
        contact_raw = db.get("contact")
        if isinstance(contact_raw, dict):
            contact["email"] = contact_raw.get("email", "")
            contact["name"] = contact_raw.get("name", "")
            contact["orcid"] = contact_raw.get("orcid", "")

    # Build contributor info
    contributor_info = {"email": "", "github": "", "name": "", "orcid": ""}
    if contributor and isinstance(contributor, dict):
        contributor_info["name"] = contributor.get("name", "") or ""
        contributor_info["email"] = contributor.get("email", "") or ""
        contributor_info["orcid"] = contributor.get("orcid", "") or ""
        contributor_info["github"] = contributor.get("github", "") or ""

    # Get other fields from db
    description = (db.get("description") if db else "")
    example = (db.get("example") if db else "")
    homepage = (db.get("homepage") if db else "") or pubmed.get("homepage", "")
    pattern = (db.get("pattern") if db else "")
    uri_format = (db.get("uri_format") if db else "")

    # Get keywords - priority: INDRA > browser-use
    keywords = []
    if pubmed and pubmed.get('keywords'):
        keywords = pubmed.get('keywords')
        logging.info("Using keywords from PubMed/INDRA")
    elif db and db.get('keywords'):
        keywords = db.get('keywords')
        logging.info("Using keywords from browser-use")
    else:
        keywords = []
        logging.warning("No keywords available from INDRA or browser-use")

    # Build publications list
    publications = []
    if pubmed:
        pub = {
            "doi": pubmed.get("doi") or "",
            "pubmed": pubmed.get("pmid") or "",
            "title": pubmed.get("title") or "",
            "year": pubmed.get("year") or None,
        }
        publications.append(pub)

    out = {
        db_key: {
            "contact": contact,
            "contributor": contributor_info,
            "description": description,
            "example": example,
            "github_request_issue": "",
            "homepage": homepage,
            "keywords": keywords,
            "name": name,
            "pattern": pattern,
            "publications": publications,
            "uri_format": uri_format,
        }
    }

    return out


def is_cache_valid() -> bool:
    """Check if the PMID cache is still valid."""
    return (pmid_cache['data'] is not None and
            pmid_cache['last_fetched'] is not None and
            datetime.now() - pmid_cache['last_fetched'] < CACHE_DURATION)


def fetch_pmid_rankings() -> List[Dict[str, Any]]:
    """
    Fetch and parse PMID rankings from GitHub TSV file with caching.

    Returns:
        List of dictionaries containing PMID ranking data

    Raises:
        requests.RequestException: If fetch fails and no cache is available
        Exception: If parsing fails
    """
    with pmid_cache['lock']:
        # Check if cache is valid
        if is_cache_valid():
            logging.info("Returning cached PMID rankings data")
            return pmid_cache['data']

        # Fetch new data
        logging.info(f"Fetching PMID rankings from {TSV_URL}")
        try:
            response = requests.get(TSV_URL, timeout=PUBMED_REQUEST_TIMEOUT)
            response.raise_for_status()

            # Parse TSV data
            tsv_content = response.text
            reader = csv.DictReader(StringIO(tsv_content), delimiter='\t')
            pmid_data = [dict(row) for row in reader]

            # Update cache
            pmid_cache['data'] = pmid_data
            pmid_cache['last_fetched'] = datetime.now()

            logging.info(f"Successfully fetched and cached {len(pmid_data)} PMID entries")
            return pmid_data

        except requests.RequestException as e:
            logging.error(f"Failed to fetch PMID rankings: {e}")
            # Return cached data if available, even if expired
            if pmid_cache['data'] is not None:
                logging.warning("Returning expired cache due to fetch failure")
                return pmid_cache['data']
            raise
        except Exception as e:
            logging.error(f"Error parsing PMID rankings: {e}")
            raise


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/pmid-rankings', methods=['GET'])
def get_pmid_rankings():
    """API endpoint to get PMID rankings data."""
    try:
        data = fetch_pmid_rankings()
        return jsonify({
            "status": "success",
            "data": data,
            "cached_at": pmid_cache['last_fetched'].isoformat() if pmid_cache['last_fetched'] else None
        })
    except Exception as e:
        logging.exception('Failed to fetch PMID rankings')
        return jsonify({
            "status": "error",
            "message": f"Failed to fetch PMID rankings: {str(e)}"
        }), 500


def validate_pmid(pmid: str) -> bool:
    """Validate PMID format."""
    return bool(pmid and re.fullmatch(PMID_PATTERN, pmid))


def validate_contributor(contributor: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Validate contributor data.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not contributor:
        return True, None

    # Validate ORCID format if provided
    orcid = contributor.get('orcid', '').strip()
    if orcid and not re.fullmatch(ORCID_PATTERN, orcid):
        return False, "Invalid ORCID format. Expected format: 0000-0000-0000-0000"

    return True, None


@app.route('/extract', methods=['POST'])
def extract():
    """
    API endpoint to extract metadata for a given PMID.

    Expects JSON with:
        - pmid: PubMed ID (numeric string)
        - contributor: Optional contributor information dict

    Returns:
        JSON with status and extracted data or error message
    """
    data = request.get_json() or {}
    pmid = (data.get('pmid') or '').strip()
    contributor = data.get('contributor') or {}

    # Validate PMID
    if not validate_pmid(pmid):
        return jsonify({
            "status": "error",
            "message": "Invalid PMID. Provide numeric PMID like 12345678."
        }), 400

    # Validate contributor data
    is_valid, error_msg = validate_contributor(contributor)
    if not is_valid:
        return jsonify({"status": "error", "message": error_msg}), 400

    try:
        # Step 1: Extract PubMed metadata
        logging.info(f"=== Starting extraction for PMID: {pmid} ===")
        logging.info("Step 1: Extracting PubMed metadata...")
        pubmed = extract_pubmed_metadata(pmid)
        
        if pubmed.get('error'):
            logging.error(f"PubMed extraction failed: {pubmed.get('error')}")
            return jsonify({"status": "error", "message": pubmed.get('error')}), 500
        
        logging.info(f"PubMed data extracted - Title: {pubmed.get('title', 'N/A')[:50]}...")

        # Step 2: Find homepage URL in abstract
        logging.info("Step 2: Searching for homepage URL in abstract...")
        abstract_text = pubmed.get('abstract') or ''
        raw_urls = re.findall(r"https?://[^\s\)\]]+", abstract_text)
        urls = [re.sub(r"[\.,;:]+$", "", u) for u in raw_urls]

        if not urls:
            logging.warning("No homepage URL found in abstract")
            bioreg_partial = format_bioregistry_json(pubmed, None, contributor)
            return jsonify({
                "status": "error",
                "message": "No homepage URL found in the PubMed abstract; cannot run browser-use scraping.",
                "data": bioreg_partial
            }), 400

        homepage_url = urls[0]
        logging.info(f"Found homepage URL: {homepage_url}")

        # Step 3: Extract database info using browser-use
        logging.info("Step 3: Starting browser-use scraping (this may take 2-5 minutes)...")
        db_data = None
        try:
            db_data = asyncio.run(extract_database_info(homepage_url))
            logging.info("Browser scraping completed successfully")
            logging.info(f"Extracted data - Name: {db_data.get('name', 'N/A')}, Prefix: {db_data.get('prefix', 'N/A')}, Keywords: {db_data.get('keywords', [])}")
        except Exception as e:
            logging.exception('Database scraping failed')
            bioreg_partial = format_bioregistry_json(pubmed, None, contributor)
            return jsonify({
                "status": "error",
                "message": f"Database scraping failed: {e}",
                "data": bioreg_partial
            }), 500

        # Step 4: Format final Bioregistry JSON
        logging.info("Step 4: Formatting final JSON...")
        bioreg = format_bioregistry_json(pubmed, db_data, contributor)
        logging.info("=== Extraction completed successfully ===")
        return jsonify({"status": "success", "data": bioreg})

    except Exception as e:
        logging.exception('Unexpected error')
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5001)
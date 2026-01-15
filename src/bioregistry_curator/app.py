from flask import Flask, request, jsonify, render_template
import re
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv() 

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


def extract_pubmed_metadata(pmid):
    """Extract metadata for a PMID using INDRA's pubmed client.

    Returns a dictionary with keys: title, doi, abstract, first_author, pmid, year, homepage (if found), description
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
    item = None
    if isinstance(raw, dict):
        item = raw.get(str(pmid)) or list(raw.values())[0]
    else:
        item = raw

    title = item.get("title") or ""
    doi = item.get("doi") or item.get("elocationid") or ""
    abstract = item.get("abstract") or ""

    # first author
    first_author = ""
    authors = item.get("authors") or item.get("author_list") or []
    if authors:
        if isinstance(authors[0], dict):
            first_author = authors[0].get("name") or authors[0].get("fullname") or ""
        else:
            first_author = str(authors[0])

    # year
    year = None
    if item.get("year"):
        try:
            year = int(item.get("year"))
        except Exception:
            year = None
    else:
        pubdate = item.get("pubdate") or ""
        m = re.search(r"(19|20)\d{2}", pubdate)
        if m:
            year = int(m.group(0))

    # find any URLs in the abstract; capture until whitespace or closing bracket
    raw_urls = re.findall(r"https?://[^\s\)\]]+", abstract)
    # clean trailing punctuation
    urls = [re.sub(r"[\.,;:]+$", "", u) for u in raw_urls]
    homepage = urls[0] if urls else ""

    # keywords: prefer INDRA-provided keywords when present
    keywords = []
    if isinstance(item, dict):
        kw = item.get('keywords') or item.get('mesh_terms') or item.get('keyword') or item.get('subject')
        if kw:
            if isinstance(kw, (list, tuple)):
                keywords = [str(x).strip() for x in kw if x]
            else:
                keywords = [k.strip() for k in str(kw).split(',') if k.strip()]

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


async def extract_database_info(homepage_url):
    """Use browser_use Agent to extract database information from homepage."""
    from browser_use import Agent
    
    logging.info(f"Initializing browser agent for {homepage_url}")

    agent = Agent(
        task=rf"""Visit {homepage_url} and extract database information.

Your task is to find and return EXACTLY these 10 fields in this exact format:

Name: [full database name]
Prefix: [short database acronym/abbreviation]
Description: [one sentence describing what identifiers represent]
Homepage: [main URL of the database]
Example: [ONE typical identifier example, like "ABC123" or "12345"]
Pattern: [regex pattern for identifiers, like ^[A-Z]{{3}}\d{{3}}$ or ^\d{{5}}$]
URI_Format: [URL pattern with $1 as placeholder for ID, like https://example.com/entry/$1]
Contact_Name: [full name of contact person]
Contact_Email: [email address]
Keywords: [exactly 3 scientific terms separated by commas]

CRITICAL INSTRUCTIONS:

1. Name: Use the FULL official database name (e.g., "Minimum Information about a Biosynthetic Gene Cluster", "Kyoto Encyclopedia of Genes and Genomes")

2. Prefix: Use the SHORT acronym/abbreviation in lowercase (e.g., "mibig", "kegg", "absd")

3. Description: Focus on the SEMANTIC SPACE, not the database itself. Answer these two questions in ONE concise sentence:
   - What kind of entities are covered? (e.g., proteins, small molecules, diseases, genes, gene clusters)
   - Why do these entities exist / what are they used for? (e.g., for comparative analysis, drug discovery, annotation)
   
   Examples of GOOD descriptions:
   - "Biosynthetic gene clusters producing specialized metabolites for comparative genomics analysis"
   - "Small molecules with published biochemical activity data for drug discovery"
   - "Antibody protein sequences with structural annotations for immune repertoire studies"
   
   Examples of BAD descriptions:
   - "A comprehensive database that provides..." (focuses on database, not entities)
   - "This resource was created to store..." (focuses on database purpose, not entity purpose)
   
   Keep it to ONE sentence. Focus on what the IDENTIFIERS represent and their purpose.

4. Example: Find ONE CANONICAL identifier in its BASE format (no version suffixes, no query parameters).
   - Look in: Search results, browse pages, documentation, example queries
   - If you see "BGC0000001.5" or "ABC123_v2", use the BASE form: "BGC0000001" or "ABC123"
   - If you see "?id=12345" in a URL, use just: "12345"
   - Use the SIMPLEST, most common format without versions, extensions, or parameters
   DO NOT include version numbers, file extensions, or URL parameters in the example.

5. Pattern: Create regex for the BASE identifier format (without versions or suffixes):
   - Match the example you provided exactly
   - If example is "BGC0000001": ^BGC\d{{7}}$ (not ^BGC\d{{7}}\.\d$)
   - If example is "ABC123": ^[A-Z]{{3}}\d{{3}}$
   - If example is "12345": ^\d{{5}}$
   - DO NOT include version patterns like \.\d or _v\d in the regex

6. URI_Format: Find the URL pattern that takes you to INDIVIDUAL ENTRIES (one identifier at a time).
   
   IMPORTANT: The URI_Format must be for viewing ONE SPECIFIC ENTRY, not:
   - Search pages (even if they show results for an ID)
   - List/browse pages showing multiple entries
   - Download pages or API endpoints
   
   You need the URL that displays the DETAILS/INFORMATION for a single identifier.
   
   Method 1 (STRONGLY PREFERRED): Extract link URLs before clicking
   - Navigate to search results, browse page, or dataset listing
   - Find clickable links to individual entry DETAIL pages
   - These links often say: "View details", "View entry", or just show the ID as a link
   - Inspect or hover over these links to see their href/URL
   - Compare 2-3 entry links to identify the pattern
   
   Example:
   - On browse page, you see links:
     <a href="/go/BGC0000001">View entry</a>
     <a href="/go/BGC0000002">View entry</a>
   - Pattern identified: https://mibig.secondarymetabolites.org/go/$1
   
   Method 2: Look for "Share", "Cite", or "Permalink" features
   - Navigate to an entry detail page
   - Find buttons labeled: "Share", "Permalink", "Cite this entry"
   - Copy the URL provided there
   
   Method 3 (Last resort): Use address bar after navigating to entries
   
   CRITICAL - VERIFY YOUR URI_FORMAT:
   After identifying the pattern, TEST IT:
   1. Take your pattern (e.g., https://example.com/go/$1)
   2. Replace $1 with a DIFFERENT example ID you found
   3. Navigate directly to that URL by typing it in the address bar
   4. Confirm it takes you to that entry's detail page
   5. If it works: use this pattern ✓
   6. If it fails (404 or wrong page): try Method 2 or find the correct pattern
   
   Example verification:
   - Pattern found: https://mibig.secondarymetabolites.org/go/$1
   - Test with ID "BGC0000005": Navigate to https://mibig.secondarymetabolites.org/go/BGC0000005
   - Does it show BGC0000005's detail page? YES → Pattern is correct ✓
   
   Only return a URI_Format that you have successfully tested and verified works.
   
   Format: Full URL with $1 as placeholder
   Example: https://example.com/go/$1

7. Contact: Search thoroughly in these locations (in order):
   - About page (look for "Principal Investigator", "Project Lead", "Contact")
   - Contact page
   - Team page (choose the PRIMARY contact or PI)
   - Footer (sometimes shows maintainer email)
   - GitHub repository if linked (check README for maintainer)
   
   If multiple contacts exist, prioritize: PI > Lead Developer > Maintainer > General contact

8. Keywords: Extract EXACTLY 3 lowercase terms that describe the semantic space. Include:
   - Entity type: what the identifiers represent (e.g., "biosynthetic gene clusters", "protein sequences", "small molecules")
   - Scientific domain: the field (e.g., "genomics", "biochemistry", "immunology")
   - Application or context: what they're used for (e.g., "secondary metabolites", "drug discovery", "comparative analysis")
   
   Guidelines:
   - Use lowercase only
   - Spaces allowed in multi-word phrases (e.g., "gene clusters")
   - NO generic database terms ("database", "resource", "tool", "collection", "platform", "data")
   - NO generic adjectives ("comprehensive", "curated", "large", "public")
   - Focus on WHAT the entities are, not HOW the database is organized
   
   Examples:
   - GOOD: "biosynthetic gene clusters, secondary metabolites, genomics"
   - GOOD: "small molecules, biochemistry, drug discovery"
   - BAD: "database, comprehensive resource, curated data"

9. If you cannot find a field after checking multiple pages (Home, About, Search, Contact, Browse), leave it EMPTY but include the label.

NAVIGATION STRATEGY:
1. Start at homepage
2. Go to About/Documentation (for Name, Description, Contact)
3. Go to Search/Browse pages (for Example, URI_Format)
4. Click 1-2 entries (for Pattern verification, but use link URLs from step 3 for URI_Format)
5. Check Contact/Team pages (for Contact info)

Return ONLY these 10 lines in the exact format shown above. No extra text, no JSON, no markdown formatting.""",
        llm_model="gpt-4o",
    )

    logging.info("Running browser agent...")
    result = await agent.run()
    
    logging.info("Browser agent completed, parsing results...")
    final = result.final_result() if hasattr(result, 'final_result') else str(result)

    # Replace escaped newlines with actual newlines
    text = (final or "").replace('\\n', '\n')

    # Parse line by line
    extracted = {
        'name': '', 'prefix': '', 'description': '', 'homepage': '', 'example': '',
        'pattern': '', 'uri_format': '', 'contact_name': '', 'contact_email': '',
        'keywords': []
    }

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        m = re.match(r"^\s*([^:]+)\s*:\s*(.*)$", ln)
        if not m:
            continue
        raw_label = m.group(1).strip()
        val = m.group(2).strip()
        
        # Normalize label for matching
        label_norm = re.sub(r"[_\-\s]+", "_", raw_label).lower()
        
        if label_norm == 'name':
            extracted['name'] = val
        elif label_norm == 'prefix':
            extracted['prefix'] = val.lower()  # Ensure lowercase
        elif label_norm == 'description':
            extracted['description'] = val
        elif label_norm == 'homepage':
            extracted['homepage'] = val
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
        elif label_norm == 'keywords':
            # Parse comma-separated keywords
            extracted['keywords'] = [kw.strip() for kw in val.split(',') if kw.strip()][:3]

    # Post-processing: Try to extract email from contact name if email is empty
    if not extracted['contact_email'] and extracted['contact_name']:
        email_match = re.search(r'([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', extracted['contact_name'])
        if email_match:
            extracted['contact_email'] = email_match.group(1)
            extracted['contact_name'] = re.sub(r'\s*[\(\[]?[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}[\)\]]?\s*', '', extracted['contact_name']).strip()

    # If pattern is empty but we have an example, try to infer pattern
    if not extracted['pattern'] and extracted['example']:
        example = extracted['example']
        if re.match(r'^[A-Z]+\d+$', example):
            letters = re.match(r'^([A-Z]+)', example).group(1)
            digits = len(re.findall(r'\d', example))
            extracted['pattern'] = f"^{letters}\\d{{{digits}}}$"
        elif re.match(r'^\d+$', example):
            digits = len(example)
            extracted['pattern'] = f"^\\d{{{digits}}}$"

    # Use homepage_url as fallback
    if not extracted['homepage']:
        extracted['homepage'] = homepage_url

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

    logging.info(f"Extracted - Name: {extracted['name']}, Prefix: {extracted['prefix']}, Keywords: {extracted['keywords']}")

    return {
        "name": extracted['name'],
        "prefix": extracted['prefix'],
        "description": extracted['description'],
        "homepage": extracted['homepage'],
        "example": extracted['example'],
        "pattern": extracted['pattern'],
        "uri_format": extracted['uri_format'],
        "keywords": extracted['keywords'],
        "contact": {
            "email": extracted['contact_email'],
            "name": extracted['contact_name'],
            "orcid": ""
        }
    }


def format_bioregistry_json(pubmed, db, contributor=None):
    """Format the final Bioregistry JSON output."""
    # Get name and prefix from db data
    name = (db.get("name") if db else "").strip()
    prefix = (db.get("prefix") if db else "").strip()

    # If no name, derive from homepage
    if not name:
        homepage = (db.get("homepage") if db else "") or pubmed.get("homepage", "")
        m = re.search(r"https?://(?:www\.)?([^/\.]+)", homepage)
        name = m.group(1) if m else "database"

    # If no prefix, derive from name
    if not prefix:
        # Remove version suffixes from name first
        clean_name = re.sub(r"(?i)\s*(?:v|version)\s*\d+(?:\.\d+)*$", "", name).strip()
        # Create prefix from clean name (alphanumeric only, lowercase)
        prefix = re.sub(r"[^0-9a-zA-Z]+", "", clean_name).lower() or "database_key"

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


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/extract', methods=['POST'])
def extract():
    data = request.get_json() or {}
    pmid = (data.get('pmid') or '').strip()
    contributor = data.get('contributor') or {}

    if not pmid or not re.fullmatch(r"\d+", pmid):
        return jsonify({"status": "error", "message": "Invalid PMID. Provide numeric PMID like 12345678."}), 400

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
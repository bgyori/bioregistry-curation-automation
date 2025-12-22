# Bioregistry Curation Automation

An automated pipeline for streamlining the Bioregistry curation process by extracting metadata from PubMed articles and database websites, generating standardized JSON output for registry entries.

## Overview

This tool automates the manual steps of Bioregistry curation by:
1. Extracting metadata from PubMed publications
2. Following database URLs to scrape additional information
3. Generating properly formatted JSON entries
4. Providing an interactive interface for curator review and editing

## Workflow

### 1. Input
Users provide a PubMed URL or PMID through a web interface.

### 2. PubMed Metadata Extraction
The pipeline automatically extracts:
- Author name
- PMID
- Article title
- DOI
- Database description
- Database URL
- Year published

### 3. Database Scraping
Using browser automation (browser-use), the tool:
- Navigates to the identified database URL
- Extracts structural information including:
  - Prefix patterns
  - ID patterns/regex
  - Example identifiers
  - Additional metadata fields
  - URI format

### 4. JSON Generation
Outputs a properly formatted JSON file following Bioregistry schema specifications.

### 5. Curator Review
Provides an editable interface where curators can:
- Review extracted information
- Correct any misidentified fields
- Add missing metadata
- Validate before final submission

## Requirements

- Python 3.9+
- Dependencies are managed via `pyproject.toml`

## Installation

1. Clone the repository:
```bash
git clone https://github.com/kanghosaeyo/bioregistry-curation-automation.git
cd bioregistry-curation-automation
```

2. Create and activate a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install the package in editable mode:
```bash
pip install -e .
```

## Usage

Run the Flask application:
```bash
cd src
python -m bioregistry_curator.app
```

Then open http://127.0.0.1:5001 in your browser.

## Technology Stack

- **Backend**: Flask web framework
- **Frontend**: Vanilla JavaScript with HTML/CSS
- **INDRA API**: PubMed metadata extraction ([documentation](https://indra.readthedocs.io/en/latest/modules/literature/index.html#module-indra.literature.pubmed_client))
- **Browser Automation**: browser-use for dynamic content scraping
- **Output Format**: JSON (Bioregistry schema compliant)

## Goals

- Reduce manual curation time by automating repetitive extraction tasks
- Minimize human error in metadata transcription
- Standardize the curation workflow
- Maintain curator oversight through review interface

## Security & Usage Notes

- This is a research tool. Be cautious when running automated web agents against external sites.
- Ensure you respect robots.txt and the site's terms of service.
- Review all automated extractions before submitting to Bioregistry.

## Development Status

This project is currently in active development as part of the Bioregistry curation efforts at the Gyori Lab for Computational Biomedicine.

## Contributing

This is a personal project for automating Bioregistry curation workflows. If you're interested in contributing or have suggestions, please open an issue.

## Related Projects

- [Bioregistry](https://github.com/biopragmatics/bioregistry) - The main Bioregistry project
- [Bioregistry Documentation](https://bioregistry.io/)

## Author

Oscar Kangho Ji - Bioregistry Curator, Gyori Lab for Computational Biomedicine, Northeastern University

## License

BSD-2-Clause

"""
n7z Job Scraper
Finds DevOps jobs in US/Canada from multiple sources.
This module is designed to be called from the web application only.
"""

import json
import os
import logging
from datetime import datetime
from typing import List, Dict
from dataclasses import asdict

from scrapers import (
    Job, GreenhouseScraper, LeverScraper, AshbyScraper,
    RemotiveScraper, HackerNewsScraper, LinkedInScraper
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(SCRIPT_DIR, 'data'))
COMPANIES_FILE = os.path.join(SCRIPT_DIR, 'companies.json')
DISCOVERED_FILE = os.path.join(DATA_DIR, 'discovered_companies.json')
KEYWORDS_FILE = os.path.join(DATA_DIR, 'keywords.json')
LOCATIONS_FILE = os.path.join(DATA_DIR, 'locations.json')


def load_companies() -> Dict:
    """Load company lists from JSON file"""
    if os.path.exists(COMPANIES_FILE):
        with open(COMPANIES_FILE, 'r') as f:
            return json.load(f)
    return {}


def load_discovered_companies() -> Dict:
    """Load discovered companies from file"""
    if os.path.exists(DISCOVERED_FILE):
        try:
            with open(DISCOVERED_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def load_keywords() -> List[str]:
    """Load search keywords from file"""
    if os.path.exists(KEYWORDS_FILE):
        try:
            with open(KEYWORDS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    # Default keywords
    return [
        'devops', 'sre', 'site reliability', 'platform engineer',
        'infrastructure', 'cloud engineer', 'devsecops', 'kubernetes', 'terraform'
    ]


def load_locations() -> Dict:
    """Load location filters from file or companies.json"""
    # First check for custom locations file
    if os.path.exists(LOCATIONS_FILE):
        try:
            with open(LOCATIONS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass

    # Fall back to companies.json locations
    companies = load_companies()
    if 'locations' in companies:
        return {
            'allowed': companies['locations'].get('allowed', []),
            'excluded': companies['locations'].get('excluded', [])
        }

    # Default locations
    return {
        'allowed': [
            'united states', 'usa', 'u.s.', 'america', 'canada', 'canadian',
            'toronto', 'vancouver', 'montreal', 'ontario', 'british columbia',
            'california', 'new york', 'texas', 'washington', 'colorado',
            'san francisco', 'seattle', 'austin', 'denver', 'boston', 'chicago',
            'remote', 'north america', 'worldwide', 'anywhere', 'global'
        ],
        'excluded': [
            'europe only', 'eu only', 'uk only', 'emea only', 'apac only',
            'india only', 'australia only', 'vienna', 'berlin', 'london',
            'paris', 'amsterdam', 'dublin', 'singapore', 'tokyo', 'sydney'
        ]
    }


def deduplicate_jobs(jobs: List[Job]) -> List[Job]:
    """Remove duplicate job listings"""
    seen = set()
    unique_jobs = []

    for job in jobs:
        key = (job.title.lower().strip(), job.company.lower().strip())
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    return unique_jobs


def save_jobs(jobs: List[Job], output_path: str):
    """Save jobs to JSON file"""
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)

    # Load existing jobs and merge
    existing_jobs = []
    json_path = f"{output_path}.json"
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                existing_data = json.load(f)
                existing_jobs = [Job(**j) for j in existing_data]
        except:
            pass

    # Merge and deduplicate
    all_jobs = existing_jobs + jobs
    unique_jobs = deduplicate_jobs(all_jobs)

    # Save JSON
    with open(json_path, 'w') as f:
        json.dump([asdict(job) for job in unique_jobs], f, indent=2)

    logger.info(f"Saved {len(unique_jobs)} jobs to {json_path}")


def print_summary(jobs: List[Job]):
    """Print summary of found jobs"""
    print("\n" + "=" * 60)
    print(f"FOUND {len(jobs)} MATCHING JOBS")
    print("=" * 60)

    by_source = {}
    for job in jobs:
        source = job.source.split('-')[0]
        by_source.setdefault(source, []).append(job)

    for source, source_jobs in sorted(by_source.items()):
        print(f"\n{source}: {len(source_jobs)} jobs")

    print("=" * 60)


def run_scraper(mode='quick', keywords=None, output_path=None, parallel=True, workers=10):
    """
    Run the job scraper.

    Args:
        mode: 'quick' for API sources only, 'full' for all sources
        keywords: List of keywords to search for, or None to load from config
        output_path: Path to save jobs, or None for default
        parallel: Enable parallel processing
        workers: Number of parallel workers

    Returns:
        List of unique jobs found
    """
    if output_path is None:
        output_path = os.path.join(DATA_DIR, 'devops_jobs')

    # Load configuration
    companies = load_companies()
    discovered = load_discovered_companies()

    if keywords is None:
        keywords = load_keywords()
    keywords = [k.strip() for k in keywords if k.strip()]

    locations = load_locations()

    logger.info(f"Keywords: {keywords}")
    logger.info(f"Allowed locations: {len(locations.get('allowed', []))} terms")

    # Scraper configuration
    config = {
        'parallel_mode': parallel,
        'max_workers': workers,
        'keywords': keywords,
        'allowed_locations': locations.get('allowed', []),
        'excluded_locations': locations.get('excluded', [])
    }

    all_jobs: List[Job] = []

    # Merge companies from companies.json and discovered
    greenhouse_companies = {}
    greenhouse_companies.update(companies.get('greenhouse', {}).get('companies', {}))
    greenhouse_companies.update(discovered.get('greenhouse', {}))

    lever_companies = {}
    lever_companies.update(companies.get('lever', {}).get('companies', {}))
    lever_companies.update(discovered.get('lever', {}))

    ashby_companies = {}
    ashby_companies.update(companies.get('ashby', {}).get('companies', {}))
    ashby_companies.update(discovered.get('ashby', {}))

    # Define scrapers
    fast_scrapers = [
        ('Remotive', RemotiveScraper(config)),
        ('Greenhouse', GreenhouseScraper(config, greenhouse_companies)),
        ('Lever', LeverScraper(config, lever_companies)),
        ('HackerNews', HackerNewsScraper(config)),
    ]

    medium_scrapers = [
        ('Ashby', AshbyScraper(config, ashby_companies)),
        ('LinkedIn', LinkedInScraper(config)),
    ]

    # Select scrapers based on mode
    if mode == 'quick':
        scrapers = fast_scrapers
        logger.info("QUICK MODE - API sources only")
    elif mode == 'full':
        scrapers = fast_scrapers + medium_scrapers
        logger.info("FULL MODE - All sources")
    else:
        scrapers = fast_scrapers
        logger.info("DEFAULT MODE - Fast sources")

    # Run scrapers
    for name, scraper in scrapers:
        try:
            logger.info(f"Running {name}...")
            jobs = scraper.scrape()
            all_jobs.extend(jobs)
            logger.info(f"{name}: Found {len(jobs)} jobs")
        except Exception as e:
            logger.error(f"Error running {name}: {e}")

    # Deduplicate and save
    unique_jobs = deduplicate_jobs(all_jobs)
    logger.info(f"Total unique jobs: {len(unique_jobs)}")

    save_jobs(unique_jobs, output_path)
    print_summary(unique_jobs)

    return unique_jobs

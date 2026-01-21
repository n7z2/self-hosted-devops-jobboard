"""
n7z Job Scraper
Finds DevOps jobs in US/Canada from multiple sources.
This module is designed to be called from the web application only.
"""

import json
import os
import logging
from typing import List
from dataclasses import asdict

from config import (
    DATA_DIR, load_companies, load_discovered_companies,
    load_keywords, load_locations, ensure_data_dir
)
from scrapers import (
    Job, GreenhouseScraper, LeverScraper, AshbyScraper,
    RemotiveScraper, LinkedInScraper
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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
    ensure_data_dir()

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


def run_scraper(keywords=None, output_path=None, parallel=True, workers=10):
    """
    Run the job scraper.

    Args:
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
        'allowed_locations': locations.get('allowed', [])
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
    scrapers = [
        ('Remotive', RemotiveScraper(config)),
        ('Greenhouse', GreenhouseScraper(config, greenhouse_companies)),
        ('Lever', LeverScraper(config, lever_companies)),
        ('Ashby', AshbyScraper(config, ashby_companies)),
        ('LinkedIn', LinkedInScraper(config)),
    ]

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

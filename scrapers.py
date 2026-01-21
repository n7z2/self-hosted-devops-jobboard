"""
Job Scraper Classes
Individual scraper implementations for different job sources and ATS systems.
"""

import requests
from bs4 import BeautifulSoup
import re
import time
import random
import logging
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import DEFAULT_KEYWORDS, matches_location_word_boundary

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """Represents a job posting"""
    title: str
    company: str
    location: str
    salary: str
    url: str
    source: str
    description: str
    remote: bool
    date_scraped: str


class JobScraper:
    """Base scraper class with common functionality"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        self.jobs: List[Job] = []
        self.parallel_mode = config.get('parallel_mode', False) if config else False
        self.max_workers = config.get('max_workers', 10) if config else 10
        self.keywords = config.get('keywords', []) if config else []
        self.allowed_locations = config.get('allowed_locations', []) if config else []

    def random_delay(self, min_sec=1, max_sec=3):
        """Random delay to avoid rate limiting"""
        if self.parallel_mode:
            time.sleep(random.uniform(min_sec * 0.3, max_sec * 0.3))
        else:
            time.sleep(random.uniform(min_sec, max_sec))

    def safe_get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Safe GET request with error handling"""
        try:
            response = self.session.get(url, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.debug(f"Error fetching {url}: {e}")
            return None

    def extract_salary(self, text: str) -> str:
        """Extract salary information from text"""
        patterns = [
            r'\$[\d,]+\s*[-–]\s*\$[\d,]+',
            r'\$[\d,]+k?\s*[-–]\s*\$?[\d,]+k?',
            r'CAD\s*[\d,]+\s*[-–]\s*[\d,]+',
            r'USD\s*[\d,]+\s*[-–]\s*[\d,]+',
            r'\$[\d,]+\+?',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group()
        return "Not specified"

    def matches_keywords(self, title: str, description: str = "") -> bool:
        """Check if job matches configured keywords"""
        keywords = self.keywords if self.keywords else DEFAULT_KEYWORDS
        text = f"{title} {description}".lower()
        return any(kw.lower() in text for kw in keywords)

    def matches_location(self, location: str, description: str = "") -> bool:
        """Check if job location is allowed using word boundary matching"""
        return matches_location_word_boundary(location, self.allowed_locations or None)

    def scrape_companies(self, companies: Dict, scrape_func) -> List[Job]:
        """
        Scrape multiple companies in parallel or sequentially.

        Args:
            companies: Dict of company_name -> board_id
            scrape_func: Function that takes (company_name, board_id) and returns List[Job]
        """
        if self.parallel_mode:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(scrape_func, name, board_id): name
                    for name, board_id in companies.items()
                }
                for future in as_completed(futures):
                    try:
                        self.jobs.extend(future.result())
                    except Exception as e:
                        logger.debug(f"Error in parallel scrape: {e}")
        else:
            for company_name, board_id in companies.items():
                self.jobs.extend(scrape_func(company_name, board_id))

        return self.jobs


class GreenhouseScraper(JobScraper):
    """Scraper for Greenhouse ATS boards"""

    def __init__(self, config: Dict = None, companies: Dict = None):
        super().__init__(config)
        self.companies = companies or {}

    def _scrape_company(self, company_name: str, board_id: str) -> List[Job]:
        """Scrape a single Greenhouse company board"""
        jobs = []
        try:
            api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs"
            response = self.safe_get(api_url)
            if not response:
                return jobs

            data = response.json()

            for job_data in data.get('jobs', []):
                title = job_data.get('title', '')

                if not self.matches_keywords(title):
                    continue

                location = job_data.get('location', {}).get('name', 'Remote')

                if not self.matches_location(location):
                    continue

                job = Job(
                    title=title,
                    company=company_name,
                    location=location,
                    salary="Not specified",
                    url=job_data.get('absolute_url', ''),
                    source=f"Greenhouse-{company_name}",
                    description="",
                    remote='remote' in location.lower(),
                    date_scraped=datetime.now().isoformat()
                )
                jobs.append(job)
                logger.info(f"Found Greenhouse {company_name}: {title}")

            self.random_delay(0.5, 1)
        except Exception as e:
            logger.debug(f"Error scraping Greenhouse {company_name}: {e}")

        return jobs

    def scrape(self) -> List[Job]:
        logger.info(f"Scraping {len(self.companies)} Greenhouse boards...")
        self.scrape_companies(self.companies, self._scrape_company)
        logger.info(f"GreenhouseScraper: Found {len(self.jobs)} jobs")
        return self.jobs


class LeverScraper(JobScraper):
    """Scraper for Lever ATS boards"""

    def __init__(self, config: Dict = None, companies: Dict = None):
        super().__init__(config)
        self.companies = companies or {}

    def _scrape_company(self, company_name: str, board_id: str) -> List[Job]:
        """Scrape a single Lever company board"""
        jobs = []
        try:
            api_url = f"https://api.lever.co/v0/postings/{board_id}"
            response = self.safe_get(api_url)
            if not response:
                return jobs

            jobs_data = response.json()

            for job_data in jobs_data:
                title = job_data.get('text', '')

                if not self.matches_keywords(title):
                    continue

                location = job_data.get('categories', {}).get('location', 'Remote')

                if not self.matches_location(str(location)):
                    continue

                job = Job(
                    title=title,
                    company=company_name,
                    location=location or 'Remote',
                    salary="Not specified",
                    url=job_data.get('hostedUrl', ''),
                    source=f"Lever-{company_name}",
                    description=job_data.get('descriptionPlain', '')[:500] if job_data.get('descriptionPlain') else '',
                    remote='remote' in str(location).lower(),
                    date_scraped=datetime.now().isoformat()
                )
                jobs.append(job)
                logger.info(f"Found Lever {company_name}: {title}")

            self.random_delay(0.5, 1)
        except Exception as e:
            logger.debug(f"Error scraping Lever {company_name}: {e}")

        return jobs

    def scrape(self) -> List[Job]:
        logger.info(f"Scraping {len(self.companies)} Lever boards...")
        self.scrape_companies(self.companies, self._scrape_company)
        logger.info(f"LeverScraper: Found {len(self.jobs)} jobs")
        return self.jobs


class AshbyScraper(JobScraper):
    """Scraper for Ashby ATS boards"""

    def __init__(self, config: Dict = None, companies: Dict = None):
        super().__init__(config)
        self.companies = companies or {}

    def _scrape_company(self, company_name: str, board_id: str) -> List[Job]:
        """Scrape a single Ashby company board"""
        jobs = []
        try:
            api_url = f"https://api.ashbyhq.com/posting-api/job-board/{board_id}"
            response = self.safe_get(api_url)
            if not response:
                return jobs

            data = response.json()

            for job_data in data.get('jobs', []):
                title = job_data.get('title', '')

                if not self.matches_keywords(title):
                    continue

                location = job_data.get('location', 'Remote')
                if isinstance(location, dict):
                    location = location.get('name', 'Remote')

                if not self.matches_location(str(location)):
                    continue

                job = Job(
                    title=title,
                    company=company_name,
                    location=str(location),
                    salary="Not specified",
                    url=job_data.get('jobUrl', job_data.get('applyUrl', '')),
                    source=f"Ashby-{company_name}",
                    description=job_data.get('descriptionPlain', '')[:500] if job_data.get('descriptionPlain') else '',
                    remote='remote' in str(location).lower(),
                    date_scraped=datetime.now().isoformat()
                )
                jobs.append(job)
                logger.info(f"Found Ashby {company_name}: {title}")

            self.random_delay(0.5, 1)
        except Exception as e:
            logger.debug(f"Error scraping Ashby {company_name}: {e}")

        return jobs

    def scrape(self) -> List[Job]:
        logger.info(f"Scraping {len(self.companies)} Ashby boards...")
        self.scrape_companies(self.companies, self._scrape_company)
        logger.info(f"AshbyScraper: Found {len(self.jobs)} jobs")
        return self.jobs


class RemotiveScraper(JobScraper):
    """Scraper for Remotive.io - Remote job board"""

    def scrape(self) -> List[Job]:
        logger.info("Scraping Remotive...")

        # Use configured keywords for search, or defaults
        keywords = self.keywords if self.keywords else DEFAULT_KEYWORDS
        seen_urls = set()

        for keyword in keywords:
            # URL encode the keyword for the search parameter
            encoded_keyword = keyword.replace(' ', '%20')
            url = f"https://remotive.com/api/remote-jobs?search={encoded_keyword}"

            response = self.safe_get(url)
            if not response:
                continue

            try:
                data = response.json()

                for job_data in data.get('jobs', [])[:20]:
                    job_url = job_data.get('url', '')

                    # Skip if we've already seen this job
                    if job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    title = job_data.get('title', 'Unknown')
                    location = job_data.get('candidate_required_location', 'Worldwide')

                    if not self.matches_location(location):
                        continue

                    job = Job(
                        title=title,
                        company=job_data.get('company_name', 'Unknown'),
                        location=location,
                        salary=job_data.get('salary', 'Not specified'),
                        url=job_url,
                        source="Remotive",
                        description=BeautifulSoup(job_data.get('description', ''), 'html.parser').get_text()[:500],
                        remote=True,
                        date_scraped=datetime.now().isoformat()
                    )
                    self.jobs.append(job)
                    logger.info(f"Found Remotive: {job.title} at {job.company}")

                self.random_delay(0.5, 1)

            except Exception as e:
                logger.error(f"Error parsing Remotive for keyword '{keyword}': {e}")

        logger.info(f"RemotiveScraper: Found {len(self.jobs)} jobs")
        return self.jobs


class LinkedInScraper(JobScraper):
    """Scraper for LinkedIn public job postings"""

    def _build_search_urls(self) -> List[str]:
        """Build LinkedIn search URLs from configured keywords and locations"""
        keywords = self.keywords if self.keywords else DEFAULT_KEYWORDS

        # Map common location terms to LinkedIn location format
        location_mapping = {
            'usa': 'United States',
            'united states': 'United States',
            'u.s.': 'United States',
            'america': 'United States',
            'canada': 'Canada',
            'north america': 'United States',
            'remote': 'Worldwide',
            'worldwide': 'Worldwide',
            'global': 'Worldwide',
            'anywhere': 'Worldwide',
        }

        # Get unique LinkedIn locations from configured locations
        linkedin_locations = set()
        for loc in self.allowed_locations:
            loc_lower = loc.lower()
            if loc_lower in location_mapping:
                linkedin_locations.add(location_mapping[loc_lower])
            else:
                # Use the location as-is if not in mapping (capitalize words)
                linkedin_locations.add(loc.title())

        # Default to US and Canada if no locations configured
        if not linkedin_locations:
            linkedin_locations = {'United States', 'Canada'}

        # Build URLs for each keyword + location combination
        # Limit to first 3 keywords and 2 locations to avoid too many requests
        urls = []
        for keyword in keywords[:3]:
            encoded_keyword = keyword.replace(' ', '%20')
            for location in list(linkedin_locations)[:2]:
                encoded_location = location.replace(' ', '%20')
                # f_WT=2 means remote jobs
                url = f'https://www.linkedin.com/jobs/search/?keywords={encoded_keyword}&location={encoded_location}&f_WT=2'
                urls.append(url)

        return urls

    def scrape(self) -> List[Job]:
        logger.info("Scraping LinkedIn...")

        # Build dynamic search URLs from keywords and locations
        searches = self._build_search_urls()
        seen_urls = set()

        for url in searches:
            try:
                response = self.safe_get(url)
                if not response:
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')
                job_cards = soup.find_all('div', class_=re.compile(r'base-card|job-search-card'))

                for card in job_cards[:10]:
                    try:
                        title_elem = card.find(['h3', 'span'], class_=re.compile(r'title|job-title'))
                        company_elem = card.find(['h4', 'a'], class_=re.compile(r'company|subtitle'))
                        location_elem = card.find(['span'], class_=re.compile(r'location'))
                        link_elem = card.find('a', class_=re.compile(r'base-card__full-link'))

                        if not title_elem:
                            continue

                        job_url = link_elem['href'] if link_elem else url

                        # Skip if we've already seen this job
                        if job_url in seen_urls:
                            continue
                        seen_urls.add(job_url)

                        title = title_elem.get_text(strip=True)
                        company = company_elem.get_text(strip=True) if company_elem else "Unknown"
                        location = location_elem.get_text(strip=True) if location_elem else "Remote"

                        if not self.matches_keywords(title):
                            continue

                        if not self.matches_location(location):
                            continue

                        job = Job(
                            title=title,
                            company=company,
                            location=location,
                            salary="Not specified",
                            url=job_url,
                            source="LinkedIn",
                            description=card.get_text()[:500],
                            remote='remote' in location.lower(),
                            date_scraped=datetime.now().isoformat()
                        )
                        self.jobs.append(job)
                        logger.info(f"Found LinkedIn: {title} at {company}")

                    except Exception as e:
                        logger.debug(f"Error parsing LinkedIn card: {e}")
                        continue

                self.random_delay(2, 4)

            except Exception as e:
                logger.debug(f"Error scraping LinkedIn: {e}")
                continue

        logger.info(f"LinkedInScraper: Found {len(self.jobs)} jobs")
        return self.jobs

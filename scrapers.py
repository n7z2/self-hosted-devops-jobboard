"""
Job Scraper Classes
Individual scraper implementations for different job sources and ATS systems.
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import random
import logging
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, quote_plus

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
        self.excluded_locations = config.get('excluded_locations', []) if config else []

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
        if not self.keywords:
            # Default DevOps keywords
            default_keywords = [
                'devops', 'sre', 'site reliability', 'platform engineer',
                'infrastructure', 'cloud engineer', 'devsecops', 'kubernetes', 'terraform'
            ]
            keywords = default_keywords
        else:
            keywords = self.keywords

        text = f"{title} {description}".lower()
        return any(kw.lower() in text for kw in keywords)

    def matches_location(self, location: str, description: str = "") -> bool:
        """Check if job location is allowed (US/Canada)"""
        text = f"{location} {description}".lower()

        # Check excluded locations first
        if self.excluded_locations:
            if any(exc.lower() in text for exc in self.excluded_locations):
                return False

        # Check allowed locations
        if self.allowed_locations:
            return any(loc.lower() in text for loc in self.allowed_locations)

        # Default US/Canada check
        us_canada_terms = [
            'united states', 'usa', 'u.s.', 'america', 'canada', 'canadian',
            'remote', 'north america', 'worldwide', 'anywhere', 'global'
        ]
        return any(term in text for term in us_canada_terms)


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

        if self.parallel_mode:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._scrape_company, name, board_id): name
                    for name, board_id in self.companies.items()
                }
                for future in as_completed(futures):
                    try:
                        jobs = future.result()
                        self.jobs.extend(jobs)
                    except Exception as e:
                        logger.debug(f"Error in parallel scrape: {e}")
        else:
            for company_name, board_id in self.companies.items():
                jobs = self._scrape_company(company_name, board_id)
                self.jobs.extend(jobs)

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

        if self.parallel_mode:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._scrape_company, name, board_id): name
                    for name, board_id in self.companies.items()
                }
                for future in as_completed(futures):
                    try:
                        jobs = future.result()
                        self.jobs.extend(jobs)
                    except Exception as e:
                        logger.debug(f"Error in parallel scrape: {e}")
        else:
            for company_name, board_id in self.companies.items():
                jobs = self._scrape_company(company_name, board_id)
                self.jobs.extend(jobs)

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

        if self.parallel_mode:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._scrape_company, name, board_id): name
                    for name, board_id in self.companies.items()
                }
                for future in as_completed(futures):
                    try:
                        jobs = future.result()
                        self.jobs.extend(jobs)
                    except Exception as e:
                        logger.debug(f"Error in parallel scrape: {e}")
        else:
            for company_name, board_id in self.companies.items():
                jobs = self._scrape_company(company_name, board_id)
                self.jobs.extend(jobs)

        logger.info(f"AshbyScraper: Found {len(self.jobs)} jobs")
        return self.jobs


class RemotiveScraper(JobScraper):
    """Scraper for Remotive.io - Remote job board"""

    def scrape(self) -> List[Job]:
        logger.info("Scraping Remotive...")

        url = "https://remotive.com/api/remote-jobs?category=devops"
        response = self.safe_get(url)

        if not response:
            return self.jobs

        try:
            data = response.json()

            for job_data in data.get('jobs', [])[:30]:
                title = job_data.get('title', 'Unknown')

                if not self.matches_keywords(title, job_data.get('description', '')):
                    continue

                location = job_data.get('candidate_required_location', 'Worldwide')

                if not self.matches_location(location, job_data.get('description', '')):
                    continue

                job = Job(
                    title=title,
                    company=job_data.get('company_name', 'Unknown'),
                    location=location,
                    salary=job_data.get('salary', 'Not specified'),
                    url=job_data.get('url', ''),
                    source="Remotive",
                    description=BeautifulSoup(job_data.get('description', ''), 'html.parser').get_text()[:500],
                    remote=True,
                    date_scraped=datetime.now().isoformat()
                )
                self.jobs.append(job)
                logger.info(f"Found Remotive: {job.title} at {job.company}")

        except Exception as e:
            logger.error(f"Error parsing Remotive: {e}")

        logger.info(f"RemotiveScraper: Found {len(self.jobs)} jobs")
        return self.jobs


class HackerNewsScraper(JobScraper):
    """Scraper for Hacker News 'Who is Hiring' threads"""

    def scrape(self) -> List[Job]:
        logger.info("Scraping Hacker News Who's Hiring...")

        search_url = "https://hn.algolia.com/api/v1/search_by_date?query=who%20is%20hiring&tags=story&hitsPerPage=5"
        response = self.safe_get(search_url)

        if not response:
            return self.jobs

        try:
            data = response.json()

            for hit in data.get('hits', []):
                if 'who is hiring' in hit.get('title', '').lower():
                    story_id = hit.get('objectID')
                    comments_url = f"https://hn.algolia.com/api/v1/items/{story_id}"
                    comments_response = self.safe_get(comments_url)

                    if not comments_response:
                        continue

                    story_data = comments_response.json()

                    for comment in story_data.get('children', [])[:100]:
                        text = comment.get('text', '')
                        if not text:
                            continue

                        if not self.matches_keywords('', text):
                            continue

                        if not self.matches_location('', text):
                            continue

                        lines = text.split('\n')
                        first_line = BeautifulSoup(lines[0], 'html.parser').get_text()
                        company = first_line.split('|')[0].strip()[:50] if '|' in first_line else "See posting"

                        title_match = re.search(
                            r'(devops|sre|infrastructure|platform|cloud)\s*(engineer|lead|manager)?',
                            text.lower()
                        )
                        title = title_match.group().title() if title_match else "DevOps Role"

                        job = Job(
                            title=title,
                            company=company,
                            location="Remote",
                            salary=self.extract_salary(text),
                            url=f"https://news.ycombinator.com/item?id={comment.get('id')}",
                            source="HackerNews",
                            description=BeautifulSoup(text, 'html.parser').get_text()[:500],
                            remote=True,
                            date_scraped=datetime.now().isoformat()
                        )
                        self.jobs.append(job)
                        logger.info(f"Found HN: {company}")

                    break

        except Exception as e:
            logger.error(f"Error parsing HN: {e}")

        logger.info(f"HackerNewsScraper: Found {len(self.jobs)} jobs")
        return self.jobs


class LinkedInScraper(JobScraper):
    """Scraper for LinkedIn public job postings"""

    def scrape(self) -> List[Job]:
        logger.info("Scraping LinkedIn...")

        searches = [
            'https://www.linkedin.com/jobs/search/?keywords=devops%20engineer&location=United%20States&f_WT=2',
            'https://www.linkedin.com/jobs/search/?keywords=sre%20engineer&location=United%20States&f_WT=2',
            'https://www.linkedin.com/jobs/search/?keywords=devops&location=Canada&f_TPR=r86400',
        ]

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

                        title = title_elem.get_text(strip=True)
                        company = company_elem.get_text(strip=True) if company_elem else "Unknown"
                        location = location_elem.get_text(strip=True) if location_elem else "Remote"
                        job_url = link_elem['href'] if link_elem else url

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

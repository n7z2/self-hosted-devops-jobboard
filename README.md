# n7z DevOps Job Board

A self hosted job scraper and web interface for finding DevOps, SRE, and Platform Engineering jobs in the US and Canada. I developed this because going through every single company career site searching for DevOps related roles is a tiresome process and there are alot of sites that already do they but they usually require some king of payement. Well you can now do this for free and self host your own job site with the ability to hide and mark a job as applied to keep track of your job applications. 

There is no catch or paid service for this but feel free to donate below if you like what you see and if it has helped you in any way.

https://buymeacoffee.com/n7z2

## What It Does

This tool automatically scrapes job postings from multiple sources:

### Job Board APIs
- **Remotive** - Remote job board with DevOps category
- **Hacker News** - Monthly "Who is Hiring" threads

### Applicant Tracking Systems (ATS)
- **Greenhouse** - 140+ tech companies (Airbnb, Cloudflare, GitLab, etc.)
- **Lever** - 100+ companies (1Password, Netlify, Postman, etc.)
- **Ashby** - 40+ companies (Ramp, Vercel, Linear, etc.)
- **SmartRecruiters** - Enterprise companies (Visa, Salesforce, Adobe, etc.)
- **BambooHR** - Mid-size companies

### Other Sources
- **LinkedIn** - Public job listings (limited)

## Features

- **Customizable Keywords** - Search for devops, sre, kubernetes, terraform, or any keywords you want
- **Location Filtering** - Filter jobs to US, Canada, or specific cities/states
- **Application Tracking** - Mark jobs as applied and track your progress
- **Hide Irrelevant Jobs** - Hide jobs you're not interested in
- **Company Discovery** - Automatically discover new companies using each ATS
- **Parallel Processing** - Fast scanning with configurable worker threads

## Quick Start

### Using Make (Recommended)

```bash
cd job_scraper
make build    # Build Docker container
make run      # Start the job board
```

Open http://localhost:5000 in your browser.

### Make Commands

| Command | Description |
|---------|-------------|
| `make help` | Show all available commands |
| `make build` | Build the Docker container |
| `make run` | Start the job board (http://localhost:5000) |
| `make stop` | Stop the job board |
| `make logs` | View container logs |
| `make clean` | Remove container and image |
| `make restart` | Rebuild and restart the container |

### Using Docker Directly

```bash
cd job_scraper
docker build -t jobboard .
docker run -p 5000:5000 -v $(pwd)/data:/app/data jobboard
```

### Manual Setup (without Docker)

```bash
cd job_scraper
pip install flask beautifulsoup4 requests
python app.py
```

## Usage

### Web Interface

1. **Find New Jobs** - Click the dropdown to choose:
   - **Quick Scan** - API sources only (fast)
   - **Full Scan** - All sources including LinkedIn

2. **Discover Companies** - Scans ATS systems to find new companies to add to your search

3. **Filter Jobs** - Filter by source, date, or application status

4. **Track Applications** - Mark jobs as applied to keep track of your progress

## Configuration

### Companies (`companies.json`)

Add your own companies to scrape:

```json
{
  "greenhouse": {
    "companies": {
      "Company Name": "board_id"
    }
  },
  "lever": {
    "companies": {
      "Company Name": "board_id"
    }
  }
}
```

### Keywords (`data/keywords.json`)

Customize search keywords via the UI or edit directly:

```json
["devops", "sre", "platform engineer", "kubernetes"]
```

### Locations (`data/locations.json`)

Customize location filters via the UI or edit directly:

```json
{
  "allowed": ["usa", "canada", "remote", "san francisco"],
  "excluded": ["europe only", "uk only", "vienna"]
}
```

## File Structure

```
job_scraper/
├── app.py              # Flask web application
├── scraper.py          # Main scraper orchestrator
├── scrapers.py         # Individual scraper classes
├── discovery.py        # Company discovery script
├── companies.json      # Company lists for each ATS
├── Dockerfile          # Docker container definition
├── docker-compose.yml  # Docker Compose configuration
├── Makefile            # Make commands for easy usage
├── .gitignore          # Git ignore rules
├── templates/
│   └── index.html      # Web UI
└── data/               # User data (not committed to git)
    ├── devops_jobs.json       # Scraped jobs
    ├── keywords.json          # Search keywords
    ├── locations.json         # Location filters
    ├── discovered_companies.json  # Discovered companies
    └── applications.db        # SQLite database for tracking
```

**Note:** The `data/` folder contains your personal job data and is excluded from git via `.gitignore`.

## How It Works

1. **Scraping**: Each ATS has a specific API format. The scrapers query these APIs for job listings.

2. **Filtering**: Jobs are filtered by:
   - Keywords in job title/description
   - Location matching (allowed/excluded lists)
   - Deduplication by title + company

3. **Storage**: Jobs are stored in JSON format and merged with existing jobs on each scan.

4. **Tracking**: Application status is stored in a SQLite database separate from job data.

## Adding New Companies

### Find the Board ID

1. **Greenhouse**: Visit `https://boards.greenhouse.io/{company}` - the URL slug is the board ID
2. **Lever**: Visit `https://jobs.lever.co/{company}` - the URL slug is the board ID
3. **Ashby**: Check the company's career page source for `ashbyhq.com` references

### Add to Configuration

Add the company to `companies.json` under the appropriate ATS section.

## Tips

- Run **Quick Scan** daily for fast updates from API sources
- Run **Full Scan** weekly for comprehensive coverage
- Use **Discover Companies** periodically to find new companies
- Hide jobs you're not interested in to keep your list clean
- Adjust location filters to match your target job market


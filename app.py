#!/usr/bin/env python3
"""
Job Board Web Application
Simple Flask app to view and track job applications
"""

from flask import Flask, render_template, jsonify, request
import json
import os
from datetime import datetime, timedelta
import sqlite3
import threading
import math

from scraper import run_scraper as scraper_run
from discovery import run_discovery as discovery_run

app = Flask(__name__)

# Configuration
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))
DB_PATH = os.path.join(DATA_DIR, 'applications.db')
JOBS_FILE = os.path.join(DATA_DIR, 'devops_jobs.json')

# Track scraper status
scraper_status = {'running': False, 'last_run': None, 'message': ''}

# Default keywords
DEFAULT_KEYWORDS = [
    'devops', 'sre', 'site reliability', 'platform engineer',
    'infrastructure', 'cloud engineer', 'devsecops', 'kubernetes', 'terraform'
]

KEYWORDS_FILE = os.path.join(DATA_DIR, 'keywords.json')
LOCATIONS_FILE = os.path.join(DATA_DIR, 'locations.json')
COMPANIES_FILE = os.path.join(os.path.dirname(__file__), 'companies.json')

# Default locations
DEFAULT_LOCATIONS = {
    'allowed': [
        'united states', 'usa', 'u.s.', 'america',
        'california', 'new york', 'texas', 'florida', 'washington', 'colorado',
        'san francisco', 'los angeles', 'seattle', 'austin', 'denver', 'boston',
        'chicago', 'atlanta', 'nyc', 'new york city', 'bay area', 'silicon valley',
        'canada', 'canadian', 'toronto', 'vancouver', 'montreal', 'calgary',
        'ottawa', 'ontario', 'british columbia', 'quebec',
        'north america', 'americas', 'us/canada', 'remote', 'worldwide', 'global', 'anywhere'
    ],
    'excluded': [
        'europe only', 'eu only', 'uk only', 'emea only', 'apac only',
        'india only', 'australia only', 'vienna', 'berlin', 'london',
        'paris', 'amsterdam', 'dublin', 'singapore', 'tokyo', 'sydney'
    ]
}


def load_locations():
    """Load location filters from file"""
    # First try custom locations file
    if os.path.exists(LOCATIONS_FILE):
        try:
            with open(LOCATIONS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass

    # Fall back to companies.json
    if os.path.exists(COMPANIES_FILE):
        try:
            with open(COMPANIES_FILE, 'r') as f:
                data = json.load(f)
                if 'locations' in data:
                    return {
                        'allowed': data['locations'].get('allowed', []),
                        'excluded': data['locations'].get('excluded', [])
                    }
        except:
            pass

    return DEFAULT_LOCATIONS.copy()


def save_locations(locations):
    """Save location filters to file"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOCATIONS_FILE, 'w') as f:
        json.dump(locations, f, indent=2)


def load_keywords():
    """Load search keywords from file"""
    if os.path.exists(KEYWORDS_FILE):
        try:
            with open(KEYWORDS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return DEFAULT_KEYWORDS.copy()


def get_company_stats():
    """Get statistics about discovered companies"""
    discovered_file = os.path.join(DATA_DIR, 'discovered_companies.json')
    stats = {
        'greenhouse': 0,
        'lever': 0,
        'ashby': 0,
        'smartrecruiters': 0,
        'bamboohr': 0,
        'total': 0,
        'last_updated': None
    }

    if os.path.exists(discovered_file):
        try:
            with open(discovered_file, 'r') as f:
                data = json.load(f)
                stats['greenhouse'] = len(data.get('greenhouse', {}))
                stats['lever'] = len(data.get('lever', {}))
                stats['ashby'] = len(data.get('ashby', {}))
                stats['smartrecruiters'] = len(data.get('smartrecruiters', {}))
                stats['bamboohr'] = len(data.get('bamboohr', {}))
                stats['total'] = stats['greenhouse'] + stats['lever'] + stats['ashby'] + stats['smartrecruiters'] + stats['bamboohr']
                stats['last_updated'] = data.get('last_updated')
        except:
            pass

    return stats


def save_keywords(keywords):
    """Save search keywords to file"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(KEYWORDS_FILE, 'w') as f:
        json.dump(keywords, f)


def detect_work_type(job):
    """Detect if job is Remote, Hybrid, or On-site"""
    location = job.get('location', '').lower()
    title = job.get('title', '').lower()
    description = job.get('description', '').lower()

    text = f"{location} {title} {description}"

    if any(term in text for term in ['remote', 'work from home', 'wfh', 'anywhere', 'distributed']):
        if 'hybrid' in text:
            return 'Hybrid'
        return 'Remote'
    elif 'hybrid' in text:
        return 'Hybrid'
    elif any(term in text for term in ['on-site', 'onsite', 'in-office', 'in office']):
        return 'On-site'

    # Check if remote flag is set
    if job.get('remote', False):
        return 'Remote'

    return None  # Unknown


def is_job_in_allowed_location(job, locations=None):
    """Check if job location matches allowed locations"""
    if locations is None:
        locations = load_locations()

    location = job.get('location', '').lower()
    description = job.get('description', '').lower()
    text = f"{location} {description}"

    allowed = locations.get('allowed', [])
    excluded = locations.get('excluded', [])

    # Check excluded locations first
    if any(term.lower() in text for term in excluded):
        return False

    # Check allowed locations
    if any(term.lower() in text for term in allowed):
        return True

    # If job is remote and no excluded terms found, include it
    if job.get('remote', False) and 'remote' in [t.lower() for t in allowed]:
        return True

    return False


def init_db():
    """Initialize SQLite database for tracking applications"""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_url TEXT UNIQUE,
            applied_date TEXT,
            notes TEXT,
            status TEXT DEFAULT 'applied'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS hidden_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_url TEXT UNIQUE,
            hidden_date TEXT
        )
    ''')
    conn.commit()
    conn.close()


def get_applied_jobs():
    """Get all applied job URLs"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT job_url, applied_date, notes, status FROM applications')
    applied = {row[0]: {'date': row[1], 'notes': row[2], 'status': row[3]} for row in c.fetchall()}
    conn.close()
    return applied


def get_hidden_jobs():
    """Get all hidden job URLs"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT job_url FROM hidden_jobs')
    hidden = set(row[0] for row in c.fetchall())
    conn.close()
    return hidden


def load_jobs():
    """Load jobs from JSON file"""
    if not os.path.exists(JOBS_FILE):
        return []
    with open(JOBS_FILE, 'r') as f:
        return json.load(f)


def run_scraper(mode='quick'):
    """Run the job scraper in background"""
    global scraper_status
    scraper_status['running'] = True
    scraper_status['message'] = f'Scraping jobs ({mode} mode)...'

    try:
        keywords = load_keywords()
        output_path = os.path.join(DATA_DIR, 'devops_jobs')

        scraper_run(
            mode=mode,
            keywords=keywords,
            output_path=output_path,
            parallel=True,
            workers=10
        )

        scraper_status['last_run'] = datetime.now().isoformat()
        scraper_status['message'] = 'Scrape completed successfully!'
    except Exception as e:
        scraper_status['message'] = f'Scrape failed: {str(e)}'
    finally:
        scraper_status['running'] = False


@app.route('/')
def index():
    """Main page - show all jobs"""
    jobs = load_jobs()
    applied = get_applied_jobs()
    hidden = get_hidden_jobs()
    keywords = load_keywords()
    locations = load_locations()

    show_hidden = request.args.get('show_hidden', 'false') == 'true'
    filter_source = request.args.get('source', '')
    filter_status = request.args.get('status', '')
    filter_date = request.args.get('date', '')
    per_page = int(request.args.get('per_page', '20'))
    page = int(request.args.get('page', '1'))

    # Validate per_page
    if per_page not in [10, 20, 50, 100]:
        per_page = 20

    enriched_jobs = []
    sources = set()

    # Calculate date cutoffs
    now = datetime.now()
    date_cutoffs = {
        'today': now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
        '3days': (now - timedelta(days=3)).isoformat(),
        '7days': (now - timedelta(days=7)).isoformat(),
        '30days': (now - timedelta(days=30)).isoformat(),
    }

    for job in jobs:
        url = job.get('url', '')
        sources.add(job.get('source', 'Unknown'))

        # Filter to allowed locations
        if not is_job_in_allowed_location(job, locations):
            continue

        if url in hidden and not show_hidden:
            continue

        if filter_source and job.get('source', '') != filter_source:
            continue

        # Date filtering
        if filter_date and filter_date in date_cutoffs:
            job_date = job.get('date_scraped', '')
            if job_date < date_cutoffs[filter_date]:
                continue

        job['applied'] = url in applied
        job['applied_info'] = applied.get(url, {})
        job['hidden'] = url in hidden
        job['work_type'] = detect_work_type(job)

        if filter_status == 'applied' and not job['applied']:
            continue
        if filter_status == 'not_applied' and job['applied']:
            continue

        enriched_jobs.append(job)

    enriched_jobs.sort(key=lambda x: x.get('date_scraped', ''), reverse=True)

    # Pagination
    total_jobs = len(enriched_jobs)
    total_pages = math.ceil(total_jobs / per_page) if total_jobs > 0 else 1
    page = max(1, min(page, total_pages))  # Clamp page to valid range
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_jobs = enriched_jobs[start_idx:end_idx]

    stats = {
        'total': len(jobs),
        'applied': len(applied),
        'hidden': len(hidden),
        'visible': total_jobs
    }

    pagination = {
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'total_jobs': total_jobs,
        'has_prev': page > 1,
        'has_next': page < total_pages,
    }

    company_stats = get_company_stats()

    return render_template('index.html',
                         jobs=paginated_jobs,
                         sources=sorted(sources),
                         stats=stats,
                         filter_source=filter_source,
                         filter_status=filter_status,
                         filter_date=filter_date,
                         show_hidden=show_hidden,
                         scraper_status=scraper_status,
                         pagination=pagination,
                         keywords=keywords,
                         locations=locations,
                         company_stats=company_stats)


@app.route('/api/scrape', methods=['POST'])
def start_scrape():
    """Start a new job scrape"""
    global scraper_status

    if scraper_status['running']:
        return jsonify({'error': 'Scraper already running'}), 400

    data = request.json or {}
    mode = data.get('mode', 'quick')

    if mode not in ['quick', 'full']:
        mode = 'quick'

    thread = threading.Thread(target=run_scraper, args=(mode,))
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'message': f'Started {mode} scrape'})


@app.route('/api/scrape/status')
def scrape_status():
    """Get current scraper status"""
    return jsonify(scraper_status)


@app.route('/api/apply', methods=['POST'])
def mark_applied():
    """Mark a job as applied"""
    data = request.json
    job_url = data.get('url')
    notes = data.get('notes', '')
    status = data.get('status', 'applied')

    if not job_url:
        return jsonify({'error': 'URL required'}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('''
            INSERT OR REPLACE INTO applications (job_url, applied_date, notes, status)
            VALUES (?, ?, ?, ?)
        ''', (job_url, datetime.now().isoformat(), notes, status))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@app.route('/api/unapply', methods=['POST'])
def unmark_applied():
    """Remove applied status"""
    data = request.json
    job_url = data.get('url')

    if not job_url:
        return jsonify({'error': 'URL required'}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('DELETE FROM applications WHERE job_url = ?', (job_url,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@app.route('/api/hide', methods=['POST'])
def hide_job():
    """Hide a job"""
    data = request.json
    job_url = data.get('url')

    if not job_url:
        return jsonify({'error': 'URL required'}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('INSERT OR IGNORE INTO hidden_jobs (job_url, hidden_date) VALUES (?, ?)',
                  (job_url, datetime.now().isoformat()))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@app.route('/api/unhide', methods=['POST'])
def unhide_job():
    """Unhide a job"""
    data = request.json
    job_url = data.get('url')

    if not job_url:
        return jsonify({'error': 'URL required'}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('DELETE FROM hidden_jobs WHERE job_url = ?', (job_url,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@app.route('/api/keywords', methods=['GET'])
def get_keywords():
    """Get current search keywords"""
    return jsonify({'keywords': load_keywords()})


@app.route('/api/keywords', methods=['POST'])
def set_keywords():
    """Set search keywords"""
    data = request.json
    keywords = data.get('keywords', [])

    if not isinstance(keywords, list):
        return jsonify({'error': 'Keywords must be a list'}), 400

    # Clean and validate keywords
    clean_keywords = [k.strip().lower() for k in keywords if k and isinstance(k, str)]

    save_keywords(clean_keywords)
    return jsonify({'success': True, 'keywords': clean_keywords})


@app.route('/api/locations', methods=['GET'])
def get_locations():
    """Get current location filters"""
    return jsonify(load_locations())


@app.route('/api/locations', methods=['POST'])
def set_locations():
    """Set location filters"""
    data = request.json
    allowed = data.get('allowed', [])
    excluded = data.get('excluded', [])

    if not isinstance(allowed, list) or not isinstance(excluded, list):
        return jsonify({'error': 'Allowed and excluded must be lists'}), 400

    # Clean and validate
    clean_allowed = [loc.strip().lower() for loc in allowed if loc and isinstance(loc, str)]
    clean_excluded = [loc.strip().lower() for loc in excluded if loc and isinstance(loc, str)]

    locations = {'allowed': clean_allowed, 'excluded': clean_excluded}
    save_locations(locations)
    return jsonify({'success': True, 'locations': locations})


# Track discovery status
discovery_status = {'running': False, 'last_run': None, 'message': '', 'stats': {}}


def run_discovery():
    """Run company discovery in background"""
    global discovery_status
    discovery_status['running'] = True
    discovery_status['message'] = 'Discovering companies...'

    try:
        stats = discovery_run(parallel=True)

        discovery_status['last_run'] = datetime.now().isoformat()
        discovery_status['stats'] = {
            'greenhouse': stats.get('greenhouse', 0),
            'lever': stats.get('lever', 0),
            'ashby': stats.get('ashby', 0),
            'smartrecruiters': stats.get('smartrecruiters', 0),
            'bamboohr': stats.get('bamboohr', 0),
            'total': stats.get('total', 0),
        }
        discovery_status['message'] = f"Discovery complete! Found {discovery_status['stats'].get('total', 0)} companies."
    except Exception as e:
        discovery_status['message'] = f'Discovery failed: {str(e)}'
    finally:
        discovery_status['running'] = False


@app.route('/api/discover', methods=['POST'])
def start_discovery():
    """Start company discovery"""
    global discovery_status

    if discovery_status['running']:
        return jsonify({'error': 'Discovery already running'}), 400

    thread = threading.Thread(target=run_discovery)
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'message': 'Started company discovery'})


@app.route('/api/discover/status')
def get_discovery_status():
    """Get current discovery status"""
    return jsonify(discovery_status)


@app.route('/api/companies')
def get_discovered_companies():
    """Get all discovered companies"""
    discovered_file = os.path.join(DATA_DIR, 'discovered_companies.json')
    if os.path.exists(discovered_file):
        with open(discovered_file, 'r') as f:
            return jsonify(json.load(f))
    return jsonify({
        'greenhouse': {},
        'lever': {},
        'ashby': {},
        'smartrecruiters': {},
        'bamboohr': {},
        'last_updated': None
    })


init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

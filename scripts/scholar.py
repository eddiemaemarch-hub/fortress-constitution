"""Google Scholar — Research Module for Rudy v2.0
Handles both legal case law research and stock/strategy research.
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

LOG_DIR = os.path.expanduser("~/rudy/logs")
CACHE_DIR = os.path.expanduser("~/rudy/data/scholar_cache")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Scholar {ts}] {msg}")
    with open(f"{LOG_DIR}/scholar.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def search_scholar(query, num_results=10):
    """Search Google Scholar for academic papers and legal cases."""
    from scholarly import scholarly

    log(f"Searching: {query}")
    results = []

    try:
        search_results = scholarly.search_pubs(query)
        for i, result in enumerate(search_results):
            if i >= num_results:
                break

            pub = {
                "title": result.get("bib", {}).get("title", ""),
                "author": ", ".join(result.get("bib", {}).get("author", [])),
                "year": result.get("bib", {}).get("pub_year", ""),
                "abstract": result.get("bib", {}).get("abstract", ""),
                "citation_count": result.get("num_citations", 0),
                "url": result.get("pub_url", result.get("eprint_url", "")),
                "source": result.get("bib", {}).get("venue", ""),
            }
            results.append(pub)
            log(f"  [{i+1}] {pub['title'][:80]} ({pub['year']})")

    except Exception as e:
        log(f"Search error: {e}")
        return {"error": str(e), "results": []}

    log(f"Found {len(results)} results")
    return {"query": query, "count": len(results), "results": results}


def search_case_law(topic, jurisdiction="", year_from=None):
    """Search Google Scholar for legal case law."""
    # Google Scholar has a case law section — construct query accordingly
    query = topic
    if jurisdiction:
        query += f" {jurisdiction}"
    if year_from:
        query += f" after:{year_from}"

    # Add legal-specific terms to improve results
    if not any(term in topic.lower() for term in ["v.", "vs.", "court", "statute", "§"]):
        query += " court ruling case law"

    return search_scholar(query)


def search_strategy(topic, num_results=10):
    """Search for trading/investment strategy research papers."""
    # Add finance-specific terms
    query = f"{topic} trading strategy options"
    return search_scholar(query, num_results)


def search_stock_research(ticker, topic=""):
    """Search for research on a specific stock/asset."""
    query = f"{ticker} {topic} stock analysis research"
    return search_scholar(query)


def format_results(data, style="detailed"):
    """Format search results for display."""
    if "error" in data:
        return f"Search error: {data['error']}"

    results = data.get("results", [])
    if not results:
        return f"No results found for: {data.get('query', '')}"

    if style == "brief":
        lines = [f"📚 *{data['count']} results for:* {data['query']}\n"]
        for i, r in enumerate(results):
            cite = f" ({r['citation_count']} citations)" if r['citation_count'] else ""
            lines.append(f"{i+1}. **{r['title']}** — {r['author']} ({r['year']}){cite}")
        return "\n".join(lines)

    else:  # detailed
        lines = [f"📚 *{data['count']} results for:* {data['query']}\n"]
        for i, r in enumerate(results):
            lines.append(f"---\n**{i+1}. {r['title']}**")
            if r['author']:
                lines.append(f"Authors: {r['author']}")
            if r['year']:
                lines.append(f"Year: {r['year']}")
            if r['source']:
                lines.append(f"Source: {r['source']}")
            if r['citation_count']:
                lines.append(f"Citations: {r['citation_count']}")
            if r['abstract']:
                # Truncate long abstracts
                abstract = r['abstract'][:500] + "..." if len(r['abstract']) > 500 else r['abstract']
                lines.append(f"Abstract: {abstract}")
            if r['url']:
                lines.append(f"URL: {r['url']}")
        return "\n".join(lines)


def save_results(data, filename=None):
    """Save results to cache for later reference."""
    if not filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        query_slug = data.get("query", "unknown")[:30].replace(" ", "_")
        filename = f"{query_slug}_{ts}.json"

    filepath = os.path.join(CACHE_DIR, filename)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    log(f"Results saved to {filepath}")
    return filepath


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 scholar.py search 'query'")
        print("  python3 scholar.py cases 'legal topic'")
        print("  python3 scholar.py strategy 'trading strategy'")
        print("  python3 scholar.py stock MSTR 'bitcoin treasury'")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "search":
        query = " ".join(sys.argv[2:])
        data = search_scholar(query)
        print(format_results(data))

    elif cmd == "cases":
        topic = " ".join(sys.argv[2:])
        data = search_case_law(topic)
        print(format_results(data))

    elif cmd == "strategy":
        topic = " ".join(sys.argv[2:])
        data = search_strategy(topic)
        print(format_results(data))

    elif cmd == "stock":
        ticker = sys.argv[2]
        topic = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
        data = search_stock_research(ticker, topic)
        print(format_results(data))

    else:
        data = search_scholar(" ".join(sys.argv[1:]))
        print(format_results(data))

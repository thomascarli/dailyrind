#!/usr/bin/env python3
"""
Batch Cheese Scraper
Scrape multiple cheeses from cheese.com

Usage:
  python3 batch_scrape.py <url1> <url2> <url3> ...
  python3 batch_scrape.py --file urls.txt
  python3 batch_scrape.py --output cheeses.json <url1> <url2>
"""

import sys
import json
import time
import random
from pathlib import Path

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser
import re


class CheeseParser(HTMLParser):
    """Parse cheese.com HTML pages"""
    
    def __init__(self, url=''):
        super().__init__()
        self.url = url
        self.data = {
            'name': '',
            'country': '',
            'milk': '',
            'texture': '',
            'color': '',
            'aged': 'Unknown',
            'rind': 'Natural',
            'flavor': 'Mild',
            'image': '',
            'description': '',
            'url': url
        }
        self.in_h1 = False
        self.in_description = False
        self.description_paragraphs = []
        self.text_content = []
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        
        if tag == 'h1':
            self.in_h1 = True
        
        if tag == 'img' and not self.data['image']:
            src = attrs_dict.get('src', '')
            # Match both /media/img/cheese/ and /media/img/cheese-suggestion/
            if '/media/img/cheese' in src:
                if src.startswith('/'):
                    self.data['image'] = f"https://www.cheese.com{src}"
                else:
                    self.data['image'] = src
        
        if tag == 'div' and attrs_dict.get('id') == 'collapse-description':
            self.in_description = True
        
        if tag == 'p' and self.in_description:
            self.description_paragraphs.append('')
    
    def handle_endtag(self, tag):
        if tag == 'h1':
            self.in_h1 = False
        if tag == 'div':
            self.in_description = False
    
    def handle_data(self, data):
        if self.in_h1:
            self.data['name'] = data.strip()
        
        if self.in_description and self.description_paragraphs:
            self.description_paragraphs[-1] += data
        
        self.text_content.append(data)
    
    def extract_data(self):
        full_text = ' '.join(self.text_content)
        
        # Country
        country_match = re.search(r'Country of origin:\s*([^\n•]+)', full_text, re.IGNORECASE)
        if country_match:
            self.data['country'] = self._clean_text(country_match.group(1))
        
        # Milk - FIXED: Better pattern to handle spacing issues
        milk_patterns = [
            # Pattern 1: "Made from [modifiers] [animal]'s milk" - allow space before apostrophe
            r'Made from\s+(?:pasteurized\s+|raw\s+|unpasteurized\s+|organic\s+|fresh\s+)*(\w+)\s*(?:\'s|\'s|s)?\s+milk',
            # Pattern 2: More flexible, but avoid "by"
            r'(?:from|using|with)\s+(?:pasteurized\s+|raw\s+|unpasteurized\s+|organic\s+|fresh\s+)*(\w+)\s*(?:\'s|\'s|s)?\s+milk',
            # Pattern 3: Just "[animal]'s milk" but not preceded by "by"
            r'(?<!by\s)(\w+)\s*(?:\'s|\'s)\s+milk',
        ]
        for pattern in milk_patterns:
            milk_match = re.search(pattern, full_text, re.IGNORECASE)
            if milk_match:
                milk_type = milk_match.group(1).lower()
                # Skip common false positives
                if milk_type in ['by', 'the', 'a', 'an', 'this', 'that', 'made', 'from', 'with']:
                    continue
                if 'cow' in milk_type:
                    self.data['milk'] = 'Cow'
                elif 'goat' in milk_type:
                    self.data['milk'] = 'Goat'
                elif 'sheep' in milk_type or 'ewe' in milk_type:
                    self.data['milk'] = 'Sheep'
                elif 'buffalo' in milk_type or 'water' in milk_type:
                    self.data['milk'] = 'Buffalo'
                else:
                    self.data['milk'] = milk_type.title()
                break
        
        # Texture
        texture_match = re.search(r'Texture:\s*([^\n•]+)', full_text, re.IGNORECASE)
        if texture_match:
            texture_text = texture_match.group(1).lower()
            if 'crumbly' in texture_text:
                self.data['texture'] = 'Crumbly'
            elif 'firm' in texture_text:
                self.data['texture'] = 'Firm'
            elif 'soft' in texture_text:
                self.data['texture'] = 'Soft'
            elif 'hard' in texture_text:
                self.data['texture'] = 'Hard'
            elif 'creamy' in texture_text:
                self.data['texture'] = 'Creamy'
            else:
                self.data['texture'] = self._clean_text(texture_text).split()[0].title()
        
        if not self.data['texture']:
            type_match = re.search(r'Type:\s*([^\n•]+)', full_text, re.IGNORECASE)
            if type_match:
                type_text = type_match.group(1).lower()
                if 'hard' in type_text:
                    self.data['texture'] = 'Hard'
                elif 'semi-hard' in type_text:
                    self.data['texture'] = 'Semi-hard'
                elif 'semi-soft' in type_text:
                    self.data['texture'] = 'Semi-soft'
                elif 'soft' in type_text:
                    self.data['texture'] = 'Soft'
        
        # Color
        color_match = re.search(r'Colou?r:\s*([^\n•]+)', full_text, re.IGNORECASE)
        if color_match:
            self.data['color'] = self._clean_text(color_match.group(1)).title()
        else:
            if 'blue' in full_text.lower() and 'vein' in full_text.lower():
                self.data['color'] = 'Blue-Veined'
            else:
                self.data['color'] = 'Yellow'
        
        # Aged - FIX: safely get texture value
        texture = self.data.get('texture') or ''
        texture_lower = texture.lower()
        
        if texture_lower in ['hard', 'semi-hard', 'firm']:
            self.data['aged'] = 'Yes'
        elif texture_lower in ['soft', 'creamy', 'fresh']:
            self.data['aged'] = 'No'
        
        if re.search(r'aged?\s+for\s+\d+', full_text, re.IGNORECASE):
            self.data['aged'] = 'Yes'
        if re.search(r'fresh|unaged', full_text, re.IGNORECASE):
            self.data['aged'] = 'No'
        
        # Rind
        rind_match = re.search(r'Rind:\s*(\w+)', full_text, re.IGNORECASE)
        if rind_match:
            self.data['rind'] = self._clean_text(rind_match.group(1)).title()
        elif 'bloomy' in full_text.lower():
            self.data['rind'] = 'Bloomy'
        elif 'washed' in full_text.lower() and 'rind' in full_text.lower():
            self.data['rind'] = 'Washed'
        
        # Flavor
        flavor_match = re.search(r'Flavou?r:\s*([^\n•]+)', full_text, re.IGNORECASE)
        if flavor_match:
            flavor_text = self._clean_text(flavor_match.group(1))
            self.data['flavor'] = flavor_text.split('and')[0].split(',')[0].strip().title()
        elif 'sharp' in full_text.lower():
            self.data['flavor'] = 'Sharp'
        elif 'strong' in full_text.lower():
            self.data['flavor'] = 'Strong'
        
        # Description
        if self.description_paragraphs:
            for para in self.description_paragraphs:
                cleaned = self._clean_text(para)
                if len(cleaned) > 50:
                    self.data['description'] = cleaned[:200] + '...' if len(cleaned) > 200 else cleaned
                    break
        
        return self.data
    
    def _clean_text(self, text):
        text = ' '.join(text.split())
        text = re.split(r'Type:|Texture:|Rind:|Flavou?r:', text)[0]
        return text.strip()


def fetch_url(url, max_retries=3):
    """Fetch URL content with retry logic"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    for attempt in range(max_retries):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=30) as response:
                return response.read().decode('utf-8')
        except (URLError, HTTPError) as e:
            if attempt < max_retries - 1:
                # Exponential backoff: 2s, 4s, 8s
                wait_time = 2 ** (attempt + 1)
                print(f"  ⚠ Error (attempt {attempt + 1}/{max_retries}): {e}", file=sys.stderr)
                print(f"  ⏳ Waiting {wait_time}s before retry...", file=sys.stderr)
                time.sleep(wait_time)
            else:
                print(f"  ✗ Failed after {max_retries} attempts: {e}", file=sys.stderr)
                return None
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}", file=sys.stderr)
            return None
    
    return None


def scrape_cheese(url):
    """Scrape single cheese"""
    if not url.startswith('https://www.cheese.com/'):
        print(f"Skipping invalid URL: {url}", file=sys.stderr)
        return None
    
    html = fetch_url(url)
    if not html:
        return None
    
    parser = CheeseParser(url)
    parser.feed(html)
    cheese_data = parser.extract_data()
    
    # Only return if we have essential data
    if cheese_data.get('name') and cheese_data.get('country') and cheese_data.get('milk'):
        return cheese_data
    
    return None


def main():
    """Batch scraper main"""
    
    # Parse arguments
    urls = []
    output_file = None
    min_delay = 1.5
    max_delay = 2.5
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        
        if arg == '--file' or arg == '-f':
            if i + 1 >= len(sys.argv):
                print("Error: --file requires a filename", file=sys.stderr)
                sys.exit(1)
            with open(sys.argv[i + 1]) as f:
                urls.extend([line.strip() for line in f if line.strip() and not line.startswith('#')])
            i += 2
        elif arg == '--output' or arg == '-o':
            if i + 1 >= len(sys.argv):
                print("Error: --output requires a filename", file=sys.stderr)
                sys.exit(1)
            output_file = sys.argv[i + 1]
            i += 2
        elif arg == '--delay' or arg == '-d':
            if i + 1 >= len(sys.argv):
                print("Error: --delay requires a number (in seconds)", file=sys.stderr)
                sys.exit(1)
            try:
                delay_value = float(sys.argv[i + 1])
                min_delay = delay_value
                max_delay = delay_value + 1.0  # Add 1 second variance
            except ValueError:
                print("Error: --delay must be a number", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif arg.startswith('http'):
            urls.append(arg)
            i += 1
        else:
            i += 1
    
    if not urls:
        print("Usage: python3 batch_scrape.py [--output FILE] [--delay SECONDS] <url1> <url2> ...")
        print("   or: python3 batch_scrape.py --file urls.txt [--output FILE] [--delay SECONDS]")
        print("\nOptions:")
        print("  --file, -f FILE      Read URLs from file (one per line)")
        print("  --output, -o FILE    Save output to file")
        print("  --delay, -d SECONDS  Set delay between requests (default: 1.5-2.5s)")
        print("\nExample:")
        print("  python3 batch_scrape.py https://www.cheese.com/brie/ https://www.cheese.com/cheddar/")
        print("  python3 batch_scrape.py --file cheese_urls_A.txt --output cheeses.json")
        print("  python3 batch_scrape.py --file urls.txt --delay 3.0  # Use 3-4 second delays")
        sys.exit(1)
    
    # Scrape all cheeses
    cheeses = []
    total = len(urls)
    
    print(f"Scraping {total} cheeses...", file=sys.stderr)
    print(f"Using {min_delay:.1f}-{max_delay:.1f} second delays to be respectful to the server", file=sys.stderr)
    print()
    
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{total}] {url}", file=sys.stderr)
        
        cheese = scrape_cheese(url)
        if cheese and cheese.get('name'):
            cheeses.append(cheese)
            print(f"  ✓ {cheese['name']}", file=sys.stderr)
        else:
            print(f"  ✗ Failed or incomplete data", file=sys.stderr)
        
        # Be polite - wait between requests with randomization
        if i < total:
            delay = random.uniform(min_delay, max_delay)
            print(f"  ⏳ Waiting {delay:.1f}s...", file=sys.stderr)
            time.sleep(delay)
    
    # Output results
    print(f"\nSuccessfully scraped {len(cheeses)}/{total} cheeses", file=sys.stderr)
    
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(cheeses, f, indent=2)
        print(f"Saved to {output_file}", file=sys.stderr)
    else:
        print(json.dumps(cheeses, indent=2))


if __name__ == "__main__":
    main()

import os, sys
sys.path.append(os.getcwd())
from src.crawler.leisu_crawler import LeisuCrawler

crawler = LeisuCrawler(headless=True)
orig = crawler._run_in_worker

def boom(*args, **kwargs):
    raise NotImplementedError('forced')

crawler._run_in_worker = boom
try:
    data = crawler.fetch_match_data('°ØÌ«ÑôÉñ', 'ÆÖºÍºì×ê', '2026-05-06 18:00')
    print('fallback_ok', bool(data), data.get('_url') if data else None)
finally:
    crawler.close()

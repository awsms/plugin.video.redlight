# -*- coding: utf-8 -*-
import re
from apis import baguettio_api
from modules import source_utils
from modules.utils import clean_file_name, normalize
from modules.settings import filter_by_name
from caches.settings_cache import get_setting
# from modules.kodi_utils import logger

class source:
	def __init__(self):
		self.scrape_provider = 'baguettio'
		self.sources = []

	def results(self, info):
		try:
			if not baguettio_api.base_url(): return source_utils.internal_results(self.scrape_provider, self.sources)
			filter_title = filter_by_name(self.scrape_provider)
			self.media_type = info.get('media_type')
			title = info.get('title', '')
			self.year = int(info.get('year') or 0)
			self.season, self.episode = info.get('season'), info.get('episode')
			imdb_id = info.get('imdb_id')
			self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			timeout = int(get_setting('redlight.results.timeout', '60'))
			if 'timeout' in info: timeout = max(1, int(info['timeout']) - 1)
			scrape_results, self.errors = baguettio_api.search(self.media_type, imdb_id, self.season, self.episode, timeout=timeout)
			if not scrape_results: return source_utils.internal_results(self.scrape_provider, self.sources)
			extras = source_utils.extras()
			def _process():
				for item in scrape_results:
					try:
						url = item.get('url')
						if not url or url.startswith('magnet:'): continue
						behavior = item.get('behaviorHints') or {}
						text = ' '.join(p for p in (item.get('name'), item.get('title'), item.get('description')) if p)
						file_name = behavior.get('filename') or self._filename_from_text(text)
						# No filename => status/metrics pseudo-stream, not a real file. Skip.
						if not file_name: continue
						file_name = normalize(file_name)
						if any(x in file_name.lower() for x in extras): continue
						if filter_title and not source_utils.check_title(title, file_name, self.aliases, self.year, self.season, self.episode): continue
						display_name = clean_file_name(file_name)
						size = self._parse_size(behavior, text)
						video_quality, details = source_utils.get_file_info(name_info=source_utils.release_info_format(file_name))
						request_headers = (behavior.get('proxyHeaders') or {}).get('request') or None
						site = self._extract_site(text)
						# Display these results under the AllDebrid label/icon/colour in the sources window
						# (a known provider). Routing/resolution still keys on scrape_provider='baguettio'.
						# 'source_site' carries the real per-link site, shown as "Site:" in the results.
						# Cache status is unknown here: the addon only reveals it (and queues conversion)
						# when the URL is actually opened, so that is detected at playback time instead.
						source_item = {'name': file_name, 'display_name': display_name, 'quality': video_quality, 'size': size,
									'size_label': '%.2f GB' % size if size else 'N/A', 'debrid': self.scrape_provider, 'source': 'alldebrid',
									'source_site': site, 'extraInfo': details, 'url_dl': url, 'url': url, 'id': url, 'direct': True, 'local': False,
									'scrape_provider': self.scrape_provider, 'request_headers': request_headers}
						yield source_item
					except Exception as e:
						from modules.kodi_utils import logger
						logger('baguettio scraper yield source error', str(e))
			self.sources = list(_process())
		except Exception as e:
			from modules.kodi_utils import logger
			logger('baguettio scraper Exception', str(e))
		source_utils.internal_results(self.scrape_provider, self.sources)
		return self.sources

	def _filename_from_text(self, text):
		if not text: return ''
		match = re.search(r'Fichier\s*:\s*([^\n]+)', text)
		return match.group(1).strip() if match else ''

	def _extract_site(self, text):
		# Site name sits between a random leading emoji (after a newline) and the 💾 size
		# marker, e.g. "\n🚀 FUTU-EDGE 💾 340 Mo". The leading emoji is not fixed.
		match = re.search(r'\n\s*\S+\s+([^\n]+?)\s*💾', text)
		return match.group(1).strip() if match else ''

	def _parse_size(self, behavior, text):
		try:
			video_size = behavior.get('videoSize')
			if video_size: return round(float(video_size) / 1073741824, 2)
		except: pass
		try:
			# Size is shown after a 💾 disk emoji, e.g. "💾 28.84 Go". Capture the number
			# + magnitude letter (T/G/M/K); units may be French (To/Go/Mo/Ko) or English
			# (TB/GB/MB/KB). Fallback to a bare "2.8 GB" / "725 MB" form.
			match = re.search(r'💾\s*([\d]+(?:[.,]\d+)?)\s*([TGMK])', text, re.IGNORECASE) \
				or re.search(r'([\d]+(?:[.,]\d+)?)\s*([TGMK])(?:i?[ob])\b', text, re.IGNORECASE)
			if not match: return 0.0
			value = float(match.group(1).replace(',', '.'))
			factor = {'T': 1024.0, 'G': 1.0, 'M': 1.0 / 1024.0, 'K': 1.0 / 1048576.0}.get(match.group(2).upper(), 0.0)
			return round(value * factor, 2)
		except: return 0.0

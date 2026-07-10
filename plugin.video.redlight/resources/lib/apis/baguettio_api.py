# -*- coding: utf-8 -*-
# Generic Stremio addon consumer (e.g. baguettio): given an IMDb id, query the
# addon's /stream/{type}/{id}.json resource and return its streams[].
import requests
from urllib.parse import urlencode
from caches.settings_cache import get_setting
from modules.kodi_utils import logger

# Self-hosted instances commonly use self-signed TLS; silence the noisy warning.
try:
	from requests.packages.urllib3.exceptions import InsecureRequestWarning
	requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
	pass

def manifest_url():
	url = get_setting('redlight.baguettio.manifest_url', '').strip()
	if url in ('', 'empty_setting'): return ''
	return url

def base_url():
	# The configured manifest URL minus the trailing /manifest.json is the resource base.
	url = manifest_url()
	if not url: return ''
	if url.endswith('/manifest.json'): url = url[:-len('/manifest.json')]
	return url.rstrip('/')

def search(media_type, imdb_id, season=None, episode=None, timeout=30):
	base = base_url()
	if not base or not imdb_id: return [], []
	if media_type == 'movie':
		stream_type, stream_id = 'movie', imdb_id
	else:
		stream_type, stream_id = 'series', '%s:%s:%s' % (imdb_id, season, episode)
	link = '%s/stream/%s/%s.json' % (base, stream_type, stream_id)
	try:
		response = requests.get(link, timeout=timeout, verify=False)
		if not response.ok: response.raise_for_status()
		return response.json().get('streams', []) or [], []
	except requests.exceptions.RequestException as e:
		logger('baguettio API', '%s\n%s' % (e, link))
		return [], []

def probe_stream(item, timeout=30):
	# Opening a stream URL is what queues an uncached torrent for conversion on the addon side,
	# and is also the only way to learn whether it is cached. Open it (without downloading the
	# body), follow redirects, and report (is_uncached, play_url). Uncached torrents resolve to a
	# 'torrent_sans_cache_*.mp4' placeholder. On any error, assume cached so Kodi still tries.
	url = item.get('url_dl') or item.get('url')
	if not url: return False, None
	headers = item.get('request_headers') or {}
	try:
		response = requests.get(url, headers=headers, stream=True, allow_redirects=True, timeout=timeout, verify=False)
		final_url = response.url or url
		disposition = response.headers.get('Content-Disposition', '')
		response.close()
		if 'sans_cache' in final_url.lower() or 'sans_cache' in disposition.lower():
			return True, None
		return False, final_url
	except requests.exceptions.RequestException as e:
		logger('baguettio API', 'probe error: %s\n%s' % (e, url))
		return False, url

def resolve_playback_url(item):
	url = item.get('url_dl') or item.get('url')
	headers = item.get('request_headers')
	if not url: return None
	if headers: return '%s|%s' % (url, urlencode(headers))
	return url

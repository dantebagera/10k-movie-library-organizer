import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  CirclePlus,
  Clapperboard,
  Compass,
  Database,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  Folder,
  Link as LinkIcon,
  Loader2,
  MonitorPlay,
  PlugZap,
  Radio,
  RefreshCcw,
  Save,
  Search,
  Server,
  ShieldCheck,
  Wand2,
  X,
} from 'lucide-react'
import { fetchJson } from '../../api/client.js'
import { setTorrentHandlingConfig } from '../../api/qbittorrent.js'
import MetadataAuthorityPanel from '../../components/MetadataAuthorityPanel.jsx'
import { cx, formatCount } from '../../utils/appUtils.js'
import { buildOllamaModelGroups, CUSTOM_OLLAMA_MODEL_VALUE } from './ollamaModels.js'

const emptySettingsState = {
  library: { directory: '', directories: [''], showAdultMovies: true },
  appData: { user_data_dir: '', tmdb_cache_dir: '' },
  plex: { url: '', token: '' },
  prowlarr: {
    url: '',
    key: '',
    indexers: [],
    trusted_release_indexers: [],
    download_default_quality: '1080p',
    download_indexer_mode: 'release'
  },
  qbittorrent: {
    mode: 'embedded',
    download_dir: '',
    incomplete_dir: '',
    effective_download_dir: '',
    effective_incomplete_dir: '',
    download_dir_in_library: true,
    installed: false,
    running: false,
    supported: true,
    version: '',
    latest_version: '',
    update_available: false
  },
  tmdb: { key: '', includeAdult: false },
  streaming: {
    enabled: true,
    label: 'Stream',
    url_template: 'https://streamimdb.ru/embed/movie/{tmdb_id}'
  },
  iptv: {
    server_url: '',
    username: '',
    password: '',
    usernameHint: '',
    configured: false,
    allowInsecureTls: false,
    counts: { live: 0, movie: 0, series: 0 },
    ffmpegAvailable: false
  },
  ollama: { url: '', model: '', candidateLimit: 15 },
  aiControl: {
    enabled: true,
    trusted_indexers: [],
    trusted_indexers_configured: false,
    max_matched_movies: 25,
    max_download_searches: 10,
    ollama_curated_lists: false,
    indexers: []
  }
};

export default function SettingsWorkspace({ notify, onReviewUnmatched, onReviewIdentities, onStreamingConfigChanged }) {
  const [forms, setForms] = useState(emptySettingsState);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState({});
  const [statuses, setStatuses] = useState({});
  const [revealed, setRevealed] = useState({});
  const [trustedIndexerDialogOpen, setTrustedIndexerDialogOpen] = useState(false);
  const [aiControlIndexerDialogOpen, setAiControlIndexerDialogOpen] = useState(false);
  const [ollamaModelCatalog, setOllamaModelCatalog] = useState({
    configured_model: '',
    free_cloud_models: [],
    local_models: [],
    warnings: []
  });
  const [ollamaCustomModel, setOllamaCustomModel] = useState(false);
  const [ollamaExactModel, setOllamaExactModel] = useState('');
  const editedFieldsRef = useRef(new Set());
  const ollamaModelGroups = buildOllamaModelGroups(ollamaModelCatalog, forms.ollama.model);

  useEffect(() => {
    let cancelled = false;
    async function loadSettings() {
      setLoading(true);
      const ollamaModelsRequest = fetchJson('/api/ollama/models').catch((error) => ({
        configured_model: '',
        free_cloud_models: [],
        local_models: [],
        warnings: [error.message]
      }));
      const requests = await Promise.allSettled([
        fetchJson('/api/config'),
        fetchJson('/api/app-data/config'),
        fetchJson('/api/plex/config'),
        fetchJson('/api/prowlarr/config'),
        fetchJson('/api/qbittorrent/config'),
        fetchJson('/api/tmdb/config'),
        fetchJson('/api/streaming/config'),
        fetchJson('/api/iptv/status'),
        fetchJson('/api/ollama/config'),
        ollamaModelsRequest,
        fetchJson('/api/ai-control/config')
      ]);
      if (cancelled) return;
      const [library, appData, plex, prowlarr, qbittorrent, tmdb, streaming, iptv, ollama, ollamaModels, aiControl] = requests;
      const loadedForms = {
        library: library.status === 'fulfilled' ? {
          directory: library.value.directory || '',
          directories: (library.value.directories && library.value.directories.length ? library.value.directories : [library.value.directory || '']).filter((path) => path !== ''),
          showAdultMovies: library.value.show_adult_movies !== false
        } : { directory: '', directories: [''], showAdultMovies: true },
        appData: appData.status === 'fulfilled' ? {
          user_data_dir: appData.value.user_data_dir || '',
          tmdb_cache_dir: appData.value.tmdb_cache_dir || ''
        } : { user_data_dir: '', tmdb_cache_dir: '' },
        plex: plex.status === 'fulfilled' ? { url: plex.value.url || '', token: plex.value.token || '' } : { url: '', token: '' },
        prowlarr: prowlarr.status === 'fulfilled' ? {
          url: prowlarr.value.url || '',
          key: prowlarr.value.key || '',
          indexers: prowlarr.value.indexers || [],
          trusted_release_indexers: prowlarr.value.trusted_release_indexers || [],
          download_default_quality: prowlarr.value.download_default_quality || '1080p',
          download_indexer_mode: prowlarr.value.download_indexer_mode || 'release'
        } : emptySettingsState.prowlarr,
        qbittorrent: qbittorrent.status === 'fulfilled' ? qbittorrent.value : emptySettingsState.qbittorrent,
        tmdb: tmdb.status === 'fulfilled' ? { key: tmdb.value.key || '', includeAdult: Boolean(tmdb.value.include_adult) } : { key: '', includeAdult: false },
        streaming: streaming.status === 'fulfilled' ? {
          enabled: streaming.value.enabled !== false,
          label: streaming.value.label || 'Stream',
          url_template: streaming.value.url_template || ''
        } : emptySettingsState.streaming,
        iptv: iptv.status === 'fulfilled' ? {
          server_url: iptv.value.server_url || '',
          username: '',
          password: '',
          usernameHint: iptv.value.username_hint || '',
          configured: Boolean(iptv.value.configured),
          allowInsecureTls: Boolean(iptv.value.allow_insecure_tls),
          counts: iptv.value.counts || emptySettingsState.iptv.counts,
          ffmpegAvailable: Boolean(iptv.value.playback?.ffmpeg_available)
        } : emptySettingsState.iptv,
        ollama: ollama.status === 'fulfilled' ? {
          url: ollama.value.url || '',
          model: ollama.value.model || '',
          candidateLimit: ollama.value.candidate_limit || 15
        } : { url: '', model: '', candidateLimit: 15 },
        aiControl: aiControl.status === 'fulfilled' ? {
          enabled: aiControl.value.enabled !== false,
          trusted_indexers: aiControl.value.trusted_indexers || [],
          trusted_indexers_configured: Boolean(aiControl.value.trusted_indexers_configured),
          max_matched_movies: aiControl.value.max_matched_movies || 25,
          max_download_searches: aiControl.value.max_download_searches || 10,
          ollama_curated_lists: Boolean(aiControl.value.ollama_curated_lists),
          indexers: aiControl.value.indexers || []
        } : emptySettingsState.aiControl
      };
      setForms((current) => {
        const merged = { ...loadedForms };
        editedFieldsRef.current.forEach((key) => {
          const [section, field] = key.split('.');
          if (!current[section] || !merged[section]) return;
          merged[section] = { ...merged[section], [field]: current[section][field] };
        });
        return merged;
      });
      if (ollamaModels.status === 'fulfilled') {
        setOllamaModelCatalog(ollamaModels.value);
      }
      const failed = requests.filter((request) => request.status === 'rejected');
      if (failed.length) {
        setStatuses((state) => ({
          ...state,
          page: { tone: 'error', message: `${failed.length} settings area${failed.length === 1 ? '' : 's'} could not be loaded.` }
        }));
      }
      setLoading(false);
    }
    loadSettings();
    return () => { cancelled = true; };
  }, []);

  function updateField(section, field, value) {
    editedFieldsRef.current.add(`${section}.${field}`);
    setForms((state) => ({
      ...state,
      [section]: { ...state[section], [field]: value }
    }));
  }

  function updateOllamaModelChoice(value) {
    if (value === CUSTOM_OLLAMA_MODEL_VALUE) {
      setOllamaCustomModel(true);
      setOllamaExactModel('');
      return;
    }
    setOllamaCustomModel(false);
    updateField('ollama', 'model', value);
  }

  async function verifyExactOllamaModel() {
    const model = ollamaExactModel.trim();
    if (!model) {
      setCardStatus('ollama', 'error', 'Enter the exact Ollama cloud model name.', 'For Gemma, use gemma4:31b-cloud.');
      return;
    }
    if (!model.toLocaleLowerCase().endsWith('cloud')) {
      setCardStatus('ollama', 'error', 'That is not a cloud model name.', 'Ollama cloud model names end with the word cloud.');
      return;
    }

    setActionState('ollama-model-lookup', true);
    try {
      const data = await fetchJson(`/api/ollama/test?url=${encodeURIComponent(forms.ollama.url || '')}&model=${encodeURIComponent(model)}`);
      updateField('ollama', 'model', model);
      setOllamaCustomModel(false);
      setCardStatus('ollama', 'success', 'Cloud model verified and selected.', `${data.model} returned valid JSON in ${formatCount(data.elapsed_ms)} ms. Save Ollama to keep this choice.`);
    } catch (error) {
      setCardStatus('ollama', 'error', 'Ollama could not use that exact model.', error.message);
    } finally {
      setActionState('ollama-model-lookup', false);
    }
  }

  function updateTrustedReleaseIndexer(indexerId, checked) {
    editedFieldsRef.current.add('prowlarr.trusted_release_indexers');
    setForms((state) => {
      const current = new Set(state.prowlarr.trusted_release_indexers || []);
      if (checked) {
        current.add(indexerId);
      } else {
        current.delete(indexerId);
      }
      return {
        ...state,
        prowlarr: {
          ...state.prowlarr,
          trusted_release_indexers: Array.from(current)
        }
      };
    });
  }

  function updateAiControlTrustedIndexer(indexerId, checked) {
    editedFieldsRef.current.add('aiControl.trusted_indexers');
    setForms((state) => {
      const current = new Set(state.aiControl.trusted_indexers || []);
      if (checked) {
        current.add(indexerId);
      } else {
        current.delete(indexerId);
      }
      return {
        ...state,
        aiControl: {
          ...state.aiControl,
          trusted_indexers: Array.from(current)
        }
      };
    });
  }

  function updateLibraryDirectory(index, value) {
    editedFieldsRef.current.add('library.directory');
    editedFieldsRef.current.add('library.directories');
    setForms((state) => {
      const directories = [...(state.library.directories || [''])];
      directories[index] = value;
      return {
        ...state,
        library: {
          ...state.library,
          directory: directories.find((path) => path.trim()) || '',
          directories
        }
      };
    });
  }

  function addLibraryDirectory() {
    editedFieldsRef.current.add('library.directories');
    setForms((state) => ({
      ...state,
      library: {
        ...state.library,
        directories: [...(state.library.directories || ['']), '']
      }
    }));
  }

  function removeLibraryDirectory(index) {
    editedFieldsRef.current.add('library.directory');
    editedFieldsRef.current.add('library.directories');
    setForms((state) => {
      const current = state.library.directories || [''];
      const directories = current.filter((_, itemIndex) => itemIndex !== index);
      const nextDirectories = directories.length ? directories : [''];
      return {
        ...state,
        library: {
          ...state.library,
          directory: nextDirectories.find((path) => path.trim()) || '',
          directories: nextDirectories
        }
      };
    });
  }

  function setActionState(key, active) {
    setSaving((state) => ({ ...state, [key]: active }));
  }

  function setCardStatus(key, tone, message, detail = '') {
    setStatuses((state) => ({ ...state, [key]: { tone, message, detail } }));
  }

  async function saveLibrary(event) {
    event.preventDefault();
    setActionState('library-save', true);
    const directories = [...new Set((forms.library.directories || []).map((path) => path.trim()).filter(Boolean))];
    try {
      const data = await fetchJson('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ directories, show_adult_movies: Boolean(forms.library.showAdultMovies) })
      });
      const savedDirectories = data.directories && data.directories.length ? data.directories : [data.directory || ''];
      setForms((state) => ({ ...state, library: { directory: data.directory || savedDirectories[0] || '', directories: savedDirectories, showAdultMovies: data.show_adult_movies !== false } }));
      setCardStatus('library', 'success', 'Library locations saved.', `${savedDirectories.length} folder${savedDirectories.length === 1 ? '' : 's'} configured.`);
      notify('Library locations saved');
    } catch (error) {
      setCardStatus('library', 'error', 'Library locations not saved.', error.message);
    } finally {
      setActionState('library-save', false);
    }
  }

  async function saveAppData(event) {
    event.preventDefault();
    setActionState('appData-save', true);
    try {
      const data = await fetchJson('/api/app-data/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(forms.appData)
      });
      setForms((state) => ({ ...state, appData: { user_data_dir: data.user_data_dir || '', tmdb_cache_dir: data.tmdb_cache_dir || '' } }));
      setCardStatus('appData', 'success', 'App data paths saved.', 'Folders are ready.');
      notify('App data paths saved');
    } catch (error) {
      setCardStatus('appData', 'error', 'App data paths not saved.', error.message);
    } finally {
      setActionState('appData-save', false);
    }
  }

  async function saveIntegration(service) {
    const endpoints = {
      plex: '/api/plex/config',
      prowlarr: '/api/prowlarr/config',
      tmdb: '/api/tmdb/config',
      streaming: '/api/streaming/config',
      ollama: '/api/ollama/config'
    };
    const payloads = {
      plex: { url: forms.plex.url, token: forms.plex.token },
      prowlarr: {
        url: forms.prowlarr.url,
        key: forms.prowlarr.key,
        trusted_release_indexers: forms.prowlarr.trusted_release_indexers || [],
        download_default_quality: forms.prowlarr.download_default_quality || '1080p',
        download_indexer_mode: forms.prowlarr.download_indexer_mode || 'release'
      },
      tmdb: { key: forms.tmdb.key, include_adult: Boolean(forms.tmdb.includeAdult) },
      streaming: {
        enabled: Boolean(forms.streaming.enabled),
        label: forms.streaming.label,
        url_template: forms.streaming.url_template
      },
      ollama: { url: forms.ollama.url, model: forms.ollama.model, candidate_limit: Number(forms.ollama.candidateLimit || 15) }
    };
    setActionState(`${service}-save`, true);
    try {
      const saved = await fetchJson(endpoints[service], {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payloads[service])
      });
      if (service === 'streaming') {
        setForms((state) => ({
          ...state,
          streaming: {
            enabled: saved.enabled !== false,
            label: saved.label || 'Stream',
            url_template: saved.url_template || ''
          }
        }));
        onStreamingConfigChanged?.(saved);
      }
      if (service === 'prowlarr') {
        const config = await fetchJson('/api/prowlarr/config');
        const aiControlConfig = await fetchJson('/api/ai-control/config').catch(() => null);
        setForms((state) => ({
          ...state,
          prowlarr: {
            url: config.url || '',
            key: config.key || '',
            indexers: config.indexers || [],
            trusted_release_indexers: config.trusted_release_indexers || [],
            download_default_quality: config.download_default_quality || '1080p',
            download_indexer_mode: config.download_indexer_mode || 'release'
          },
          aiControl: aiControlConfig ? {
            ...state.aiControl,
            trusted_indexers: aiControlConfig.trusted_indexers || state.aiControl.trusted_indexers || [],
            trusted_indexers_configured: Boolean(aiControlConfig.trusted_indexers_configured),
            indexers: aiControlConfig.indexers || state.aiControl.indexers || []
          } : state.aiControl
        }));
      }
      if (service === 'ollama') {
        setOllamaModelCatalog((current) => ({
          ...current,
          configured_model: forms.ollama.model
        }));
        setOllamaCustomModel(false);
      }
      setCardStatus(service, 'success', `${serviceLabel(service)} settings saved.`, 'Run Test to verify the saved connection.');
      notify(`${serviceLabel(service)} settings saved`);
      return true;
    } catch (error) {
      setCardStatus(service, 'error', `${serviceLabel(service)} settings not saved.`, error.message);
      return false;
    } finally {
      setActionState(`${service}-save`, false);
    }
  }

  async function saveQbittorrent() {
    setActionState('qbittorrent-save', true);
    try {
      const config = await fetchJson('/api/qbittorrent/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: forms.qbittorrent.mode,
          download_dir: forms.qbittorrent.download_dir || '',
          incomplete_dir: forms.qbittorrent.incomplete_dir || ''
        })
      });
      setTorrentHandlingConfig(config);
      setForms((state) => ({ ...state, qbittorrent: { ...state.qbittorrent, ...config } }));
      setCardStatus(
        'qbittorrent',
        config.download_dir_in_library ? 'success' : 'neutral',
        'qBittorrent settings saved.',
        config.download_dir_in_library
          ? `Completed movies move to ${config.effective_download_dir}.`
          : 'The completed folder is outside Cinema Paradiso libraries, so automatic metadata discovery is disabled.'
      );
      notify('qBittorrent settings saved');
    } catch (error) {
      setCardStatus('qbittorrent', 'error', 'qBittorrent settings not saved.', error.message);
    } finally {
      setActionState('qbittorrent-save', false);
    }
  }

  async function updateQbittorrent() {
    setActionState('qbittorrent-update', true);
    setCardStatus('qbittorrent', 'neutral', 'Updating portable qBittorrent.', 'Checking the latest official GitHub release.');
    try {
      const result = await fetchJson('/api/qbittorrent/update', { method: 'POST' });
      setTorrentHandlingConfig(result);
      setForms((state) => ({ ...state, qbittorrent: { ...state.qbittorrent, ...result } }));
      if (result.update_result === 'current') {
        setCardStatus('qbittorrent', 'success', 'qBittorrent is already current.', `Portable runtime ${result.version}.`);
        notify(`qBittorrent ${result.version} is already current`);
      } else {
        setCardStatus('qbittorrent', 'success', `qBittorrent updated to ${result.version}.`, 'The embedded WebUI restarted with the existing profile and downloads.');
        notify(`qBittorrent updated to ${result.version}`);
      }
    } catch (error) {
      setCardStatus('qbittorrent', 'error', 'qBittorrent update failed.', error.message);
      notify(`qBittorrent update failed: ${error.message}`, 'error');
    } finally {
      setActionState('qbittorrent-update', false);
    }
  }

  async function saveIPTV() {
    setActionState('iptv-save', true);
    try {
      const saved = await fetchJson('/api/iptv/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          server_url: forms.iptv.server_url,
          username: forms.iptv.username,
          password: forms.iptv.password,
          allow_insecure_tls: Boolean(forms.iptv.allowInsecureTls)
        })
      });
      setForms((state) => ({
        ...state,
        iptv: {
          ...state.iptv,
          server_url: saved.server_url || state.iptv.server_url,
          username: '',
          password: '',
          usernameHint: saved.username_hint || state.iptv.usernameHint,
          configured: Boolean(saved.configured)
        }
      }));
      setCardStatus('iptv', 'success', 'IPTV provider saved.', 'Saved credentials remain on the Flask backend.');
      notify('IPTV provider saved');
      return true;
    } catch (error) {
      setCardStatus('iptv', 'error', 'IPTV provider not saved.', error.message);
      return false;
    } finally {
      setActionState('iptv-save', false);
    }
  }

  async function testIPTV() {
    setActionState('iptv-test', true);
    try {
      const data = await fetchJson('/api/iptv/test', { method: 'POST' });
      setCardStatus('iptv', 'success', 'IPTV provider connected.', data.status ? `Account status: ${data.status}.` : 'Xtream authentication succeeded.');
    } catch (error) {
      setCardStatus('iptv', 'error', 'IPTV connection failed.', error.message);
    } finally {
      setActionState('iptv-test', false);
    }
  }

  async function syncIPTV() {
    setActionState('iptv-sync', true);
    try {
      await fetchJson('/api/iptv/sync', { method: 'POST' });
      setCardStatus('iptv', 'success', 'IPTV catalog sync started.', 'Live TV, movies, and series will replace the previous catalog together.');
      notify('IPTV catalog sync started');
    } catch (error) {
      setCardStatus('iptv', 'error', 'IPTV sync did not start.', error.message);
    } finally {
      setActionState('iptv-sync', false);
    }
  }

  async function saveAiControl(options = {}) {
    const includeTrusted = Boolean(options.includeTrusted);
    setActionState('ai-control-save', true);
    try {
      const payload = {
        enabled: Boolean(forms.aiControl.enabled),
        max_matched_movies: Number(forms.aiControl.max_matched_movies || 25),
        max_download_searches: Number(forms.aiControl.max_download_searches || 10),
        ollama_curated_lists: Boolean(forms.aiControl.ollama_curated_lists)
      };
      if (includeTrusted) {
        payload.trusted_indexers = forms.aiControl.trusted_indexers || [];
      }
      const data = await fetchJson('/api/ai-control/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      setForms((state) => ({
        ...state,
        aiControl: {
          enabled: data.enabled !== false,
          trusted_indexers: data.trusted_indexers || [],
          trusted_indexers_configured: Boolean(data.trusted_indexers_configured),
          max_matched_movies: data.max_matched_movies || 25,
          max_download_searches: data.max_download_searches || 10,
          ollama_curated_lists: Boolean(data.ollama_curated_lists),
          indexers: data.indexers || state.aiControl.indexers || []
        }
      }));
      setCardStatus('ai-control', 'success', 'AI Control settings saved.', 'The experimental command policy is updated.');
      notify('AI Control settings saved');
    } catch (error) {
      setCardStatus('ai-control', 'error', 'AI Control settings not saved.', error.message);
    } finally {
      setActionState('ai-control-save', false);
    }
  }

  async function testIntegration(service) {
    const urls = {
      plex: '/api/plex/test',
      prowlarr: '/api/prowlarr/test',
      tmdb: `/api/tmdb/test?key=${encodeURIComponent(forms.tmdb.key || '')}`,
      ollama: `/api/ollama/test?url=${encodeURIComponent(forms.ollama.url || '')}&model=${encodeURIComponent(forms.ollama.model || '')}`
    };
    setActionState(`${service}-test`, true);
    try {
      const data = await fetchJson(urls[service]);
      if (service === 'plex') {
        setCardStatus('plex', 'success', 'Plex connected.', `${formatCount(data.movie_libraries)} movie libraries found.`);
      } else if (service === 'prowlarr') {
        setCardStatus('prowlarr', 'success', 'Prowlarr connected.', `${formatCount(data.indexers)} indexers available.`);
      } else if (service === 'tmdb') {
        setCardStatus('tmdb', 'success', 'TMDB key is valid.', 'Discovery metadata is available.');
      } else {
        setCardStatus('ollama', 'success', 'Ollama model answered correctly.', `${data.model} returned valid JSON in ${formatCount(data.elapsed_ms)} ms.`);
      }
    } catch (error) {
      setCardStatus(service, 'error', `${serviceLabel(service)} test failed.`, error.message);
    } finally {
      setActionState(`${service}-test`, false);
    }
  }

  async function runPlexAction(action) {
    const endpoint = action === 'sync' ? '/api/plex/sync' : '/api/plex/force-scan';
    const method = action === 'sync' ? 'GET' : 'POST';
    setActionState(`plex-${action}`, true);
    try {
      const data = await fetchJson(endpoint, { method });
      setCardStatus('plex', 'success', action === 'sync' ? 'Plex cache refreshed.' : 'Plex scan requested.', data.cached ? `${formatCount(data.cached)} files cached.` : 'Plex will refresh its movie sections.');
      notify(action === 'sync' ? 'Plex cache refreshed' : 'Plex scan requested');
    } catch (error) {
      setCardStatus('plex', 'error', action === 'sync' ? 'Plex cache refresh failed.' : 'Plex scan failed.', error.message);
    } finally {
      setActionState(`plex-${action}`, false);
    }
  }

  function trustedIndexerSummary() {
    const trustedIds = new Set((forms.prowlarr.trusted_release_indexers || []).map(String));
    if (!trustedIds.size) return 'None trusted';
    const names = (forms.prowlarr.indexers || [])
      .filter((indexer) => trustedIds.has(String(indexer.id)))
      .map((indexer) => indexer.name || `Indexer ${indexer.id}`);
    if (!names.length) return `${trustedIds.size} trusted`;
    if (names.length === 1) return `${names[0]} trusted`;
    if (names.length === 2) return `${names.join(', ')} trusted`;
    return `${names.length} trusted`;
  }

  function aiControlIndexerSummary() {
    const trustedIds = new Set((forms.aiControl.trusted_indexers || []).map(String));
    if (!trustedIds.size && !forms.aiControl.trusted_indexers_configured) return 'YTS/YIFY default';
    if (!trustedIds.size) return 'None trusted';
    const names = (forms.aiControl.indexers || [])
      .filter((indexer) => trustedIds.has(String(indexer.id)))
      .map((indexer) => indexer.name || `Indexer ${indexer.id}`);
    if (!names.length) return `${trustedIds.size} trusted`;
    if (names.length === 1) return `${names[0]} trusted`;
    if (names.length === 2) return `${names.join(', ')} trusted`;
    return `${names.length} trusted`;
  }

  const summary = [
    { key: 'library', label: 'Library roots', ready: (forms.library.directories || []).some((path) => path.trim()), tone: 'blue' },
    { key: 'plex', label: 'Plex', ready: Boolean(forms.plex.url && forms.plex.token), tone: 'cyan' },
    { key: 'prowlarr', label: 'Prowlarr', ready: Boolean(forms.prowlarr.url && forms.prowlarr.key), tone: 'gold' },
    { key: 'qbittorrent', label: 'qBittorrent', ready: forms.qbittorrent.mode === 'system' || Boolean(forms.qbittorrent.installed), tone: 'gold' },
    { key: 'tmdb', label: 'TMDB', ready: Boolean(forms.tmdb.key), tone: 'green' },
    { key: 'streaming', label: 'Streaming', ready: Boolean(forms.streaming.enabled && forms.streaming.url_template), tone: 'green' },
    { key: 'iptv', label: 'IPTV', ready: Boolean(forms.iptv.configured), tone: 'gold' },
    { key: 'ollama', label: 'Ollama', ready: Boolean(forms.ollama.url && forms.ollama.model), tone: 'violet' },
    { key: 'ai-control', label: 'AI Control', ready: Boolean(forms.aiControl.enabled), tone: 'violet' }
  ];
  const configuredCount = summary.filter((item) => item.ready).length;

  return (
    <section className="settings-workspace">
      <div className="library-header">
        <div>
          <p className="screen-kicker">System console</p>
          <h2>Settings</h2>
          <p>Configure the local archive root, app data folders, and optional integrations without mixing file cleanup into Movie View.</p>
        </div>
        <div className="settings-summary">
          <strong>{configuredCount} / {summary.length}</strong>
          <span>configured</span>
        </div>
      </div>

      <div className="settings-chip-row" aria-label="Configuration summary">
        {summary.map((item) => (
          <span key={item.key} className={cx('settings-chip', `settings-chip-${item.tone}`, item.ready ? 'settings-chip-ready' : 'settings-chip-missing')}>
            {item.ready ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            {item.label}
            <small>{item.ready ? 'Ready' : 'Missing'}</small>
          </span>
        ))}
      </div>

      {loading ? (
        <div className="library-status">
          <Loader2 size={16} className="spin" />
          <span>Loading settings...</span>
        </div>
      ) : statuses.page ? (
        <SettingsInlineStatus status={statuses.page} />
      ) : null}

      <MetadataAuthorityPanel
        fetchJson={fetchJson}
        notify={notify}
        onReviewUnmatched={onReviewUnmatched}
        onReviewIdentities={onReviewIdentities}
      />

      <div className="settings-grid">
        <form className="settings-panel settings-panel-wide" onSubmit={saveLibrary}>
          <SettingsPanelHeader icon={Folder} title="Library Locations" label="Offline roots" text="Every folder is scanned as one merged archive for Library, Cleanup, duplicate detection, and Plex matching." />
          <div className="library-location-list">
            {(forms.library.directories && forms.library.directories.length ? forms.library.directories : ['']).map((directory, index) => (
              <label className="dialog-field library-location-field" key={`library-dir-${index}`}>
                <span>{index === 0 ? 'Primary movie folder' : `Movie folder ${index + 1}`}</span>
                <span className="library-location-input">
                  <input value={directory || ''} onChange={(event) => updateLibraryDirectory(index, event.target.value)} placeholder="E:\\Movies" />
                  <button type="button" className="secret-toggle library-location-remove" onClick={() => removeLibraryDirectory(index)} disabled={(forms.library.directories || []).length <= 1} aria-label={`Remove movie folder ${index + 1}`}>
                    <X size={15} />
                  </button>
                </span>
              </label>
            ))}
          </div>
          <label className="settings-checkbox-field">
            <input
              type="checkbox"
              checked={forms.library.showAdultMovies !== false}
              onChange={(event) => updateField('library', 'showAdultMovies', event.target.checked)}
            />
            <span>
              <strong>Show adult movies in Movie View</strong>
              <small>File View and Cleanup still show every local file.</small>
            </span>
          </label>
          <SettingsInlineStatus status={statuses.library} />
          <div className="dialog-actions">
            <button type="button" className="btn btn-secondary" onClick={addLibraryDirectory}>
              <CirclePlus size={15} /> Add location
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving['library-save']}>
              {saving['library-save'] ? <Loader2 size={15} className="spin" /> : <Save size={15} />} Save locations
            </button>
          </div>
        </form>

        <form className="settings-panel settings-panel-wide" onSubmit={saveAppData}>
          <SettingsPanelHeader icon={Database} title="App Data" label="Local storage" text="User lists and edited collections live in data. TMDB cache can be rebuilt when needed." />
          <label className="dialog-field">
            <span>User data folder</span>
            <input value={forms.appData.user_data_dir || ''} onChange={(event) => updateField('appData', 'user_data_dir', event.target.value)} />
          </label>
          <label className="dialog-field">
            <span>TMDB cache folder</span>
            <input value={forms.appData.tmdb_cache_dir || ''} onChange={(event) => updateField('appData', 'tmdb_cache_dir', event.target.value)} />
          </label>
          <SettingsInlineStatus status={statuses.appData} />
          <div className="dialog-actions">
            <button type="submit" className="btn btn-primary" disabled={saving['appData-save']}>
              {saving['appData-save'] ? <Loader2 size={15} className="spin" /> : <Save size={15} />} Save folders
            </button>
          </div>
        </form>
      </div>

      <div className="settings-section-heading">
        <div>
          <h3>Integrations</h3>
          <p>Save credentials first, then test the saved service connection.</p>
        </div>
      </div>

      <div className="settings-integration-grid">
        <IntegrationCard
          id="settings-plex"
          icon={Server}
          title="Plex"
          accent="cyan"
          status={statuses.plex}
          loading={saving}
          fields={(
            <>
              <label className="dialog-field">
                <span>Plex URL</span>
                <input value={forms.plex.url || ''} onChange={(event) => updateField('plex', 'url', event.target.value)} placeholder="http://localhost:32400" />
              </label>
              <SecretField
                label="Plex token"
                value={forms.plex.token || ''}
                revealed={revealed.plex}
                onReveal={() => setRevealed((state) => ({ ...state, plex: !state.plex }))}
                onChange={(value) => updateField('plex', 'token', value)}
              />
            </>
          )}
          actions={(
            <>
              <ActionButton loading={saving['plex-save']} icon={Save} label="Save Plex" onClick={() => saveIntegration('plex')} primary />
              <ActionButton loading={saving['plex-test']} icon={PlugZap} label="Test saved" onClick={() => testIntegration('plex')} />
              <ActionButton loading={saving['plex-sync']} icon={RefreshCcw} label="Refresh Plex Cache" onClick={() => runPlexAction('sync')} />
              <ActionButton loading={saving['plex-scan']} icon={Radio} label="Force Plex Scan" onClick={() => runPlexAction('scan')} />
            </>
          )}
        />

        <IntegrationCard
          id="settings-prowlarr"
          icon={Search}
          title="Prowlarr"
          accent="gold"
          status={statuses.prowlarr}
          fields={(
            <>
              <label className="dialog-field">
                <span>Prowlarr URL</span>
                <input value={forms.prowlarr.url || ''} onChange={(event) => updateField('prowlarr', 'url', event.target.value)} placeholder="http://localhost:9696" />
              </label>
              <SecretField
                label="API key"
                value={forms.prowlarr.key || ''}
                revealed={revealed.prowlarr}
                onReveal={() => setRevealed((state) => ({ ...state, prowlarr: !state.prowlarr }))}
                onChange={(value) => updateField('prowlarr', 'key', value)}
              />
              <p className="trusted-indexer-summary">
                <span>Release watchlist trust</span>
                <strong>{trustedIndexerSummary()}</strong>
              </p>
              <div className="settings-subsection">
                <span className="settings-subsection-title">Automation defaults</span>
                <div className="settings-two-column">
                  <label className="dialog-field">
                    <span>Default download quality</span>
                    <select
                      value={forms.prowlarr.download_default_quality || '1080p'}
                      onChange={(event) => updateField('prowlarr', 'download_default_quality', event.target.value)}
                    >
                      <option value="1080p">1080p</option>
                      <option value="4K">4K</option>
                    </select>
                  </label>
                  <label className="dialog-field">
                    <span>Download trusted indexers</span>
                    <select
                      value={forms.prowlarr.download_indexer_mode || 'release'}
                      onChange={(event) => updateField('prowlarr', 'download_indexer_mode', event.target.value)}
                    >
                      <option value="release">Use release trusted indexers</option>
                      <option value="all">Use all enabled indexers</option>
                    </select>
                  </label>
                </div>
              </div>
            </>
          )}
          actions={(
            <>
              <ActionButton loading={saving['prowlarr-save']} icon={Save} label="Save Prowlarr" onClick={() => saveIntegration('prowlarr')} primary />
              <ActionButton loading={saving['prowlarr-test']} icon={PlugZap} label="Test saved" onClick={() => testIntegration('prowlarr')} />
              <ActionButton loading={false} icon={ShieldCheck} label="Trusted indexers" onClick={() => setTrustedIndexerDialogOpen(true)} />
            </>
          )}
        />

        <IntegrationCard
          id="settings-ai-control"
          icon={Bot}
          title="AI Control Experimental"
          accent="violet"
          status={statuses['ai-control']}
          fields={(
            <>
              <label className="settings-checkbox-field">
                <input
                  type="checkbox"
                  checked={forms.aiControl.enabled !== false}
                  onChange={(event) => updateField('aiControl', 'enabled', event.target.checked)}
                />
                <span>
                  <strong>Enable AI Control</strong>
                  <small>Shows the experimental command workspace in the sidebar.</small>
                </span>
              </label>
              <div className="settings-two-column">
                <label className="dialog-field">
                  <span>Max matched movies</span>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    value={forms.aiControl.max_matched_movies || 25}
                    onChange={(event) => updateField('aiControl', 'max_matched_movies', event.target.value)}
                  />
                </label>
                <label className="dialog-field">
                  <span>Max download searches</span>
                  <input
                    type="number"
                    min="1"
                    max="50"
                    value={forms.aiControl.max_download_searches || 10}
                    onChange={(event) => updateField('aiControl', 'max_download_searches', event.target.value)}
                  />
                </label>
              </div>
              <p className="settings-runtime-detail">Download quality is fixed to 1080p and delete uses Recycle Bin in v1.</p>
              <label className="settings-checkbox-field">
                <input
                  type="checkbox"
                  checked={Boolean(forms.aiControl.ollama_curated_lists)}
                  onChange={(event) => updateField('aiControl', 'ollama_curated_lists', event.target.checked)}
                />
                <span>
                  <strong>Allow Ollama-curated lists</strong>
                  <small>Creative AI lists are not guaranteed factual. TMDB still confirms saved movie identities.</small>
                </span>
              </label>
              <p className="trusted-indexer-summary">
                <span>AI Control download trust</span>
                <strong>{aiControlIndexerSummary()}</strong>
                <small>YTS/YIFY default when no AI Control-specific selection is saved.</small>
              </p>
            </>
          )}
          actions={(
            <>
              <ActionButton loading={saving['ai-control-save']} icon={Save} label="Save AI Control" onClick={() => saveAiControl()} primary />
              <ActionButton loading={false} icon={ShieldCheck} label="Trusted indexers" onClick={() => setAiControlIndexerDialogOpen(true)} />
            </>
          )}
        />

        <IntegrationCard
          id="settings-qbittorrent"
          icon={Download}
          title="qBittorrent"
          accent="gold"
          status={statuses.qbittorrent}
          fields={(
            <>
              <label className="dialog-field">
                <span>Torrent handling</span>
                <select value={forms.qbittorrent.mode || 'embedded'} onChange={(event) => updateField('qbittorrent', 'mode', event.target.value)}>
                  <option value="embedded">Embedded qBittorrent</option>
                  <option value="system">System default client</option>
                </select>
              </label>
              <label className="dialog-field">
                <span>Movie download folder</span>
                <input
                  value={forms.qbittorrent.download_dir || ''}
                  onChange={(event) => updateField('qbittorrent', 'download_dir', event.target.value)}
                  placeholder="Uses the primary movie folder when empty"
                />
                <small>Resolved: {forms.qbittorrent.effective_download_dir || forms.library.directory || 'Not configured'}</small>
              </label>
              <label className="dialog-field">
                <span>Incomplete downloads folder</span>
                <input
                  value={forms.qbittorrent.incomplete_dir || ''}
                  onChange={(event) => updateField('qbittorrent', 'incomplete_dir', event.target.value)}
                  placeholder="Uses app data/qbittorrent/incomplete when empty"
                />
                <small>Resolved: {forms.qbittorrent.effective_incomplete_dir || 'Saved after configuration'}</small>
              </label>
              {forms.qbittorrent.download_dir_in_library === false ? (
                <p className="settings-path-warning"><AlertTriangle size={14} /> Completed movies outside library roots are not discovered automatically.</p>
              ) : null}
              {forms.qbittorrent.incomplete_dir_in_library ? (
                <p className="settings-path-warning"><AlertTriangle size={14} /> Incomplete downloads cannot be stored inside a movie library.</p>
              ) : null}
              <p className="settings-runtime-detail">
                {forms.qbittorrent.installed
                  ? `Portable qBittorrent ${forms.qbittorrent.version || 'runtime'} · ${forms.qbittorrent.running ? 'Running' : 'Stopped'}`
                  : forms.qbittorrent.supported === false
                    ? 'Portable qBittorrent is unavailable in this build.'
                    : 'The embedded portable qBittorrent runtime is missing.'}
              </p>
            </>
          )}
          actions={(
            <>
              <ActionButton loading={saving['qbittorrent-save']} icon={Save} label="Save qBittorrent" onClick={saveQbittorrent} primary />
              {forms.qbittorrent.installed && forms.qbittorrent.mode === 'embedded' ? (
                <ActionButton loading={saving['qbittorrent-update']} icon={RefreshCcw} label="Update qBittorrent" onClick={updateQbittorrent} />
              ) : null}
              {forms.qbittorrent.installed ? (
                <ActionButton loading={false} icon={ExternalLink} label="Open Downloads" onClick={() => window.location.assign('/downloads')} />
              ) : null}
            </>
          )}
        />

        <IntegrationCard
          id="settings-tmdb"
          icon={Clapperboard}
          title="TMDB"
          accent="green"
          status={statuses.tmdb}
          fields={(
            <>
              <SecretField
                label="TMDB API key"
                value={forms.tmdb.key || ''}
                revealed={revealed.tmdb}
                onReveal={() => setRevealed((state) => ({ ...state, tmdb: !state.tmdb }))}
                onChange={(value) => updateField('tmdb', 'key', value)}
              />
              <label className="settings-checkbox-field">
                <input
                  type="checkbox"
                  checked={Boolean(forms.tmdb.includeAdult)}
                  onChange={(event) => updateField('tmdb', 'includeAdult', event.target.checked)}
                />
                <span>
                  <strong>Include adult titles in metadata search</strong>
                  <small>Used for matching and Unmatched Metadata search, not normal Discover browsing.</small>
                </span>
              </label>
            </>
          )}
          actions={(
            <>
              <ActionButton loading={saving['tmdb-save']} icon={Save} label="Save TMDB" onClick={() => saveIntegration('tmdb')} primary />
              <ActionButton loading={saving['tmdb-test']} icon={PlugZap} label="Test key" onClick={() => testIntegration('tmdb')} />
            </>
          )}
        />

        <IntegrationCard
          id="settings-streaming"
          icon={MonitorPlay}
          title="Streaming Link"
          accent="green"
          status={statuses.streaming}
          fields={(
            <>
              <label className="settings-checkbox-field">
                <input
                  type="checkbox"
                  checked={forms.streaming.enabled !== false}
                  onChange={(event) => updateField('streaming', 'enabled', event.target.checked)}
                />
                <span>
                  <strong>Enable Stream buttons</strong>
                  <small>When disabled, Stream is hidden from movie cards and details.</small>
                </span>
              </label>
              <label className="dialog-field">
                <span>Button label</span>
                <input value={forms.streaming.label || ''} onChange={(event) => updateField('streaming', 'label', event.target.value)} placeholder="Stream" />
              </label>
              <label className="dialog-field">
                <span>URL template</span>
                <input value={forms.streaming.url_template || ''} onChange={(event) => updateField('streaming', 'url_template', event.target.value)} placeholder="https://streamimdb.ru/embed/movie/{tmdb_id}" />
                <small>Use {'{tmdb_id}'} or {'{imdb_id}'} where the provider expects the movie ID. Example: https://streamimdb.ru/embed/movie/{'{tmdb_id}'}.</small>
                <small>If you use {'{imdb_id}'}, CP resolves it from TMDB first.</small>
              </label>
            </>
          )}
          actions={(
            <ActionButton loading={saving['streaming-save']} icon={Save} label="Save Streaming" onClick={() => saveIntegration('streaming')} primary />
          )}
        />

        <IntegrationCard
          id="settings-iptv"
          icon={Radio}
          title="IPTV Provider"
          accent="gold"
          status={statuses.iptv}
          fields={(
            <>
              <label className="dialog-field">
                <span>Xtream server URL</span>
                <input value={forms.iptv.server_url || ''} onChange={(event) => updateField('iptv', 'server_url', event.target.value)} placeholder="https://provider.example:2096" />
              </label>
              <label className="dialog-field">
                <span>Username</span>
                <input value={forms.iptv.username || ''} onChange={(event) => updateField('iptv', 'username', event.target.value)} placeholder={forms.iptv.usernameHint || 'Xtream username'} autoComplete="off" />
                {forms.iptv.usernameHint ? <small>Saved account: {forms.iptv.usernameHint}. Leave blank to keep it.</small> : null}
              </label>
              <SecretField
                label="Password"
                value={forms.iptv.password || ''}
                revealed={revealed.iptv}
                onReveal={() => setRevealed((state) => ({ ...state, iptv: !state.iptv }))}
                onChange={(value) => updateField('iptv', 'password', value)}
              />
              <label className="settings-checkbox-field">
                <input
                  type="checkbox"
                  checked={Boolean(forms.iptv.allowInsecureTls)}
                  onChange={(event) => updateField('iptv', 'allowInsecureTls', event.target.checked)}
                />
                <span>
                  <strong>Allow invalid provider TLS certificate</strong>
                  <small>Required only when the IPTV server uses a self-signed or expired HTTPS certificate.</small>
                </span>
              </label>
              <p className="settings-runtime-detail">
                {forms.iptv.configured
                  ? `${formatCount(forms.iptv.counts.live)} channels · ${formatCount(forms.iptv.counts.movie)} movies · ${formatCount(forms.iptv.counts.series)} series`
                  : 'One active Xtream provider is supported in Cinema Paradiso 2.8.'}
              </p>
              <p className="settings-runtime-detail">
                Integrated playback: {forms.iptv.ffmpegAvailable ? 'FFmpeg ready' : 'FFmpeg not found on this machine'}
              </p>
            </>
          )}
          actions={(
            <>
              <ActionButton loading={saving['iptv-save']} icon={Save} label="Save provider" onClick={saveIPTV} primary />
              <ActionButton loading={saving['iptv-test']} icon={PlugZap} label="Test saved" onClick={testIPTV} />
              <ActionButton loading={saving['iptv-sync']} icon={RefreshCcw} label="Sync catalog" onClick={syncIPTV} />
            </>
          )}
        />

        <IntegrationCard
          id="settings-ollama"
          icon={Bot}
          title="Ollama"
          accent="violet"
          status={statuses.ollama}
          fields={(
            <>
              <label className="dialog-field">
                <span>Ollama URL</span>
                <input value={forms.ollama.url || ''} onChange={(event) => updateField('ollama', 'url', event.target.value)} placeholder="http://localhost:11434" />
              </label>
              <label className="dialog-field">
                <span>Model</span>
                <select
                  aria-label="Ollama model"
                  value={ollamaCustomModel ? CUSTOM_OLLAMA_MODEL_VALUE : (forms.ollama.model || '')}
                  onChange={(event) => updateOllamaModelChoice(event.target.value)}
                >
                  {!forms.ollama.model && <option value="">Choose a model</option>}
                  {ollamaModelGroups.current && (
                    <option value={ollamaModelGroups.current.model}>{ollamaModelGroups.current.model} — Current model</option>
                  )}
                  {ollamaModelGroups.selected && (
                    <option value={ollamaModelGroups.selected.model}>{ollamaModelGroups.selected.model} — Verified selection</option>
                  )}
                  <optgroup label="Free cloud models">
                    {ollamaModelGroups.freeCloud.length ? ollamaModelGroups.freeCloud.map((item) => (
                      <option key={item.model} value={item.model}>{item.model} — Free Cloud</option>
                    )) : <option disabled>No free cloud models reported</option>}
                  </optgroup>
                  {ollamaModelGroups.local.length ? (
                    <optgroup label="Local models">
                      {ollamaModelGroups.local.map((item) => (
                        <option key={item.model} value={item.model}>{item.model}</option>
                      ))}
                    </optgroup>
                  ) : null}
                  <option value={CUSTOM_OLLAMA_MODEL_VALUE}>Find an exact cloud model…</option>
                </select>
                {ollamaCustomModel ? (
                  <span className="ollama-model-lookup">
                    <input
                      aria-label="Exact Ollama cloud model"
                      value={ollamaExactModel}
                      onChange={(event) => setOllamaExactModel(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault();
                          verifyExactOllamaModel();
                        }
                      }}
                      placeholder="For example: gemma4:31b-cloud"
                      autoFocus
                    />
                    <ActionButton
                      loading={saving['ollama-model-lookup']}
                      icon={Search}
                      label="Verify & use"
                      onClick={verifyExactOllamaModel}
                    />
                  </span>
                ) : null}
                <small>Ollama reports only a short recommendation list, not its full cloud catalog. If a cloud model is missing, enter its exact name and CP will test it before selecting it.</small>
                {(ollamaModelCatalog.warnings || []).length ? (
                  <small>Model list warning: {ollamaModelCatalog.warnings.join(' ')}</small>
                ) : null}
              </label>
              <label className="dialog-field">
                <span>AI candidate limit</span>
                <input
                  type="number"
                  min="1"
                  max="50"
                  step="1"
                  value={forms.ollama.candidateLimit || 15}
                  onChange={(event) => updateField('ollama', 'candidateLimit', event.target.value)}
                />
                <small>CP asks Ollama for this many candidates, then validates them with TMDB. Final results may be fewer after duplicates, TV entries, or unresolved titles are removed. Allowed range: 1-50.</small>
              </label>
            </>
          )}
          actions={(
            <>
              <ActionButton loading={saving['ollama-save']} icon={Save} label="Save Ollama" onClick={() => saveIntegration('ollama')} primary />
              <ActionButton loading={saving['ollama-test']} icon={PlugZap} label="Test Model" onClick={() => testIntegration('ollama')} />
            </>
          )}
        />
      </div>
      {trustedIndexerDialogOpen ? (
        <TrustedIndexerDialog
          prowlarr={forms.prowlarr}
          saving={Boolean(saving['prowlarr-save'])}
          onToggle={updateTrustedReleaseIndexer}
          onSave={() => saveIntegration('prowlarr')}
          onClose={() => setTrustedIndexerDialogOpen(false)}
        />
      ) : null}
      {aiControlIndexerDialogOpen ? (
        <AIControlIndexerDialog
          aiControl={forms.aiControl}
          saving={Boolean(saving['ai-control-save'])}
          onToggle={updateAiControlTrustedIndexer}
          onSave={() => saveAiControl({ includeTrusted: true })}
          onClose={() => setAiControlIndexerDialogOpen(false)}
        />
      ) : null}
    </section>
  );
}

function TrustedIndexerDialog({ prowlarr, saving, onToggle, onSave, onClose }) {
  const indexers = prowlarr.indexers || [];
  const trustedIds = prowlarr.trusted_release_indexers || [];

  async function saveAndClose() {
    const saved = await onSave();
    if (saved) onClose();
  }

  return (
    <div className="modal-backdrop trusted-indexer-backdrop" role="presentation" onClick={onClose}>
      <section className="small-dialog trusted-indexer-dialog" role="dialog" aria-modal="true" aria-label="Trusted release watchlist indexers" onClick={(event) => event.stopPropagation()}>
        <header className="dialog-header">
          <div>
            <p className="screen-kicker">Prowlarr</p>
            <h2>Trusted release watchlist indexers</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close trusted indexers">
            <X size={20} />
          </button>
        </header>
        <p className="trusted-indexer-detail">Only selected indexers can mark followed movies as Available. Normal Discover and torrent search still use Prowlarr normally.</p>
        <div className="settings-checkbox-group trusted-indexer-list">
          {indexers.length ? (
            indexers.map((indexer) => (
              <label className="settings-checkbox-field" key={indexer.id}>
                <input
                  type="checkbox"
                  checked={trustedIds.includes(String(indexer.id))}
                  onChange={(event) => onToggle(String(indexer.id), event.target.checked)}
                />
                <span>
                  <strong>{indexer.name || `Indexer ${indexer.id}`}</strong>
                  <small>{/yts|yify/i.test(indexer.name || '') ? 'Default trusted release source.' : 'Manual trust for followed-release availability.'}</small>
                </span>
              </label>
            ))
          ) : (
            <p className="settings-empty-note">Save and test Prowlarr to load enabled indexers. No trusted indexers selected.</p>
          )}
          {indexers.length && !trustedIds.length ? (
            <p className="settings-empty-note">No trusted indexers selected. Followed releases will stay Watching.</p>
          ) : null}
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={saveAndClose} disabled={saving}>
            {saving ? <Loader2 size={15} className="spin" /> : <Save size={15} />} Save trusted indexers
          </button>
        </div>
      </section>
    </div>
  );
}

function AIControlIndexerDialog({ aiControl, saving, onToggle, onSave, onClose }) {
  const indexers = aiControl.indexers || [];
  const trustedIds = aiControl.trusted_indexers || [];

  async function saveAndClose() {
    const saved = await onSave();
    if (saved) onClose();
  }

  return (
    <div className="modal-backdrop trusted-indexer-backdrop" role="presentation" onClick={onClose}>
      <section className="small-dialog trusted-indexer-dialog" role="dialog" aria-modal="true" aria-label="AI Control trusted indexers" onClick={(event) => event.stopPropagation()}>
        <header className="dialog-header">
          <div>
            <p className="screen-kicker">AI Control download trust</p>
            <h2>AI Control trusted indexers</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close AI Control trusted indexers">
            <X size={20} />
          </button>
        </header>
        <p className="trusted-indexer-detail">Only selected indexers are used when AI Control plans downloads. YTS/YIFY is the default when no AI-specific selection is saved.</p>
        <div className="settings-checkbox-group trusted-indexer-list">
          {indexers.length ? (
            indexers.map((indexer) => (
              <label className="settings-checkbox-field" key={`ai-control-indexer-${indexer.id}`}>
                <input
                  type="checkbox"
                  checked={trustedIds.includes(String(indexer.id))}
                  onChange={(event) => onToggle(String(indexer.id), event.target.checked)}
                />
                <span>
                  <strong>{indexer.name || `Indexer ${indexer.id}`}</strong>
                  <small>{/yts|yify/i.test(indexer.name || '') ? 'Default AI Control download source.' : 'Manual trust for AI Control download planning.'}</small>
                </span>
              </label>
            ))
          ) : (
            <p className="settings-empty-note">Save and test Prowlarr to load enabled indexers. YTS/YIFY is used by default when available.</p>
          )}
          {indexers.length && !trustedIds.length && aiControl.trusted_indexers_configured ? (
            <p className="settings-empty-note">No AI Control trusted indexers selected. Download commands will be blocked.</p>
          ) : null}
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={saveAndClose} disabled={saving}>
            {saving ? <Loader2 size={15} className="spin" /> : <Save size={15} />} Save AI Control indexers
          </button>
        </div>
      </section>
    </div>
  );
}

function serviceLabel(service) {
  return {
    plex: 'Plex',
    prowlarr: 'Prowlarr',
    tmdb: 'TMDB',
    streaming: 'Streaming',
    ollama: 'Ollama'
  }[service] || service;
}

function SettingsPanelHeader({ icon: Icon, title, label, text }) {
  return (
    <header className="settings-panel-header">
      <span className="settings-panel-icon"><Icon size={18} /></span>
      <div>
        <span>{label}</span>
        <h3>{title}</h3>
        <p>{text}</p>
      </div>
    </header>
  );
}

function SettingsInlineStatus({ status }) {
  if (!status) return null;
  const Icon = status.tone === 'error' ? AlertTriangle : CheckCircle2;
  return (
    <p className={cx('settings-inline-status', `settings-inline-${status.tone || 'neutral'}`)}>
      <Icon size={15} />
      <span>{status.message}</span>
      {status.detail && <small>{status.detail}</small>}
    </p>
  );
}

function IntegrationCard({ id, icon, title, accent, status, fields, actions }) {
  return (
    <section id={id} className={cx('settings-panel', 'integration-card', `integration-${accent}`)}>
      <SettingsPanelHeader icon={icon} title={title} label="Integration" text={integrationText(title)} />
      <div className="settings-field-stack">
        {fields}
      </div>
      <SettingsInlineStatus status={status} />
      <div className="settings-action-grid">
        {actions}
      </div>
    </section>
  );
}

function integrationText(title) {
  return {
    Plex: 'Read-only Plex cache and Plex server scan controls.',
    Prowlarr: 'Source search for upgrades and torrent lookup.',
    qBittorrent: 'Portable downloads powered by the original qBittorrent WebUI.',
    TMDB: 'Posters, plots, cast, discovery lists, and trailers.',
    'Streaming Link': 'Configurable embedded movie stream URL template.',
    'IPTV Provider': 'Separate Xtream catalog and integrated local playback.',
    Ollama: 'AI recommendations and interpretation through your selected Ollama model.'
  }[title] || '';
}

function SecretField({ label, value, revealed, onReveal, onChange }) {
  return (
    <label className="dialog-field secret-field">
      <span>{label}</span>
      <span className="secret-input-wrap">
        <input type={revealed ? 'text' : 'password'} value={value} onChange={(event) => onChange(event.target.value)} autoComplete="off" />
        <button type="button" className="secret-toggle" onClick={onReveal} aria-label={revealed ? `Hide ${label}` : `Reveal ${label}`}>
          {revealed ? <EyeOff size={15} /> : <Eye size={15} />}
        </button>
      </span>
    </label>
  );
}

function ActionButton({ loading, icon: Icon, label, onClick, primary, disabled = false }) {
  return (
    <button type="button" className={cx('btn', primary ? 'btn-primary' : 'btn-secondary')} onClick={onClick} disabled={loading || disabled}>
      {loading ? <Loader2 size={15} className="spin" /> : <Icon size={15} />} {label}
    </button>
  );
}
